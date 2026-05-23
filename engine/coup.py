"""
Coup game engine — base game, 2-6 players.

Public API:
  new_game(player_names, seed=None) -> GameState
  legal_actions(state)             -> List[Move]
  apply_action(state, move)        -> GameState   (non-mutating)
  is_terminal(state)               -> bool

Turn flow
---------
ACTION_SELECTION
  -> (challengeable action)  AWAIT_CHALLENGE  -> AWAIT_BLOCK | resolve
  -> (Foreign Aid)           AWAIT_BLOCK      -> resolve
  -> (Coup / Income)         resolve immediately
AWAIT_BLOCK     -> AWAIT_BLOCK_CHALLENGE | resolve
AWAIT_BLOCK_CHALLENGE -> LOSE_INFLUENCE | resolve
LOSE_INFLUENCE  -> (continuation determines next phase)
EXCHANGE_SELECTION -> ACTION_SELECTION (next player)
GAME_OVER
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass, field
from enum import Enum
from itertools import combinations
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Domain enums
# ---------------------------------------------------------------------------

class Card(Enum):
    DUKE       = "Duke"
    ASSASSIN   = "Assassin"
    CAPTAIN    = "Captain"
    AMBASSADOR = "Ambassador"
    CONTESSA   = "Contessa"


class Phase(Enum):
    ACTION_SELECTION    = "action_selection"
    AWAIT_CHALLENGE     = "await_challenge"
    AWAIT_BLOCK         = "await_block"
    AWAIT_BLOCK_CHALLENGE = "await_block_challenge"
    LOSE_INFLUENCE      = "lose_influence"
    EXCHANGE_SELECTION  = "exchange_selection"
    GAME_OVER           = "game_over"


class MoveType(Enum):
    # ACTION_SELECTION
    INCOME     = "income"
    FOREIGN_AID = "foreign_aid"
    COUP       = "coup"
    TAX        = "tax"
    ASSASSINATE = "assassinate"
    STEAL      = "steal"
    EXCHANGE   = "exchange"
    # AWAIT_CHALLENGE / AWAIT_BLOCK_CHALLENGE
    CHALLENGE  = "challenge"
    PASS       = "pass"
    # AWAIT_BLOCK
    BLOCK      = "block"
    # LOSE_INFLUENCE
    REVEAL     = "reveal"
    # EXCHANGE_SELECTION
    KEEP       = "keep"


class LossContinuation(Enum):
    END_TURN       = "end_turn"       # nothing more to do this turn
    CONTINUE_ACTION = "continue_action"  # challenger lost; proceed to block/resolve
    RESOLVE_ACTION  = "resolve_action"   # block was a lie; action fires
    BLOCK_STANDS    = "block_stands"     # block challenge defender won; turn ends


# ---------------------------------------------------------------------------
# Which card is required to claim each action, and which cards block each action
# ---------------------------------------------------------------------------

REQUIRES: Dict[str, Card] = {
    "tax":        Card.DUKE,
    "assassinate": Card.ASSASSIN,
    "steal":      Card.CAPTAIN,
    "exchange":   Card.AMBASSADOR,
}

BLOCKS: Dict[str, List[Card]] = {
    "foreign_aid": [Card.DUKE],
    "assassinate": [Card.CONTESSA],
    "steal":       [Card.CAPTAIN, Card.AMBASSADOR],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Move:
    move_type:    MoveType
    target:       Optional[int]       = None  # player index for targeted actions
    block_card:   Optional[Card]      = None  # BLOCK: card being claimed
    card_index:   Optional[int]       = None  # REVEAL: index into influence list
    keep_indices: Optional[List[int]] = None  # KEEP: indices into combined hand+drawn


@dataclass
class Player:
    name:      str
    coins:     int
    influence: List[Card]  # face-down (alive)
    revealed:  List[Card]  # face-up (lost)

    @property
    def num_influence(self) -> int:
        return len(self.influence)

    @property
    def is_alive(self) -> bool:
        return bool(self.influence)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name":      self.name,
            "coins":     self.coins,
            "influence": [c.value for c in self.influence],
            "revealed":  [c.value for c in self.revealed],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Player:
        return cls(
            name=d["name"],
            coins=d["coins"],
            influence=[Card(c) for c in d["influence"]],
            revealed=[Card(c) for c in d["revealed"]],
        )


@dataclass
class PendingAction:
    action_type:         str
    actor:               int
    target:              Optional[int]
    challenge_queue:     List[int]        # players who may still challenge the action
    block_eligible:      List[int]        # players who may still block (consumed as queue)

    blocker:             Optional[int]       = None
    blocker_card:        Optional[Card]      = None
    block_challenge_queue: Optional[List[int]] = None  # players who may challenge the block

    losing_player:       Optional[int]              = None
    loss_continuation:   Optional[LossContinuation] = None

    drawn_cards:         Optional[List[Card]] = None  # Ambassador exchange

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type":         self.action_type,
            "actor":               self.actor,
            "target":              self.target,
            "challenge_queue":     self.challenge_queue,
            "block_eligible":      self.block_eligible,
            "blocker":             self.blocker,
            "blocker_card":        self.blocker_card.value if self.blocker_card else None,
            "block_challenge_queue": self.block_challenge_queue,
            "losing_player":       self.losing_player,
            "loss_continuation":   self.loss_continuation.value if self.loss_continuation else None,
            "drawn_cards":         [c.value for c in self.drawn_cards] if self.drawn_cards else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PendingAction:
        return cls(
            action_type=d["action_type"],
            actor=d["actor"],
            target=d["target"],
            challenge_queue=d["challenge_queue"],
            block_eligible=d["block_eligible"],
            blocker=d["blocker"],
            blocker_card=Card(d["blocker_card"]) if d["blocker_card"] else None,
            block_challenge_queue=d["block_challenge_queue"],
            losing_player=d["losing_player"],
            loss_continuation=LossContinuation(d["loss_continuation"]) if d["loss_continuation"] else None,
            drawn_cards=[Card(c) for c in d["drawn_cards"]] if d["drawn_cards"] else None,
        )


@dataclass
class HistoryEntry:
    player: int
    desc:   str

    def to_dict(self) -> Dict[str, Any]:
        return {"player": self.player, "desc": self.desc}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> HistoryEntry:
        return cls(player=d["player"], desc=d["desc"])


@dataclass
class GameState:
    players:                List[Player]
    deck:                   List[Card]
    phase:                  Phase
    active_player:          int   # whose turn it is
    current_decision_player: int  # who must act right now (may differ in response phases)
    pending:                Optional[PendingAction]
    history:                List[HistoryEntry]

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def alive_players(self) -> List[int]:
        return [i for i, p in enumerate(self.players) if p.is_alive]

    @property
    def winner(self) -> Optional[int]:
        alive = self.alive_players
        return alive[0] if len(alive) == 1 else None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "players":                 [p.to_dict() for p in self.players],
            "deck":                    [c.value for c in self.deck],
            "phase":                   self.phase.value,
            "active_player":           self.active_player,
            "current_decision_player": self.current_decision_player,
            "pending":                 self.pending.to_dict() if self.pending else None,
            "history":                 [h.to_dict() for h in self.history],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GameState:
        return cls(
            players=[Player.from_dict(p) for p in d["players"]],
            deck=[Card(c) for c in d["deck"]],
            phase=Phase(d["phase"]),
            active_player=d["active_player"],
            current_decision_player=d["current_decision_player"],
            pending=PendingAction.from_dict(d["pending"]) if d["pending"] else None,
            history=[HistoryEntry.from_dict(h) for h in d["history"]],
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, s: str) -> GameState:
        return cls.from_dict(json.loads(s))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def new_game(player_names: List[str], seed: Optional[int] = None) -> GameState:
    if not (2 <= len(player_names) <= 6):
        raise ValueError("Coup requires 2–6 players")
    rng = random.Random(seed)
    deck: List[Card] = [card for card in Card for _ in range(3)]  # 15 cards
    rng.shuffle(deck)
    players = []
    for name in player_names:
        influence = [deck.pop(), deck.pop()]
        players.append(Player(name=name, coins=2, influence=influence, revealed=[]))
    return GameState(
        players=players,
        deck=deck,
        phase=Phase.ACTION_SELECTION,
        active_player=0,
        current_decision_player=0,
        pending=None,
        history=[],
    )


def is_terminal(state: GameState) -> bool:
    return state.phase == Phase.GAME_OVER


def legal_actions(state: GameState) -> List[Move]:
    """All legal moves for state.current_decision_player."""
    p   = state.current_decision_player
    plr = state.players[p]

    if state.phase == Phase.ACTION_SELECTION:
        assert p == state.active_player
        if plr.coins >= 10:
            return [Move(MoveType.COUP, target=t) for t in _alive_others(state, p)]

        moves: List[Move] = [Move(MoveType.INCOME), Move(MoveType.FOREIGN_AID)]
        if plr.coins >= 7:
            moves += [Move(MoveType.COUP, target=t) for t in _alive_others(state, p)]
        moves.append(Move(MoveType.TAX))
        moves.append(Move(MoveType.EXCHANGE))
        if plr.coins >= 3:
            moves += [Move(MoveType.ASSASSINATE, target=t) for t in _alive_others(state, p)]
        moves += [Move(MoveType.STEAL, target=t) for t in _alive_others(state, p)]
        return moves

    if state.phase == Phase.AWAIT_CHALLENGE:
        return [Move(MoveType.CHALLENGE), Move(MoveType.PASS)]

    if state.phase == Phase.AWAIT_BLOCK:
        assert state.pending is not None
        moves = [Move(MoveType.PASS)]
        for card in BLOCKS.get(state.pending.action_type, []):
            moves.append(Move(MoveType.BLOCK, block_card=card))
        return moves

    if state.phase == Phase.AWAIT_BLOCK_CHALLENGE:
        return [Move(MoveType.CHALLENGE), Move(MoveType.PASS)]

    if state.phase == Phase.LOSE_INFLUENCE:
        return [Move(MoveType.REVEAL, card_index=i) for i in range(len(plr.influence))]

    if state.phase == Phase.EXCHANGE_SELECTION:
        assert state.pending is not None
        combined = plr.influence + (state.pending.drawn_cards or [])
        n_keep   = plr.num_influence
        return [
            Move(MoveType.KEEP, keep_indices=list(idxs))
            for idxs in combinations(range(len(combined)), n_keep)
        ]

    return []


def apply_action(state: GameState, move: Move) -> GameState:
    """Non-mutating: returns a new GameState with the move applied."""
    state = copy.deepcopy(state)
    _apply(state, move)
    return state


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log(state: GameState, player: int, desc: str) -> None:
    state.history.append(HistoryEntry(player=player, desc=desc))


def _alive_others(state: GameState, player: int) -> List[int]:
    return [i for i in state.alive_players if i != player]


def _turn_order_from(state: GameState, start_after: int) -> List[int]:
    """Alive players in turn order, starting from the player after start_after."""
    n = len(state.players)
    order: List[int] = []
    i = (start_after + 1) % n
    while i != start_after:
        if state.players[i].is_alive:
            order.append(i)
        i = (i + 1) % n
    return order


def _next_turn(state: GameState) -> None:
    alive = state.alive_players
    if len(alive) <= 1:
        state.phase = Phase.GAME_OVER
        state.pending = None
        return
    n = len(state.players)
    nxt = (state.active_player + 1) % n
    while not state.players[nxt].is_alive:
        nxt = (nxt + 1) % n
    state.active_player          = nxt
    state.current_decision_player = nxt
    state.pending                = None
    state.phase                  = Phase.ACTION_SELECTION


def _advance_turn_phase(state: GameState) -> None:
    """After a PendingAction is created, decide what happens next."""
    pending = state.pending
    assert pending is not None
    _skip_dead(state, pending.challenge_queue)
    if pending.challenge_queue:
        state.phase                  = Phase.AWAIT_CHALLENGE
        state.current_decision_player = pending.challenge_queue.pop(0)
    else:
        _proceed_to_block_or_resolve(state)


def _proceed_to_block_or_resolve(state: GameState) -> None:
    """All challenges done (or never applicable). Go to block phase or resolve."""
    pending = state.pending
    assert pending is not None
    _skip_dead(state, pending.block_eligible)
    if pending.block_eligible:
        state.phase                  = Phase.AWAIT_BLOCK
        state.current_decision_player = pending.block_eligible.pop(0)
    else:
        _resolve_action(state)


def _skip_dead(state: GameState, queue: List[int]) -> None:
    """Remove dead players from the front of a queue in-place."""
    while queue and not state.players[queue[0]].is_alive:
        queue.pop(0)


def _force_lose_influence(
    state: GameState, player_idx: int, cont: LossContinuation
) -> None:
    assert state.pending is not None
    state.pending.losing_player     = player_idx
    state.pending.loss_continuation = cont
    state.phase                     = Phase.LOSE_INFLUENCE
    state.current_decision_player   = player_idx


def _resolve_action(state: GameState) -> None:
    pending = state.pending
    assert pending is not None
    at     = pending.action_type
    actor  = pending.actor
    target = pending.target

    if at == "income":
        state.players[actor].coins += 1
        _next_turn(state)

    elif at == "foreign_aid":
        state.players[actor].coins += 2
        _next_turn(state)

    elif at == "coup":
        # Coins already deducted at declaration; target loses influence.
        _force_lose_influence(state, target, LossContinuation.END_TURN)  # type: ignore[arg-type]

    elif at == "tax":
        state.players[actor].coins += 3
        _next_turn(state)

    elif at == "assassinate":
        if not state.players[target].is_alive:  # type: ignore[index]
            # Target died during block-challenge resolution; coins already spent.
            _next_turn(state)
        else:
            _force_lose_influence(state, target, LossContinuation.END_TURN)  # type: ignore[arg-type]

    elif at == "steal":
        stolen = min(2, state.players[target].coins)  # type: ignore[index]
        state.players[target].coins -= stolen           # type: ignore[index]
        state.players[actor].coins  += stolen
        _next_turn(state)

    elif at == "exchange":
        drawn = [state.deck.pop() for _ in range(min(2, len(state.deck)))]
        pending.drawn_cards          = drawn
        state.phase                  = Phase.EXCHANGE_SELECTION
        state.current_decision_player = actor


def _after_influence_loss(state: GameState) -> None:
    """Continuation logic executed once a REVEAL move has been applied."""
    # Check for game over first
    if len(state.alive_players) <= 1:
        state.phase   = Phase.GAME_OVER
        state.pending = None
        return

    pending = state.pending
    assert pending is not None
    cont = pending.loss_continuation

    if cont == LossContinuation.END_TURN:
        _next_turn(state)

    elif cont == LossContinuation.CONTINUE_ACTION:
        # Challenger lost; action claim stands. Proceed to block or resolve.
        _proceed_to_block_or_resolve(state)

    elif cont == LossContinuation.RESOLVE_ACTION:
        # Block was a lie; blocker lost. Fire the action.
        _resolve_action(state)

    elif cont == LossContinuation.BLOCK_STANDS:
        # Block-challenge defender revealed card; block stands.
        _next_turn(state)


def _defended_challenge(
    state: GameState,
    claimant: int,
    claimed_card: Card,
    challenger: int,
    cont_if_win: LossContinuation,
    cont_if_lose: LossContinuation,
) -> None:
    """
    Resolve a challenge.
    - If claimant has claimed_card: challenger loses influence (cont_if_win continues).
    - Otherwise: claimant loses influence (cont_if_lose continues).
    On successful defence the claimant reshuffles and draws a new card.
    """
    claimant_player  = state.players[claimant]
    challenger_name  = state.players[challenger].name

    if claimed_card in claimant_player.influence:
        # Claimant reveals, reshuffles, draws replacement
        idx = claimant_player.influence.index(claimed_card)
        claimant_player.influence.pop(idx)
        state.deck.append(claimed_card)
        random.shuffle(state.deck)
        new_card = state.deck.pop()
        claimant_player.influence.append(new_card)
        _log(
            state, challenger,
            f"{challenger_name} challenges {claimant_player.name} — "
            f"{claimant_player.name} reveals {claimed_card.value}, challenge FAILS; "
            f"{challenger_name} loses influence",
        )
        _force_lose_influence(state, challenger, cont_if_win)
    else:
        _log(
            state, challenger,
            f"{challenger_name} challenges {claimant_player.name} — "
            f"{claimant_player.name} was bluffing, challenge SUCCEEDS; "
            f"{claimant_player.name} loses influence",
        )
        _force_lose_influence(state, claimant, cont_if_lose)


# ---------------------------------------------------------------------------
# Phase handlers
# ---------------------------------------------------------------------------

def _apply(state: GameState, move: Move) -> None:
    phase = state.phase
    p     = state.current_decision_player

    if phase == Phase.ACTION_SELECTION:
        _do_action_selection(state, move, p)
    elif phase == Phase.AWAIT_CHALLENGE:
        _do_challenge_response(state, move, p)
    elif phase == Phase.AWAIT_BLOCK:
        _do_block_response(state, move, p)
    elif phase == Phase.AWAIT_BLOCK_CHALLENGE:
        _do_block_challenge_response(state, move, p)
    elif phase == Phase.LOSE_INFLUENCE:
        _do_reveal(state, move, p)
    elif phase == Phase.EXCHANGE_SELECTION:
        _do_exchange(state, move, p)


def _do_action_selection(state: GameState, move: Move, p: int) -> None:
    mt  = move.move_type
    plr = state.players[p]

    if mt == MoveType.INCOME:
        _log(state, p, f"{plr.name} takes Income")
        plr.coins += 1
        _next_turn(state)
        return

    if mt == MoveType.COUP:
        assert plr.coins >= 7
        plr.coins -= 7
        t = move.target
        _log(state, p, f"{plr.name} Coups {state.players[t].name}")  # type: ignore[index]
        state.pending = PendingAction(
            action_type="coup", actor=p, target=t,
            challenge_queue=[], block_eligible=[],
        )
        _force_lose_influence(state, t, LossContinuation.END_TURN)  # type: ignore[arg-type]
        return

    others = _turn_order_from(state, p)

    if mt == MoveType.FOREIGN_AID:
        _log(state, p, f"{plr.name} declares Foreign Aid")
        state.pending = PendingAction(
            action_type="foreign_aid", actor=p, target=None,
            challenge_queue=[],   # not challengeable
            block_eligible=others,
        )
        _advance_turn_phase(state)
        return

    if mt == MoveType.TAX:
        _log(state, p, f"{plr.name} claims Duke — Tax")
        state.pending = PendingAction(
            action_type="tax", actor=p, target=None,
            challenge_queue=others, block_eligible=[],
        )

    elif mt == MoveType.EXCHANGE:
        _log(state, p, f"{plr.name} claims Ambassador — Exchange")
        state.pending = PendingAction(
            action_type="exchange", actor=p, target=None,
            challenge_queue=others, block_eligible=[],
        )

    elif mt == MoveType.ASSASSINATE:
        assert plr.coins >= 3
        plr.coins -= 3
        t = move.target
        _log(state, p, f"{plr.name} claims Assassin — Assassinate {state.players[t].name}")  # type: ignore[index]
        state.pending = PendingAction(
            action_type="assassinate", actor=p, target=t,
            challenge_queue=others, block_eligible=[t],  # only target can block
        )

    elif mt == MoveType.STEAL:
        t = move.target
        _log(state, p, f"{plr.name} claims Captain — Steal from {state.players[t].name}")  # type: ignore[index]
        state.pending = PendingAction(
            action_type="steal", actor=p, target=t,
            challenge_queue=others, block_eligible=[t],  # only target can block
        )

    _advance_turn_phase(state)


def _do_challenge_response(state: GameState, move: Move, p: int) -> None:
    pending  = state.pending
    assert pending is not None
    plr_name = state.players[p].name

    if move.move_type == MoveType.PASS:
        _log(state, p, f"{plr_name} passes")
        _skip_dead(state, pending.challenge_queue)
        if pending.challenge_queue:
            state.current_decision_player = pending.challenge_queue.pop(0)
        else:
            _proceed_to_block_or_resolve(state)
        return

    # CHALLENGE
    required = REQUIRES[pending.action_type]
    _defended_challenge(
        state,
        claimant=pending.actor,
        claimed_card=required,
        challenger=p,
        cont_if_win=LossContinuation.CONTINUE_ACTION,
        cont_if_lose=LossContinuation.END_TURN,
    )


def _do_block_response(state: GameState, move: Move, p: int) -> None:
    pending  = state.pending
    assert pending is not None
    plr_name = state.players[p].name

    if move.move_type == MoveType.PASS:
        _log(state, p, f"{plr_name} passes on block")
        _skip_dead(state, pending.block_eligible)
        if pending.block_eligible:
            state.current_decision_player = pending.block_eligible.pop(0)
        else:
            _resolve_action(state)
        return

    # BLOCK
    card = move.block_card
    assert card is not None
    pending.blocker      = p
    pending.blocker_card = card
    _log(state, p, f"{plr_name} blocks with {card.value}")

    bq = _turn_order_from(state, p)  # everyone else may challenge the block
    pending.block_challenge_queue = bq
    _skip_dead(state, pending.block_challenge_queue)

    if pending.block_challenge_queue:
        state.phase                  = Phase.AWAIT_BLOCK_CHALLENGE
        state.current_decision_player = pending.block_challenge_queue.pop(0)
    else:
        _next_turn(state)


def _do_block_challenge_response(state: GameState, move: Move, p: int) -> None:
    pending  = state.pending
    assert pending is not None
    plr_name = state.players[p].name

    if move.move_type == MoveType.PASS:
        _log(state, p, f"{plr_name} passes on challenging block")
        assert pending.block_challenge_queue is not None
        _skip_dead(state, pending.block_challenge_queue)
        if pending.block_challenge_queue:
            state.current_decision_player = pending.block_challenge_queue.pop(0)
        else:
            _next_turn(state)
        return

    # CHALLENGE
    assert pending.blocker is not None and pending.blocker_card is not None
    _defended_challenge(
        state,
        claimant=pending.blocker,
        claimed_card=pending.blocker_card,
        challenger=p,
        cont_if_win=LossContinuation.BLOCK_STANDS,
        cont_if_lose=LossContinuation.RESOLVE_ACTION,
    )


def _do_reveal(state: GameState, move: Move, p: int) -> None:
    plr  = state.players[p]
    idx  = move.card_index
    assert idx is not None
    card = plr.influence.pop(idx)
    plr.revealed.append(card)
    _log(state, p, f"{plr.name} reveals {card.value}")
    _after_influence_loss(state)


def _do_exchange(state: GameState, move: Move, p: int) -> None:
    pending = state.pending
    assert pending is not None and pending.drawn_cards is not None
    plr      = state.players[p]
    combined = plr.influence + pending.drawn_cards
    assert move.keep_indices is not None
    keep     = [combined[i] for i in move.keep_indices]
    returned = [combined[i] for i in range(len(combined)) if i not in move.keep_indices]
    _log(state, p, f"{plr.name} exchanges, returns {[c.value for c in returned]}")
    plr.influence = keep
    state.deck.extend(returned)
    random.shuffle(state.deck)
    _next_turn(state)
