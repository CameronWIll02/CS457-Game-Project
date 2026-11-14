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

## 5. Sprint 3 Prompt – Code Generation

**Used to generate:** `server.py`, `client.py`, `protocol.py`, `game_engine.py`, `pokedex.py`, `tests/test_protocol.py`, `tests/test_game_engine.py`, `README.md`, the Sprint 3 round-cap edits to `docs/protocol_blueprint.md` and `docs/fsm_specification.md`, and this section of `docs/ai_prompts.md`
**Constraint goal:** generated code must implement `protocol_blueprint.md`,
`fsm_specification.md`, and `concurrency_design.md` exactly. That means no new message types, fields,
error codes, or states (except the round-cap rule), and the same NDJSON framing and termination
handling.

**Design ownership:** I made these decisions **before I wrote the prompt below**:

- the protocol (message types, fields, error codes, NDJSON framing),
- the FSM (states, per-player readiness regions, forfeit and rematch rules),
- the concurrency design (thread-per-client, one `game_lock`, send-under-lock
  broadcasts, deferred forfeit handling, FIFO lobby rotation),
- the client UX flow (message-driven prompts, numbered choices, `q` / Ctrl-C to leave),
- the 50-round cap `DRAW` rule (from my Sprint 0 SOW),
- the PAR/SLP-only status scope.

The AI's job was to implement those decisions as code, not to make them.

