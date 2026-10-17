# Protocol Blueprint

**Course:** CS 457 – Computer Networks
**Project:** Gen 1 Pokémon Battle Simulator over TCP
**Sprint:** 1 – Design
**Author:** Cameron Will

---

## 1. Overview

Two client nodes and one server node (all on CML) communicate over a single TCP
connection per client. The server holds all game state. Clients send player
actions, and the server validates them, resolves rounds, and broadcasts results.

**Game scope (drives the message contents below):**

- About 15–20 curated species, all at one fixed level. Stats are base stats only, with no EVs/DVs.
- Small curated movesets and no held items.
- The server randomly assigns each player a fixed team at game start.
- Rounds are **simultaneous**. Both players submit a `MOVE` each round, and the round
  resolves only when both are in.
- If a player's active Pokémon faints, that player must submit a `SWITCH` before
  the next round can resolve.
- Teams are fully visible. `GAME_START` gives each player complete information about both teams.

---

## 2. Message Framing

### 2.1 The problem: TCP is a byte stream, not a message stream

TCP guarantees ordered, reliable delivery of **bytes**. It does **not** preserve the
boundaries between separate `send()` calls. A single `recv()` can therefore return:

| Situation | What `recv()` returns |
|---|---|
| **Fragmentation** | Part of one message. The rest arrives in a later `recv()`. |
| **Coalescing** | Two or more messages glued together in one buffer. |
| **Both** | The end of one message, a full message, and the start of another. |

This happens because of Nagle's algorithm, MSS/segment boundaries, and the size of
the receiver's buffer. It is normal behavior, not a bug. If a receiver assumes
"one `recv()` = one message", its `json.loads()` calls will fail at random.

### 2.2 The solution: newline-delimited JSON (NDJSON)

- Every message is **one JSON object serialized on a single line**, followed by
  exactly one `\n` (0x0A).
- Senders use `json.dumps(obj)` with **no `indent`** argument. `json.dumps` escapes any
  newline inside a string value as `\\n`, so a raw `\n` byte can only ever appear
  as the delimiter.
- Encoding is UTF-8, so `"Pokémon"` is safe.
- Receivers keep a per-connection **byte buffer**, append every `recv()` result to
  it, and pull out complete lines only.

```python
buffer = b""

def on_data(data: bytes):
    global buffer
    buffer += data
    while b"\n" in buffer:
        line, buffer = buffer.split(b"\n", 1)
        if line.strip():
            handle_message(json.loads(line.decode("utf-8")))
    if len(buffer) > MAX_LINE_BYTES:          # e.g. 64 KiB guard
        send_error("MALFORMED_MESSAGE", "Line exceeds maximum length")
        buffer = b""
```

Any bytes left in `buffer` after the loop belong to a message whose remaining
bytes have not arrived yet. They are kept for the next `recv()`.

### 2.3 Worked example: one wire stream, three `recv()` calls

The server sends three messages back to back:

```text
{"type":"STATE_UPDATE","round":3,...}\n{"type":"ERROR","error_code":"INVALID_MOVE","detail":"..."}\n{"type":"STATE_UPDATE","round":4,...}\n
```

The client's `recv(4096)` calls might return these chunks:

| `recv()` # | Bytes received | Complete lines extracted | Left in buffer |
|---|---|---|---|
| 1 | `{"type":"STATE_UPDATE","round":3,...}\n{"type":"ERR` | `STATE_UPDATE` (round 3) | `{"type":"ERR` |
| 2 | `OR","error_code":"INVALID_MOVE","detail":"..."}\n{"type":"STATE_UPDATE","rou` | `ERROR` | `{"type":"STATE_UPDATE","rou` |
| 3 | `nd":4,...}\n` | `STATE_UPDATE` (round 4) | *(empty)* |

Chunk 1 is a fragment and a full message coalesced together. Chunk 2 finishes the
fragment and starts a new one. Chunk 3 finishes the last one. The newline framing
handles all three cases without any special-case code.

---

## 3. Shared Object Types

The message schemas below reuse these objects.

### 3.1 `Move`

| Key | Type | Description |
|---|---|---|
| `name` | string | Move name. This is also the value sent in `MOVE.move_name`. |
| `type` | string | Gen 1 type (`"Fire"`, `"Water"`, `"Psychic"`, …). |
| `power` | integer | Base power (`0` for status moves). |
| `accuracy` | integer | Accuracy percentage, 0–100. |

