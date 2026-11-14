# Gen 1 Pokémon Battle Simulator over TCP

CS 457 – Computer Networks. One server and two clients battle over TCP using
newline-delimited JSON. Python 3 standard library only, no installs needed.

Design docs:

- [docs/protocol_blueprint.md](docs/protocol_blueprint.md): messages and framing
- [docs/fsm_specification.md](docs/fsm_specification.md): server states
- [docs/concurrency_design.md](docs/concurrency_design.md): threading and locking

## Files

| File | Purpose |
|---|---|
| `server.py` | Accept loop, one worker thread per client, FSM, `game_lock` |
| `client.py` | Terminal client |
| `protocol.py` | NDJSON `send_line()` and `LineBuffer` |
| `game_engine.py` | Battle rules (stats, damage, status, win/draw), no sockets |
| `pokedex.py` | Species, moves, Gen 1 type chart |
| `tests/` | `unittest` tests for the framing and the engine |

## Running

Start the server on a port from 1024 to 65535. It listens on all interfaces.

```bash
python3 server.py -p 8080
```

Start two clients, each in its own terminal (or on its own CML node). `-i`
takes a hostname, which is resolved with DNS.

```bash
python3 client.py -i server.will.edu -p 8080
python3 client.py -i localhost -p 8080        # same machine
```

Each client asks for a player name and then waits in the lobby. The game starts
when two players are in the lobby.

- When it is your turn, enter the number of a move (or, after a faint, of a
  replacement Pokémon).
- Type `q` at any prompt, or press Ctrl-C, to leave. If you leave mid-game,
  your opponent wins by forfeit.
- After a game ends, both players go back into the lobby queue, winner first,
  and the next game starts with the first two players in the queue. A third
  client that connects during a game waits its turn.

The server console prints a timestamped log of every FSM transition and every
message sent and received.

## Game rules

- Each player gets 3 random distinct species at level 50.
- Rounds are simultaneous. Each round resolves in speed order; on a speed tie,
  player1 moves first.
- A player whose active Pokémon faints must switch before the next round can
  resolve.
- A side with no usable Pokémon loses. If both sides run out in the same round,
  or round 50 resolves with both sides still alive, the game is a draw.
- The only status conditions are paralysis (Thunder Wave) and sleep (Hypnosis).

## Tests

From the repository root:

```bash
python3 -m unittest -v
```
