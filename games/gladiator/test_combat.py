"""Headless tests for Gladiator's first combat rules slice."""
from __future__ import annotations

import unittest

try:
    from .combat import (ActionKind, Arena, BodyPart, Duel, FighterState, Intent,
                         Position, Posture, Wound, WEAPONS, marksman_intent,
                         profile_vitals)
except ImportError:
    from combat import (ActionKind, Arena, BodyPart, Duel, FighterState, Intent,
                        Position, Posture, Wound, WEAPONS, marksman_intent,
                        profile_vitals)


def duel() -> Duel:
    return Duel(
        Arena(5, 5, cover={Position(2, 2)}),
        {
            "Mara": FighterState("Mara", Position(0, 2), WEAPONS["blade"]),
            "Teren": FighterState("Teren", Position(4, 2), WEAPONS["bow"]),
        },
    )


class CombatRulesTests(unittest.TestCase):
    def test_grid_distance_and_line_of_sight(self) -> None:
        fight = duel()
        self.assertEqual(fight.distance("Mara", "Teren"), 4)
        self.assertTrue(fight.arena.visible(Position(0, 2), Position(4, 2)))
        fight.arena.blocked.add(Position(2, 2))
        self.assertFalse(fight.arena.visible(Position(0, 2), Position(4, 2)))

    def test_melee_cannot_strike_from_far_away(self) -> None:
        fight = duel()
        events = fight.queue_intent(Intent("Mara", ActionKind.STRIKE, Position(4, 2)))
        events += fight.resolve()
        self.assertTrue(any(event.kind == "blocked" for event in events))
        self.assertEqual(fight.actor("Teren").hp, 40)

    def test_projectile_travels_and_hits_later(self) -> None:
        fight = duel()
        fight.queue_intent(Intent("Teren", ActionKind.SHOOT, Position(0, 2),
                                  BodyPart.ARM))
        fired = fight.resolve()
        self.assertTrue(any(event.kind == "projectile" for event in fired))
        self.assertEqual(fight.actor("Mara").hp, 40)
        hit = fight.resolve()
        self.assertTrue(any(event.kind == "hit" for event in hit))
        self.assertLess(fight.actor("Mara").hp, 40)
        self.assertEqual(fight.actor("Mara").wounds[-1].part, BodyPart.ARM)

    def test_ranged_ammunition_requires_reload(self) -> None:
        fight = duel()
        shooter = fight.actor("Teren")
        shooter.loaded = 0
        self.assertFalse(shooter.can_fire())
        fight.queue_intent(Intent("Teren", ActionKind.RELOAD))
        fight.resolve()
        events = fight.resolve()
        self.assertTrue(any(event.kind == "reload" for event in events))
        self.assertEqual(shooter.loaded, shooter.weapon.ammo)

    def test_cover_stops_projectile(self) -> None:
        fight = duel()
        fight.actor("Mara").position = Position(2, 2)
        fight.queue_intent(Intent("Teren", ActionKind.SHOOT, Position(2, 2)))
        fight.resolve()
        events = fight.resolve()
        self.assertTrue(any(event.kind == "cover" for event in events))
        self.assertEqual(fight.actor("Mara").hp, 40)

    def test_guard_reduces_damage_and_restores_posture(self) -> None:
        fight = duel()
        fighter = fight.actor("Mara")
        fighter.position = Position(1, 2)
        fight.queue_intent(Intent("Mara", ActionKind.GUARD))
        fight.resolve()
        self.assertEqual(fighter.posture_mode, Posture.GUARD)
        fight.queue_intent(Intent("Teren", ActionKind.SHOOT, Position(1, 2)))
        fight.resolve()
        fight.resolve()
        self.assertLess(fighter.hp, 40)
        self.assertGreater(fighter.hp, 30)

    def test_concealment_spends_stamina_and_focus_action_recovers(self) -> None:
        fight = duel()
        fighter = fight.actor("Mara")
        before = fighter.stamina
        fight.queue_intent(Intent("Mara", ActionKind.CONCEAL))
        fight.resolve()
        self.assertTrue(fighter.concealed)
        self.assertLess(fighter.stamina, before)
        fighter.focus = 5
        fight.queue_intent(Intent("Mara", ActionKind.FOCUS))
        fight.resolve()
        self.assertGreater(fighter.focus, 5)

    def test_wound_changes_follow_up_movement_cost(self) -> None:
        fight = duel()
        fighter = fight.actor("Mara")
        fighter.wounds.append(Wound(BodyPart.LEG, 3))
        before = fighter.stamina
        fight.move("Mara", Position(1, 2))
        self.assertEqual(fighter.stamina, before - 7)

    def test_marksman_repositions_instead_of_firing_every_turn(self) -> None:
        fight = duel()
        fight.fighters["Teren"].name = "The Marksman"
        fight.fighters["The Marksman"] = fight.fighters.pop("Teren")
        first = marksman_intent(fight, "Mara", 1)
        third = marksman_intent(fight, "Mara", 3)
        self.assertEqual(first.kind, ActionKind.SHOOT)
        self.assertEqual(third.kind, ActionKind.MOVE)

    def test_profile_changes_starting_vitals_without_creating_a_class(self) -> None:
        hp, stamina = profile_vitals({
            "height": "tall",
            "stats": {"might": 1, "agility": 1, "endurance": 4, "wit": 1},
        })
        self.assertEqual(hp, 58)
        self.assertEqual(stamina, 102)


if __name__ == "__main__":
    unittest.main()
