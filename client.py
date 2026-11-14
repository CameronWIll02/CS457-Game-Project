"""Terminal client for the Gen 1 Pokemon battle simulator.

Single-threaded and message-driven: the client blocks on recv(), runs every
chunk through LineBuffer, and only asks the user for input when the latest
STATE_UPDATE says it is this player's turn (awaiting[my_role]).
"""

import argparse
import math
import socket
import sys

from protocol import (PORT_MAX, PORT_MIN, LineBuffer, MalformedLine,
                      parse_port, send_line)

RECV_SIZE = 4096
CONNECT_TIMEOUT = 10
NAME_MAX_LEN = 20
HP_BAR_WIDTH = 10
RULE = "=" * 56


class ConnectionLost(Exception):
    """The server closed the connection or the socket failed."""


class Quit(Exception):
    """The user typed q (or stdin closed)."""


def hp_bar(hp, max_hp):
    filled = math.ceil(HP_BAR_WIDTH * hp / max_hp) if hp > 0 else 0
    return "[{}{}] {}/{}".format("#" * filled, "-" * (HP_BAR_WIDTH - filled),
                                 hp, max_hp)


def ask(prompt):
    """input() that turns 'q' and end-of-input into Quit."""
    try:
        text = input(prompt).strip()
    except EOFError:
        raise Quit()
    if text.lower() == "q":
        raise Quit()
    return text


def choose(options, prompt):
    """Ask for a 1-based number until it is valid. Returns the index."""
    while True:
        text = ask(prompt)
        if text.isdigit() and 1 <= int(text) <= len(options):
            return int(text) - 1
        print("  Please enter a number from 1 to {} (or q to quit)."
              .format(len(options)))


