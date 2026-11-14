"""Game server: networking, FSM, and concurrency.

Follows docs/concurrency_design.md:
- The main thread only runs the accept() loop and spawns one daemon worker
  thread per connection.
- Workers recv() and parse outside game_lock, then handle each complete
  message inside one `with game_lock:` critical section.
- Every read or write of shared state and every socket write happens under
  game_lock. Broadcasts are sent while holding it.
- Send failures are recorded inside the lock and handled by on_player_left()
  after the lock is released. on_player_left() is idempotent.
"""

import argparse
import logging
import random
import socket
import sys
import threading
from collections import deque

import game_engine
import pokedex
from game_engine import ROLES, other
from protocol import (PORT_MAX, PORT_MIN, LineBuffer, MalformedLine,
                      parse_port, send_line)

HOST = "0.0.0.0"
PLAYERS_NEEDED = 2
NAME_MAX_LEN = 20
RECV_SIZE = 4096

# Server states in which a game is in progress (forfeit on disconnect).
IN_GAME_STATES = ("GAME_START", "READINESS", "EVALUATE_ROUND", "CHECK_FAINT",
                  "CHECK_WIN_DRAW")
# Message types a client may send. Anything else is MALFORMED_MESSAGE.
CLIENT_TYPES = ("CONNECT", "MOVE", "SWITCH", "DISCONNECT")

log = logging.getLogger("server")


class Client:
    """One TCP connection. name is set by CONNECT, role while in a game."""

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.name = None
        self.role = None

    def label(self):
        who = self.name or "{}:{}".format(*self.addr)
        return "{} ({})".format(who, self.role) if self.role else who


