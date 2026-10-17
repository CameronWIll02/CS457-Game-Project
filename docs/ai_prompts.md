# AI Prompt Log

**Course:** CS 457 – Computer Networks
**Project:** Gen 1 Pokémon Battle Simulator over TCP
**Author:** Cameron Will

---

## 1. Purpose

This file records the exact prompts used to guide AI tools on this project. It
shows which parts of the design are mine and which parts the AI tool produced from them.

---

## 2. Design Ownership Statement

**All message schemas and state transitions in this project were designed by me
before I wrote the prompt below.** This includes:

- all 9 message types,
- their directions and required fields,
- the `ERROR` codes,
- the newline-delimited JSON framing choice,
- the FSM states and their transitions (including independent per-player
  `AWAITING_MOVES` / `AWAITING_SWITCH` readiness, the forfeit-on-disconnect rule,
  and the `GAME_OVER` → `CLEANUP` → `WAITING_FOR_PLAYERS` rematch loop).

The AI was not asked to invent the protocol. The prompt told it which messages and
states to use, forbade it from adding new message types or states, and asked it
only to write up and format that design as documentation (`protocol_blueprint.md`
and `fsm_specification.md`).

---

## 3. Sprint 1 Prompt – Design Document Generation

**Used to generate:** `docs/protocol_blueprint.md`, `docs/fsm_specification.md`, `docs/ai_prompts.md`
**Constraint goal:** keep the AI tied to my existing protocol and FSM design.

```text
I'm building Sprint 1 deliverables for a CS 457 Computer Networks class project: a
Gen 1 Pokémon battle simulator played over TCP between two CML client nodes and one
server. Game is scoped to ~15-20 curated species, all fixed at one level (base stats
only, no EVs/DVs), small curated movesets, no held items. Server randomly assigns
each player a fixed team at game start. Round structure: both players submit a move
simultaneously each round (not strict alternating turns); if a Pokémon faints, its
player must submit a SWITCH before the next round can resolve.

Create three files in docs/:

1. docs/protocol_blueprint.md
   - Framing: newline-delimited JSON (\n after every message). Explain TCP
     stream fragmentation/coalescing and how newline framing solves it, with a
     concrete multi-message wire-stream example.
   - Document these 9 message types, each with direction, purpose, and a full
     JSON schema (keys + types) with a sample payload:
     CONNECT (C→S), LOBBY_WAIT (S→C), GAME_START (S→C broadcast, includes
     assigned role, the player's own team, and the opponent's team — full info,
     nothing hidden), MOVE (C→S, move_name), SWITCH (C→S, switch_to species),
     STATE_UPDATE (S→C broadcast, includes round number, both active Pokémon's
     current/max HP and status, a short event log, and an "awaiting" field
     naming which player(s) still need to act and with what message type),
     ERROR (S→C, error_code + detail — codes: INVALID_MOVE, OUT_OF_TURN,
     MALFORMED_MESSAGE, FAINTED_POKEMON_SELECTED), DISCONNECT (C→S),
     GAME_OVER (S→C broadcast, result: WIN/DRAW/FORFEIT, winner, final state).
   - Cover connection termination: graceful DISCONNECT vs TCP FIN teardown vs
     abrupt RST/kill, the recv() 0-byte EOF rule and the infinite-loop danger
     of not checking `if not data: break`, and catching ConnectionResetError /
     BrokenPipeError / ConnectionAbortedError in the receive loop.

2. docs/fsm_specification.md
   - A Mermaid stateDiagram-v2 diagram for these states and transitions:
     INIT → WAITING_FOR_PLAYERS → GAME_START → AWAITING_MOVES → EVALUATE_ROUND
     → CHECK_FAINT → (AWAITING_SWITCH if a player's Pokémon fainted, else skip)
     → CHECK_WIN_DRAW → (loop back to AWAITING_MOVES, or → GAME_OVER) →
     CLEANUP → back to WAITING_FOR_PLAYERS.
   - Critical: AWAITING_MOVES and AWAITING_SWITCH must be modeled as tracking
     each player's readiness independently — one player can be in
     AWAITING_SWITCH while the other is already back in AWAITING_MOVES for the
     next round. Don't collapse this into a single shared "waiting" state.
   - Model these edge transitions explicitly: invalid/out-of-turn MOVE or
     SWITCH → send ERROR, state unchanged, only that client re-prompted;
     DISCONNECT from any state after GAME_START → CLEANUP with opponent
     declared winner by forfeit; GAME_OVER → CLEANUP → reset to
     WAITING_FOR_PLAYERS for a rematch.
   - Below the diagram, add a short prose walkthrough of each state and its
     entry/exit triggers.

3. docs/ai_prompts.md
   - Document this exact prompt as the one used to constrain AI-generated
     design docs, and note that all message schemas and state transitions
     were designed by me before generating this prompt, not invented by the
     AI. Leave a placeholder section for the Sprint 3 prompt I'll use to
     constrain code generation against this exact protocol.

Match the existing formatting style of sow_template.md in the repo root. Don't
invent additional message types or states beyond what's specified above.
```