class GameClient:
    def __init__(self, sock, name):
        self.sock = sock
        self.name = name
        self.buffer = LineBuffer()
        self._reset_game()

    def _reset_game(self):
        self.role = None
        self.opponent = None
        self.team = []         # my team entries (dicts), kept up to date
        self.opp_team = []
        self.state = None      # latest STATE_UPDATE
        self.sent = None       # (round, action) of the last MOVE/SWITCH sent
        self.waiting_shown = False

    # ---- network -------------------------------------------------------

    def send(self, obj):
        if not send_line(self.sock, obj):
            raise ConnectionLost()

    def run(self):
        self.send({"type": "CONNECT", "player_name": self.name})
        while True:
            try:
                data = self.sock.recv(RECV_SIZE)
            except OSError:
                raise ConnectionLost()
            if not data:
                raise ConnectionLost()
            for item in self.buffer.feed(data):
                if isinstance(item, MalformedLine):
                    print("[warning] Ignoring bad line from server: "
                          + item.detail)
                else:
                    self.handle(item)
            self.maybe_prompt()

    # ---- incoming messages ---------------------------------------------

    def handle(self, msg):
        handler = {
            "LOBBY_WAIT": self.on_lobby_wait,
            "GAME_START": self.on_game_start,
            "STATE_UPDATE": self.on_state_update,
            "ERROR": self.on_error,
            "GAME_OVER": self.on_game_over,
        }.get(msg["type"])
        if handler is None:
            print("[warning] Ignoring unexpected message: " + msg["type"])
        else:
            handler(msg)

    def on_lobby_wait(self, msg):
        print("Waiting for an opponent... ({}/{} in lobby)".format(
            msg.get("players_connected"), msg.get("players_needed")))

    def on_game_start(self, msg):
        self._reset_game()
        self.role = msg["role"]
        self.opponent = msg["opponent_name"]
        self.team = msg["your_team"]
        self.opp_team = msg["opponent_team"]
        print()
        print(RULE)
        print("GAME START: {} vs {}".format(self.name, self.opponent))
        print("You are {}.".format(self.role))
        print(RULE)
        print_team("Your team", self.team, details=True)
        print_team("{}'s team".format(self.opponent), self.opp_team,
                   details=True)

    def on_state_update(self, msg):
        self.state = msg
        self.waiting_shown = False
        opp_role = "player2" if self.role == "player1" else "player1"
        update_team(self.team, msg["active"][self.role])
        update_team(self.opp_team, msg["active"][opp_role])
        print()
        print("{:-^56}".format(" Round {} ".format(msg["round"])))
        for line in msg["events"]:
            print("  " + line)
        if msg["events"]:
            print()
        for label, role in (("You ({})".format(self.name), self.role),
                            (self.opponent, opp_role)):
            mon = msg["active"][role]
            print("  {:<16} {:<10} {} {}".format(
                label[:16], mon["species"], hp_bar(mon["hp"], mon["max_hp"]),
                mon["status"]))
        remaining = msg["remaining"]
        print("  Score (Pokemon left): {} {} - {} {}".format(
            self.name, remaining[self.role], remaining[opp_role],
            self.opponent))

    def on_error(self, msg):
        if self.role is None:
            # Reply to an action that crossed paths with GAME_OVER.
            print("  (Your last action arrived after the game ended.)")
            return
        print("  [ERROR {}] {}".format(msg["error_code"], msg["detail"]))
        self.sent = None  # re-prompt for the same action

    def on_game_over(self, msg):
        result, winner = msg["result"], msg["winner"]
        names = {self.role: self.name}
        names["player2" if self.role == "player1" else "player1"] = \
            self.opponent
        final = msg["final_state"]
        if msg["events"]:
            print()
            print("{:-^56}".format(" Round {} ".format(final["round"])))
            for line in msg["events"]:
                print("  " + line)
        print()
        print(RULE)
        if result == "DRAW":
            print("GAME OVER after round {}: it's a DRAW!".format(
                final["round"]))
        elif result == "FORFEIT":
            print("GAME OVER: your opponent left. {} wins by forfeit!"
                  .format(names.get(winner, winner)))
        else:
            print("GAME OVER after round {}: {} wins!".format(
                final["round"], names.get(winner, winner)))
        print(RULE)
        for role in ("player1", "player2"):
            print_team("{} ({})".format(names.get(role, role), role),
                       final["teams"][role])
        print("Match record:")
        for player, rec in msg["record"].items():
            print("  {:<20} W {}  L {}  D {}".format(
                player, rec["wins"], rec["losses"], rec["draws"]))
        print("Returning to the lobby for a rematch (q to quit when "
              "prompted, or Ctrl-C).")
        self._reset_game()

    # ---- prompting -----------------------------------------------------

    def maybe_prompt(self):
        if self.state is None or self.role is None:
            return
        action = self.state["awaiting"].get(self.role)
        key = (self.state["round"], action)
        if action is None or key == self.sent:
            if not self.waiting_shown:
                print("Waiting for {}...".format(self.opponent))
                self.waiting_shown = True
            return
        if action == "MOVE":
            self.prompt_move()
        elif action == "SWITCH":
            self.prompt_switch()
        else:
            return
        self.sent = key

    def active_entry(self):
        species = self.state["active"][self.role]["species"]
        return next(p for p in self.team if p["species"] == species)

    def prompt_move(self):
        moves = self.active_entry()["moves"]
        print("Your turn: choose a move")
        for number, move in enumerate(moves, 1):
            print("  {}. {:<13} {:<9} power {:>3}  acc {:>3}%".format(
                number, move["name"], move["type"], move["power"],
                move["accuracy"]))
        index = choose(moves, "Move number (q to quit): ")
        self.send({"type": "MOVE", "move_name": moves[index]["name"]})

    def prompt_switch(self):
        options = [p for p in self.team if p["status"] != "FNT"]
        print("Your Pokemon fainted: choose a replacement")
        for number, mon in enumerate(options, 1):
            print("  {}. {:<10} {} {}".format(
                number, mon["species"], hp_bar(mon["hp"], mon["max_hp"]),
                mon["status"]))
        index = choose(options, "Pokemon number (q to quit): ")
        self.send({"type": "SWITCH", "switch_to": options[index]["species"]})


