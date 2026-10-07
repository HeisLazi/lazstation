# Haven Story - Story Mode (mod source)

This folder is the versioned source of the Haven Story mod. The installed
copy the game actually loads lives at:

```
~/games/cataclysm/cataclysmdda-0.I/data/mods/haven_story/
```

Run `../install_story.sh` to (re)install it and to create the ready-made
`HavenStory` world. Never edit the installed copy - edit here, reinstall.

## Files

| file | what it is | how to edit it |
| --- | --- | --- |
| `modinfo.json` | mod identity + dependency on `dda` | name/version only |
| `scenario.json` | `haven_bound` start: shelter, intro mission granted | description text is the pitch - keep it short |
| `items.json` | 3 keepsakes: flyer, chit, roadmap | descriptions carry lore, keep each under ~500 chars |
| `missions_intro.json` | `MISSION_HAVEN_INTRO` (auto-granted, survive day 1) | the endgoal speech lives in `dialogue.offer` |
| `missions_intro.json` | `MISSION_HAVEN_INTRO` (auto-granted, survive day 1) | the endgoal speech lives in `description` (mission log) |
| `missions_act1.json` | Act 1 hub: Q1 -> Q2 -> Q3 -> Q4 chain + 2 optional sides | every mission needs all 9 `dialogue` keys |
| `missions_side_vex.json` | Side Arc A (mad scientist): VEX1 -> VEX2 -> VEX3A / VEX3B choice | finales are pick-one; text says so |

## Gotchas (learned the hard way)

- **No `dialogue` on `ORIGIN_GAME_START` missions.** The engine never
  reads it (no NPC will ever speak it) and reports it as an unread-data
  error at character creation. Zero of 37 vanilla game-start missions
  have one. Put the briefing in `description` instead - it shows in the
  mission log, which is exactly where a game-start goal belongs.

## Rules this mod follows (CDDA 0.I)

- New ids are prefixed `haven_` / `MISSION_HAVEN_` - never touch vanilla ids.
- No mapgen, no custom NPCs, no talk overrides in v1: missions use
  `ORIGIN_GAME_START` (scenario-granted), `ORIGIN_OPENER_NPC` /
  `ORIGIN_ANY_NPC` (any survivor can offer) and `ORIGIN_SECONDARY`
  (followup chains). This keeps the mod sandbox-safe and load-safe.
- Quest web, not quest line: Q1's chit unlocks Q2's trust (Micah), Q2 or
  Side B each produce the `alternator_car` Q3 needs. Two routes, one tower.
- Validate after every edit:

```bash
python3 -m json.tool haven_story/missions_act1.json > /dev/null
cd ~/games/cataclysm/cataclysmdda-0.I && ./cataclysm --check-mods haven_story
```