### 3.2 `Pokemon` (full team entry)

| Key | Type | Description |
|---|---|---|
| `species` | string | Species name. It is unique within a team and used as the `SWITCH` target. |
| `types` | array[string] | One or two Gen 1 types. |
| `hp` | integer | Current HP. |
| `max_hp` | integer | Max HP, from base stats at the fixed level. |
| `stats` | object | `{ "attack": int, "defense": int, "special": int, "speed": int }` |
| `status` | string | `"OK"`, `"PSN"`, `"BRN"`, `"PAR"`, `"SLP"`, `"FRZ"`, or `"FNT"`. |
| `moves` | array[`Move`] | Curated moveset (1–4 moves). |

### 3.3 `ActiveSummary` (compact per-player battle view)

| Key | Type | Description |
|---|---|---|
| `species` | string | Species of the currently active Pokémon. |
| `hp` | integer | Current HP. |
| `max_hp` | integer | Max HP. |
| `status` | string | Same enum as `Pokemon.status`. |

### 3.4 Player roles

Roles are always the strings `"player1"` or `"player2"`. The server assigns them in
lobby queue order: when a game starts, the first player in the queue becomes
`player1` and the second becomes `player2`. All per-player objects are keyed by role.

---

## 4. Message Types

Every message has a top-level `"type"` key (string). The server rejects any message
whose `type` is missing or unknown with `ERROR` / `MALFORMED_MESSAGE`.

| # | Type | Direction | Purpose |
|---|---|---|---|
| 1 | `CONNECT` | C → S | Join the lobby. |
| 2 | `LOBBY_WAIT` | S → C | Acknowledge the join and wait for an opponent. |
| 3 | `GAME_START` | S → C (broadcast) | Assign role and teams, and start the battle. |
| 4 | `MOVE` | C → S | Choose a move for this round. |
| 5 | `SWITCH` | C → S | Replace a fainted active Pokémon. |
| 6 | `STATE_UPDATE` | S → C (broadcast) | Report round results and who must act next. |
| 7 | `ERROR` | S → C | Reject an invalid or out-of-turn action. |
| 8 | `DISCONNECT` | C → S | Leave gracefully. |
| 9 | `GAME_OVER` | S → C (broadcast) | Report the final result. |

---

### 4.1 `CONNECT`

**Direction:** Client → Server
**Purpose:** The first message a client sends after the TCP handshake. It registers
the player in the lobby.

| Key | Type | Description |
|---|---|---|
| `type` | string | `"CONNECT"` |
| `player_name` | string | Display name (1–20 characters). |

```json
{"type": "CONNECT", "player_name": "Red"}
```

---

### 4.2 `LOBBY_WAIT`

**Direction:** Server → Client
**Purpose:** Confirms the `CONNECT` and tells the client that no opponent is
available yet. The server also sends it to a player who is still connected after
`CLEANUP` returns the server to the lobby for a rematch.

| Key | Type | Description |
|---|---|---|
| `type` | string | `"LOBBY_WAIT"` |
| `players_connected` | integer | Players currently in the lobby (including this one). |
| `players_needed` | integer | Players required to start (always `2`). |
| `message` | string | Human-readable status line. |

```json
{"type": "LOBBY_WAIT", "players_connected": 1, "players_needed": 2, "message": "Waiting for an opponent..."}
```

---

### 4.3 `GAME_START`

**Direction:** Server → Client (sent to both players, each copy personalized)
**Purpose:** Starts the battle. Each player gets their role, their own team, and the
opponent's full team. **Nothing is hidden.** The first Pokémon in each team array
is the starting active Pokémon.

| Key | Type | Description |
|---|---|---|
| `type` | string | `"GAME_START"` |
| `role` | string | This recipient's role: `"player1"` or `"player2"`. |
| `opponent_name` | string | Opponent's `player_name`. |
| `your_team` | array[`Pokemon`] | Recipient's assigned team. Index 0 starts active. |
| `opponent_team` | array[`Pokemon`] | Opponent's assigned team (full info). Index 0 starts active. |