def update_team(team, summary):
    for mon in team:
        if mon["species"] == summary["species"]:
            mon["hp"] = summary["hp"]
            mon["status"] = summary["status"]


def print_team(title, team, details=False):
    print(title + ":")
    for mon in team:
        line = "  {:<10} {} {}".format(
            mon["species"], hp_bar(mon["hp"], mon["max_hp"]), mon["status"])
        if details:
            stats = mon["stats"]
            line += "  {}  Atk {} Def {} Spc {} Spe {}".format(
                "/".join(mon["types"]), stats["attack"], stats["defense"],
                stats["special"], stats["speed"])
        print(line)
        if details:
            print("             moves: " + ", ".join(
                m["name"] for m in mon["moves"]))


# ---- command line --------------------------------------------------------

class ArgParser(argparse.ArgumentParser):
    """argparse that exits with status 1 (not 2) on bad arguments."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print("{}: error: {}".format(self.prog, message), file=sys.stderr)
        sys.exit(1)


def parse_args(argv=None):
    parser = ArgParser(description="Gen 1 Pokemon battle client.",
                       epilog="example: python3 client.py -i server.will.edu "
                              "-p 8080")
    parser.add_argument("-i", "--hostname", required=True,
                        help="server hostname (resolved with DNS)")
    parser.add_argument("-p", "--port", required=True,
                        help="server TCP port ({}-{})".format(PORT_MIN,
                                                              PORT_MAX))
    args = parser.parse_args(argv)
    port = parse_port(args.port)
    if port is None:
        parser.error("invalid port '{}': must be an integer from {} to {}"
                     .format(args.port, PORT_MIN, PORT_MAX))
    args.port = port
    return args


def connect(hostname, port):
    try:
        address = socket.gethostbyname(hostname)
    except socket.gaierror:
        print("[ERROR] Unable to resolve DNS hostname '{}'.".format(hostname),
              file=sys.stderr)
        print("Please check your Cisco router DNS configuration "
              "('ip dns server' / 'ip host') or verify domain spelling.",
              file=sys.stderr)
        sys.exit(1)
    try:
        sock = socket.create_connection((address, port),
                                        timeout=CONNECT_TIMEOUT)
    except ConnectionRefusedError:
        print("[ERROR] Connection refused by {} ({}) on port {}. Is the "
              "server running?".format(hostname, address, port),
              file=sys.stderr)
        sys.exit(1)
    except (TimeoutError, socket.timeout):
        print("[ERROR] Timed out connecting to {} ({}) on port {}."
              .format(hostname, address, port), file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print("[ERROR] Could not connect to {} ({}) on port {}: {}".format(
            hostname, address, port, exc.strerror or exc), file=sys.stderr)
        sys.exit(1)
    sock.settimeout(None)
    return sock


def ask_name():
    while True:
        name = ask("Player name (1-{} characters, q to quit): ".format(
            NAME_MAX_LEN))
        if 1 <= len(name) <= NAME_MAX_LEN:
            return name
        print("  Name must be 1-{} characters.".format(NAME_MAX_LEN))


def main(argv=None):
    args = parse_args(argv)
    sock = connect(args.hostname, args.port)
    print("Connected to {}:{}.".format(args.hostname, args.port))
    try:
        GameClient(sock, ask_name()).run()
    except (Quit, KeyboardInterrupt):
        send_line(sock, {"type": "DISCONNECT", "reason": "user quit"})
        print("\nDisconnected. Goodbye!")
    except ConnectionLost:
        print("\nConnection to server lost.")
        sys.exit(1)
    finally:
        sock.close()


if __name__ == "__main__":
    main()
