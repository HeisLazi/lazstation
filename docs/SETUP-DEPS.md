# LAZSTATION — machine setup

The console itself needs only **Python 3.11+** and a terminal. The external
games it shelves need their own installs. After cloning on a new machine,
work through the list for the games you want. Entries whose program is
missing fail `lazstation doctor` with `cannot find ...` — that is the
checklist telling you what is left.

## Official repos

```bash
sudo pacman -S crawl-tiles nethack
```

## AUR (build with makepkg, install the resulting package)

```bash
git clone https://aur.archlinux.org/brogue-ce.git && cd brogue-ce && makepkg -si
git clone https://aur.archlinux.org/openfootmanager-bin.git && cd openfootmanager-bin && makepkg -si
git clone https://aur.archlinux.org/paper-soccer.git && cd paper-soccer && makepkg -si
```

Known build-time deps: `boost` (paper-soccer), `webkit2gtk-4.1` (openfootmanager).

## Steam (install from the client)

| slug | app id | notes |
| --- | --- | --- |
| caves-of-qud | 333640 | paid, native Linux |
| slay-the-spire-2 | 2868840 | paid, native Linux |
| warsim | 659540 | paid, Windows-only → Proton |
| neo-scavenger | 248860 | paid, native Linux (free demo: 270680) |

Entries use `steam steam://rungameid/<id>`, so they boot as soon as the game
is owned and installed. Nothing to configure.

## Manual

- **Aurora 4X** (`aurora-4x`): free Windows game under Wine. Follow
  `games/aurora-4x/INSTALL.md`.
- **Rogue** (`rogue`): built from source (Qt5 + SDL). See `BUILD-NOTES.md`
  below if you ever need to rebuild it.

## NetHack quirk (Arch package)

```bash
sudo ln -sf /etc/nethack/sysconf /var/games/nethack/sysconf
sudo usermod -aG games "$USER"   # re-login after this
```

Without the symlink the game stalls on `Unable to open SYSCF_FILE`;
without the group, scoreboards don't save (harmless warning otherwise).

## Games that live outside package managers

| slug | lives at |
| --- | --- |
| dwarf-fortress, dwarf-fortress-dfhack | `~/Games/df` (`run_df`, `dfhack`) |
| cataclysm | `~/Games/cdda` (`cataclysm-tiles`) |
| rogue | `~/Games/Rogue-Collection-main/build/release/rogue-collection` |

Copy/symlink your installs to the same paths and the entries resolve.

## Verify

```bash
lazstation doctor          # every manifest resolves
python3 -m unittest discover -s tests
bash tools/smoke.sh
```
