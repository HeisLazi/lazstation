# Luna execution guide — Ekse Slaan Ball

**Original planning date:** 24 September 2026. This is the historical execution guide. Current repository progress is recorded in [HANDOFF.md](HANDOFF.md) and `STATUS.md`; P00–P03 plus the MUD-01/UI-01 slices are recorded complete. Follow the current handoff rather than restarting at P00.
This guide is deliberately explicit so an executor does not have to reconstruct decisions from chat. It does not guarantee correctness: passing observable acceptance cases and reviewing the actual change are required.

## 1. Start here

Repository: `/home/lazi/Projects/personal/heisprojects/termstation`.
Owned folder: `games/touchline/`. Display name: **Ekse Slaan Ball**. Keep the existing slug `touchline` for save/manifest compatibility.

Read workspace/repository instructions and `docs/GAME-BRIEF.md`, then:

1. [DESIGN.md](DESIGN.md): intended player experience and constraints.
2. [ROADMAP.md](ROADMAP.md): milestone outcomes.
3. [IMPLEMENTATION.md](IMPLEMENTATION.md): package order, dependencies and deliverables.
4. [ENGINEERING_CONTRACTS.md](ENGINEERING_CONTRACTS.md): records, transitions and acceptance cases.

The “default first assignment is P00 only” and copyable P00 prompt below describe the original planning handoff, not the current implementation state. See [HANDOFF.md](HANDOFF.md) before assigning or implementing further work.

Newest user instructions take precedence. Within these plans, DESIGN defines behavior, IMPLEMENTATION defines package boundaries, and ENGINEERING_CONTRACTS supplies defaults. Report genuine contradictions; do not silently choose a convenient weaker requirement.

Under the original plan, the default first assignment was **P00 only**. A later instruction may explicitly authorise a range. Complete all packages in that range in order, verifying and committing coherent slices without requesting routine approval between them. This document does not authorise a full rewrite when the assigned scope is one package.

## 2. Protect the shared workspace

Before editing, inspect status, branch, worktrees and the staged diff. As of this plan, shared docs/tools are modified and `sdk/termstation_ui.py`, `tests/` and `.claude/` are untracked. Treat that as dated context, inspect again and preserve other work.

- Do not edit or stage `sdk/`, `termstation/`, `bin/`, root `tools/`, `install.sh`, other games or another worktree.
- Do not use `git add .`, `git add -A`, reset, clean, stash, amend, push or checkout unrelated work.
- If the index contains someone else's changes, preserve it and do not include those changes in your commit. Resolve ownership or use an authorised isolated worktree.
- Do not copy an untracked shared helper into your commit merely to make the repository look complete. Report its provenance/dependency accurately.
- Keep generated careers, PTY captures and large benchmark outputs under a fresh task directory in `/tmp`.
- Do not modify personal career saves. Fixtures must be synthetic, small and explicitly generated for tests.

Use game-local rule modules per the scoped architecture decision in IMPLEMENTATION. Document that exception to the brief's single-file rule in P00; it does not relax other boundaries.

## 3. Workflow for every package

1. Read the package card and previous completion evidence. Confirm dependencies actually passed.
2. Write the package's working checklist in `games/touchline/STATUS.md`: ID, base SHA, intended paths, behavior, acceptance case IDs, required commands and exclusions.
3. Inspect existing implementations and callers before choosing interfaces. Use ENGINEERING_CONTRACTS defaults unless a demonstrated problem requires a recorded revision.
4. Create a minimal reproducible failing case for the new rule or known bug. For baseline P00, reproduce and record existing behavior without repairing the game.
5. Implement one end-to-end behavior. Data → rule → state/event → presentation when applicable. Do not create all future folders or empty services.
6. Run targeted tests. Fix the cause of failures; do not remove assertions, widen tolerances without evidence, or relabel a broken required feature as out of scope.
7. Run the package regression set. UI/integration work also needs both PTY sizes, saved-state checks and doctor. Inspect actual frames, not just command exit status.
8. Review the diff for scope, placeholder code, unintended writes, hidden information leakage and migration risks.
9. Update STATUS with evidence and limitations. Stage explicit owned files, review the staged diff, commit and inspect post-commit status.
10. Report the result and next package. Continue only within the authorised range; do not require new approval for ordinary fixes in that range.

