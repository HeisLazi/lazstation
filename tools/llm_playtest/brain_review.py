"""System 2: stronger models review what the LLM players (llm_player.py)
experienced -- fun, depth, confusion, economy -- citing step numbers.

usage: brain_review.py [agy|gemini|both] [--dir D] [--prev FILE] [--prev-dir D]
                       [--changes FILE] [--notes FILE] [--shots D]

  --dir       playtest logs to review (default: <repo>/.playtests)
  --prev      the previous round's ranked change list -> a RESOLVED/UNRESOLVED scorecard
  --prev-dir  the previous round's logs, for a feelings comparison
  --changes   what the developer changed since the previous round
  --notes     harness artifacts the reviewer must not blame on the game
  --shots     PNG screenshots for a visual review (Gemini only)

Writes <dir>/brain_agy.md and/or <dir>/brain_gemini.md. agy runs `agy -p=...`;
Gemini reads GEMINI_API_KEY (else the opencode config) and walks a model list,
skipping any whose daily quota is spent.
"""
import argparse, base64, collections, glob, json, os, shutil, subprocess, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
GEMINI_MODELS = ("gemini-flash-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite")

ap = argparse.ArgumentParser()
ap.add_argument("which", nargs="?", default="agy", choices=("agy", "gemini", "both"))
ap.add_argument("--dir", default=os.environ.get("PLAYTEST_DIR", os.path.join(REPO, ".playtests")))
ap.add_argument("--prev")
ap.add_argument("--prev-dir")
ap.add_argument("--changes")
ap.add_argument("--notes")
ap.add_argument("--shots")
a = ap.parse_args()


def personas(folder):
    return sorted(os.path.basename(p)[:-6] for p in glob.glob(f"{folder}/*.jsonl"))


def rows_of(folder, p):
    return [json.loads(line) for line in open(f"{folder}/{p}.jsonl") if line.strip()]


