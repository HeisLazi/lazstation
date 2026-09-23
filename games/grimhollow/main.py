#!/usr/bin/env python3
"""Grimhollow: a small party adventure about a bell under a drowned town."""
from __future__ import annotations

import copy
import os
import random
import sys
from collections import deque
from typing import Any

import termstation_sdk as ts

import content

PAGE = 18  # title, compact panel, choices and prompt fit the 20-row picture
DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def new_party() -> list[dict[str, Any]]:
    """Create a save-safe copy of the four editable starting companions."""
    party = []
    starts = [(0, 0), (0, 2), (0, 4), (1, 3)]
    for template, pos in zip(content.PARTY[:4], starts):
        member = copy.deepcopy(template)
        member.update(
            max_hp=member["hp"], pos=list(pos), level=1, xp=0, guard=0,
            slots={spell: content.SPELLS[spell]["uses"] for spell in member["spells"]},
        )
        party.append(member)
    return party


def defaults() -> dict[str, Any]:
    return {
        "version": 1,
        "party": new_party(),
        "gold": 12,
        "inventory": {"Draught": 2, "Ration": 2},
        "quest_status": "not_started",
        "quest_clue": False,
        "encounter_done": False,
        "seen_intro": False,
        "visited_vault": False,
    }


def prepare_save(save: dict[str, Any]) -> dict[str, Any]:
    """Repair fields added by later versions and clamp old save values."""
    base = defaults()
    for key, value in base.items():
        save.setdefault(key, copy.deepcopy(value))
    if not isinstance(save.get("party"), list) or not save["party"]:
        save["party"] = new_party()
    save["party"] = save["party"][:4]
    for member in save["party"]:
        template = next((p for p in content.PARTY if p["id"] == member.get("id")), None)
        if template:
            for key, value in template.items():
                member.setdefault(key, copy.deepcopy(value))
        member.setdefault("max_hp", member.get("hp", 1))
        member.setdefault("level", 1)
        member.setdefault("xp", 0)
        member.setdefault("guard", 0)
        member.setdefault("pos", [0, 0])
        member.setdefault("slots", {spell: content.SPELLS[spell]["uses"]
                                      for spell in member.get("spells", [])
                                      if spell in content.SPELLS})
        member["hp"] = max(0, min(int(member["hp"]), int(member["max_hp"])))
    if not isinstance(save.get("inventory"), dict):
        save["inventory"] = {}
    for item in content.ITEMS:
        save["inventory"].setdefault(item, 0)
    save["version"] = 1
    return save


def fit(text: str) -> str:
    """Keep a line inside the variable-width picture stage."""
    width, _ = ts.size()
    return text[:max(1, width - 1)]


def page(title: str, lines: list[str] | None = None, page_height: int = PAGE) -> None:
    ts.tv_clear(page=page_height)
    ts.tv_print(ts.title(title))
    for line in lines or []:
        ts.tv_print(fit(line))


def choose(title: str, lines: list[str], options: list[str], page_height: int = PAGE) -> int:
    """Render a compact numbered page and return a zero-based choice."""
    page(title, lines, page_height)
    ts.tv_print()
    ts.tv_print("Choose:")
    for index, option in enumerate(options, 1):
        ts.tv_print(f" {index}. {fit(option)}")
    return ts.ask_int("choose", 1, len(options)) - 1