```text
I'm implementing Sprint 3 of my CS 457 Computer Networks project: a Gen 1 Pokémon
battle simulator over TCP. Read these first; they are the spec and the code must
follow them exactly:
- docs/protocol_blueprint.md (messages, fields, error codes, NDJSON framing,
  termination handling)
- docs/fsm_specification.md (server states and transitions, edge-case table)
- docs/concurrency_design.md (threading model, game_lock rules, race handling)
- sow_template.md (game rules)

Do NOT invent new message types, fields, error codes, or FSM states, except the
single round-cap change in TASK 4. If something in the spec is ambiguous, pick the
simplest reading, implement it, and list it in your final summary.

=== TASK 1: Project structure (Python 3, standard library only) ===
- protocol.py: send_line(conn, obj) -> bool (NDJSON encode + sendall, catches
  BrokenPipeError/ConnectionResetError/ConnectionAbortedError and returns False),
  and a LineBuffer class that accumulates recv() bytes and yields complete
  decoded JSON objects, with the 64 KiB max-line guard from the blueprint.
  Malformed lines must surface as a parse error the server turns into
  ERROR MALFORMED_MESSAGE, never an exception that kills the thread.
- pokedex.py: curated data for ~15 Gen 1 species (accurate Gen 1 base stats:
  hp, attack, defense, special, speed; Gen 1 types) and their small movesets
  (2-4 moves each, accurate Gen 1 type/power/accuracy). Include at least the
  species used in the blueprint samples (Charizard, Jolteon, Snorlax,
  Blastoise, Alakazam, Gengar). Include the Gen 1 type chart, including the
  Gen 1 quirk that Ghost-type moves have no effect on Psychic.
- game_engine.py: pure game logic, no sockets. Team generation (3 random
  distinct species per player at fixed level 50), Gen 1 stat calculation at
  level 50 from base stats only (no DVs/stat exp), simplified Gen 1 damage
  formula (level, power, attack/defense or special/special, STAB 1.5x, type
  effectiveness, random factor 217-255/255, accuracy check; no crits), speed
  ordering (tie: player1 first), faint marking, remaining counts, win/draw
  check. Status: implement only PAR (speed quartered, 25% chance to skip turn)
  and SLP (1-3 turns asleep, can't move). Thunder Wave (fails on Ground
  types) and Hypnosis are the only status moves. Leave other status values
  in the enum but unused. Every event appends a short human-readable line to
  the round's events list.
- server.py: networking, FSM, and concurrency exactly per
  concurrency_design.md: main thread accept() loop spawning daemon worker
  threads; recv() outside game_lock; every state access and every socket
  write under `with game_lock:`; broadcasts sent while holding the lock;
  send failures recorded and handled by on_player_left() after the lock is
  released; on_player_left() idempotent; FIFO lobby queue with the rematch
  rotation rule; roles by queue order; match record keyed by player_name.
  Log each FSM transition and each received/sent message type to stdout with
  a timestamp so the console doubles as the execution log.
- client.py: see TASK 3.
- tests/test_protocol.py: unittest tests for LineBuffer covering
  fragmentation (one message split across chunks), coalescing (several
  messages in one chunk), both at once (the 3-recv() example from the
  blueprint §2.3), and an oversize line.
- tests/test_game_engine.py: a few unittest tests: type effectiveness incl.
  Ghost vs Psychic = 0, speed ordering, faint and remaining counts,
  round-cap draw.
- README.md: how to run server, two clients, and the tests.

=== TASK 2: CLI arguments (argparse) ===
- server.py: -p PORT required; -h help. Bind to 0.0.0.0. Validate port is an
  integer in 1024-65535; on failure print a clear message plus usage and
  exit(1). Set SO_REUSEADDR.
- client.py: -i HOSTNAME required, -p PORT required, -h help. Same port
  validation. Resolve with socket.gethostbyname(args.hostname). Catch
  socket.gaierror and print, with no traceback:
    [ERROR] Unable to resolve DNS hostname '<name>'.
    Please check your Cisco router DNS configuration ('ip dns server' /
    'ip host') or verify domain spelling.
  then sys.exit(1). Also catch ConnectionRefusedError / TimeoutError /
  OSError on connect with a friendly message and exit(1). No hardcoded IPs
  anywhere. Help text example: python3 client.py -i server.will.edu -p 8080

=== TASK 3: Client UI ===
- Single-threaded and message-driven: block on recv(), run messages through
  LineBuffer, and only prompt for input when the latest STATE_UPDATE's
  awaiting[my_role] is "MOVE" or "SWITCH".
- Prompt for a player name, send CONNECT.
- LOBBY_WAIT: print "Waiting for an opponent...".
- GAME_START: show my role, my team, and the opponent's team.
- STATE_UPDATE: clear, readable display: round number, the events log, both
  active Pokémon with an HP bar like [#######---] 31/78 and status, the
  remaining count per side as the score, then either "Your turn: choose a
  move" with a numbered move list, "Your Pokémon fainted: choose a
  replacement" with a numbered list of non-fainted team members, or
  "Waiting for <opponent>...". Input is a number; re-prompt locally on
  invalid input before sending anything.
- ERROR: print the detail and re-prompt for the same action.
- GAME_OVER: show the result, winner, final teams, and the match record,
  then return to waiting for the lobby (rematch rotation).
- Typing "q" at any prompt, or Ctrl-C, sends DISCONNECT and exits cleanly.
- If the server connection drops (EOF or socket exception), print
  "Connection to server lost." and exit cleanly, no traceback.

=== TASK 4: Round-cap draw (the only spec change) ===
My Sprint 0 SOW defines a draw as reaching a 50-round cap with both sides
still having usable Pokémon. Implement it in CHECK_WIN_DRAW: if round 50
resolves and neither side has run out, the result is DRAW, winner null.
Update docs/protocol_blueprint.md GAME_OVER result description and the
fsm_specification.md CHECK_WIN_DRAW walkthrough to include this rule, and
add a Changelog line: "Sprint 3: added 50-round cap DRAW condition (from
SOW §1.2)." Make the cap a named constant.

=== TASK 5: docs/ai_prompts.md ===
Replace the Sprint 3 placeholder with this exact prompt. Add an ownership
note: protocol, FSM, concurrency design, client UX flow, round-cap rule,
and the PAR/SLP-only status scope were my decisions before this prompt.
Fill "Notes / deviations" with any spec ambiguities you resolved.

=== Verification before you finish ===
- Run all tests and make them pass.
- Start the server on a free port and drive two clients from a script
  (subprocess with piped stdin) through at least 3 rounds, to confirm the
  game works end to end. Fix anything that breaks. Don't commit the script.
- Confirm `python3 client.py -i doesnotexist.invalid -p 8080` prints the
  friendly DNS error and exits with status 1.
- Confirm bad ports (e.g. -p 80, -p abc) are rejected on both programs.
- Run a PEP 8 check (pycodestyle or flake8 if available) and fix issues.
Don't commit. Summarize what you built and any deviations.
```

