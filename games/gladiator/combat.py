"""Deterministic, curses-independent rules for Gladiator's combat slice.

Content belongs in this game-local module while the rules are proven. The
renderer should consume these value objects and never decide combat outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from random import Random


class Posture(str, Enum):
    PRESSURE = "pressure"
    GUARD = "guard"
    MOBILE = "mobile"
    CONCEAL = "conceal"
    COMMIT = "commit"
    RECOVER = "recover"


class BodyPart(str, Enum):
    HEAD = "head"
    ARM = "arm"
    TORSO = "torso"
    LEG = "leg"


class ActionKind(str, Enum):
    MOVE = "move"
    STRIKE = "strike"
    SHOOT = "shoot"
    GUARD = "guard"
    CONCEAL = "conceal"
    FOCUS = "focus"
    RELOAD = "reload"


@dataclass(frozen=True)
class Position:
    x: int
    y: int

    def step(self, dx: int, dy: int) -> "Position":
        return Position(self.x + dx, self.y + dy)


@dataclass(frozen=True)
class Weapon:
    name: str
    style: str
    reach: int
    damage: int
    accuracy: int = 90
    projectile: bool = False
    travel: int = 0
    ammo: int = 0
    reload_turns: int = 0


WEAPONS = {
    "spear": Weapon("spear", "spear-control", 2, 10, 88),
    "blade": Weapon("blade", "duelist", 1, 12, 94),
    "bow": Weapon("bow", "marksman", 6, 11, 82, True, 2, 3, 1),
    "javelin": Weapon("javelin", "controller", 5, 13, 78, True, 1, 2, 1),
}


@dataclass
class Wound:
    part: BodyPart
    severity: int

    @property
    def label(self) -> str:
        return f"{self.part.value} wound ({self.severity})"


@dataclass
class FighterState:
    name: str
    position: Position
    weapon: Weapon
    max_hp: int = 40
    hp: int = 40
    max_stamina: int = 100
    stamina: int = 100
    max_posture: int = 100
    posture: int = 70
    max_focus: int = 100
    focus: int = 50
    posture_mode: Posture = Posture.PRESSURE
    facing: tuple[int, int] = (1, 0)
    concealed: bool = False
    wounds: list[Wound] = field(default_factory=list)
    loaded: int = 0
    reload_remaining: int = 0
    height: str = "average"
    stats: dict[str, int] = field(default_factory=lambda: {
        "might": 1, "agility": 1, "endurance": 1, "wit": 1,
    })

    def __post_init__(self) -> None:
        if self.weapon.projectile and not self.loaded:
            self.loaded = self.weapon.ammo

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def leg_penalty(self) -> int:
        return sum(w.severity for w in self.wounds if w.part == BodyPart.LEG)

    @property
    def arm_penalty(self) -> int:
        return sum(w.severity for w in self.wounds if w.part == BodyPart.ARM)

    def can_move(self) -> bool:
        return self.alive and self.stamina >= 4 and self.reload_remaining == 0

    def can_fire(self) -> bool:
        return self.alive and self.weapon.projectile and self.loaded > 0 and self.reload_remaining == 0


def profile_vitals(profile: dict) -> tuple[int, int]:
    """Translate the opening profile into combat-facing starting values."""
    stats = profile.get("stats", {})
    endurance = int(stats.get("endurance", 1))
    height_bonus = {"short": -2, "average": 0, "tall": 2}.get(
        profile.get("height", "average"), 0)
    return 40 + endurance * 4 + height_bonus, 100 + int(
        stats.get("agility", 1)) * 2


@dataclass(frozen=True)
class Intent:
    actor: str
    kind: ActionKind
    target: Position | None = None
    body_part: BodyPart | None = None
    commitment: int = 1
    reveal: int = 0


@dataclass
class Projectile:
    owner: str
    origin: Position
    target: Position
    damage: int
    turns: int
    body_part: BodyPart | None = None


@dataclass(frozen=True)
class CombatEvent:
    text: str
    kind: str = "info"


@dataclass
class Arena:
    width: int = 5
    height: int = 5
    blocked: set[Position] = field(default_factory=set)
    cover: set[Position] = field(default_factory=set)

    def inside(self, position: Position) -> bool:
        return 0 <= position.x < self.width and 0 <= position.y < self.height

    def open(self, position: Position) -> bool:
        return self.inside(position) and position not in self.blocked

    def line(self, origin: Position, target: Position) -> list[Position]:
        """Return an orthogonal line; diagonal shots are intentionally excluded."""
        if origin.x != target.x and origin.y != target.y:
            return []
        points: list[Position] = []
        dx = (target.x > origin.x) - (target.x < origin.x)
        dy = (target.y > origin.y) - (target.y < origin.y)
        current = origin.step(dx, dy)
        while current != target:
            points.append(current)
            current = current.step(dx, dy)
        points.append(target)
        return points

    def distance(self, a: Position, b: Position) -> int:
        return abs(a.x - b.x) + abs(a.y - b.y)

    def visible(self, origin: Position, target: Position) -> bool:
        path = self.line(origin, target)
        return bool(path) and all(self.open(point) for point in path[:-1])


@dataclass
class Duel:
    arena: Arena
    fighters: dict[str, FighterState]
    projectiles: list[Projectile] = field(default_factory=list)
    intents: dict[str, Intent] = field(default_factory=dict)
    rng: Random = field(default_factory=lambda: Random(1))

    def actor(self, name: str) -> FighterState:
        return self.fighters[name]

    def distance(self, source: str, target: str) -> int:
        return self.arena.distance(self.actor(source).position, self.actor(target).position)

    def threat_cells(self, name: str, kind: ActionKind = ActionKind.STRIKE) -> set[Position]:
        fighter = self.actor(name)
        if kind == ActionKind.SHOOT:
            cells = set(self.arena.line(fighter.position,
                                         Position(fighter.position.x + fighter.facing[0] * fighter.weapon.reach,
                                                  fighter.position.y + fighter.facing[1] * fighter.weapon.reach)))
            return {cell for cell in cells if self.arena.open(cell)}
        cells: set[Position] = set()
        for x in range(self.arena.width):
            for y in range(self.arena.height):
                point = Position(x, y)
                if self.arena.distance(fighter.position, point) <= fighter.weapon.reach:
                    cells.add(point)
        return cells

    def set_posture(self, name: str, posture: Posture) -> list[CombatEvent]:
        fighter = self.actor(name)
        cost = 8 if posture in {Posture.CONCEAL, Posture.COMMIT} else 0
        if fighter.stamina < cost:
            return [CombatEvent(f"{name} cannot enter {posture.value} posture.", "blocked")]
        fighter.stamina -= cost
        fighter.posture_mode = posture
        fighter.concealed = posture == Posture.CONCEAL
        return [CombatEvent(f"{name} shifts into {posture.value} posture.", "stance")]

    def queue_intent(self, intent: Intent) -> list[CombatEvent]:
        fighter = self.actor(intent.actor)
        if not fighter.alive:
            return [CombatEvent(f"{intent.actor} cannot act while down.", "blocked")]
        if intent.kind == ActionKind.SHOOT and not fighter.can_fire():
            return [CombatEvent(f"{intent.actor} has no loaded projectile.", "blocked")]
        self.intents[intent.actor] = intent
        return [CombatEvent(f"{intent.actor} commits to {intent.kind.value}.", "intent")]

    def move(self, name: str, target: Position) -> list[CombatEvent]:
        fighter = self.actor(name)
        if not fighter.can_move() or not self.arena.open(target):
            return [CombatEvent(f"{name} cannot move there.", "blocked")]
        if self.arena.distance(fighter.position, target) != 1:
            return [CombatEvent(f"{name} can only move one cell.", "blocked")]
        fighter.position = target
        fighter.stamina -= 4 + fighter.leg_penalty
        fighter.posture = max(0, fighter.posture - 3)
        fighter.concealed = False
        return [CombatEvent(f"{name} moves to ({target.x},{target.y}).", "move")]

    def resolve(self) -> list[CombatEvent]:
        events: list[CombatEvent] = []
        for fighter in self.fighters.values():
            if fighter.reload_remaining > 0:
                fighter.reload_remaining -= 1
                if fighter.reload_remaining == 0:
                    fighter.loaded = fighter.weapon.ammo
                    events.append(CombatEvent(f"{fighter.name} finishes reloading.", "reload"))
        ordered = sorted(self.intents.values(), key=lambda intent: (
            intent.commitment, -self.actor(intent.actor).focus))
        for intent in ordered:
            if not self.actor(intent.actor).alive:
                continue
            events.extend(self._resolve_intent(intent))
        self.intents.clear()
        events.extend(self._advance_projectiles())
        for fighter in self.fighters.values():
            fighter.stamina = min(fighter.max_stamina, fighter.stamina + 5)
            fighter.posture = min(fighter.max_posture, fighter.posture + 4)
            if fighter.posture_mode == Posture.RECOVER:
                fighter.focus = min(fighter.max_focus, fighter.focus + 10)
        return events

    def _resolve_intent(self, intent: Intent) -> list[CombatEvent]:
        fighter = self.actor(intent.actor)
        if intent.kind == ActionKind.MOVE and intent.target:
            return self.move(intent.actor, intent.target)
        if intent.kind == ActionKind.GUARD:
            fighter.stamina = max(0, fighter.stamina - 5)
            fighter.posture = min(fighter.max_posture, fighter.posture + 18)
            fighter.posture_mode = Posture.GUARD
            return [CombatEvent(f"{intent.actor} raises a guard.", "guard")]
        if intent.kind == ActionKind.FOCUS:
            fighter.stamina = max(0, fighter.stamina - 3)
            fighter.focus = min(fighter.max_focus, fighter.focus + 18)
            fighter.posture_mode = Posture.RECOVER
            return [CombatEvent(f"{intent.actor} studies the exchange.", "focus")]
        if intent.kind == ActionKind.RELOAD:
            fighter.reload_remaining = fighter.weapon.reload_turns
            return [CombatEvent(f"{intent.actor} starts reloading.", "reload")]
        if intent.kind == ActionKind.CONCEAL:
            return self.set_posture(intent.actor, Posture.CONCEAL)
        if intent.kind == ActionKind.SHOOT and intent.target:
            return self._shoot(intent, fighter)
        if intent.kind == ActionKind.STRIKE and intent.target:
            return self._strike(intent, fighter)
        return [CombatEvent(f"{intent.actor}'s action has no valid target.", "blocked")]

    def _shoot(self, intent: Intent, fighter: FighterState) -> list[CombatEvent]:
        target = intent.target
        if not target or not self.arena.visible(fighter.position, target):
            return [CombatEvent(f"{fighter.name}'s shot is blocked.", "blocked")]
        distance = self.arena.distance(fighter.position, target)
        if distance > fighter.weapon.reach:
            return [CombatEvent(f"{fighter.name}'s target is out of range.", "blocked")]
        fighter.loaded -= 1
        fighter.stamina = max(0, fighter.stamina - 10 - fighter.arm_penalty)
        fighter.focus = max(0, fighter.focus - 8)
        fighter.concealed = False
        damage = fighter.weapon.damage + (5 if distance >= 3 else 0)
        self.projectiles.append(Projectile(fighter.name, fighter.position, target,
                                            damage, fighter.weapon.travel,
                                            intent.body_part))
        return [CombatEvent(f"{fighter.name} fires toward ({target.x},{target.y}).", "projectile")]

    def _strike(self, intent: Intent, fighter: FighterState) -> list[CombatEvent]:
        target = intent.target
        if not target or self.arena.distance(fighter.position, target) > fighter.weapon.reach:
            return [CombatEvent(f"{fighter.name}'s strike cannot reach.", "blocked")]
        defender = next((other for other in self.fighters.values()
                         if other.name != fighter.name and other.position == target), None)
        if defender is None:
            return [CombatEvent(f"{fighter.name} cuts empty air.", "miss")]
        cost = 12 + (fighter.arm_penalty * 2)
        if fighter.stamina < cost:
            return [CombatEvent(f"{fighter.name} is too winded to strike.", "blocked")]
        fighter.stamina -= cost
        fighter.posture = max(0, fighter.posture - 8)
        fighter.concealed = False
        damage = fighter.weapon.damage + (4 if fighter.posture_mode == Posture.COMMIT else 0)
        return self._apply_hit(fighter, defender, damage, intent.body_part)

    def _advance_projectiles(self) -> list[CombatEvent]:
        events: list[CombatEvent] = []
        remaining: list[Projectile] = []
        for projectile in self.projectiles:
            projectile.turns -= 1
            if projectile.turns > 0:
                remaining.append(projectile)
                continue
            defender = next((fighter for fighter in self.fighters.values()
                             if fighter.name != projectile.owner
                             and fighter.position == projectile.target), None)
            if defender is None:
                events.append(CombatEvent("The projectile misses its target.", "miss"))
                continue
            attacker = self.actor(projectile.owner)
            if defender.position in self.arena.cover:
                events.append(CombatEvent(f"{defender.name} takes cover.", "cover"))
                continue
            events.extend(self._apply_hit(attacker, defender, projectile.damage,
                                          projectile.body_part))
        self.projectiles = remaining
        return events

    def _apply_hit(self, attacker: FighterState, defender: FighterState,
                   damage: int, requested: BodyPart | None) -> list[CombatEvent]:
        if defender.posture_mode == Posture.GUARD:
            damage = max(1, damage // 2)
            defender.posture = max(0, defender.posture - 15)
        part = requested or self._likely_part(defender)
        wound = Wound(part, max(1, damage // 10))
        defender.wounds.append(wound)
        defender.hp = max(0, defender.hp - damage)
        defender.focus = max(0, defender.focus - 5)
        defender.posture = max(0, defender.posture - damage)
        return [CombatEvent(f"{attacker.name} hits {defender.name} for {damage} ({part.value}).", "hit"),
                CombatEvent(f"{defender.name} suffers a {wound.label}.", "wound")]

    def _likely_part(self, defender: FighterState) -> BodyPart:
        parts = [BodyPart.TORSO, BodyPart.ARM, BodyPart.LEG, BodyPart.HEAD]
        if defender.posture_mode == Posture.GUARD:
            parts = [BodyPart.ARM, BodyPart.TORSO, BodyPart.LEG]
        return parts[self.rng.randrange(len(parts))]


def best_enemy_step(duel: Duel, foe: FighterState,
                    player: FighterState, retreat: bool = False) -> Position | None:
    candidates = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        target = foe.position.step(dx, dy)
        if duel.arena.open(target):
            distance = duel.arena.distance(target, player.position)
            visible = duel.arena.visible(target, player.position)
            score = distance if retreat else (-distance if visible else distance)
            candidates.append((score, target))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def marksman_intent(duel: Duel, player_name: str, turn: int) -> Intent:
    foe = duel.actor("The Marksman")
    player = duel.actor(player_name)
    if foe.reload_remaining or foe.loaded == 0:
        return Intent(foe.name, ActionKind.RELOAD)
    if duel.distance(foe.name, player.name) <= 2:
        target = best_enemy_step(duel, foe, player, retreat=True)
        return Intent(foe.name, ActionKind.MOVE, target) if target else Intent(
            foe.name, ActionKind.GUARD)
    if (foe.can_fire() and duel.arena.visible(foe.position, player.position)
            and turn % 3 != 0):
        return Intent(foe.name, ActionKind.SHOOT, player.position)
    target = best_enemy_step(duel, foe, player)
    return Intent(foe.name, ActionKind.MOVE, target) if target else Intent(
        foe.name, ActionKind.CONCEAL)
