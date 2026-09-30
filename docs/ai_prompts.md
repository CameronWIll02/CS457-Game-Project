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

## 4. Sprint 3 Prompt – Code Generation (Placeholder)

> **TODO (Sprint 3):** Insert the exact prompt used to constrain AI code generation.

**Will be used to generate:** *TBD (e.g. `server.py`, `client.py`, `protocol.py`, `game_engine.py`)*
**Constraint goal:** generated code must implement `protocol_blueprint.md` and
`fsm_specification.md` exactly. That means no new message types, fields, error codes, or
states, and the same NDJSON framing and termination handling.

```text
<Sprint 3 prompt goes here>
```

**Notes / deviations from the generated code:** *TBD*
