"""Grimhollow's editable world and rules-facing content.

Change names, descriptions, dialogue, map rows, items, encounters, or spell
numbers here. The game engine and save rules live in main.py.
"""

# Character entries are independent starting companions. Keep the party at or
# below four; changing a name or stat here changes a new save, not old saves.
PARTY = [
    dict(id="mara", name="Mara Venn", role="Vanguard", hp=34, ac=15,
         attack=5, damage=(1, 8), bonus=3, reach=1, speed=2,
         spells=[], blurb="A bridge-guard who counts exits before faces."),
    dict(id="orren", name="Orren Vale", role="Arcanist", hp=23, ac=12,
         attack=4, damage=(1, 6), bonus=2, reach=3, speed=2,
         spells=["cinder_lance", "mothlight"], blurb="A careful scholar with ash on his cuffs."),
    dict(id="tavi", name="Tavi Reed", role="Pathfinder", hp=27, ac=14,
         attack=5, damage=(1, 8), bonus=3, reach=4, speed=2,
         spells=[], blurb="A patient scout who can read wet stone."),
    dict(id="ilyra", name="Sister Ilyra", role="Cantor", hp=29, ac=14,
         attack=3, damage=(1, 6), bonus=2, reach=1, speed=2,
         spells=["lantern_mend", "silver_note"], blurb="Keeps the last songs of the drowned chapel."),
]

# Tactical map art is five rows by seven columns. '#' is impassable rubble.
TACTICAL_MAP = [
    ".......",
    "..#....",
    ".......",
    "..#....",
    ".......",
]

# Combatants are data, so new encounters can be added without changing rules.
ENCOUNTERS = {
    "cinder_vault": dict(
        name="The Cinder Vault",
        enemies=[
            dict(id="hound", name="Ashbound Hound", glyph="H", hp=25, ac=13,
                 attack=4, damage=(1, 6), bonus=2, reach=1, speed=2, xp=18),
            dict(id="mote", name="Bell Mote", glyph="M", hp=12, ac=12,
                 attack=3, damage=(1, 4), bonus=1, reach=3, speed=2, xp=8),
        ],
        gold=16,
        reward_item="Draught",
        reward_count=1,
        intro=[
            "A narrow stair descends beneath the kiln.",
            "The map is cramped, the stone warm beneath your boots.",
        ],
        battle_start="The vault doors seal behind you. Choose an action for each ally.",
        victory="The Ashbound Hound falls. The bell-mote gutters out.",
        defeat="The companions drag one another back into the rain.",
        defeat_hint="Rest at camp before returning.",
    ),
}

# Spell fields: kind is attack or heal; dice/bonus set effect size; range is
# measured in Manhattan grid steps. Uses refresh at camp.
SPELLS = {
    "cinder_lance": dict(name="Cinder Lance", kind="attack", range=5,
                         dice=(1, 8), bonus=3, uses=2,
                         text="a bright coal skips through the dark"),
    "mothlight": dict(name="Mothlight", kind="attack", range=4,
                      dice=(1, 6), bonus=2, uses=2,
                      text="pale sparks swarm a foe"),
    "lantern_mend": dict(name="Lantern Mend", kind="heal", range=4,
                         dice=(1, 8), bonus=4, uses=2,
                         text="warm light closes a wound"),
    "silver_note": dict(name="Silver Note", kind="attack", range=4,
                        dice=(1, 6), bonus=2, uses=1,
                        text="a clear note rings inside a foe's bones"),
}

# Item effects are simple and intentionally easy to retune.
ITEMS = {
    "Draught": dict(kind="heal", amount=14, text="a bitter red tonic"),
    "Ration": dict(kind="rest", amount=1, text="a wrapped meal for camp"),
    "Bell Shard": dict(kind="quest", amount=0, text="a warm piece of the drowned bell"),
}

# Dialogue is presented in order; each choice has a short player response and
# a state key consumed by the engine. Edit wording freely while keeping keys.
DIALOGUE = {
    "fenna": dict(
        speaker="Captain Fenna",
        lines=[
            "A bell rang below the old kiln. By dawn, the river ferries had gone quiet.",
            "I need someone to bring back the bell's clapper and find who lit it.",
        ],
        choices=[
            ("Take the contract", "Then go while the ash is still warm.", "accept"),
            ("Ask about the ferries", "Three boats are tied up. No bodies, no tracks. Just silence.", "ask"),
            ("Leave the conversation", "Fenna turns back to the river map.", "leave"),
        ],
        accept_response="Fenna presses a brass token into your palm.",
        insight_success="You notice the route marked behind the kiln.",
        insight_failure="Fenna has no more to add.",
    ),
}

QUESTS = {
    "bell_below": dict(
        title="The Bell Below",
        summary="Enter the Cinder Vault and recover its warm bell shard.",
        complete="The shard is quiet now. Fenna can send the ferries again.",
        rumour="Speak with Captain Fenna to learn what the river has lost.",
        reward_xp=30,
        reward_gold=20,
    ),
}

CAMP_TEXT = "A dry fire and a watch rota make the dark feel smaller."
VAULT_LOCKED = ["The kiln door is sealed with a river-watch mark.",
                "Captain Fenna may know how to open it."]
VAULT_QUIET = "The vault is quiet now."
GREYHARBOR_EXIT = "The river keeps its secrets for another night."

HUB_TEXT = [
    "Greyharbor sits where the river forgets its name.",
    "A cold bell-note drifts from the abandoned kiln to the east.",
]

OPENING = [
    "Rain has stopped over Greyharbor, though the river still runs black.",
    "Somewhere beneath the abandoned kiln, a bell answers the dark.",
    "Four strangers gather beneath the lantern at the west gate.",
]