```json
{
  "type": "GAME_START",
  "role": "player1",
  "opponent_name": "Blue",
  "your_team": [
    {"species": "Charizard", "types": ["Fire", "Flying"], "hp": 78, "max_hp": 78,
     "stats": {"attack": 84, "defense": 78, "special": 85, "speed": 100}, "status": "OK",
     "moves": [{"name": "Flamethrower", "type": "Fire", "power": 95, "accuracy": 100},
               {"name": "Slash", "type": "Normal", "power": 70, "accuracy": 100},
               {"name": "Earthquake", "type": "Ground", "power": 100, "accuracy": 100}]},
    {"species": "Jolteon", "types": ["Electric"], "hp": 65, "max_hp": 65,
     "stats": {"attack": 65, "defense": 60, "special": 110, "speed": 130}, "status": "OK",
     "moves": [{"name": "Thunderbolt", "type": "Electric", "power": 95, "accuracy": 100},
               {"name": "Thunder Wave", "type": "Electric", "power": 0, "accuracy": 100}]},
    {"species": "Snorlax", "types": ["Normal"], "hp": 160, "max_hp": 160,
     "stats": {"attack": 110, "defense": 65, "special": 65, "speed": 30}, "status": "OK",
     "moves": [{"name": "Body Slam", "type": "Normal", "power": 85, "accuracy": 100},
               {"name": "Earthquake", "type": "Ground", "power": 100, "accuracy": 100}]}
  ],
  "opponent_team": [
    {"species": "Blastoise", "types": ["Water"], "hp": 79, "max_hp": 79,
     "stats": {"attack": 83, "defense": 100, "special": 85, "speed": 78}, "status": "OK",
     "moves": [{"name": "Surf", "type": "Water", "power": 95, "accuracy": 100},
               {"name": "Ice Beam", "type": "Ice", "power": 95, "accuracy": 100}]},
    {"species": "Alakazam", "types": ["Psychic"], "hp": 55, "max_hp": 55,
     "stats": {"attack": 50, "defense": 45, "special": 135, "speed": 120}, "status": "OK",
     "moves": [{"name": "Psychic", "type": "Psychic", "power": 90, "accuracy": 100},
               {"name": "Thunder Wave", "type": "Electric", "power": 0, "accuracy": 100}]},
    {"species": "Gengar", "types": ["Ghost", "Poison"], "hp": 60, "max_hp": 60,
     "stats": {"attack": 65, "defense": 60, "special": 130, "speed": 110}, "status": "OK",
     "moves": [{"name": "Thunderbolt", "type": "Electric", "power": 95, "accuracy": 100},
               {"name": "Hypnosis", "type": "Psychic", "power": 0, "accuracy": 60}]}
  ]
}
```

> On the wire this is a single line. It is pretty-printed here only for readability.

---

### 4.4 `MOVE`

**Direction:** Client → Server
**Purpose:** Locks in the player's move for the current round. It is valid only while that
player is in `AWAITING_MOVES`. The opponent never sees a locked-in move until the round
resolves in `STATE_UPDATE`.

| Key | Type | Description |
|---|---|---|
| `type` | string | `"MOVE"` |
| `move_name` | string | Must exactly match a `Move.name` of the sender's **active** Pokémon. |

```json
{"type": "MOVE", "move_name": "Flamethrower"}
```