### Completion status vocabulary

Use `not_started`, `in_progress`, `verification_failed`, `blocked` or `complete`. These are project document fields, not tool goal statuses. `complete` requires the package's observable gates. Existing baseline defects do not make P00 fail if correctly reproduced/documented; failure to execute a required check due to an unresolved dependency is a verification gap, not a pass.

For an external blocker, record the exact action/error, affected tests and what can still proceed. Continue independent work. Ask the user only when a real decision/access change is necessary. Do not ask them to run commands you can execute.

## 4. P00 exact work order

1. Inspect Git state and Python version; read current manifest, SDK imports, tests and PTY scenario.
2. Confirm `main.py` imports and what exists only in the working tree. Record committed versus uncommitted prerequisites.
3. Run the current unit tests with isolated environment variables.
4. Run `season_scenario.json` at both sizes from fresh, different save directories. Inspect home, tactics, full-time and season-review frames, including all side borders.
5. Run doctor under isolated XDG directories. Record each failure accurately.
6. Add `games/touchline/benchmarks.py`: explicit CLI, no import-time work; seed/count arguments; JSON output with version/environment/elapsed time/counts; optional explicit output destination; no career save writes or awards. Use SDK-boundary patches in this legacy harness where needed and disclose them. Production simulation must later be pure.
7. Add a small game-local fixture generator for fresh/live/midseason/finished synthetic v2 saves. Validate their stated lifecycle state, serialize/reload and check equality. Keep fixture provenance and engine version. The fixture generator is not a migration.
8. Add `games/touchline/ARCHITECTURE.md` documenting the local-module decision and legacy boundary; `BASELINE.md` recording actual evidence, defects and benchmark method; and `STATUS.md` recording P00.
9. Add focused harness/fixture checks only where needed. Do not change `main.py` simulation behavior, introduce new dependencies or repair shared tools in P00.
10. Review and commit explicit created/changed game paths. Report P01's prerequisites and any unresolved baseline limitations.

### Existing commands, checked against the current CLI during planning

These are future execution instructions; their inclusion is not a claim they passed. Reinspect CLI changes before using them. Run blocks sequentially in one shell, or explicitly retain the two task variables between shell calls. A new attempt must get a fresh temporary directory.

```bash
cd /home/lazi/Projects/personal/heisprojects/termstation
esb_repo="$(pwd)"
esb_run="$(mktemp -d /tmp/esb-p00.XXXXXX)"
export PYTHONDONTWRITEBYTECODE=1
export TERM=xterm-256color
export TERMSTATION_ACHIEVEMENTS=""
export TERMSTATION_SAVE_DIR="$esb_run/unit-save"
export TERMSTATION_SHARED_DIR="$esb_run/shared"
export XDG_DATA_HOME="$esb_run/xdg-data"
export XDG_CONFIG_HOME="$esb_run/xdg-config"
export XDG_STATE_HOME="$esb_run/xdg-state"
export XDG_CACHE_HOME="$esb_run/xdg-cache"
python3 --version
git status --short --branch
git diff --cached --name-status
git worktree list
python3 -m unittest games.touchline.test_game
```

```bash
cd "$esb_repo/games/touchline"
TERMSTATION=1 TERMSTATION_NAME="Ekse Slaan Ball" \
TERMSTATION_SAVE_DIR="$esb_run/pty80-save" PYTHONPATH="$esb_repo/sdk" \
python3 ../../tools/ptytest.py 80 24 --script season_scenario.json \
  --artifacts "$esb_run/pty80"

TERMSTATION=1 TERMSTATION_NAME="Ekse Slaan Ball" \
TERMSTATION_SAVE_DIR="$esb_run/pty110-save" PYTHONPATH="$esb_repo/sdk" \
python3 ../../tools/ptytest.py 110 30 --script season_scenario.json \
  --artifacts "$esb_run/pty110"

cd "$esb_repo"
python3 -m termstation doctor
git diff --check
```

