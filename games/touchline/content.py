"""Editable Ekse Slaan Ball league and narrative data.

Edit club details, roster rows, prospect rows, formations, tactics, or the
round-by-round fixtures here. Roster rows are name, position, pace, passing,
finishing, defending, stamina, age, and fee in thousands; simulation rules live
in main.py.
"""

CLUBS = [
    dict(id="BRP", name="Brineport Rovers", budget=230,
         ground="Saltglass Park", style="A quick side from the old docks."),
    dict(id="GLA", name="Glasswind Athletic", budget=210,
         ground="The Lantern Ground", style="Patient passing, sharp wide play."),
    dict(id="LVA", name="Lantern Vale FC", budget=195,
         ground="Vale End", style="A stubborn club from the upper valley."),
    dict(id="CWC", name="Copperworks City", budget=280,
         ground="Foundry Field", style="Big support and an even bigger wage bill."),
    dict(id="RDW", name="Red Dune Wanderers", budget=185,
         ground="The Suncourt", style="Fast breaks across a wide, dry pitch."),
    dict(id="BWA", name="Breakwater Albion", budget=250,
         ground="Breaker Lane", style="Strong in the air, calm under pressure."),
]

# Each club starts with one goalkeeper, four defenders, four midfielders, one
# winger, and two forwards. Add or retune a row without touching the engine.
ROSTER_ROWS = {
    "BRP": [
        ("Enno Vale", "GK", 52, 67, 16, 74, 61, 27, 45),
        ("Temba Uus", "DEF", 69, 60, 34, 72, 74, 25, 61),
        ("Rafi Nair", "DEF", 64, 67, 28, 68, 79, 23, 55),
        ("Calen Moyo", "DEF", 71, 55, 30, 70, 70, 29, 58),
        ("Yaro Kess", "DEF", 59, 62, 26, 75, 65, 31, 43),
        ("Ansel Vika", "MID", 66, 74, 48, 57, 78, 24, 68),
        ("Dira Ndem", "MID", 72, 68, 58, 54, 75, 22, 77),
        ("Lomani Ilse", "MID", 63, 79, 44, 61, 82, 26, 71),
        ("Fen Sable", "MID", 75, 66, 51, 53, 69, 21, 65),
        ("Oren Dask", "WNG", 84, 67, 61, 40, 80, 23, 108),
        ("Miko Jarden", "FWD", 76, 56, 78, 32, 73, 25, 115),
        ("Kesa Amel", "FWD", 70, 64, 74, 29, 79, 20, 120),
    ],
    "GLA": [
        ("Maren Sol", "GK", 58, 73, 14, 78, 64, 26, 58),
        ("Bastian Quill", "DEF", 62, 70, 31, 75, 76, 28, 65),
        ("Nia Voss", "DEF", 74, 68, 27, 71, 80, 22, 83),
        ("Sello Kade", "DEF", 67, 74, 36, 67, 72, 24, 76),
        ("Ruen Malk", "DEF", 55, 62, 22, 77, 68, 32, 38),
        ("Elior Tane", "MID", 68, 82, 51, 58, 77, 23, 94),
        ("Pia Noss", "MID", 73, 78, 60, 52, 74, 21, 101),
        ("Dalen Or", "MID", 61, 85, 43, 65, 81, 27, 88),
        ("Venn Aru", "MID", 77, 71, 57, 56, 70, 25, 91),
        ("Lio Fenner", "WNG", 88, 75, 66, 39, 78, 20, 130),
        ("Aren Miret", "FWD", 79, 69, 82, 30, 72, 24, 142),
        ("Zola Kint", "FWD", 72, 72, 77, 37, 75, 29, 116),
    ],
    "LVA": [
        ("Tarin Eske", "GK", 48, 63, 12, 77, 59, 30, 37),
        ("Koro Sen", "DEF", 64, 58, 23, 79, 77, 26, 60),
        ("Mira Daal", "DEF", 71, 64, 35, 73, 73, 22, 78),
        ("Jori Pell", "DEF", 57, 69, 24, 82, 70, 31, 50),
        ("Niko Rell", "DEF", 68, 61, 31, 74, 80, 24, 69),
        ("Sana Vei", "MID", 70, 73, 47, 69, 81, 25, 84),
        ("Eren Moss", "MID", 58, 81, 39, 73, 79, 28, 75),
        ("Pela Dune", "MID", 75, 69, 56, 62, 74, 23, 88),
        ("Omi Taret", "MID", 65, 76, 45, 71, 84, 20, 80),
        ("Suri Bell", "WNG", 82, 70, 63, 48, 77, 22, 112),
        ("Davi Harel", "FWD", 72, 61, 80, 41, 71, 27, 111),
        ("Toma Esh", "FWD", 77, 68, 76, 35, 78, 24, 123),
    ],
    "CWC": [
        ("Orin Taal", "GK", 63, 72, 13, 81, 68, 25, 80),
        ("Vey Korr", "DEF", 70, 69, 34, 79, 82, 24, 104),
        ("Hana Venn", "DEF", 76, 74, 30, 73, 79, 22, 118),
        ("Malo Senn", "DEF", 66, 62, 28, 83, 75, 29, 90),
        ("Ivo Marr", "DEF", 60, 71, 32, 77, 85, 27, 95),
        ("Rhea Tovin", "MID", 78, 84, 63, 63, 83, 23, 145),
        ("Jalen Orr", "MID", 69, 79, 57, 73, 86, 26, 132),
        ("Mina Kade", "MID", 74, 82, 54, 68, 81, 21, 139),
        ("Teren Vaal", "MID", 64, 76, 66, 71, 78, 28, 121),
        ("Kei Rusk", "WNG", 87, 78, 72, 46, 84, 24, 169),
        ("Olan Mase", "FWD", 81, 73, 86, 39, 82, 25, 188),
        ("Seli Dorn", "FWD", 73, 70, 80, 42, 77, 22, 156),
    ],
    "RDW": [
        ("Nuru Senn", "GK", 55, 65, 11, 75, 63, 28, 48),
        ("Kale Orun", "DEF", 81, 57, 29, 68, 78, 23, 72),
        ("Rima Tesh", "DEF", 72, 63, 26, 73, 82, 25, 71),
        ("Daro Sile", "DEF", 68, 59, 33, 70, 75, 30, 59),
        ("Una Varo", "DEF", 75, 66, 38, 66, 80, 21, 86),
        ("Sefu Aran", "MID", 83, 72, 61, 53, 82, 22, 112),
        ("Nessa Korr", "MID", 74, 70, 56, 62, 87, 24, 94),
        ("Ilan Venn", "MID", 68, 76, 48, 69, 79, 26, 88),
        ("Maro Pell", "MID", 78, 65, 64, 57, 74, 20, 97),
        ("Tali Rook", "WNG", 91, 64, 69, 35, 80, 19, 146),
        ("Evo Nari", "FWD", 85, 58, 83, 31, 78, 23, 137),
        ("Kiri Sol", "FWD", 76, 66, 75, 43, 81, 27, 108),
    ],
    "BWA": [
        ("Halen Drift", "GK", 57, 70, 16, 82, 65, 29, 63),
        ("Boro Kelm", "DEF", 65, 66, 30, 84, 82, 28, 88),
        ("Sena Marr", "DEF", 71, 73, 35, 78, 79, 24, 99),
        ("Iri Taal", "DEF", 62, 75, 28, 81, 85, 22, 92),
        ("Mikel Oru", "DEF", 58, 69, 31, 86, 72, 32, 66),
        ("Tavo Senn", "MID", 67, 79, 48, 77, 88, 27, 111),
        ("Esha Venn", "MID", 74, 76, 62, 70, 80, 22, 129),
        ("Ren Kade", "MID", 63, 82, 47, 76, 83, 25, 112),
        ("Osa Quill", "MID", 69, 74, 59, 73, 86, 23, 116),
        ("Luma Vale", "WNG", 80, 77, 70, 50, 78, 24, 145),
        ("Jori Ndem", "FWD", 75, 71, 85, 48, 84, 26, 162),
        ("Pavo Ilse", "FWD", 68, 67, 79, 55, 87, 30, 128),
    ],
}


