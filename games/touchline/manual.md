# Ekse Slaan Ball

You are the manager of one of six original Sable Coast clubs. A career runs
through ten home-and-away league rounds, then rolls into a new season with
player development, contracts, finances and academy arrivals carried forward.

## The desk

Choose a club to start. The Home page shows your next fixture, current plan,
table position, board confidence, transfer room and the latest state-driven
news. The save updates after each decision and match window.

| Key | Page or action |
|---|---|
| `1`–`7` | Home, Squad, Plan, Training, Market, Table, Logs |
| `M` | Start or resume matchday |
| `?` | In-game controls and system guide |
| `Q` | Save and quit |
| `Tab` | Move to the next main page |

## Squad and selection

Browse the roster with Up/Down. Press `X` to toggle a starter. If the XI is
full, the selected player replaces the weakest like-for-like starter; the
match engine fills any remaining gaps. `!` means a player is still injured.
Press `V` to accept a fair incoming offer for the selected player. Keep at
least eleven players registered.

Fitness is short-term readiness. Sharpness reflects match readiness. Form is
recent performance. Morale and manager trust respond to results, minutes and
ratings. Player attributes and potential are individual; the broad position
rating is only a quick comparison.

## Tactical plan

The Plan page changes the shape in and out of possession independently:

| Key | Instruction |
|---|---|
| `I` / `O` | Cycle the in-possession / out-of-possession shape |
| `P` | Press intensity |
| `L` | Defensive line |
| `W` | Width |
| `B` | Build-up style |
| `T` | Tempo |
| Left/Right | Move the currently focused instruction |

Every plan has a visible trade-off. High pressure can create high regains but
uses more energy. A high line compresses space while giving direct balls a
route behind. Short build-up protects possession but asks players to pass under
pressure. Width opens crossing lanes and can leave wider transition space.
Formation profiles also feed the match model: 3-5-2 adds a midfield screen but
leaves more room behind its back three; 4-3-3 adds box presence; 4-4-2 balances
forward occupation and midfield cover. The Plan page explains the selected
shape, and the profile values live beside the formation slots in `content.py`.

## Weekly preparation

On Training, use Up/Down to choose a focus and Enter to set it. Press `I` to
cycle intensity. Training applies once when matchday starts. Recovery improves
readiness; technical sessions build skill or tactical familiarity; high
intensity increases fatigue and injury exposure. Those are probabilities and
costs, not automatic injuries.

## Matchday

Press Enter to play the next 15-minute window. The event feed records the
phase, zone, action, tactical context, chance quality, and result. The same
ledger drives goals, shots, xG, player performances, the report and career
news. Better finishing changes conversion; it does not manufacture better
chances. The opposing manager can adapt to the score late in the match.

| Key | Match action |
|---|---|
| `Enter` | Play the next 15 minutes; at full time, settle the whole round |
| `1` | Cycle your press |
| `2` | Cycle your defensive line |
| `3` | Cycle your width |
| `4` | Choose a bench player for a substitution (five per match) |
| `Q` | Quick-sim the remaining periods with the same match engine |
| `Esc` | Pause and return to Home; `M` resumes |

At full time, press Enter again to update all three fixtures, the table,
finances, player form, morale, trust and injury outlook for the round.

## Recruitment

Scout a target with `S`. The report has a confidence level and ranges for
skills, value, wages and potential; further reports cost £2k and reduce
uncertainty. Press `O` to negotiate. The arrows adjust transfer fee and weekly
wage separately. A counteroffer exposes the agent's changed terms; `C` accepts
the counter. The club enforces cash, transfer and wage ceilings. Incoming
players become part of the same persistent squad and can be trained, selected
or sold later.

## League and career

The table sorts by points, goal difference, goals scored, then club name. The
current proof league has six clubs and ten rounds; each opponent is met home
and away. Complete the final round, review the season, then press Enter on Home
to begin the next one. Players age, deals run down, and every club receives a
new academy prospect. The same clubs and competition continue across seasons.

The career autosaves in the console's selected save slot. Quit with `Q` at a
desk page; an active match can be resumed from Home.
