"""An LLM plays Poke and Mon's Tournament through a real PTY, deciding turn by
turn from the screen alone (no scripted policy), and narrates what it thinks
and feels. Logs one JSON line per decision for brain_review.py.

usage: llm_player.py PERSONA STEPS COLS ROWS [MODEL]

  PERSONA  casual | minmaxer | spammer | visual
  MODEL    oc:<opencode model>   e.g. oc:opencode/big-pickle   (default; free, sequential only)
           gemini:<model>        e.g. gemini:gemini-flash-lite-latest
           <openrouter model>    e.g. typesafe/jev-router

Environment:
  PLAYTEST_DIR   where logs and per-persona saves go (default: <repo>/.playtests)
  GAME_ROOT      build under test (default: this repo). Point it at a frozen copy
                 (`git archive <rev> sdk games/beastling tools | tar -x -C DIR`) so
                 every session in a round plays the same build.
  VISION=1       the player sees a colour screenshot instead of text (Gemini only)
  RESUME=1       continue a session an API error cut short (keeps save + log)
  PLAYER_PACE    seconds between Gemini calls per player (default 11)
  GEMINI_API_KEY / OPENROUTER_API_KEY -- else read from the opencode / hermes
                 config files on this machine. Never printed.
"""
import collections, fcntl, json, os, pty, re, select, shutil, struct, sys, tempfile, termios, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.environ.get("GAME_ROOT", REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, HERE)
from vt import render          # noqa: E402
import vt_color                # noqa: E402

PERSONA, STEPS = sys.argv[1], int(sys.argv[2])
COLS, ROWS = int(sys.argv[3]), int(sys.argv[4])
MODEL = sys.argv[5] if len(sys.argv) > 5 else "oc:opencode/big-pickle"
OUT = os.environ.get("PLAYTEST_DIR", os.path.join(REPO, ".playtests"))
os.makedirs(OUT, exist_ok=True)
SAVE = f"{OUT}/save_{PERSONA}"
RESUME = os.environ.get("RESUME") == "1"
if not RESUME:
    shutil.rmtree(SAVE, ignore_errors=True)
    os.makedirs(SAVE)

PERSONAS = {
    "casual": "a casual player who likes monster-battling games, plays for fun, dislikes reading much text, "
              "and gets bored when nothing interesting is happening",
    "minmaxer": "a competitive player who reads every screen carefully, tracks resources (HP, PP, coins) and "
                "type matchups, and tries to find the strongest strategy",
    "spammer": "a player who looks for the simplest repeatable way to win and tests whether pressing the same "
               "strong move over and over is enough; you report honestly whether it works",
    "visual": "a casual player who plays by looking at the screen like anyone would -- colours, layout, what "
              "stands out -- likes monster-battling games, and has no patience for clutter",
}
VISION = os.environ.get("VISION") == "1"
SEES = ("one screenshot of the terminal at a time (an image, exactly what a human sees, colours included)"
        if VISION else "one text screen at a time")
SYSTEM = f"""You are {PERSONAS[PERSONA]}. You are playtesting a terminal creature-battling game called "Poke and Mon". \
You see exactly what a human player sees: {SEES}. Decide for yourself; nobody tells you what is best.

Each turn reply with ONE JSON object and nothing else:
{{"input": "<exactly what to type before pressing Enter>", "thought": "<your reasoning, max 30 words>", "feel": "<curious|excited|bored|confused|frustrated|satisfied>"}}

Rules: menus take the number shown in [brackets]; [Y/n] prompts take y or n; where the screen says "press enter" use an empty \
input (""). Text prompts take text. Weigh your options like a real player: notice HP, PP and coins, remember what worked, and \
change your approach if something is not working. If anything looks broken, blank, cut off or confusing, say so plainly in \
"thought". Your goal is to explore the Tournament mode (option 2 on the main menu) as deeply as a real player reasonably \
would. If you would stop playing, set "input" to "QUIT" and give the honest reason in "thought"."""