def _make_player(player_id, club_id, row):
    name, position, pace, passing, finishing, defending, stamina, age, value = row
    return dict(id=player_id, club=club_id, name=name, position=position,
                pace=pace, passing=passing, finishing=finishing,
                defending=defending, stamina=stamina, morale=68,
                fitness=94, age=age, value=value)


PLAYERS = {}
for club in CLUBS:
    for number, row in enumerate(ROSTER_ROWS[club["id"]], 1):
        player_id = f"{club['id']}-{number:02d}"
        PLAYERS[player_id] = _make_player(player_id, club["id"], row)

# Free-agent data supplies the opening market. These players can be bought;
# sold squad players join this pool too.
PROSPECT_ROWS = [
    ("Aro Noss", "GK", 62, 71, 14, 80, 72, 20, 99),
    ("Lena Voss", "DEF", 79, 72, 40, 76, 83, 21, 132),
    ("Teren Kint", "DEF", 68, 77, 34, 81, 79, 23, 116),
    ("Sana Pell", "MID", 76, 83, 64, 62, 80, 22, 154),
    ("Jaro Vei", "MID", 70, 78, 60, 72, 88, 24, 139),
    ("Miri Dask", "WNG", 88, 76, 71, 45, 78, 20, 166),
    ("Kalo Miret", "FWD", 80, 69, 86, 39, 79, 22, 178),
    ("Vela Aru", "FWD", 73, 75, 81, 42, 84, 19, 171),
]
PROSPECT_IDS = []
for number, row in enumerate(PROSPECT_ROWS, 1):
    player_id = f"FA-{number:02d}"
    PROSPECT_IDS.append(player_id)
    PLAYERS[player_id] = _make_player(player_id, None, row)