---

## 4. Sprint 2 Prompt – Concurrency Design

**Used to generate:** `docs/concurrency_design.md`, the Sprint 2 addendum to `docs/protocol_blueprint.md`, and this section of `docs/ai_prompts.md`
**Constraint goal:** have the AI write up my concurrency design without changing it, and keep it consistent with the Sprint 1 protocol and FSM.

**Design ownership:** I made these decisions **before I wrote the prompt below**:

- the threading model (one daemon worker thread per client, with the main thread only
  running `accept()`),
- the single-lock strategy (one `game_lock` for all shared state, with `recv()` always outside it),
- sending broadcasts while holding the lock,
- deferred forfeit handling for send failures (record the failed player, then call
  `on_player_left()` after releasing the lock),
- the score and record design (`STATE_UPDATE.remaining` and the `GAME_OVER.record`
  match record keyed by player name).

The AI's job was to write up and format those decisions, not to make them.

```text
I'm writing Sprint 2 design docs for my CS 457 Computer Networks project: a Gen 1
Pokémon battle simulator over TCP (2 clients, 1 server). Sprint 1 docs already exist
in docs/: protocol_blueprint.md, fsm_specification.md, ai_prompts.md. Read all three
first. Everything below must stay consistent with them: same message names, fields,
error codes, state names, and newline-delimited JSON framing. Do not invent new
message types, error codes, or FSM states. Match their formatting style.

All design decisions below are mine. Your job is to write them up clearly, not to
change them.

=== TASK 1: Create docs/concurrency_design.md ===

1. Concurrency model: multi-threading, one worker thread per client connection.
   - Main thread: creates the listening socket (bind/listen), loops on accept(),
     and spawns a daemon threading.Thread running client_loop(conn, addr) for
     each connection. The main thread never blocks on a client socket, so the
     server keeps accepting while games run.
   - Explain why I chose threading over selectors: the Sprint 1 protocol
     blueprint already specifies a blocking per-client receive loop
     (client_loop), which maps directly onto thread-per-client. Briefly note the
     tradeoff (selectors needs no locks but a different code structure).
   - Capacity: the game needs exactly 2 players. A third connection while a game
     is running waits in the lobby (receives LOBBY_WAIT) until CLEANUP returns
     the server to WAITING_FOR_PLAYERS.

2. Connection lifecycle, step by step: accept() → spawn thread → CONNECT received
   → register in lobby (under lock) → LOBBY_WAIT or GAME_START → in-game message
   servicing → teardown via DISCONNECT, 0-byte recv (FIN), or socket exception
   (RST), all converging on the finally block calling on_player_left() exactly
   as described in protocol_blueprint.md section 5.

3. Shared resources inventory. Make a table listing each one, which threads read
   or write it, and what goes wrong if it's unprotected:
   - lobby / connected-client list (player name → socket, role)
   - FSM state (current server state)
   - teams (both players' Pokémon, HP, status)
   - per-player readiness (each player's AWAITING_MOVES / AWAITING_SWITCH /
     locked-in region state) and pending locked-in moves
   - round counter
   - remaining-Pokémon counts (per-battle score)
   - match record (wins/losses/draws per player name, persists across
     rematches, in memory only while the server process runs)

4. Locking strategy:
   - A single threading.Lock named game_lock protects ALL shared resources
     above. Explain why one coarse lock is the right choice here: only 2
     players, short critical sections, and it eliminates lock-ordering
     deadlocks entirely.
   - recv() always happens OUTSIDE the lock (never block on the network while
     holding it). Only after a complete NDJSON line is parsed does the thread
     acquire game_lock.
   - Critical section for handling a message: acquire game_lock → validate the
     message against the current FSM state and that player's readiness →
     mutate state → if both players are now locked in, resolve the round
     (EVALUATE_ROUND → CHECK_FAINT → CHECK_WIN_DRAW) inside the same critical
     section → build outgoing messages → send them → release.
   - Broadcasts are sent WHILE holding game_lock with sendall(). Justify: this
     guarantees both clients receive every STATE_UPDATE in the same order and
     no other thread can mutate state between the two sends. Acknowledge the
     tradeoff that a slow client delays the lock briefly, which is acceptable
     for a 2-player game.
   - Send failures during a broadcast (BrokenPipeError / ConnectionResetError /
     ConnectionAbortedError) must NOT call on_player_left() from inside the
     locked section (threading.Lock is not reentrant, so that would
     deadlock). Instead, record the failed player and handle the forfeit right
     after releasing the lock.
   - Use `with game_lock:` blocks so the lock is released even if an exception
     is raised.

5. Race conditions and how the lock prevents each. Give a short scenario for each:
   - Both players' final MOVEs arrive at the same moment: without the lock,
     both threads could see "both locked in" and resolve the round twice. With
     it, exactly one thread resolves and the other sees the round already
     advanced.
   - A player double-sends MOVE: the second is rejected with OUT_OF_TURN
     because the lock-in check and the write are atomic.
   - One player disconnects while the other's MOVE is resolving: the forfeit
     waits for the lock, then sees the current state.
   - Both players disconnect at nearly the same time: the forfeit/GAME_OVER
     logic checks the FSM state under the lock, so GAME_OVER and CLEANUP happen
     exactly once.
   - Two clients CONNECT at once: role assignment (player1/player2) happens
     under the lock, so both can't become player1.

6. Turn enforcement: summarize how every MOVE/SWITCH is checked under the lock
   against that player's own readiness region before any state is touched.
   Rejected messages produce ERROR to that client only, with no state change
   and the opponent's locked-in move preserved. Reference the edge-case table
   in fsm_specification.md rather than duplicating it.

7. Score and leaderboard synchronization:
   - Per-battle score: remaining (non-fainted) Pokémon count per side, stored
     server-side and recomputed in CHECK_FAINT.
   - Match record: dict keyed by player_name → {wins, losses, draws}, updated
     exactly once per game inside the critical section that builds GAME_OVER
     (including FORFEIT results). Note the limitation that it's keyed by
     display name and lives in memory only.
   - Both are broadcast to both clients: remaining counts in every
     STATE_UPDATE, the match record in every GAME_OVER.

8. A Mermaid sequenceDiagram (in this same file) with participants: Client 1
   (player1), Game Server, Client 2 (player2). Use autonumber. Show:
   - Client 1 sends MOVE. Note over the server: acquire game_lock, validate.
     Use an alt/else block:
       alt valid → note "player1 locked in, waiting for player2", server
       sends nothing yet, releases lock
       else invalid move or out of turn → ERROR to Client 1 only, state
       unchanged
   - Client 2 sends MOVE. Note: acquire game_lock, validate.
       alt valid and both locked in → note: resolve round by speed order,
       apply damage, check faints, update remaining counts → STATE_UPDATE to
       Client 1 and STATE_UPDATE to Client 2 (with the identical payload,
       including the remaining counts) → release lock
       else invalid → ERROR to Client 2 only, player1's locked-in move kept
   - An opt block for when a side has no Pokémon left: GAME_OVER to both
     clients including the updated match record.
   Keep the syntax conservative (no HTML except <br> in notes) so it renders
   on GitHub. Below the diagram, add a short numbered narrative explaining
   each step.

=== TASK 2: Minimal addendum to docs/protocol_blueprint.md ===
- Add a "remaining" field to the STATE_UPDATE schema:
  {"player1": int, "player2": int} = count of non-fainted Pokémon per side.
  Update its key table and sample payload.
- Add a "record" field to the GAME_OVER schema:
  {"<player_name>": {"wins": int, "losses": int, "draws": int}, ...} for both
  players. Update its key table and sample payload.
- Add a short "Changelog" note at the bottom: "Sprint 2: added
  STATE_UPDATE.remaining and GAME_OVER.record for score synchronization."
- Change nothing else in the file.

=== TASK 3: Update docs/ai_prompts.md ===
- Add a "Sprint 2 Prompt – Concurrency Design" section ABOVE the existing
  Sprint 3 placeholder, containing this exact prompt. Add a design ownership
  note there: the threading model, the single-lock strategy, send-under-lock
  broadcasting, deferred forfeit handling, and the score/record design were my
  decisions before this prompt was written.
- Leave the Sprint 3 placeholder as is.
```

**Notes / deviations from the generated docs:**

- The sequence diagram uses a nested `alt` / `else` (`STATE_UPDATE` if the game
  continues, `GAME_OVER` if it is decided) instead of a `STATE_UPDATE` followed by
  an `opt` block. Per the FSM, `CHECK_WIN_DRAW` sends `STATE_UPDATE` only when the game
  continues and goes straight to `GAME_OVER` otherwise.

---

## 5. Sprint 3 Prompt – Code Generation (Placeholder)

> **TODO (Sprint 3):** Insert the exact prompt used to constrain AI code generation.

**Will be used to generate:** *TBD (e.g. `server.py`, `client.py`, `protocol.py`, `game_engine.py`)*
**Constraint goal:** generated code must implement `protocol_blueprint.md` and
`fsm_specification.md` exactly. That means no new message types, fields, error codes, or
states, and the same NDJSON framing and termination handling.

```text
<Sprint 3 prompt goes here>
```

**Notes / deviations from the generated code:** *TBD*