def feel_table(folder):
    out = []
    for p in personas(folder):
        dec = [r for r in rows_of(folder, p) if "thought" in r]
        c = collections.Counter(r["feel"] for r in dec)
        out.append(f"  {p:<9} {len(dec):>3} decisions  " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    return "\n".join(out) or "  (none)"


def digest(folder):
    parts = []
    for p in personas(folder):
        rows = rows_of(folder, p)
        dec = [r for r in rows if "thought" in r]
        parts.append(f"\n===== PLAYER: {p} ({len(dec)} decisions) =====")
        parts.append("Timeline (step | typed | feeling | thought):")
        for r in dec:
            parts.append(f"  {r['step']:>3} | {r['input']!r:<8} | {r['feel']:<10} | {r['thought']}")
        flagged = [r for r in dec if r["feel"] in ("confused", "frustrated", "bored")][:7]
        for r in flagged + dec[:1]:
            parts.append(f"\n--- screen at step {r['step']} (player felt {r['feel']}: {r['thought'][:80]}) ---")
            parts.append(r["screen"])
        for r in rows:
            if r.get("event"):
                parts.append(f"\n!!! EVENT {r['event']} at step {r['step']}:\n{r.get('screen', '')}")
    return "\n".join(parts)


def read(path):
    return open(path).read().strip() if path else ""


INTRO = """You are reviewing LLM playtests of "Poke and Mon", a terminal creature-battling game. Its Tournament mode is \
a hub ("the Arena District": Arena Gate, Squad Hall, Market, Infirmary, Yard, Hall of Fame), a 6-round bracket of \
team fights, per-move PP that persists between fights, support moves, AI that switches and heals, and prize coins \
spent on healing/PP/items. LLM players (not scripted bots) played it through a real terminal and narrated their \
reasoning and feelings. Sessions may end early for API reasons -- not a game problem. Judge the game, not the model."""

FRESH = """Write an honest, evidence-based review. Cite step numbers and quote screens/thoughts; never invent.
1. FUN: for each player, when were they engaged and when did interest drop?
2. DEPTH: does repeating one action win, or do players weigh real choices (matchups, PP, swaps, coins)? Quote them.
3. CONFUSION / UX: anything unclear, cut off, blank or misleading (quote it).
4. ECONOMY & DIFFICULTY: prices, prizes, whether resources felt tight or irrelevant.
5. TOP 8 CHANGES ranked by impact, one sentence each with the evidence.
End with a one-paragraph verdict: would this hold a player's attention, and what is the biggest gap?"""

SCORED = """The previous round's ranked list of changes was:
{prev}

{changes}

Feelings per player, previous round vs this one:
PREVIOUS:
{feel_prev}
THIS ROUND:
{feel_now}

Write an honest, evidence-based review of THIS round. Cite step numbers and quote screens/thoughts. If a situation \
never came up, say "not exercised" rather than guessing.
1. SCORECARD: each previous item -- RESOLVED / PARTLY / UNRESOLVED / REGRESSED / NOT EXERCISED -- with evidence.
2. NEW PROBLEMS (bugs, confusion, anything cut off, blank or misleading -- quote it).
3. DEPTH: do players weigh real choices? Quote thoughts. Any single-action win?
4. FUN: engaged vs bored, compared with the previous round.
5. TOP 5 NEXT CHANGES, ranked by impact, one sentence each with evidence.
End with a one-paragraph verdict: is the Tournament mode a game worth playing, and what is the biggest gap left?"""


def gemini_key():
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        key = json.load(open(os.path.expanduser("~/.local/share/opencode/auth.json")))["google"]["key"]
    return key


def gemini(prompt, images=()):
    parts = [{"text": prompt}]
    for p in images:
        parts.append({"text": f"[screenshot: {os.path.basename(p)}]"})
        parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(open(p, "rb").read()).decode()}})
    body = json.dumps({"contents": [{"role": "user", "parts": parts}],
                       "generationConfig": {"maxOutputTokens": 12000, "temperature": 0.3}}).encode()
    err, key = "", gemini_key()
    for model in GEMINI_MODELS:
        for attempt in range(4):
            req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                         data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    d = json.load(r)
                cand = (d.get("candidates") or [{}])[0]
                text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])
                               if not p.get("thought"))
                if text.strip():
                    cut = "" if cand.get("finishReason") in (None, "STOP") else f"\n\n[cut short: {cand['finishReason']}]"
                    return f"[model: {model}]\n\n{text}{cut}"
                err = f"{model}: empty ({cand.get('finishReason')})"
            except urllib.error.HTTPError as e:
                txt = e.read()[:400].decode("utf-8", "replace")
                err = f"{model}: HTTP {e.code} {txt[:120]}"
                if e.code == 429 and "quota" in txt.lower():
                    break                      # a daily quota won't refill in minutes: next model
                if e.code == 429 or e.code >= 500:
                    time.sleep(20 + attempt * 20)
                    continue
                break
            except Exception as e:
                err = f"{model}: {e}"
                time.sleep(10)
    return f"[gemini failed: {err}]"


def agy(prompt):
    exe = shutil.which("agy") or os.path.expanduser("~/.local/bin/agy")
    r = subprocess.run([exe, "-p=" + prompt, "--effort", "high"], capture_output=True, text=True,
                       timeout=1200, cwd=tempfile.mkdtemp(prefix="brain-"))
    return r.stdout or r.stderr


if __name__ == "__main__":
    body = digest(a.dir)
    notes = read(a.notes)
    head = INTRO + (f"\nHARNESS ARTIFACTS (not the game):\n{notes}" if notes else "")
    if a.prev:
        task = SCORED.format(prev=read(a.prev), changes=read(a.changes) or "(no change notes given)",
                             feel_prev=feel_table(a.prev_dir) if a.prev_dir else "  (not given)",
                             feel_now=feel_table(a.dir))
    else:
        task = FRESH
    prompt = f"{head}\n\n{task}"
    print("digest chars:", len(body))
    if a.which in ("gemini", "both"):
        shots = sorted(glob.glob(f"{a.shots}/*.png")) if a.shots else []
        extra = ("\n\nYou also get colour screenshots. Add a VISUAL REVIEW section: colour, contrast, alignment, "
                 "readability, anything cramped or unclear." if shots else "")
        out = gemini(prompt + extra + "\n\n" + body, shots)
        open(f"{a.dir}/brain_gemini.md", "w").write(out)
        print("gemini review:", len(out), "chars ->", f"{a.dir}/brain_gemini.md")
    if a.which in ("agy", "both"):
        out = agy(prompt + "\n\n" + body)
        open(f"{a.dir}/brain_agy.md", "w").write(out)
        print("agy review:", len(out), "chars ->", f"{a.dir}/brain_agy.md")