# ------------------------------------------------------------------ keys (lazy, never printed)
def gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        key = json.load(open(os.path.expanduser("~/.local/share/opencode/auth.json")))["google"]["key"]
    return key


def openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        m = re.search(r"^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*['\"]?([^'\"\s]+)",
                      open(os.path.expanduser("~/.hermes/.env")).read(), re.M)
        key = m.group(1)
    return key


def give_up(err: str):
    return json.dumps({"input": "QUIT", "thought": f"llm error {err[:80]}", "feel": "frustrated"}), 0.0


# ------------------------------------------------------------------ backends
_last_call = 0.0
PACE = float(os.environ.get("PLAYER_PACE", "11"))
_thinking_off = True                 # dropped if the model rejects thinkingConfig


def gemini(messages, max_tokens=600, image_png=None):
    """One decision. An empty candidate (no content.parts) is a real Gemini
    outcome -- finishReason MAX_TOKENS when a thinking model spends the budget
    before answering, MALFORMED_RESPONSE in strict JSON mode -- so it is
    retried, not fatal. `image_png` rides along with the LAST user message."""
    import base64
    global _last_call, _thinking_off
    name = MODEL.split(":", 1)[1]
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] in ("user", "assistant")]
    if image_png is not None:
        contents[-1]["parts"].append({"inline_data": {"mime_type": "image/png",
                                                      "data": base64.b64encode(image_png).decode()}})
    gen = {"maxOutputTokens": max_tokens, "temperature": 0.8, "responseMimeType": "application/json"}
    err, key = "", gemini_key()
    for attempt in range(8):
        wait = PACE - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        # gemini-3.5-flash-lite rejects thinkingBudget:0 with a bare 400 but takes thinkingLevel:"minimal".
        cfg = dict(gen, **({"thinkingConfig": {"thinkingLevel": "minimal"}} if _thinking_off else {}))
        body = json.dumps({"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                           "generationConfig": cfg}).encode()
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent", data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.load(r)
            cand = (d.get("candidates") or [{}])[0]
            parts = (cand.get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if text.strip():
                return text, 0.0
            reason = cand.get("finishReason") or d.get("promptFeedback", {}).get("blockReason") or "no candidates"
            err = f"empty reply ({reason})"
            if reason == "MAX_TOKENS":
                gen["maxOutputTokens"] = min(4096, gen["maxOutputTokens"] * 2)
            elif reason == "MALFORMED_RESPONSE":
                gen.pop("responseMimeType", None)         # plain text; the caller regexes the {...} out
                gen["temperature"] = min(1.2, gen["temperature"] + 0.1)
            time.sleep(2)
        except urllib.error.HTTPError as e:
            body_txt = e.read()[:300].decode("utf-8", "replace")
            err = f"HTTP {e.code} {body_txt[:80]}"
            if e.code == 400 and _thinking_off:
                _thinking_off = False
                gen["maxOutputTokens"] = max(gen["maxOutputTokens"], 2048)
                continue
            if e.code == 429 and "quota" in body_txt.lower() and "PerDay" in body_txt:
                break                                      # a daily quota won't refill in minutes
            time.sleep((20 + attempt * 15) if e.code == 429 else (8 + attempt * 6) if e.code >= 500 else 3)
        except Exception as e:
            err = str(e)
            time.sleep(2 + attempt * 3)
    return give_up(err)


def opencode(messages):
    """One decision through `opencode run` (free opencode models). It takes a
    single message, so the conversation is flattened into a transcript.
    Sequential only: parallel opencode runs lock its database."""
    import subprocess
    model = MODEL.split(":", 1)[1]
    parts = [m["content"] if m["role"] != "assistant" else "YOUR REPLY: " + m["content"] for m in messages]
    prompt = "\n\n".join(parts) + "\n\nReply with ONE JSON object and nothing else."
    scratch = tempfile.mkdtemp(prefix="oc-player-")       # empty cwd: nothing for the agent to touch
    err = ""
    for attempt in range(3):
        try:
            r = subprocess.run(["opencode", "run", "--agent", "build", "-m", model, prompt],
                               capture_output=True, text=True, timeout=240, cwd=scratch)
            found = re.findall(r"\{[^{}]*\"input\"[^{}]*\}", r.stdout or "", re.S)
            if found:
                return found[-1], 0.0
            err = "no JSON: " + ((r.stdout or "") + (r.stderr or "")).strip()[-80:]
        except subprocess.TimeoutExpired:
            err = "timeout"
        time.sleep(5 + attempt * 10)
    return give_up(err)


def openrouter(messages, max_tokens=220):
    body = json.dumps({"model": MODEL, "max_tokens": max_tokens, "temperature": 0.7, "messages": messages}).encode()
    err, key = "", openrouter_key()
    for attempt in range(3):
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r)
            return d["choices"][0]["message"]["content"], d.get("usage", {}).get("cost", 0.0)
        except Exception as e:
            err = str(e)
            time.sleep(2 + attempt * 3)
    return give_up(err)


def llm(messages, image_png=None):
    if MODEL.startswith("gemini:"):
        return gemini(messages, image_png=image_png)
    if MODEL.startswith("oc:"):
        return opencode(messages)
    return openrouter(messages)


# ------------------------------------------------------------------ the game, in a real terminal
pid, fd = pty.fork()
if pid == 0:
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "sdk"), TERM="xterm-256color",
               TERMSTATION_SAVE_DIR=SAVE, COLUMNS=str(COLS), LINES=str(ROWS))
    os.chdir(os.path.join(ROOT, "games", "beastling"))
    os.execvpe("python3", ["python3", "main.py"], env)
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
raw = ""