def distance(a: list[int] | tuple[int, int], b: list[int] | tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def roll_damage(dice: tuple[int, int], bonus: int, rng: Any = random) -> int:
    count, sides = dice
    return sum(rng.randint(1, sides) for _ in range(count)) + bonus


def resolve_attack(attack_bonus: int, armour: int, dice: tuple[int, int],
                   damage_bonus: int, rng: Any = random) -> dict[str, Any]:
    """Resolve a d20 attack; natural 20 doubles rolled dice, natural 1 misses."""
    roll = rng.randint(1, 20)
    hit = roll == 20 or (roll != 1 and roll + attack_bonus >= armour)
    if not hit:
        return {"roll": roll, "total": roll + attack_bonus, "hit": False,
                "critical": False, "damage": 0}
    critical = roll == 20
    count, sides = dice
    amount = sum(rng.randint(1, sides) for _ in range(count))
    if critical:
        amount += sum(rng.randint(1, sides) for _ in range(count))
    return {"roll": roll, "total": roll + attack_bonus, "hit": True,
            "critical": critical, "damage": max(1, amount + damage_bonus)}


def resolve_check(modifier: int, difficulty: int, rng: Any = random) -> dict[str, Any]:
    """A d20 ability check with the usual natural 1/20 extremes."""
    roll = rng.randint(1, 20)
    return {"roll": roll, "total": roll + modifier,
            "success": roll == 20 or (roll != 1 and roll + modifier >= difficulty)}


def grid_bounds() -> tuple[int, int]:
    return len(content.TACTICAL_MAP[0]), len(content.TACTICAL_MAP)


def blocked_tiles() -> set[tuple[int, int]]:
    blocked = set()
    for y, row in enumerate(content.TACTICAL_MAP):
        for x, tile in enumerate(row):
            if tile == "#":
                blocked.add((x, y))
    return blocked


def path_to(start: tuple[int, int], goals: set[tuple[int, int]],
            blocked: set[tuple[int, int]], occupied: set[tuple[int, int]]) -> list[tuple[int, int]]:
    """Breadth-first path over the editable grid, returning steps after start."""
    width, height = grid_bounds()
    queue = deque([start])
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    end = None
    while queue:
        here = queue.popleft()
        if here in goals:
            end = here
            break
        for dx, dy in DIRECTIONS:
            nxt = (here[0] + dx, here[1] + dy)
            if (0 <= nxt[0] < width and 0 <= nxt[1] < height
                    and nxt not in blocked and nxt not in occupied
                    and nxt not in previous):
                previous[nxt] = here
                queue.append(nxt)
    if end is None:
        return []
    route = []
    while end != start:
        route.append(end)
        end = previous[end]  # type: ignore[assignment]
    route.reverse()
    return route


def attack_positions(target: dict[str, Any], reach: int,
                     blocked: set[tuple[int, int]], occupied: set[tuple[int, int]]) -> set[tuple[int, int]]:
    width, height = grid_bounds()
    tx, ty = target["pos"]
    return {
        (x, y)
        for y in range(height)
        for x in range(width)
        if distance((x, y), (tx, ty)) <= reach
        and (x, y) not in blocked and (x, y) not in occupied
    }


def advance(unit: dict[str, Any], targets: list[dict[str, Any]],
            everybody: list[dict[str, Any]]) -> int:
    """Move toward the nearest legal attack square, at most speed tiles."""
    blocked = blocked_tiles()
    occupied = {tuple(other["pos"]) for other in everybody if other is not unit and other["hp"] > 0}
    candidates = []
    for target in targets:
        if target["hp"] <= 0:
            continue
        goals = attack_positions(target, int(unit.get("reach", 1)), blocked,
                                 occupied | {tuple(t["pos"]) for t in targets if t is not target and t["hp"] > 0})
        route = path_to(tuple(unit["pos"]), goals, blocked, occupied)
        if route:
            candidates.append((len(route), target["name"], route))
    if not candidates:
        return 0
    _, _, route = min(candidates, key=lambda row: (row[0], row[1]))
    steps = min(int(unit.get("speed", 2)), len(route))
    unit["pos"] = list(route[steps - 1])
    return steps


def in_range(unit: dict[str, Any], target: dict[str, Any], reach: int | None = None) -> bool:
    return distance(unit["pos"], target["pos"]) <= (reach if reach is not None else unit.get("reach", 1))


def active_enemies(enemies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [enemy for enemy in enemies if enemy["hp"] > 0]


def living_party(party: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [member for member in party if member["hp"] > 0]


def spawn_enemies(key: str) -> list[dict[str, Any]]:
    copies = copy.deepcopy(content.ENCOUNTERS[key]["enemies"])
    spots = [(6, 1), (6, 3), (5, 0), (5, 4)]
    for enemy, pos in zip(copies, spots):
        enemy["max_hp"] = enemy["hp"]
        enemy["pos"] = list(pos)
        enemy["guard"] = 0
    return copies


def draw_grid(party: list[dict[str, Any]], enemies: list[dict[str, Any]]) -> list[str]:
    cells = [list(row) for row in content.TACTICAL_MAP]
    for index, member in enumerate(party):
        if member["hp"] > 0:
            x, y = member["pos"]
            cells[y][x] = str(index + 1)
    for enemy in enemies:
        if enemy["hp"] > 0:
            x, y = enemy["pos"]
            cells[y][x] = enemy.get("glyph", "E")
    return [" " + " ".join(row) for row in cells]


def combat_lines(round_no: int, actor: dict[str, Any], party: list[dict[str, Any]],
                 enemies: list[dict[str, Any]], note: str) -> list[str]:
    nearest = min(distance(actor["pos"], e["pos"]) for e in active_enemies(enemies))
    lines = [f"Round {round_no} | {actor['name']} HP {actor['hp']}/{actor['max_hp']} "
             f"AC {actor['ac']} | nearest foe {nearest}"]
    lines.extend(draw_grid(party, enemies))
    active = active_enemies(enemies)
    lines.append("Foes: " + (", ".join(f"{e['name']} {e['hp']}" for e in active) or "none"))
    lines.append("Log: " + note)
    return lines


def roll_message(attacker: dict[str, Any], target: dict[str, Any], result: dict[str, Any]) -> str:
    if not result["hit"]:
        return f"{attacker['name']} rolls {result['roll']}+{attacker['attack']} and misses {target['name']}."
    critical = " CRITICAL!" if result["critical"] else ""
    target["hp"] = max(0, target["hp"] - result["damage"])
    return f"{attacker['name']} rolls {result['roll']} and hits {target['name']} for {result['damage']}.{critical}"


def weapon_attack(attacker: dict[str, Any], target: dict[str, Any], rng: Any = random) -> str:
    result = resolve_attack(attacker["attack"], target["ac"], tuple(attacker["damage"]),
                            attacker["bonus"], rng)
    return roll_message(attacker, target, result)


def cast_spell(caster: dict[str, Any], target: dict[str, Any], spell_id: str,
               party: list[dict[str, Any]], rng: Any = random) -> str:
    """Cast one known spell on a legal target, consuming a refreshed use."""
    spell = content.SPELLS[spell_id]
    caster.setdefault("slots", {}).setdefault(spell_id, spell["uses"])
    if caster["slots"][spell_id] <= 0:
        return f"{spell['name']} has no uses left."
    if not in_range(caster, target, spell["range"]):
        return f"{target['name']} is beyond {spell['name']}'s reach."
    caster["slots"][spell_id] -= 1
    if spell["kind"] == "heal":
        amount = roll_damage(tuple(spell["dice"]), spell["bonus"], rng)
        restored = min(amount, target["max_hp"] - target["hp"])
        target["hp"] += restored
        return f"{caster['name']} casts {spell['name']}: {target['name']} regains {restored} HP."
    result = resolve_attack(caster["attack"] + 1, target["ac"], tuple(spell["dice"]),
                            spell["bonus"], rng)
    message = roll_message({**caster, "attack": caster["attack"] + 1}, target, result)
    return f"{caster['name']} casts {spell['name']}; {message}"


def award_xp(party: list[dict[str, Any]], amount: int) -> list[str]:
    """Grant XP and apply each level-up once, carrying extra XP forward."""
    changes = []
    for member in party:
        member["xp"] = member.get("xp", 0) + amount
        while member["xp"] >= member.get("level", 1) * 30:
            member["xp"] -= member["level"] * 30
            member["level"] += 1
            member["max_hp"] += 3
            member["hp"] = min(member["max_hp"], member["hp"] + 3)
            member["attack"] += 1
            changes.append(f"{member['name']} reaches level {member['level']}.")
    return changes


def get_spell_options(actor: dict[str, Any], party: list[dict[str, Any]],
                      enemies: list[dict[str, Any]]) -> list[str]:
    options = []
    for spell_id in actor.get("spells", []):
        spell = content.SPELLS.get(spell_id)
        if not spell or actor.get("slots", {}).get(spell_id, spell["uses"]) <= 0:
            continue
        targets = (living_party(party) if spell["kind"] == "heal" else active_enemies(enemies))
        if any(in_range(actor, target, spell["range"])
               and (spell["kind"] != "heal" or target["hp"] < target["max_hp"])
               for target in targets):
            options.append(spell_id)
    return options


def choose_heal_target(actor: dict[str, Any], party: list[dict[str, Any]], spell_id: str | None = None) -> dict[str, Any]:
    candidates = [m for m in living_party(party)
                  if m["hp"] < m["max_hp"]
                  and (spell_id is None or in_range(actor, m, content.SPELLS[spell_id]["range"]))]
    return min(candidates, key=lambda m: (m["hp"] / m["max_hp"], m["name"]))


def use_draught(save: dict[str, Any], party: list[dict[str, Any]], target: dict[str, Any] | None = None) -> str:
    if save["inventory"].get("Draught", 0) <= 0:
        return "There are no draughts left."
    injured = [m for m in living_party(party) if m["hp"] < m["max_hp"]]
    if not injured:
        return "Everyone is already at full health."
    target = target or min(injured, key=lambda m: (m["hp"] / m["max_hp"], m["name"]))
    target["hp"] = min(target["max_hp"], target["hp"] + content.ITEMS["Draught"]["amount"])
    save["inventory"]["Draught"] -= 1
    return f"{target['name']} drinks a draught and now has {target['hp']}/{target['max_hp']} HP."


def enemy_turn(enemy: dict[str, Any], party: list[dict[str, Any]], enemies: list[dict[str, Any]],
               rng: Any = random) -> str:
    targets = living_party(party)
    if enemy["hp"] <= 0 or not targets:
        return ""
    target = min(targets, key=lambda m: (distance(enemy["pos"], m["pos"]), m["hp"]))
    if not in_range(enemy, target):
        advance(enemy, [target], enemies + party)
    if not in_range(enemy, target):
        return f"{enemy['name']} scrapes across the stone toward {target['name']}."
    result = resolve_attack(enemy["attack"], target["ac"], tuple(enemy["damage"]),
                            enemy["bonus"], rng)
    if not result["hit"]:
        return f"{enemy['name']} rolls {result['roll']} and misses {target['name']}."
    damage = max(0, result["damage"] - target.get("guard", 0))
    target["guard"] = 0
    target["hp"] = max(0, target["hp"] - damage)
    return f"{enemy['name']} hits {target['name']} for {damage} damage."


def combat(save: dict[str, Any], encounter_key: str = "cinder_vault",
           rng: Any = random) -> bool:
    """Resolve a full grid battle. True means the party won."""
    party = save["party"]
    enemies = spawn_enemies(encounter_key)
    for index, member in enumerate(party):
        member["pos"] = list([(0, 0), (0, 2), (0, 4), (1, 3)][index])
        member["guard"] = 0
    note = content.ENCOUNTERS[encounter_key]["battle_start"]
    round_no = 1
    rng = rng or random
    while living_party(party) and active_enemies(enemies):
        for actor in living_party(party):
            if not active_enemies(enemies):
                break
            legal_targets = [e for e in active_enemies(enemies) if in_range(actor, e)]
            first = "Attack" if legal_targets else "Advance toward a foe"
            choices = [first, "Move to a chosen lane"]
            spell_options = get_spell_options(actor, party, enemies)
            if spell_options:
                choices.append("Cast a spell")
            if actor["hp"] < actor["max_hp"] and save["inventory"].get("Draught", 0) > 0:
                choices.append("Use a draught")
            index = choose(
                f"{actor['name']}  |  {actor['role']}",
                combat_lines(round_no, actor, party, enemies, note),
                choices,
                page_height=19,
            )
            selected = choices[index]
            if selected in ("Attack", "Advance toward a foe"):
                if selected == "Attack":
                    target = min(legal_targets, key=lambda e: (e["hp"], e["name"]))
                    note = weapon_attack(actor, target, rng)
                else:
                    steps = advance(actor, active_enemies(enemies), party + enemies)
                    note = f"{actor['name']} advances {steps} tile(s) through the rubble."
            elif selected == "Move to a chosen lane":
                directions = ["North", "East", "South", "West", "Hold position"]
                d = choose("Choose a lane", ["Each move covers up to two open tiles."], directions)
                dx, dy = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}.get(d, (0, 0))
                occupied = {tuple(m["pos"]) for m in party + enemies
                            if m is not actor and m["hp"] > 0}
                moved = 0
                for _ in range(actor["speed"]):
                    nxt = (actor["pos"][0] + dx, actor["pos"][1] + dy)
                    if (nxt[0] < 0 or nxt[1] < 0 or nxt[0] >= grid_bounds()[0]
                            or nxt[1] >= grid_bounds()[1] or nxt in blocked_tiles()
                            or nxt in occupied):
                        break
                    actor["pos"] = list(nxt)
                    moved += 1
                note = f"{actor['name']} moves {moved} tile(s) {directions[d].lower()}."
            elif selected == "Cast a spell":
                spell_ids = spell_options
                spell_pick = choose(
                    "Known spells",
                    [f"{content.SPELLS[s]['name']}: {content.SPELLS[s]['text']}"
                     for s in spell_ids],
                    [f"{content.SPELLS[s]['name']} ({actor['slots'].get(s, 0)} left)"
                     for s in spell_ids],
                )
                spell_id = spell_ids[spell_pick]
                spell = content.SPELLS[spell_id]
                if spell["kind"] == "heal":
                    target = choose_heal_target(actor, party, spell_id)
                else:
                    targets = [e for e in active_enemies(enemies)
                               if in_range(actor, e, spell["range"])]
                    target = min(targets, key=lambda e: (e["hp"], e["name"]))
                note = cast_spell(actor, target, spell_id, party, rng)
            elif selected == "Use a draught":
                note = use_draught(save, party)
            ts.save(save)

        if not active_enemies(enemies) or not living_party(party):
            break
        for enemy in active_enemies(enemies):
            note = enemy_turn(enemy, party, enemies, rng)
            if not living_party(party):
                break
        ts.save(save)
        round_no += 1

    won = bool(living_party(party) and not active_enemies(enemies))
    if won:
        encounter = content.ENCOUNTERS[encounter_key]
        save["gold"] += encounter["gold"]
        save["inventory"][encounter["reward_item"]] = (
            save["inventory"].get(encounter["reward_item"], 0) + encounter["reward_count"])
        save["inventory"]["Bell Shard"] = save["inventory"].get("Bell Shard", 0) + 1
        save["encounter_done"] = True
        save["visited_vault"] = True
        save["quest_status"] = "complete"
        quest = content.QUESTS["bell_below"]
        save["gold"] += quest["reward_gold"]
        award_xp(party, quest["reward_xp"] + sum(enemy.get("xp", 0) for enemy in enemies))
    ts.save(save)
    encounter = content.ENCOUNTERS[encounter_key]
    page("VICTORY" if won else "WITHDRAWAL",
         [encounter["victory"] if won else encounter["defeat"],
          f"Gold: {save['gold']}   Bell Shards: {save['inventory'].get('Bell Shard', 0)}",
          content.QUESTS["bell_below"]["complete"] if won else encounter["defeat_hint"]])
    ts.tv_pause("press enter to return to Greyharbor")
    return won


def show_dialogue(save: dict[str, Any]) -> None:
    dialogue = content.DIALOGUE["fenna"]
    body = [f"{dialogue['speaker']}: {line}" for line in dialogue["lines"]]
    options = [row[0] for row in dialogue["choices"]]
    selected = choose("CAPTAIN FENNA", body, options)
    _, reply, action = dialogue["choices"][selected]
    if action == "accept":
        save["quest_status"] = "active"
        response = dialogue["accept_response"]
    elif action == "ask":
        result = resolve_check(2, 12)
        save["quest_clue"] = bool(result["success"])
        response = (f"Insight {result['roll']}+2: " +
                    (dialogue["insight_success"] if result["success"]
                     else dialogue["insight_failure"]))
    else:
        response = "Fenna turns back to the river map."
    page(dialogue["speaker"], [reply, response])
    ts.tv_pause("press enter to continue")
    ts.save(save)


def party_screen(save: dict[str, Any]) -> None:
    while True:
        party = save["party"]
        items = [f"{name}: {count}" for name, count in save["inventory"].items() if count]
        lines = [f"Gold {save['gold']}  |  " + (", ".join(items) if items else "No supplies")]
        for member in party:
            lines.append(f"{member['name']:<14} {member['role']:<11} "
                         f"HP {member['hp']:>2}/{member['max_hp']}  AC {member['ac']}  L{member['level']}")
        choice = choose("PARTY & PACK", lines,
                        ["Use a draught", "View quest", "Back"])
        if choice == 0:
            note = use_draught(save, party)
            page("PACK", [note])
            ts.tv_pause()
            ts.save(save)
        elif choice == 1:
            status = save["quest_status"]
            quest = content.QUESTS["bell_below"]
            desc = (quest["summary"] if status == "active" else
                    quest["complete"] if status == "complete" else quest["rumour"])
            page(quest["title"], [f"Status: {status.replace('_', ' ')}", desc])
            ts.tv_pause()
        else:
            return


def camp(save: dict[str, Any]) -> None:
    rations = save["inventory"].get("Ration", 0)
    options = ["Long rest" if rations else "Rest by the fire"]
    options.append("Back")
    selected = choose("CAMP", [content.CAMP_TEXT,
                                f"Rations: {rations}  |  Spell uses return after a rest."], options)
    if selected == 1:
        return
    if rations:
        save["inventory"]["Ration"] -= 1
    for member in save["party"]:
        member["hp"] = member["max_hp"]
        member["guard"] = 0
        for spell_id in member.get("spells", []):
            if spell_id in content.SPELLS:
                member.setdefault("slots", {})[spell_id] = content.SPELLS[spell_id]["uses"]
    page("RESTED", ["The party is rested. Wounds close and spells return.",
                     f"Rations remaining: {save['inventory'].get('Ration', 0)}"])
    ts.save(save)
    ts.tv_pause("press enter to return")


def venture(save: dict[str, Any]) -> None:
    if save["encounter_done"]:
        page(content.ENCOUNTERS["cinder_vault"]["name"], [content.QUESTS["bell_below"]["complete"],
                                                           content.VAULT_QUIET])
        ts.tv_pause("press enter to return")
        return
    if save["quest_status"] != "active":
        page(content.ENCOUNTERS["cinder_vault"]["name"], content.VAULT_LOCKED)
        ts.tv_pause("press enter to return")
        return
    page(content.ENCOUNTERS["cinder_vault"]["name"], content.ENCOUNTERS["cinder_vault"]["intro"])
    ts.tv_pause("enter the vault")
    combat(save)


def main() -> int:
    ts.tv("Grimhollow")
    if os.environ.get("GRIMHOLLOW_SEED") is not None:
        random.seed(int(os.environ["GRIMHOLLOW_SEED"]))
    save = prepare_save(ts.load(defaults()))
    ts.save(save)
    if not save.get("seen_intro"):
        page("GRIMHOLLOW", content.OPENING + ["", "A party adventure in the river town of Greyharbor."])
        ts.tv_pause("press enter to begin")
        save["seen_intro"] = True
        ts.save(save)

    while True:
        quest_status = save["quest_status"].replace("_", " ")
        lines = content.HUB_TEXT + [
            f"Party {len(save['party'])}/4  |  Gold {save['gold']}  |  The Bell Below: {quest_status}",
        ]
        selected = choose("GREYHARBOR", lines,
                          ["Talk to Captain Fenna", "Enter the Cinder Vault",
                           "Party and inventory", "Camp and rest", "Save and quit"])
        if selected == 0:
            show_dialogue(save)
        elif selected == 1:
            venture(save)
        elif selected == 2:
            party_screen(save)
        elif selected == 3:
            camp(save)
        else:
            ts.save(save)
            page("SAVE COMPLETE", [content.GREYHARBOR_EXIT])
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        try:
            ts.tv_print("\nJourney saved. The party returns to the lantern.")
        except Exception:
            pass
        raise SystemExit(130)