class GameServer:
    def __init__(self, rng=None):
        self.game_lock = threading.Lock()
        self.rng = rng or random.Random()
        # Everything below is shared state, protected by game_lock.
        self.state = "INIT"
        self.registered = set()  # clients that sent CONNECT and haven't left
        self.lobby = deque()     # FIFO queue of waiting clients
        self.players = {}        # role -> Client while a game exists
        self.battle = None       # teams, round counter, remaining counts
        self.region = {}         # role -> "AWAITING_MOVES" / "AWAITING_SWITCH"
        self.pending = {}        # role -> locked-in move_name or None
        self.record = {}         # player_name -> {"wins", "losses", "draws"}
        self._failed = []        # clients whose send failed in this section

    # ---- locking helpers ----------------------------------------------

    def run_locked(self, fn, *args):
        """Run fn under game_lock, then forfeit anyone whose send failed.

        on_player_left() takes game_lock itself and threading.Lock is not
        reentrant, so failed players are handled only after the lock is
        released (concurrency_design.md 5.5).
        """
        with self.game_lock:
            self._failed = []
            fn(*args)
            failed, self._failed = self._failed, []
        for client in failed:
            self.on_player_left(client)

    def on_player_left(self, client):
        self.run_locked(self._player_left, client)

    # ---- state transitions and sends (caller holds game_lock) ----------

    def _set_state(self, new_state):
        if new_state != self.state:
            log.info("FSM %s -> %s", self.state, new_state)
            self.state = new_state

    def _set_region(self, role, new_region):
        old = self.region.get(role)
        if self.pending.get(role) is not None:
            old = "locked in"
        log.info("FSM %s region %s -> %s", role, old, new_region)
        self.region[role] = new_region

    def _send(self, client, obj):
        if client in self._failed:
            return
        if send_line(client.conn, obj):
            log.info("SEND %s -> %s", obj["type"], client.label())
        else:
            log.info("SEND %s -> %s FAILED (peer gone)", obj["type"],
                     client.label())
            self._failed.append(client)

    def _broadcast(self, obj):
        for role in ROLES:
            self._send(self.players[role], obj)

    def _send_error(self, client, code, detail):
        self._send(client, {"type": "ERROR", "error_code": code,
                            "detail": detail})

    def _role_in_game(self, client):
        if self.state in IN_GAME_STATES and client.role in self.players:
            if self.players[client.role] is client:
                return client.role
        return None

    # ---- message dispatch (caller holds game_lock) ---------------------

    def start(self):
        with self.game_lock:
            log.info("FSM INIT: loaded %d species",
                     len(pokedex.SPECIES))
            self._set_state("WAITING_FOR_PLAYERS")

    def _handle(self, client, msg):
        mtype = msg["type"]
        if mtype not in CLIENT_TYPES:
            self._send_error(client, "MALFORMED_MESSAGE",
                             "Unknown message type '{}'.".format(mtype))
        elif mtype == "CONNECT":
            self._on_connect(client, msg)
        elif client not in self.registered:
            self._send_error(client, "OUT_OF_TURN",
                             "Send CONNECT before any other message.")
        elif mtype == "MOVE":
            self._on_move(client, msg)
        elif mtype == "SWITCH":
            self._on_switch(client, msg)

    def _on_connect(self, client, msg):
        name = msg.get("player_name")
        if not isinstance(name, str) or not 1 <= len(name) <= NAME_MAX_LEN:
            self._send_error(client, "MALFORMED_MESSAGE",
                             "player_name must be a string of 1-{} "
                             "characters.".format(NAME_MAX_LEN))
            return
        if client in self.registered:
            self._send_error(client, "OUT_OF_TURN", "Already connected.")
            return
        client.name = name
        self.registered.add(client)
        self.lobby.append(client)
        log.info("LOBBY %s joined, queue: %s", name, self._queue_names())
        if (self.state == "WAITING_FOR_PLAYERS"
                and len(self.lobby) >= PLAYERS_NEEDED):
            self._start_game()
        else:
            self._send(client, self._lobby_wait())

    def _on_move(self, client, msg):
        move_name = msg.get("move_name")
        if not isinstance(move_name, str):
            self._send_error(client, "MALFORMED_MESSAGE",
                             "MOVE needs a 'move_name' string.")
            return
        role = self._role_in_game(client)
        if role is None:
            self._send_error(client, "OUT_OF_TURN",
                             "You are not in a running game.")
            return
        if self.region[role] == "AWAITING_SWITCH":
            self._send_error(client, "OUT_OF_TURN",
                             "Your Pokemon fainted: send a SWITCH first.")
            return
        if self.pending[role] is not None:
            self._send_error(client, "OUT_OF_TURN",
                             "You already locked in a move this round.")
            return
        if not self.battle.has_move(role, move_name):
            active = self.battle.active_pokemon(role)
            self._send_error(client, "INVALID_MOVE",
                             "{} does not know {}.".format(active.species,
                                                           move_name))
            return
        log.info("FSM %s region AWAITING_MOVES -> locked in", role)
        self.pending[role] = move_name
        if all(self.pending[r] is not None for r in ROLES):
            self._resolve_round()

    def _on_switch(self, client, msg):
        species = msg.get("switch_to")
        if not isinstance(species, str):
            self._send_error(client, "MALFORMED_MESSAGE",
                             "SWITCH needs a 'switch_to' string.")
            return
        role = self._role_in_game(client)
        if role is None:
            self._send_error(client, "OUT_OF_TURN",
                             "You are not in a running game.")
            return
        if self.region[role] != "AWAITING_SWITCH":
            self._send_error(client, "OUT_OF_TURN",
                             "Your active Pokemon has not fainted.")
            return
        code = self.battle.switch_error(role, species)
        if code == "INVALID_MOVE":
            self._send_error(client, code,
                             "{} is not on your team.".format(species))
            return
        if code == "FAINTED_POKEMON_SELECTED":
            self._send_error(client, code, "{} has fainted and cannot be "
                             "sent out.".format(species))
            return
        self.battle.switch(role, species)
        self._set_region(role, "AWAITING_MOVES")
        events = ["{} sent out {}!".format(client.name, species)]
        self._broadcast(self._state_update(events))

    # ---- game flow (caller holds game_lock) ----------------------------

    def _start_game(self):
        self._set_state("GAME_START")
        first, second = self.lobby.popleft(), self.lobby.popleft()
        self.players = {"player1": first, "player2": second}
        first.role, second.role = "player1", "player2"
        self.battle = game_engine.Battle(rng=self.rng)
        log.info("GAME %s vs %s", first.label(), second.label())
        for role in ROLES:
            mine, theirs = self.players[role], self.players[other(role)]
            self._send(mine, {
                "type": "GAME_START",
                "role": role,
                "opponent_name": theirs.name,
                "your_team": [p.to_dict() for p in self.battle.teams[role]],
                "opponent_team": [p.to_dict()
                                  for p in self.battle.teams[other(role)]],
            })
        self.pending = {role: None for role in ROLES}
        for role in ROLES:
            self._set_region(role, "AWAITING_MOVES")
        self._set_state("READINESS")
        self._broadcast(self._state_update([]))

    def _resolve_round(self):
        battle = self.battle
        self._set_state("EVALUATE_ROUND")
        events = battle.resolve_round(dict(self.pending))
        self._set_state("CHECK_FAINT")
        fainted = battle.check_faint(events)
        self._set_state("CHECK_WIN_DRAW")
        for line in events:
            log.info("ROUND %d: %s", battle.round, line)
        result = battle.outcome()
        if result is not None:
            self._game_over(result[0], result[1], events)
            return
        battle.round += 1
        for role in ROLES:
            region = "AWAITING_SWITCH" if role in fainted else "AWAITING_MOVES"
            self._set_region(role, region)
            self.pending[role] = None
        self._set_state("READINESS")
        self._broadcast(self._state_update(events))

    def _game_over(self, result, winner, events):
        self._set_state("GAME_OVER")
        self._update_record(result, winner)
        self._broadcast(self._game_over_msg(result, winner, events))
        if result == "WIN":
            order = [self.players[winner], self.players[other(winner)]]
        else:
            order = [self.players["player1"], self.players["player2"]]
        self._cleanup(order)

    def _player_left(self, client):
        if client not in self.registered:
            return  # already handled (idempotent)
        log.info("LEFT %s", client.label())
        self.registered.discard(client)
        if client in self.lobby:
            self.lobby.remove(client)
            log.info("LOBBY %s removed, queue: %s", client.name,
                     self._queue_names())
        role = self._role_in_game(client)
        if role is not None:
            winner = other(role)
            survivor = self.players[winner]
            self._set_state("CLEANUP")
            self._update_record("WIN", winner)
            self._send(survivor, self._game_over_msg("FORFEIT", winner, []))
            self._cleanup([survivor])
        try:
            client.conn.shutdown(socket.SHUT_RDWR)  # wake its recv()
        except OSError:
            pass

    def _cleanup(self, requeue):
        """Reset per-game state, then rotate the finished players back in.

        requeue is the finished players in rotation order: winner then
        loser, or player1 then player2 on a draw.
        """
        self._set_state("CLEANUP")
        for client in self.players.values():
            client.role = None
        self.players = {}
        self.battle = None
        self.region = {}
        self.pending = {}
        for client in requeue:
            if client in self.registered and client not in self._failed:
                self.lobby.append(client)
        self._set_state("WAITING_FOR_PLAYERS")
        log.info("LOBBY queue: %s", self._queue_names())
        for client in list(self.lobby):
            self._send(client, self._lobby_wait())
        if len(self.lobby) >= PLAYERS_NEEDED:
            self._start_game()

    def _update_record(self, result, winner):
        names = {role: self.players[role].name for role in ROLES}
        for name in names.values():
            self.record.setdefault(name, {"wins": 0, "losses": 0,
                                          "draws": 0})
        if result == "DRAW":
            for name in names.values():
                self.record[name]["draws"] += 1
        else:
            self.record[names[winner]]["wins"] += 1
            self.record[names[other(winner)]]["losses"] += 1
        log.info("RECORD %s", self._players_record())

    # ---- message builders (caller holds game_lock) ---------------------

    def _lobby_wait(self):
        if self.state == "WAITING_FOR_PLAYERS":
            text = "Waiting for an opponent..."
        else:
            text = "A game is in progress. You are in line for the next one."
        return {"type": "LOBBY_WAIT", "players_connected": len(self.lobby),
                "players_needed": PLAYERS_NEEDED, "message": text}

    def _state_update(self, events):
        awaiting = {}
        for role in ROLES:
            if self.pending[role] is not None:
                awaiting[role] = None
            elif self.region[role] == "AWAITING_SWITCH":
                awaiting[role] = "SWITCH"
            else:
                awaiting[role] = "MOVE"
        return {"type": "STATE_UPDATE", "round": self.battle.round,
                "active": self.battle.active_summaries(), "events": events,
                "awaiting": awaiting, "remaining": self.battle.remaining()}

    def _game_over_msg(self, result, winner, events):
        return {"type": "GAME_OVER", "result": result, "winner": winner,
                "final_state": {"round": self.battle.round,
                                "teams": self.battle.team_summaries()},
                "events": list(events),
                "record": self._players_record()}

    def _players_record(self):
        return {self.players[role].name:
                dict(self.record[self.players[role].name]) for role in ROLES}

    def _queue_names(self):
        return [client.name for client in self.lobby]

    # ---- worker thread -------------------------------------------------

    def client_loop(self, conn, addr):
        """Blocking receive loop (protocol_blueprint.md 5.2), one per client.

        recv() and parsing happen outside game_lock. All three ways a client
        can leave (DISCONNECT, FIN, RST) end in the finally block.
        """
        client = Client(conn, addr)
        log.info("CONN %s:%s connected", *addr)
        buffer = LineBuffer()
        try:
            while True:
                data = conn.recv(RECV_SIZE)
                if not data:  # EOF: peer sent FIN
                    log.info("EOF from %s", client.label())
                    break
                for item in buffer.feed(data):
                    if isinstance(item, MalformedLine):
                        log.info("RECV malformed line <- %s: %s",
                                 client.label(), item.detail)
                        self.run_locked(self._send_error, client,
                                        "MALFORMED_MESSAGE", item.detail)
                        continue
                    log.info("RECV %s <- %s", item["type"], client.label())
                    if item["type"] == "DISCONNECT":
                        log.info("DISCONNECT from %s: %s", client.label(),
                                 item.get("reason", ""))
                        return
                    self.run_locked(self._handle, client, item)
        except OSError as exc:  # ConnectionReset/BrokenPipe/ConnectionAborted
            log.info("Connection lost from %s: %r", client.label(), exc)
        except Exception:
            log.exception("Unexpected error handling %s", client.label())
        finally:
            self.on_player_left(client)
            conn.close()
            log.info("CLOSED %s:%s", *addr)


