"""GameServer message tests with fake sockets (no network)."""

import logging
import random
import unittest

from game_engine import Battle, Pokemon
from protocol import LineBuffer
from server import Client, GameServer

logging.disable(logging.CRITICAL)


class FakeConn:
    """Records everything sent to it."""

    def __init__(self):
        self.buffer = LineBuffer()
        self.received = []

    def sendall(self, data):
        self.received.extend(self.buffer.feed(data))

    def shutdown(self, how):
        pass

    def last(self, mtype):
        return [m for m in self.received if m["type"] == mtype][-1]


class GameOverEventsTest(unittest.TestCase):
    def setUp(self):
        self.server = GameServer(rng=random.Random(0))
        self.server.start()
        self.red = Client(FakeConn(), ("127.0.0.1", 1))
        self.blue = Client(FakeConn(), ("127.0.0.1", 2))
        for client, name in ((self.red, "Red"), (self.blue, "Blue")):
            self.server.run_locked(self.server._handle, client,
                                   {"type": "CONNECT", "player_name": name})

    def test_final_round_events_reach_both_clients(self):
        # One-Pokemon teams; Alakazam outspeeds and KOs a 1 HP Gengar.
        teams = {"player1": [Pokemon("Alakazam")],
                 "player2": [Pokemon("Gengar")]}
        teams["player2"][0].hp = 1
        self.server.battle = Battle(rng=random.Random(0), teams=teams)
        for client, move in ((self.red, "Psychic"), (self.blue, "Lick")):
            self.server.run_locked(self.server._handle, client,
                                   {"type": "MOVE", "move_name": move})
        over_red = self.red.conn.last("GAME_OVER")
        over_blue = self.blue.conn.last("GAME_OVER")
        self.assertEqual(over_red, over_blue)
        self.assertEqual(over_red["result"], "WIN")
        self.assertEqual(over_red["winner"], "player1")
        self.assertEqual(over_red["events"][-1], "Gengar fainted!")
        self.assertTrue(over_red["events"][0].startswith(
            "Alakazam used Psychic!"))

    def test_forfeit_has_empty_events(self):
        self.server.on_player_left(self.blue)
        over = self.red.conn.last("GAME_OVER")
        self.assertEqual(over["result"], "FORFEIT")
        self.assertEqual(over["winner"], "player1")
        self.assertEqual(over["events"], [])


if __name__ == "__main__":
    unittest.main()
