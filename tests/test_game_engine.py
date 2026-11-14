"""Game engine tests: type chart, speed order, faints, round cap."""

import random
import unittest

import pokedex
from game_engine import ROUND_CAP, Battle, Pokemon, calc_hp, calc_stat


def battle_with(p1_species, p2_species, seed=0):
    teams = {"player1": [Pokemon(name) for name in p1_species],
             "player2": [Pokemon(name) for name in p2_species]}
    return Battle(rng=random.Random(seed), teams=teams)


class TypeChartTest(unittest.TestCase):
    def test_ghost_has_no_effect_on_psychic(self):
        """Gen 1 quirk: Ghost moves do nothing to Psychic types."""
        self.assertEqual(pokedex.type_multiplier("Ghost", ["Psychic"]), 0)

    def test_effectiveness(self):
        self.assertEqual(pokedex.type_multiplier("Water", ["Fire"]), 2)
        self.assertEqual(pokedex.type_multiplier("Fire", ["Water"]), 0.5)
        self.assertEqual(pokedex.type_multiplier("Electric", ["Ground"]), 0)
        self.assertEqual(pokedex.type_multiplier("Normal", ["Ghost"]), 0)
        self.assertEqual(pokedex.type_multiplier("Ice", ["Fire"]), 1)
        # Dual types multiply: Electric is 2x on Water and 2x on Flying.
        self.assertEqual(
            pokedex.type_multiplier("Electric", ["Water", "Flying"]), 4)

    def test_lick_does_not_affect_alakazam(self):
        battle = battle_with(["Gengar"], ["Alakazam"])
        events = battle.resolve_round({"player1": "Lick",
                                       "player2": "Thunder Wave"})
        alakazam = battle.active_pokemon("player2")
        self.assertEqual(alakazam.hp, alakazam.max_hp)
        self.assertIn("Gengar used Lick! It doesn't affect Alakazam...",
                      events)


class StatsAndOrderTest(unittest.TestCase):
    def test_level_50_stats(self):
        mon = Pokemon("Charizard")
        self.assertEqual(mon.max_hp, calc_hp(78))
        self.assertEqual(mon.max_hp, 138)
        self.assertEqual(mon.stats["speed"], calc_stat(100))
        self.assertEqual(mon.stats["speed"], 105)

    def test_faster_pokemon_moves_first(self):
        battle = battle_with(["Snorlax"], ["Jolteon"])
        self.assertEqual(battle.turn_order(), ["player2", "player1"])

    def test_speed_tie_player1_first(self):
        battle = battle_with(["Snorlax"], ["Snorlax"])
        self.assertEqual(battle.turn_order(), ["player1", "player2"])

    def test_paralysis_quarters_speed(self):
        battle = battle_with(["Jolteon"], ["Snorlax"])
        battle.active_pokemon("player1").status = "PAR"
        # Jolteon 135 // 4 = 33 is now slower than Snorlax's 35.
        self.assertEqual(battle.turn_order(), ["player2", "player1"])


class FaintAndOutcomeTest(unittest.TestCase):
    def test_faint_marks_fnt_and_updates_remaining(self):
        battle = battle_with(["Alakazam", "Snorlax"], ["Gengar", "Chansey"])
        battle.active_pokemon("player2").hp = 1
        events = battle.resolve_round({"player1": "Psychic",
                                       "player2": "Thunderbolt"})
        fainted = battle.check_faint(events)
        self.assertEqual(fainted, ["player2"])
        self.assertEqual(battle.active_pokemon("player2").status, "FNT")
        self.assertEqual(battle.remaining(), {"player1": 2, "player2": 1})
        self.assertIn("Gengar fainted!", events)
        # Alakazam is faster, so Gengar's move was skipped.
        self.assertFalse(any(e.startswith("Gengar used") for e in events))
        self.assertIsNone(battle.outcome())

    def test_win_when_a_side_runs_out(self):
        battle = battle_with(["Alakazam"], ["Gengar"])
        battle.active_pokemon("player2").hp = 0
        battle.check_faint([])
        self.assertEqual(battle.outcome(), ("WIN", "player1"))

    def test_draw_when_both_run_out(self):
        battle = battle_with(["Alakazam"], ["Gengar"])
        battle.active_pokemon("player1").hp = 0
        battle.active_pokemon("player2").hp = 0
        self.assertEqual(battle.outcome(), ("DRAW", None))

    def test_round_cap_draw(self):
        battle = battle_with(["Chansey"], ["Chansey"])
        battle.round = ROUND_CAP - 1
        self.assertIsNone(battle.outcome())
        battle.round = ROUND_CAP
        battle.resolve_round({"player1": "Thunder Wave",
                              "player2": "Thunder Wave"})
        self.assertEqual(battle.remaining(), {"player1": 1, "player2": 1})
        self.assertEqual(battle.outcome(), ("DRAW", None))

    def test_switch_validation(self):
        battle = battle_with(["Alakazam", "Snorlax"], ["Gengar"])
        battle.active_pokemon("player1").hp = 0
        battle.check_faint([])
        self.assertEqual(battle.switch_error("player1", "Mew"),
                         "INVALID_MOVE")
        self.assertEqual(battle.switch_error("player1", "Alakazam"),
                         "FAINTED_POKEMON_SELECTED")
        self.assertIsNone(battle.switch_error("player1", "Snorlax"))
        battle.switch("player1", "Snorlax")
        self.assertEqual(battle.active_pokemon("player1").species, "Snorlax")


if __name__ == "__main__":
    unittest.main()