# ---- command line --------------------------------------------------------

class ArgParser(argparse.ArgumentParser):
    """argparse that exits with status 1 (not 2) on bad arguments."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print("{}: error: {}".format(self.prog, message), file=sys.stderr)
        sys.exit(1)


def parse_args(argv=None):
    parser = ArgParser(description="Gen 1 Pokemon battle server.",
                       epilog="example: python3 server.py -p 8080")
    parser.add_argument("-p", "--port", required=True,
                        help="TCP port to listen on ({}-{})".format(
                            PORT_MIN, PORT_MAX))
    args = parser.parse_args(argv)
    port = parse_port(args.port)
    if port is None:
        parser.error("invalid port '{}': must be an integer from {} to {}"
                     .format(args.port, PORT_MIN, PORT_MAX))
    args.port = port
    return args


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(message)s")
    server = GameServer()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((HOST, args.port))
    except OSError as exc:
        print("[ERROR] Cannot listen on port {}: {}".format(
            args.port, exc.strerror), file=sys.stderr)
        sys.exit(1)
    srv.listen()
    log.info("Listening on %s:%d", HOST, args.port)
    server.start()
    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=server.client_loop, args=(conn, addr),
                             daemon=True).start()
    except KeyboardInterrupt:
        log.info("Server shutting down")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
