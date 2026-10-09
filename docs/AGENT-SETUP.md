# AGENT SETUP GUIDE — LAZSTATION game shelf

You are an AI coding agent on a fresh CachyOS/Arch machine. The human has
pulled this repo and wants every shelf game installed and boot-verified.
Work top to bottom. Anything needing the human's sudo password or Steam
login must be handed to them as a copy-paste block — never stall waiting.

## 0. Orient

```bash
ls ~/Projects/lazstation/games/          # one dir per game, each has game.toml
python3 -m termstation doctor            # from the repo root
```

`doctor` is the checklist: `✗ ... cannot find 'X'` means that game is not
installed yet. Goal state: 22/22 `✓`. Note `doctor` TRUSTS absolute paths
without checking they exist — verify those with `ls` yourself
(dwarf-fortress, dfhack, cataclysm run.sh target, rogue binary).

## 1. Official repo packages (human runs this — needs sudo)

```fish
sudo pacman -S crawl-tiles nethack
```

Verify headless: `crawl-tiles --version` prints `Crawl version ...`.
NetHack needs a pty + `script(1)`; it must get past `Unable to open
SYSCF_FILE` into curses mode (see §4 if that error appears).

## 2. AUR packages (build as the user with makepkg, human installs)

No yay/paru on these machines. For each of `brogue-ce`,
`openfootmanager-bin`, `paper-soccer`:

```bash
git clone https://aur.archlinux.org/<pkg>.git /tmp/aur-build/<pkg>
cd /tmp/aur-build/<pkg> && makepkg --noconfirm
```

Known build deps (human): `boost` (paper-soccer), `webkit2gtk-4.1`
(openfootmanager). Then the human runs:

```fish
sudo pacman -U /tmp/aur-build/<pkg>/*.pkg.tar.zst
```

Expected binaries (must match the `entry` in each game.toml):
`/usr/bin/brogue-ce`, `/usr/bin/openfootmanager`, `/usr/bin/paper-soccer`.
If a PKGBUILD ever renames one, update the game.toml, not the system.

Verify headless: `paper-soccer` with no args prints help, exit 0.
`brogue-ce` / `openfootmanager` are SDL/GTK — `SDL_VIDEODRIVER=dummy
timeout 10 brogue-ce` must exit without missing-lib errors; full visual
boot needs the human's display (ask them to launch once each).

## 3. Steam entries (human only)

Entries are `steam steam://rungameid/<id>` — nothing to configure, they
boot once the game is owned + installed:

| slug | id | status |
| --- | --- | --- |
| caves-of-qud | 333640 | paid, native Linux |
| slay-the-spire-2 | 2868840 | paid, native Linux |
| warsim | 659540 | paid, Windows-only (Proton) |
| neo-scavenger | 248860 | paid, native Linux (free demo: 270680) |

`which steam` must exist; the human buys/installs. Do NOT mark these
broken — they resolve via doctor as long as the client exists.

## 4. NetHack quirk (Arch package, human runs)

Symptom: game stalls on `Unable to open SYSCF_FILE`, blank screen.
The package ships sysconf at `/etc/nethack/sysconf` but the binary reads
`/var/games/nethack/sysconf`, and scoreboards need the `games` group:

```fish
sudo ln -sf /etc/nethack/sysconf /var/games/nethack/sysconf
sudo usermod -aG games $USER   # re-login after this
```

## 5. Manual installs (human)

- **aurora-4x**: Wine game, files only on https://aurora2.pentarch.org
  (was down Oct 2026 — retry). Full install + patch into
  `~/Games/aurora4x/` so `Aurora.exe` exists. Guide: `games/aurora-4x/INSTALL.md`.
  `run.sh` prints the guide itself if the exe is missing (exit 3, by design).
- **rogue**: local Qt build, see `docs/ROGUE-BUILD-NOTES.md`. Binary:
  `~/Games/Rogue-Collection-main/build/release/rogue-collection`.
  Crashes headless (upstream null-screen bug) — verify on a display.
- **dwarf-fortress / dfhack**: `~/Games/df/{run_df,dfhack}` (plus DFHack
  release matching DF version). **cataclysm**: `~/Games/cdda/cataclysm-tiles`.
  Copy these trees from the old machine; they are not in git.

## 6. Console changes in this repo you should know

- Shelves/compartments: `termstation/library.py` (`COMPARTMENTS`,
  `compartment_for`) + `termstation/carousel.py` (`c` key,
  `cycle_compartment`, config persistence). Every manifest MUST carry a
  tag that maps to a shelf — enforced by
  `tests/test_compartments.py::test_every_bundled_game_has_a_shelf`.
  Cabinet fallback exists but no game may use it.
- `tools/smoke.sh` skips dirs without `main.py` (external entries are
  covered by doctor, not pty-render).

## 7. Accept

```bash
python3 -m termstation doctor            # 22/22 ✓
python3 -m unittest discover -s tests    # 16 tests OK
bash tools/smoke.sh                      # all green EXCEPT:
```

Known pre-existing failure (fails on pristine tree, not yours to fix
unless asked): `unbound frame missing` — the wip stub exits 1 on smoke's
`1` key. Everything else must pass. Then `git add -A && git commit`
with a plain-English message and push.