**Notes / deviations from the generated code:**

*Inputs*

- The implementation's game rules were checked against `sow_template.md` and
  match it. A team size of 3 is a deliberate choice; the SOW's 6 was an
  example.

*Game rules*

- **Stats are level-50 values.** `GAME_START` sends the stats calculated at
  level 50, not raw base stats. For example, Charizard has `max_hp` 138, not the 78
  shown in the blueprint sample.
- **Physical vs special is decided by move type**, as in Gen 1.
- **Every hit does at least 1 damage**, unless the type chart gives 0x.
- **Sleep lasts 1–3 turns.** The Pokémon loses that many turns. On the last one
  it wakes up ("X woke up!") but still does not move that turn.
- **Status moves can fail.** Thunder Wave and Hypnosis still roll for accuracy,
  and they fail ("But it failed!") on a target that already has a status.
  Thunder Wave also fails on Ground types ("It doesn't affect X...").
- **No secondary effects.** Damaging moves never cause status, flinch, or
  recoil (for example Body Slam never paralyzes).
- **The roster has 17 species.** Movesets are curated and do not always match
  real Gen 1 learnsets. Gengar has Lick as a third move so that a Ghost-type
  attack exists.

*Server handling of unspecified cases*

- **Server-to-client message types sent by a client** (for example
  `GAME_OVER`) count as unknown types, so they get `MALFORMED_MESSAGE`.
- **Any message before `CONNECT`, or a second `CONNECT`,** gets `OUT_OF_TURN`.
- **A `player_name` outside 1–20 characters** gets `MALFORMED_MESSAGE`.
- **Rematches start automatically.** When the server re-enters
  `WAITING_FOR_PLAYERS`, every lobby member gets `LOBBY_WAIT`, and `GAME_START`
  follows right away if two or more are queued.
- **After a forfeit, only the survivor re-enters the queue.**
- **A player whose send failed during the critical section that runs
  `CLEANUP` is not put back in the queue.**
- **`on_player_left()` also shuts down the departed socket,** following the
  FSM's "close the departed player's socket". This wakes that player's worker
  thread if it is blocked in `recv()`.
- **Oversize lines.** After reporting an oversize partial line, `LineBuffer`
  skips the rest of that line up to its newline, so the tail is not reported
  as a second error. A complete line over 64 KiB is also rejected.
- **The last round's events are not sent to clients.** On `WIN` / `DRAW`,
  `GAME_OVER` replaces `STATE_UPDATE` (per the FSM), and `GAME_OVER` has no
  `events` field. Clients therefore never see that round's events (the server
  log still has them). I left this alone because adding a field is out of scope.

*Client and CLI*

- **Stale-prompt guard.** The client remembers the `(round, action)` it last
  sent. That way, a `STATE_UPDATE` that was built before its action reached the
  server does not prompt it again.
- **Exit status.** Connection lost exits with status 1. `q` and Ctrl-C exit
  with status 0.
- **An `ERROR` that arrives after `GAME_OVER`** is shown as a short note rather
  than as an error.
- **All argument errors exit with status 1,** including missing arguments.
  argparse's default would be 2.

*Docs*

- **The FSM state-diagram labels for `CHECK_WIN_DRAW` were not updated** for
  the round cap. Only the walkthrough was, as the prompt asked.

*Sprint 3 follow-ups (requested after the first code generation)*

- **Added `GAME_OVER.events`.** It carries the final round's event lines, and
  is empty for a `FORFEIT`. `server.py` fills it in, `client.py` prints it before
  the result, and the blueprint key table, sample payload, and Changelog cover
  it. The `GAME_OVER` arrows in the `concurrency_design.md` sequence diagram now
  include it. This resolves the "last round's events are not sent to clients"
  note above. `tests/test_server.py` checks it for a `WIN` and a `FORFEIT`,
  using fake sockets.
- **Changed the FSM diagram label** `CHECK_WIN_DRAW --> GAME_OVER` to "one
  side out of usable Pokemon (WIN), or both out / round cap reached (DRAW)".
  This resolves the "diagram labels not updated" note above.
- **Added a note under the `GAME_START` sample in the blueprint** saying that
  sample stat values are illustrative and the implementation computes level-50
  stats from base stats.
