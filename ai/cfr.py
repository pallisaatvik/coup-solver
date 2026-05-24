"""
External Sampling MCCFR for 2-player Coup.

Two module-level dicts accumulate across all iterations:
  regrets[info_set][move_type]      — cumulative counterfactual regret
  strategy_sum[info_set][move_type] — cumulative strategy (for average strategy)

The average strategy (not the current regret-matched strategy) converges to
Nash equilibrium for 2-player zero-sum games.
"""

import pickle
import random
from typing import Dict, Tuple

from engine.coup import GameState, Move, apply_action, is_terminal, legal_actions, new_game
from ai.infoset import info_set_key

regrets:      Dict[tuple, Dict[str, float]] = {}
strategy_sum: Dict[tuple, Dict[str, float]] = {}


def _regret_match(info_set: tuple, action_keys: list) -> Dict[str, float]:
    r = regrets.get(info_set, {})
    pos = {a: max(0.0, r.get(a, 0.0)) for a in action_keys}
    total = sum(pos.values())
    if total > 0:
        return {a: pos[a] / total for a in action_keys}
    n = len(action_keys)
    return {a: 1.0 / n for a in action_keys}


def average_strategy(info_set: tuple, action_keys: list) -> Dict[str, float]:
    s = strategy_sum.get(info_set, {})
    total = sum(s.get(a, 0.0) for a in action_keys)
    if total > 0:
        return {a: s.get(a, 0.0) / total for a in action_keys}
    n = len(action_keys)
    return {a: 1.0 / n for a in action_keys}


def traverse(state: GameState, player: int, trajectory: tuple) -> float:
    """
    External Sampling MCCFR traversal.
    Returns the expected utility for `player` from this state.
    """
    if is_terminal(state):
        return 1.0 if state.players[player].is_alive else -1.0

    current = state.current_decision_player
    actions = legal_actions(state)
    keys    = [a.move_type.value for a in actions]
    iset    = info_set_key(state, current, trajectory)
    strat   = _regret_match(iset, keys)

    if current == player:
        # Traversing player: evaluate ALL actions
        values: Dict[str, float] = {}
        for a, k in zip(actions, keys):
            next_state = apply_action(state, a)
            values[k] = traverse(next_state, player, trajectory + ((current, k),))

        ev = sum(strat[k] * values[k] for k in keys)

        # Update regrets and strategy sum
        r = regrets.setdefault(iset, {})
        s = strategy_sum.setdefault(iset, {})
        for k in keys:
            r[k] = r.get(k, 0.0) + values[k] - ev
            s[k] = s.get(k, 0.0) + strat[k]

        return ev

    else:
        # Other player: sample ONE action
        chosen_k = random.choices(keys, weights=[strat[k] for k in keys])[0]
        chosen_a = actions[keys.index(chosen_k)]

        # Still update strategy sum for this player
        s = strategy_sum.setdefault(iset, {})
        for k in keys:
            s[k] = s.get(k, 0.0) + strat[k]

        next_state = apply_action(state, chosen_a)
        return traverse(next_state, player, trajectory + ((current, chosen_k),))


def run_iteration() -> None:
    """One MCCFR iteration: traverse as P0 then as P1."""
    state = new_game(["P0", "P1"])
    traverse(state, 0, ())
    traverse(state, 1, ())


def save(path: str = "ai/strategy.pkl") -> None:
    with open(path, "wb") as f:
        pickle.dump({"regrets": regrets, "strategy_sum": strategy_sum}, f)


def load(path: str = "ai/strategy.pkl") -> None:
    global regrets, strategy_sum
    with open(path, "rb") as f:
        d = pickle.load(f)
    regrets      = d["regrets"]
    strategy_sum = d["strategy_sum"]
