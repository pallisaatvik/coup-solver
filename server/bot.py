"""
Heuristic bot for Coup. Placeholder until the CFR bot (Phase 2) is ready.
Single public function: bot_move(state) -> Move
"""

import random
from engine.coup import GameState, Move, MoveType, Phase, legal_actions


# Weights by move type for each phase
_ACTION_WEIGHTS = {
    MoveType.COUP:        10.0,
    MoveType.ASSASSINATE:  4.0,
    MoveType.TAX:          3.0,
    MoveType.STEAL:        3.0,
    MoveType.EXCHANGE:     2.0,
    MoveType.FOREIGN_AID:  1.5,
    MoveType.INCOME:       1.0,
}

_CHALLENGE_WEIGHTS = {
    MoveType.CHALLENGE: 0.2,
    MoveType.PASS:      0.8,
}

_BLOCK_WEIGHTS = {
    MoveType.BLOCK: 3.0,
    MoveType.PASS:  1.0,
}


def bot_move(state: GameState) -> Move:
    moves = legal_actions(state)
    assert moves, "bot_move called with no legal moves"

    phase = state.phase

    if phase == Phase.ACTION_SELECTION:
        weights = [_ACTION_WEIGHTS.get(m.move_type, 1.0) for m in moves]

    elif phase == Phase.AWAIT_CHALLENGE:
        weights = [_CHALLENGE_WEIGHTS.get(m.move_type, 1.0) for m in moves]

    elif phase == Phase.AWAIT_BLOCK:
        weights = [_BLOCK_WEIGHTS.get(m.move_type, 1.0) for m in moves]

    elif phase == Phase.AWAIT_BLOCK_CHALLENGE:
        weights = [_CHALLENGE_WEIGHTS.get(m.move_type, 1.0) for m in moves]

    elif phase == Phase.LOSE_INFLUENCE:
        # Always pick index 0; no strategic difference for a random bot
        return moves[0]

    else:
        # EXCHANGE_SELECTION: uniform random
        weights = [1.0] * len(moves)

    return random.choices(moves, weights=weights, k=1)[0]
