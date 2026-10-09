import unittest
from pathlib import Path

from termstation import library
from termstation.library import Game


def _game(tags):
    return Game(slug="t", name="T", entry=["x"], root=Path("."), tags=tags)


class CompartmentTests(unittest.TestCase):
    def test_first_match_wins(self):
        self.assertEqual(compartment_for_tags(["roguelike", "cards"]),
                         "roguelikes")
        self.assertEqual(compartment_for_tags(["football", "management"]),
                         "sports")
        self.assertEqual(compartment_for_tags(["strategy", "sim"]),
                         "strategy")

    def test_fallthrough_to_cabinet(self):
        self.assertEqual(compartment_for_tags([]), "cabinet")
        self.assertEqual(compartment_for_tags(["mystery"]), "cabinet")

    def test_titles(self):
        self.assertEqual(library.compartment_title("all"), "All Games")
        self.assertEqual(library.compartment_title("sports"), "Sports")
        self.assertEqual(library.compartment_title("nope"), "Cabinet")

    def test_keys_start_with_all(self):
        keys = library.compartment_keys()
        self.assertEqual(keys[0], "all")
        self.assertIn("roguelikes", keys)

    def test_every_bundled_game_has_a_shelf(self):
        """No game may silently fall into the Cabinet: shelves are the
        library's organisation, so every manifest must carry a tag that
        maps to one."""
        games_dir = Path(__file__).resolve().parent.parent / "games"
        homeless = []
        for entry in sorted(games_dir.iterdir()):
            if not entry.is_dir() or not (entry / "game.toml").exists():
                continue
            game = library.load_manifest(entry)
            if library.compartment_for(game) == library.CABINET_KEY:
                homeless.append(f"{game.slug}: {game.tags}")
        self.assertEqual(homeless, [])


def compartment_for_tags(tags):
    return library.compartment_for(_game(tags))


if __name__ == "__main__":
    unittest.main()
