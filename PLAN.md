# Coup Solver — Project Plan

## Overview

Two main modes:
- **Play** — user plays Coup against 3 trained bots in real time
- **Viewer** — browse recorded/generated game states and see what action the bot recommends (and why)

---

## Stack

| Layer | Choice | Reason |
|---|---|---|
| Game engine + AI | Python | CFR libraries, numpy, easy scripting |
| Backend API | FastAPI + WebSockets | async, fast, easy to self-host on Railway |
| Frontend | Vanilla JS or lightweight React | keep it simple; no build toolchain needed initially |
| Hosting | Railway | already wired up |

---

## 1. Game Engine (`engine/`)

Core library with no UI or network dependencies — everything else builds on this.

- **State representation** — full game state: player coin counts, number of influences remaining, whose turn it is, pending action/challenge/block, card assignments (hidden from opponents)
- **Action space** — all legal actions from a given state: Income, Foreign Aid, Coup, Duke (Tax), Assassin, Captain (Steal), Ambassador (Exchange), plus responses: Challenge, Block, Pass
- **Transition function** — apply an action to a state and return the next state(s), handling probability (e.g. card reveals on challenges)
- **Terminal detection** — detect game over, identify winner
- **History log** — structured record of every action and response in a game, serializable to JSON

Deliverable: `engine/coup.py` with `GameState`, `Action`, `apply_action()`, `legal_actions()`, `is_terminal()`

---

## 2. Bot AI (`ai/`)

Coup is a hidden-information extensive-form game, making it a good fit for **Counterfactual Regret Minimization (CFR)** — the same family of algorithms used for poker solvers.

### Card visibility and information sets

There are 3 copies of each card (15 total). Seeing any card narrows the distribution over the remaining hidden cards. Visibility has three tiers:

- **Public** — lost influence (discard pile) + cards revealed during a successful challenge defence (shown to all before reshuffling)
- **Private** — cards drawn during your own Ambassador Exchange (seen only by you, then returned to deck)
- **Hidden** — opponent face-down cards + deck

Each player therefore has a different information set even in the same game state. The formula for a given player:

```
hidden copies of X = 3 − hand.count(X) − public_revealed.count(X) − private_exchange_observations.count(X)
```

Implications for implementation:
- The engine's `GameState` is the **ground truth** (referee view, all cards known)
- Each player needs a **private observation log** — a persistent record of cards seen through their own Exchanges — to reconstruct their information set at any point
- CFR must operate over per-player information sets, not the shared ground-truth state
- The `GameState` already tracks `player.revealed` (public) and `pending.drawn_cards` (exchange draw, ephemeral); Phase 2 must persist Exchange observations per player across turns

### Training pipeline

- Implement CFR (or CFR+) over the game tree
- Self-play: bots play against copies of themselves, iteratively updating regret tables
- Each player's strategy is a probability distribution over actions given their **information set** (hand + public revealed + private Exchange history)
- Run for enough iterations until strategies converge (Nash equilibrium approximation)
- Save trained strategy to a file (`ai/strategy.json` or `.pkl`)

### Bot inference

- Given a game state (from the player's perspective), load the strategy and sample an action
- Expose a function `bot_action(info_set) -> Action`
- Bots should be configurable: use trained strategy, or fall back to heuristic/random for weaker difficulty levels

### Stretch: explanations

- Log the top-ranked actions and their probabilities at each decision point
- Use this to power the Viewer mode's "why" panel

---

## 3. Backend API (`server/`)

FastAPI app exposing:

### REST endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/game/new` | Start a new game session, returns `game_id` |
| GET | `/game/{id}` | Get current game state (from requesting player's perspective) |
| POST | `/game/{id}/action` | Submit a player action |
| GET | `/game/{id}/history` | Full action history for the game |
| GET | `/viewer/states` | List pregenerated game states for the viewer |
| GET | `/viewer/state/{id}` | A specific game state + bot recommendation + explanation |

### WebSocket

- `ws://host/game/{id}/live` — push updates to the frontend whenever the game state changes (bot takes a turn, challenge resolved, etc.)
- Needed so the UI doesn't have to poll

### Bot turn loop

- After the player submits an action, the server advances the game through all bot turns automatically, emitting each step over the WebSocket before waiting for the next player input

---

## 4. Frontend (`index.html` + `static/`)

Keep it in plain HTML/CSS/JS files served statically, at least initially.

### Mode switcher

Simple nav: **Play** | **Viewer**

---

### Play mode

**Layout:**
- Top: opponent players (3 bots) — each showing coin count, number of face-down influence cards, player name
- Center: action log (scrollable), current prompt ("Your turn — choose an action")
- Bottom: your hand (2 cards, face up to you), your coins, action buttons

**Interactions:**
- On your turn: render buttons for each legal action
- On a bot action: display what the bot did, then prompt you to Challenge / Block / Pass if applicable
- Card loss / challenge reveal: animate the card flipping face up and being removed
- Game over: show winner, option to play again or review history

**WebSocket client:**
- Connect on game start
- On each message, re-render the relevant parts of the UI
- Queue bot-turn animations so they don't all fire at once

---

### Viewer mode

**Layout:**
- Left panel: game state — all player info (in this mode, all cards visible), action history up to this point
- Right panel: recommended action, probability distribution over all legal actions, short explanation ("Captain has 34% chance because opponents are unlikely to challenge — only 2 cards left in deck that could contradict")
- Timeline scrubber at the bottom to step through a game turn by turn

**Data source:**
- Either a pregenerated library of interesting states, or let the user paste a game history JSON and replay it

---

## 5. Work Breakdown

### Phase 1 — Game engine (no AI yet)
- [ ] Implement full Coup rules in Python
- [ ] Write unit tests covering all action types, challenges, blocks, edge cases
- [ ] Serialization: game state ↔ JSON

### Phase 2 — Bot training
- [ ] Implement CFR self-play loop
- [ ] Validate convergence (strategy stops changing meaningfully)
- [ ] Export trained strategy; write `bot_action()` inference function
- [ ] Generate a library of game state + recommendation pairs for the Viewer

### Phase 3 — Backend
- [ ] FastAPI app with game session management
- [ ] WebSocket push for live game updates
- [ ] Wire bot inference into the turn loop
- [ ] Viewer endpoints serving pregenerated states

### Phase 4 — Frontend: Play mode
- [ ] Static HTML layout: opponents, log, hand, action buttons
- [ ] WebSocket client, state rendering
- [ ] Action submission, bot-turn animation sequencing
- [ ] Game over / replay flow

### Phase 5 — Frontend: Viewer mode
- [ ] State display (all cards visible)
- [ ] Recommendation + probability panel
- [ ] Timeline scrubber

### Phase 6 — Polish + deploy
- [ ] Mobile-friendly layout
- [ ] Difficulty levels (random → heuristic → trained CFR)
- [ ] Railway deployment config (Dockerfile or nixpacks)
- [ ] Rate limiting / session cleanup so the server stays healthy

---

## Open questions

- How many CFR iterations are needed for reasonable play quality? May need to experiment.
- Store game sessions in memory (simple, stateless restarts) or a lightweight DB like SQLite?
- Should the viewer states be pregenerated offline, or computed on the fly per request?