def drain(quiet=0.15, maxwait=2.0) -> bool:
    global raw
    end, last = time.time() + maxwait, time.time()
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.04)
        if r:
            try:
                c = os.read(fd, 65536)
            except OSError:
                return False
            if not c:
                return False
            raw += c.decode("utf-8", "replace")
            last = time.time()
        elif time.time() - last > quiet:
            break
    return True


HEAD, CLEAR_SIG = None, None


def trim_raw():
    """Keep the PTY stream bounded WITHOUT cutting through an escape code (a
    plain `raw[-N:]` once split ESC[4;3H and left a stray '4;3H' line on every
    later screen). Cut at the latest full-picture clear -- the game blanks the
    picture row by row from its top-left corner -- and keep the cabinet
    drawing from the session start."""
    global raw, HEAD, CLEAR_SIG
    if CLEAR_SIG is None:
        # The neo theme paints the picture: its clear puts a colour code between
        # the cursor move and the blanks, so allow one.
        m = re.search(r"\x1b\[\d+;\d+H(?:\x1b\[[0-9;]*m)?(?= {40,})", raw)
        if m:
            CLEAR_SIG, HEAD = m.group(0), raw[:m.start()]
    if len(raw) > 300000 and CLEAR_SIG:
        cut = raw.rfind(CLEAR_SIG + " " * 40)
        if cut > len(HEAD):
            raw = HEAD + raw[cut:]


_CHROME = set("─━═│║╭╮╰╯╔╗╚╝├┤╟╢")


def screen_text() -> str:
    """The picture as plain text: cropped to the cabinet's inner columns (found
    from its top corners, double-line or rounded), minus the title bar and
    rules. Cropping by column keeps a game's own │ boxes intact."""
    trim_raw()
    rows = render(raw, COLS, ROWS).splitlines()
    left = right = None
    for line in rows:
        for tl, tr in (("╔", "╗"), ("╭", "╮")):
            if tl in line and tr in line:
                left, right = line.index(tl), line.rindex(tr)
                break
        if left is not None:
            break
    lines = []
    for line in rows:
        inner = (line[left + 1:right] if left is not None else line).rstrip()
        bare = inner.strip()
        if bare and "LAZSTATION" not in bare and set(bare) - _CHROME:
            lines.append(inner)
    return "\n".join(lines)