Capture each command's exit code and output before executing the next; never infer all commands passed from the last command's exit status. PTY named frames being present does not prove all border cells are correct. Read them and record remaining replay limitations. `TERMSTATION_SAVE_DIR` is mandatory; XDG isolation alone does not isolate standalone game saves.

New domain tests should use a game-local `checks/` folder and absolute imports from `games.touchline.esb`. Once it exists, run from the repository root with `python3 -m unittest discover -s games/touchline/checks -p 'test_*.py'`. Do not invent successful output before the tests exist.

## 5. Boundaries that prevent false completion

| Tempting shortcut | Required behavior instead |
|---|---|
| Add a formation bonus and print a movement explanation. | Simulate the movement and derive the explanation from recorded state. |
| Choose a score and generate matching highlights afterwards. | Actions produce chances and outcomes; score/stat projections reconcile from events. |
| Narrow random scout ranges every time a report is opened. | Update from new authorised evidence; repeated views are read-only. |
| Increase every attribute when a player is happy. | Change only supported decisions/readiness paths within the shared effect budget. |
| Copy a mentor's traits to a mentee or force friendships. | Record opportunities, consent, contacts and gradual selective learning. |
| Add many screens with stub buttons. | Complete a smaller usable path, record the rest as unimplemented. |
| Return a default on corrupt saves or silently drop fields. | Preserve the original, report the failure and test a defined migration. |
| Call code deterministic because it uses one seed. | Prove process replay, save/resume and independence from presentation/reporting. |
| Use a perfect AI scout/manager to make implementation easy. | Route AI decisions through its club's information and authority view. |
| Make a flaky outcome assertion pass by choosing a convenient seed. | Assert deterministic mechanisms; assess uncertain outcomes across held-out seed sets. |

Tests may patch clocks, SDK persistence or deterministic draws at explicit boundaries. They must not mock away the football, relationship or transaction rule being claimed as working. A forced draw verifies one branch; it does not establish a realistic distribution.

## 6. What to do when stuck

- **Required dependency absent:** identify it from imports/runtime, preserve shared files, record the affected gate and continue independent package work. Do not replace a missing renderer with a stub and declare PTY success.
- **Mechanism exists but results are implausible:** inspect the event trace and units first; test smaller scenarios before adding compensating bonuses.
- **Performance target missed:** profile the measured workload; preserve rules while optimising data access/update frequency. Document any proposed fidelity change before applying it.
- **Data/model ambiguity:** choose the smallest default consistent with the design, record the choice and its test. Escalate only consequential product changes or unresolved contradictions.
- **Tests fail after a change:** reproduce on the current change, locate the first divergent event, fix and rerun relevant checks. Preserve a regression case when it captures a real rule failure.
- **Scope proves too large:** split the package into named sub-slices with explicit remaining gates. Do not call the parent complete. Continue work within the authorised scope.
- **Context nearly exhausted:** update STATUS with exact progress, commands, current errors and next action. Resuming starts there; it must not redo completed packages or abandon the original scope.

## 7. Completion report template

```text
Package/sub-slice:
Base SHA and final commit:
Implemented behavior:
Acceptance case IDs and actual results:
Commands/exit codes and artifact locations:
Save/API/schema changes:
Known baseline issues versus new failures:
Still unsupported / remaining package gates:
Owned committed files; unrelated work preserved:
Next exact action:
```

Do not claim gameplay verification for documentation-only changes. Do not push or alter other worktrees. The user's choice of Luna is an execution choice; it does not reduce the acceptance standard.

## 8. Copyable starting prompt

```text
Implement P00 for Ekse Slaan Ball in
/home/lazi/Projects/personal/heisprojects/termstation.
Read workspace instructions, docs/GAME-BRIEF.md and games/touchline/LUNA_HANDOFF.md.
Follow its reading order, exact P00 work order and completion report template.
Only edit games/touchline. Preserve all unrelated changes and saves.
Use isolated synthetic test data. Establish the actual baseline and benchmark
evidence, record architecture/known issues, and commit only reviewed owned files.
Do not implement P01 or new gameplay in this assignment. Do not ask me to run
commands or approve routine fixes within scope. If required verification is
blocked, report the exact blocker and do all independent work you can.
```
