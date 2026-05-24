"""
Bot for Coup. Loads a trained CFR strategy if available; falls back to a
weighted-random heuristic for info sets not seen during training.
Single public function: bot_move(state) -> Move
"""

import random
from pathlib import Path

from engine.coup import GameState, Move, MoveType, Phase, legal_actions


# ---------------------------------------------------------------------------
# CFR strategy (loaded once at import time)
# ---------------------------------------------------------------------------

_cfr_loaded = False


def _try_load_cfr():
    global _cfr_loaded
    if Path("ai/strategy.pkl").exists():
        from ai.cfr import load
        load()
        _cfr_loaded = True
        print("CFR strategy loaded.")


_try_load_cfr()


# ---------------------------------------------------------------------------
# Heuristic weights (fallback)
# ---------------------------------------------------------------------------

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


def _heuristic_move(state: GameState) -> Move:
    moves = legal_actions(state)
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
        return moves[0]
    else:
        weights = [1.0] * len(moves)

    return random.choices(moves, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def bot_move(state: GameState) -> Move:
    moves = legal_actions(state)
    assert moves, "bot_move called with no legal moves"

    if _cfr_loaded:
        from ai.cfr import average_strategy, strategy_sum
        from ai.infoset import info_set_key
        keys  = [m.move_type.value for m in moves]
        # Use empty trajectory at inference time (stateless server).
        # Falls back to heuristic for unseen info sets.
        iset  = info_set_key(state, state.current_decision_player, ())
        if iset in strategy_sum:
            strat  = average_strategy(iset, keys)
            chosen = random.choices(keys, weights=[strat[k] for k in keys])[0]
            return moves[keys.index(chosen)]

    return _heuristic_move(state)