# Slots are filled from the manager's available players by position and rating.
FORMATIONS = {
    "4-4-2": ["GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD"],
    "4-3-3": ["GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "WNG", "FWD", "FWD"],
    "3-5-2": ["GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "WNG", "FWD", "FWD"],
}

# Formation modifiers are deliberately small probability deltas, not hidden
# overall bonuses. Edit these alongside FORMATIONS; pass support and box
# presence belong to the in-possession shape, while screen and space belong to
# the out-of-possession shape.
FORMATION_EFFECTS = {
    "4-4-2": dict(pass_support=.006, box_presence=.004,
                  midfield_screen=.008, space_behind=.000),
    "4-3-3": dict(pass_support=.000, box_presence=.014,
                  midfield_screen=.000, space_behind=.000),
    "3-5-2": dict(pass_support=.015, box_presence=.011,
                  midfield_screen=.026, space_behind=.045),
}
FORMATION_NOTES = {
    "4-4-2": "Two forwards occupy the line; the midfield keeps a steady screen.",
    "4-3-3": "Three high outlets stretch the back line and attack the box.",
    "3-5-2": "A midfield overload aids circulation, but three defenders leave space behind.",
}

# Tactic values alter match output, post-match fatigue, and injury chance.
TACTICS = {
    "Balanced": dict(attack=0, defence=0, fatigue=0, injury_risk=0.0),
    "High Press": dict(attack=5, defence=1, fatigue=11, injury_risk=0.035),
    "Deep Counter": dict(attack=2, defence=4, fatigue=3, injury_risk=0.005),
}

# Ten rounds: five opponents home and away. Each round has three fixtures.
FIXTURES = [
    [("BRP", "BWA"), ("GLA", "RDW"), ("LVA", "CWC")],
    [("BRP", "RDW"), ("BWA", "CWC"), ("GLA", "LVA")],
    [("BRP", "CWC"), ("RDW", "LVA"), ("BWA", "GLA")],
    [("BRP", "LVA"), ("CWC", "GLA"), ("RDW", "BWA")],
    [("BRP", "GLA"), ("LVA", "BWA"), ("CWC", "RDW")],
    [("BWA", "BRP"), ("RDW", "GLA"), ("CWC", "LVA")],
    [("RDW", "BRP"), ("CWC", "BWA"), ("LVA", "GLA")],
    [("CWC", "BRP"), ("LVA", "RDW"), ("GLA", "BWA")],
    [("LVA", "BRP"), ("GLA", "CWC"), ("BWA", "RDW")],
    [("GLA", "BRP"), ("BWA", "LVA"), ("RDW", "CWC")],
]

TRAINING = {
    "Finishing": "finishing",
    "Passing": "passing",
    "Defending": "defending",
    "Pace": "pace",
    "Conditioning": "stamina",
}

# These named managers give AI clubs a tactical identity. Edit their approach
# and risk appetite alongside CLUBS; match logic interprets the values.
MANAGERS = {
    "BRP": dict(name="Sera Uus", approach="Front-foot", risk=66,
                formation="4-3-3", line="high", press="high", build="short"),
    "GLA": dict(name="Milo Fenner", approach="Patient", risk=54,
                formation="4-3-3", line="mid", press="mid", build="short"),
    "LVA": dict(name="Tarin Eske", approach="Compact", risk=38,
                formation="4-4-2", line="low", press="low", build="direct"),
    "CWC": dict(name="Rhea Tovin", approach="Possession", risk=58,
                formation="4-3-3", line="mid", press="high", build="short"),
    "RDW": dict(name="Nuru Senn", approach="Vertical", risk=74,
                formation="4-4-2", line="mid", press="mid", build="direct"),
    "BWA": dict(name="Halen Drift", approach="Patient counter", risk=43,
                formation="3-5-2", line="low", press="mid", build="direct"),
}

# Candid identity signals are used by previews, board targets, and home support.
# Re-tune them here without changing simulation formulas.
CLUB_IDENTITY = {
    "BRP": dict(expectation=3, patience=58, attendance=8600,
                supporter_style="Front-foot football; dockside pride."),
    "GLA": dict(expectation=2, patience=61, attendance=8100,
                supporter_style="Clever passing and a fearless derby."),
    "LVA": dict(expectation=5, patience=72, attendance=5700,
                supporter_style="Resilience, local prospects, no surrender."),
    "CWC": dict(expectation=1, patience=49, attendance=11600,
                supporter_style="Silverware is the minimum conversation."),
    "RDW": dict(expectation=6, patience=67, attendance=5300,
                supporter_style="Run hard, play brave, make the trip count."),
    "BWA": dict(expectation=2, patience=63, attendance=9300,
                supporter_style="Compete for every ball and every cup."),
}

# Training focus effects are explained to the manager before a week is applied.
# Effects are interpreted by main.py; these strings are player-facing content.
TRAINING_PLANS = {
    "Recovery": "Restore readiness; little technical growth this week.",
    "Tactical": "Build shape familiarity and passing decisions.",
    "Finishing": "Sharpen composure and final-third timing.",
    "Defending": "Improve positioning and duels; moderate workload.",
    "Conditioning": "Raise stamina over time; the heaviest workload.",
}

# Small editable phrase banks make reports state-driven without hiding the cause.
# Templates use {player}, {club}, {opponent}, and {detail} where shown.
COMMENTARY = {
    "regain_high": [
        "{player} reads the next pass and wins it high.",
        "{player} jumps the passing lane; the press finally bites.",
    ],
    "through_ball": [
        "{player} releases {detail} into the space behind the line.",
        "A first-time ball finds {detail} running beyond the defence.",
    ],
    "wide_attack": [
        "{player} gets outside the full-back and sends it into the box.",
        "The move is stretched wide; {player} has room to cross.",
    ],
    "central_progression": [
        "{player} carries the move through the middle third.",
        "The central lane opens for {player} to turn and advance.",
    ],
    "goal": [
        "{player} keeps the finish low and finds the corner.",
        "{player} arrives on the pass and buries the chance.",
    ],
    "save": [
        "The keeper reads it early and pushes the shot away.",
        "A strong hand turns the effort around the post.",
    ],
    "miss": [
        "The shot drifts wide under pressure.",
        "{player} gets the contact wrong; the chance goes begging.",
    ],
    "turnover": [
        "The pass is forced; possession turns over in midfield.",
        "The press closes the lane and the move breaks down.",
    ],
    "bad_connection": [
        "The receiver and passer are not on the same page.",
        "The timing is off; the next pass never reaches its target.",
    ],
    "blocked_cross_corner": [
        "{player}'s cross is blocked behind for a corner.",
        "The defender gets a touch; {player} wins a corner from the delivery.",
    ],
    "morale": [
        "{player} asks for a clearer route back into the starting XI.",
        "{player} says the extra minutes helped settle the week.",
    ],
}

# Supported match-plan choices and their human-readable trade-offs. The sim
# derives each effect from the choice; these descriptions are not hidden stats.
INSTRUCTIONS = {
    "press": {
        "low": "Save legs; concede easier build-up.",
        "mid": "Balance pressure with shape and recovery.",
        "high": "Win higher; leave space and spend more energy.",
    },
    "line": {
        "low": "Protect depth; surrender territory and invite crosses.",
        "mid": "Keep a compact, adjustable block.",
        "high": "Compress the pitch; risk runs behind.",
    },
    "width": {
        "narrow": "Crowd central lanes; expose the far touchline.",
        "balanced": "Use both lanes without overcommitting.",
        "wide": "Create crossing space; leave wider counter lanes.",
    },
    "build": {
        "short": "Keep the ball; ask for composure under pressure.",
        "balanced": "Mix patient passes and early forward play.",
        "direct": "Attack depth quickly; concede some control.",
    },
    "tempo": {
        "slow": "Fewer possessions; preserve legs and shape.",
        "standard": "A measured match rhythm.",
        "fast": "More attacks; increase fatigue and loose decisions.",
    },
}

# Rivalries are story context only: results build their memory; they do not add
# an arbitrary match bonus. Extend with original clubs and a short reason.
RIVALRIES = [
    dict(home="BRP", away="GLA", name="The Saltglass Derby",
         reason="The docks and the lantern quarter argue over the coast."),
    dict(home="CWC", away="BWA", name="The Foundry Tide",
         reason="Two working ports with very different ideas of power."),
]

# Personalities affect willingness, development, and state-triggered voice.
PERSONALITIES = [
    dict(id="professional", label="Professional", growth=1.08, patience=1.08),
    dict(id="ambitious", label="Ambitious", growth=1.12, patience=0.92),
    dict(id="steady", label="Steady", growth=0.98, patience=1.12),
    dict(id="fiery", label="Fiery", growth=1.02, patience=0.86),
]

# Duration is the number of future match rounds missed. Exposure changes chance;
# no injury is guaranteed by fatigue, training, or a tactical instruction.
INJURIES = [
    dict(name="muscle tightness", rounds=(1, 2)),
    dict(name="ankle knock", rounds=(1, 3)),
    dict(name="hamstring strain", rounds=(2, 4)),
]

# Player facts seed scouting stories and academy generation. Add an ID and one
# concise evidence-backed note; notes are never treated as match bonuses.
PLAYER_REPORT_NOTES = {
    "GLA-10": "Repeatedly attacks the channel behind the full-back.",
    "BRP-10": "Carries at speed and wants the ball early in transition.",
    "BRP-07": "Sees forward passes but can be pulled out of the midfield screen.",
    "CWC-11": "Strong first movement in the box; likes service early.",
    "LVA-02": "Wins contact and protects the central lane.",
    "RDW-10": "The fastest wide runner in this division; leaves space after a sprint.",
    "BWA-11": "Aerial target who brings nearby teammates into play.",
}

LEAGUE_NAME = "Sable Coast League"
SEASON_ROUNDS = len(FIXTURES)
MATCH_PERIODS = 6

# Use this 3x3 sketch to keep zone vocabulary consistent in the match room.
# The first row is the attacking team's final third.
ZONE_GRID = (
    ("L-FINAL", "C-FINAL", "R-FINAL"),
    ("L-MID", "C-MID", "R-MID"),
    ("L-BUILD", "C-BUILD", "R-BUILD"),
)

# Terminal pitch sketches are authored art and should be edited here rather
# than embedded in drawing code. Rows are rendered with a monospace font.
FORMATION_ART = {
    "4-4-2": ("  W    ST   ST   W  ", "FB  CB      CB  FB", "       GK         "),
    "4-3-3": ("W       ST       W", "    CM  CM  CM    ", "FB  CB      CB  FB"),
    "3-5-2": ("      ST  ST      ", "WB  CM  CM  CM  WB", "    CB  CB  CB    "),
}

# Reusable career headlines. Simulation supplies state; these strings supply
# the fictional world's voice and are safe to rewrite without changing rules.
NEWS_LINES = {
    "career_open": "You take charge at {club}. The season is yours to shape.",
    "kickoff": "{title}. The opening plans are set.",
    "win": "Full time: {result}. {winner} take the points.",
    "draw": "Full time: {result}. The points are shared.",
    "goal": "{player} scores in {result}.",
    "injury": "{player} has {injury}; likely out {duration} round(s).",
    "round_close": "Round {round} closes: {count} fixtures settled; {leader} lead the table.",
    "season_close": "Season {season} ends. {champion} are champions; you finish {place}.",
    "season_open": "Season {season} opens. {count} academy players join the pyramid.",
    "signing": "{player} signs for {club} for £{fee}k and £{wage}k/week.",
    "sale": "{club} sign {player} for £{fee}k.",
}

MATCH_LINES = {
    "blocked_attack": "{player} probes the final third; the defence holds.",
    "substitution": "{incoming} replaces {outgoing} after {minute} minutes.",
    "ai_chase": "The opposition raise their press and tempo as they chase the game.",
    "ai_protect": "The opposition lower their risk to protect the lead.",
}

# Match-feed explanations describe visible outcomes; rules and coefficients
# remain in main.py so these lines can be edited without changing simulation.
TACTICAL_REASONS = {
    "high_regain": "Their {press} press closes the first lane.",
    "bad_link": "{reason}",
    "through_ball": "{build} delivery tests the opponent's {line} line.",
    "build_lane": "The {build} build reaches the {lane} lane against a {line} block.",
    "line_closed": "The {line} block closes the next lane.",
    "wide_cross": "Width creates a delivery, but the box is crowded.",
    "shot": "{action} from {zone}; {pressure} pressure; {xg:.2f} xG.",
    "substitution": "Fresh {position} legs replace a tiring player.",
}

# Names for generated academy players. Extend both lists freely; the career
# save stores generated full names and attributes as persistent player records.
FIRST_NAMES = ["Kavi", "Mara", "Timo", "Nela", "Sefu", "Ruan", "Asha", "Daro",
               "Lena", "Mika", "Tali", "Eren", "Yara", "Niko", "Sana", "Omi"]
SURNAMES = ["Voss", "Kade", "Miret", "Senn", "Dune", "Taal", "Orun", "Pell",
            "Noss", "Vale", "Korr", "Ilse", "Malk", "Rook", "Vei", "Aru"]