**Rejections:** `INVALID_MOVE` (not in the active Pokémon's moveset) and `OUT_OF_TURN`
(the sender is in `AWAITING_SWITCH`, has already locked in this round, or no
game is running).

---

### 4.5 `SWITCH`

**Direction:** Client → Server
**Purpose:** Replaces a **fainted** active Pokémon. It is valid only while that player is
in `AWAITING_SWITCH`. Voluntary mid-battle switching is out of scope.

| Key | Type | Description |
|---|---|---|
| `type` | string | `"SWITCH"` |
| `switch_to` | string | `species` of a non-fainted Pokémon on the sender's team. |

```json
{"type": "SWITCH", "switch_to": "Snorlax"}
```

**Rejections:**

- `FAINTED_POKEMON_SELECTED`: the target has `status == "FNT"`.
- `INVALID_MOVE`: the species is not on the sender's team.
- `OUT_OF_TURN`: the sender is not in `AWAITING_SWITCH`.

---

### 4.6 `STATE_UPDATE`

**Direction:** Server → Client (broadcast, identical copy to both)
**Purpose:** Reports the battle state after each resolved round, after each accepted
`SWITCH`, and once right after `GAME_START` (round 1, nothing resolved yet). The
`awaiting` field tells each client whether it must act and which message it must send.

| Key | Type | Description |
|---|---|---|
| `type` | string | `"STATE_UPDATE"` |
| `round` | integer | The round now being collected (starts at `1`). |
| `active` | object | `{ "player1": ActiveSummary, "player2": ActiveSummary }` |
| `events` | array[string] | Short, ordered log of what just happened (can be empty). |
| `awaiting` | object | `{ "player1": string \| null, "player2": string \| null }`. Each value is `"MOVE"`, `"SWITCH"`, or `null` (nothing required from that player right now). |
| `remaining` | object | `{ "player1": int, "player2": int }`. Count of non-fainted Pokémon on each side. |

```json
{
  "type": "STATE_UPDATE",
  "round": 4,
  "active": {
    "player1": {"species": "Charizard", "hp": 31, "max_hp": 78, "status": "OK"},
    "player2": {"species": "Alakazam", "hp": 0, "max_hp": 55, "status": "FNT"}
  },
  "events": [
    "Alakazam used Psychic! Charizard lost 47 HP.",
    "Charizard used Flamethrower!",
    "Alakazam fainted!"
  ],
  "awaiting": {"player1": "MOVE", "player2": "SWITCH"},
  "remaining": {"player1": 3, "player2": 1}
}
```

In this example player1 may lock in its round-4 `MOVE` right away. Player2 must
`SWITCH` and then send a `MOVE` before round 4 can resolve.

---

### 4.7 `ERROR`

**Direction:** Server → Client (only the offending client)
**Purpose:** Rejects a message. **The game state does not change**, the opponent
receives nothing, and the offending client should re-prompt its user for the same
action.

| Key | Type | Description |
|---|---|---|
| `type` | string | `"ERROR"` |
| `error_code` | string | One of the codes below. |
| `detail` | string | Human-readable explanation. |

| `error_code` | Trigger |
|---|---|
| `INVALID_MOVE` | `MOVE.move_name` is not in the active Pokémon's moveset, or `SWITCH.switch_to` is not a species on the sender's team. |
| `OUT_OF_TURN` | The action type does not match what the server is waiting for from this player (`MOVE` while awaiting a `SWITCH`, a second `MOVE` in the same round, `SWITCH` with no fainted Pokémon, or any action before `GAME_START`). |
| `MALFORMED_MESSAGE` | The line is not valid UTF-8 or JSON, `type` is missing or unknown, a required key is missing or has the wrong type, or the line exceeds the max length. |
| `FAINTED_POKEMON_SELECTED` | `SWITCH.switch_to` names a Pokémon whose status is `"FNT"`. |

```json
{"type": "ERROR", "error_code": "FAINTED_POKEMON_SELECTED", "detail": "Alakazam has fainted and cannot be sent out."}
```

---

### 4.8 `DISCONNECT`

**Direction:** Client → Server
**Purpose:** Graceful, intentional leave. If a game is in progress, the opponent wins
by forfeit (see Section 5).

| Key | Type | Description |
|---|---|---|
| `type` | string | `"DISCONNECT"` |
| `reason` | string (optional) | Free-text reason, logged by the server. |

```json
{"type": "DISCONNECT", "reason": "user quit"}
```

---

### 4.9 `GAME_OVER`

**Direction:** Server → Client (broadcast to every player still connected)
**Purpose:** Ends the battle. After sending it, the server enters `CLEANUP` and returns
to `WAITING_FOR_PLAYERS`.

| Key | Type | Description |
|---|---|---|
| `type` | string | `"GAME_OVER"` |
| `result` | string | `"WIN"` (a side ran out of usable Pokémon), `"DRAW"` (both sides ran out in the same round), or `"FORFEIT"` (the opponent disconnected). |
| `winner` | string \| null | Winning role (`"player1"` / `"player2"`), or `null` on a `DRAW`. |
| `final_state` | object | `{ "round": int, "teams": { "player1": array[ActiveSummary], "player2": array[ActiveSummary] } }`. Every team member's final HP and status. |
| `record` | object | `{ "<player_name>": { "wins": int, "losses": int, "draws": int }, ... }` for both players. Match record including this game's result. |

```json
{
  "type": "GAME_OVER",
  "result": "WIN",
  "winner": "player1",
  "final_state": {
    "round": 9,
    "teams": {
      "player1": [
        {"species": "Charizard", "hp": 0, "max_hp": 78, "status": "FNT"},
        {"species": "Jolteon", "hp": 22, "max_hp": 65, "status": "PAR"},
        {"species": "Snorlax", "hp": 160, "max_hp": 160, "status": "OK"}
      ],
      "player2": [
        {"species": "Blastoise", "hp": 0, "max_hp": 79, "status": "FNT"},
        {"species": "Alakazam", "hp": 0, "max_hp": 55, "status": "FNT"},
        {"species": "Gengar", "hp": 0, "max_hp": 60, "status": "FNT"}
      ]
    }
  },
  "record": {
    "Red": {"wins": 2, "losses": 1, "draws": 0},
    "Blue": {"wins": 1, "losses": 2, "draws": 0}
  }
}
```

---

## 5. Connection Termination

A client can leave in three ways. The server must handle all three and turn each
into the same game outcome. If a game is in progress, the remaining player gets
`GAME_OVER` with `result: "FORFEIT"` and is the `winner`.

| Scenario | What happens on the wire | What the server's `recv()` / `send()` sees |
|---|---|---|
| **Graceful `DISCONNECT`** | The client sends `{"type":"DISCONNECT"}\n`, then closes its socket (FIN). | A normal `DISCONNECT` line, followed by a 0-byte `recv()`. |
| **TCP FIN teardown** (no `DISCONNECT`) | The client calls `close()` or exits normally (Ctrl-C, window closed). The OS sends FIN. | `recv()` returns `b""` (EOF). |
| **Abrupt reset (RST)** | The client crashes or is killed with data still unread in its receive buffer, or sets `SO_LINGER` to 0, or the server writes to a socket the peer has already closed. | `recv()` raises `ConnectionResetError`. `send()` raises `BrokenPipeError` or `ConnectionResetError`. On Windows, `ConnectionAbortedError` is possible. |

> A node that loses power or network entirely (for example a CML link shut down)
> sends **neither** FIN nor RST. The server only finds out when a later `send()`
> fails. An optional `settimeout()` or `SO_KEEPALIVE` can detect this sooner.

### 5.1 The 0-byte `recv()` rule

`recv()` returning **zero bytes** (`b""`) means that **the peer has closed its sending
direction and no more data will ever arrive**. It never means "no data yet". A
blocking socket with no data simply blocks, and a non-blocking one raises
`BlockingIOError`.

**Danger:** EOF is sticky. After the peer has closed, every later `recv()` returns
`b""` immediately. A receive loop that does not check for this spins forever at
100% CPU, appending nothing to its buffer and never noticing the player has left:

```python
# WRONG: infinite busy loop once the client closes
while True:
    data = conn.recv(4096)
    buffer += data            # b"" forever
```

### 5.2 Correct receive loop

```python
def client_loop(conn, player):
    buffer = b""
    try:
        while True:
            data = conn.recv(4096)
            if not data:                       # EOF: peer sent FIN
                break
            buffer += data
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                msg = parse_or_error(conn, line)   # sends MALFORMED_MESSAGE on failure
                if msg is None:
                    continue
                if msg["type"] == "DISCONNECT":    # graceful leave
                    return
                game.handle(player, msg)
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError) as e:
        log(f"{player} connection lost: {e!r}")  # abrupt RST / dead socket
    finally:
        game.on_player_left(player)              # forfeit, CLEANUP (see FSM spec)
        conn.close()
```

Rules for every send and receive path:

- **Every** `recv()` call site checks `if not data: break`.
- **Every** `send()` / `sendall()` call site (including broadcasts) catches
  `BrokenPipeError`, `ConnectionResetError`, and `ConnectionAbortedError`, and treats
  the failure as that player leaving. Python ignores `SIGPIPE` by default, so a
  write to a dead socket raises an exception instead of killing the process.
- The `finally` block runs for all three termination scenarios. As a result
  `on_player_left()` is the single place that applies the forfeit, sends `GAME_OVER` to
  the survivor, and moves the server to `CLEANUP`.
- The client side follows the same rules. If the server connection drops, the
  client reports "connection lost" and exits cleanly instead of hanging.

---

## Changelog

- **Sprint 2:** added `STATE_UPDATE.remaining` and `GAME_OVER.record` for score synchronization.
