# LLM playtesting

Scripted bots only prove what they were scripted to do. These tools have LLMs
**play** a game through a real terminal, deciding turn by turn from the screen
alone and narrating what they think and feel. Stronger models then review the
sessions. It was built for Beastling's Tournament mode ("Poke and Mon"), but
the player harness works on any screen-driven game.

## The loop

1. **Freeze the build** so every session in a round plays the same code:

       git archive HEAD sdk games/beastling tools | tar -x -C /tmp/build-abc123
       export GAME_ROOT=/tmp/build-abc123

2. **Play** (system 1) — one session per persona:

       python3 tools/llm_playtest/llm_player.py casual 70 66 24 oc:opencode/big-pickle
       python3 tools/llm_playtest/llm_player.py minmaxer 70 66 24 gemini:gemini-flash-lite-latest
       VISION=1 python3 tools/llm_playtest/llm_player.py visual 40 66 24 gemini:gemini-3.5-flash

   Personas: `casual`, `minmaxer`, `spammer` (tests whether one repeated move
   wins), `visual` (plays from colour screenshots). Logs land in `.playtests/`
   (gitignored), one JSON line per decision: screen, input, thought, feeling.

3. **Review** (system 2) — what was fun, deep, confusing; ranked changes:

       python3 tools/llm_playtest/brain_review.py both
       # next round: score the fixes against the last round's ranked list
       python3 tools/llm_playtest/brain_review.py agy --prev last/top.md \
           --prev-dir last/ --changes changes.md --notes harness_notes.md

4. **Measure** what an LLM session can't: whether careful play beats spam,
   with the real economy (prizes, coins, Infirmary):

       python3 games/beastling/sim/district_sim.py 200 new

5. **Check screens** at the 66x24 minimum (the row budget is tight):

       python3 games/beastling/sim/seed_district.py /tmp/s worst
       python3 tools/llm_playtest/shot.py 66 24 2,4 infirmary.png --save /tmp/s

## Models and keys

- `oc:<model>` runs `opencode run --agent build -m <model>`. Free; about 13 s a
  decision with `opencode/big-pickle`. **One session at a time**: parallel
  opencode runs lock its database.
- `gemini:<model>` needs `GEMINI_API_KEY` (else the opencode config's Google
  key). Free-tier quotas are per model per day (flash-lite: 500 requests); a
  spent quota ends the session. `RESUME=1` continues a cut-short session.
- Anything else is an OpenRouter model (`OPENROUTER_API_KEY`).

Keys are read at call time and never printed or logged.

## Reading the results

Judge the game, not the model: a different player model plays differently.
Check a reviewer's claims against the logs before acting on them (one round-2
claim, "the swap preview ignores coverage moves", was false; the preview had
said "KO'd in 1" and the players swapped in anyway).