LOG = f"{OUT}/{PERSONA}.jsonl"
prior = []
if RESUME and os.path.exists(LOG):
    prior = [json.loads(line) for line in open(LOG) if line.strip()]
    while prior and str(prior[-1].get("thought", "")).startswith("llm error"):
        prior.pop()                                  # a harness QUIT for an API error is not a decision
    with open(LOG, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in prior)
log = open(LOG, "a" if RESUME else "w")
history = [(r["screen"], json.dumps({k: r.get(k, "") for k in ("input", "thought", "feel")}))
           for r in prior if "thought" in r][-10:]
feel, cost = collections.Counter(), 0.0
drain(1.2)
prev_screen, same = "", 0
step0 = (prior[-1]["step"] + 1) if prior else 0
if prior:
    log.write(json.dumps({"step": step0, "event": "RESUMED (harness: API error ended the previous process; the "
                          "player restarted the game and carries on -- not a game event)",
                          "screen": screen_text()}) + "\n")
step = step0
for step in range(step0, step0 + STEPS):
    scr = screen_text()
    if "Traceback" in raw:
        log.write(json.dumps({"step": step, "event": "CRASH", "screen": scr}) + "\n")
        break
    same = same + 1 if scr == prev_screen else 0
    note = "\n(NOTE: the screen did not change after your last input.)" if same >= 1 else ""
    if prior and step == step0:
        note += "\n(NOTE: you closed the game and reopened it; your Tournament progress is saved.)"
    prev_screen = scr
    msgs = [{"role": "system", "content": SYSTEM}]
    image = None
    if VISION:
        for s, a in history[-10:]:
            msgs.append({"role": "user", "content": "(an earlier screen)"})
            msgs.append({"role": "assistant", "content": a})
        msgs.append({"role": "user", "content": "SCREEN: see the attached screenshot." + note})
        png = f"{OUT}/{PERSONA}_screen.png"
        vt_color.to_png(vt_color.render_cells(raw, COLS, ROWS), png)
        image = open(png, "rb").read()
    else:
        for i, (s, a) in enumerate(history[-10:]):
            old = i < len(history[-10:]) - 2
            shown = "\n".join(s.splitlines()[:3]) + "\n[...older screen trimmed...]" if old else s
            msgs.append({"role": "user", "content": "SCREEN:\n" + shown})
            msgs.append({"role": "assistant", "content": a})
        msgs.append({"role": "user", "content": "SCREEN:\n" + scr + note})
    reply, c = llm(msgs, image_png=image)
    cost += c
    m = re.search(r"\{.*\}", reply or "", re.S)
    try:
        act = json.loads(m.group(0)) if m else {"input": "", "thought": "(empty reply)", "feel": "confused"}
    except Exception:
        act = {"input": "", "thought": "(unparseable reply) " + (reply or "")[:60], "feel": "confused"}
    typed = str(act.get("input", ""))
    feel[act.get("feel", "?")] += 1
    log.write(json.dumps({"step": step, "screen": scr, "input": typed, "thought": act.get("thought", ""),
                          "feel": act.get("feel", "")}) + "\n")
    log.flush()
    history.append((scr, json.dumps(act)))
    if typed.strip().upper() == "QUIT":
        break
    try:
        os.write(fd, (typed + "\n").encode())
    except OSError:
        break
    if not drain():
        log.write(json.dumps({"step": step + 1, "event": "GAME_EXITED", "screen": screen_text()}) + "\n")
        break
log.close()
print(f"[{PERSONA}] {step + 1 - step0} decisions | feel: {dict(feel)} | model cost ${cost:.3f} | log {LOG}")
