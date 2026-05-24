"""
Evaluate CFR bot win rate against the heuristic bot.
Usage: python3 -m ai.evaluate [--games N]
"""

import argparse
import sys
from pathlib import Path

sys.setrecursionlimit(10_000)


def _cfr_move(state, trajectory):
    from ai.cfr import average_strategy, strategy_sum
    from ai.infoset import info_set_key
    from engine.coup import legal_actions
    import random

    actions = legal_actions(state)
    keys    = [a.move_type.value for a in actions]
    iset    = info_set_key(state, state.current_decision_player, trajectory)
    strat   = average_strategy(iset, keys)
    chosen  = random.choices(keys, weights=[strat[k] for k in keys])[0]
    return actions[keys.index(chosen)], trajectory + ((state.current_decision_player, chosen),)


def _heuristic_move(state):
    from server.bot import bot_move
    return bot_move(state)


def play_game(cfr_is_p0: bool):
    """Play one game. Returns True if CFR bot wins."""
    from engine.coup import new_game, apply_action, is_terminal

    state      = new_game(["CFR", "Heuristic"] if cfr_is_p0 else ["Heuristic", "CFR"])
    cfr_player = 0 if cfr_is_p0 else 1
    trajectory = ()

    while not is_terminal(state):
        p = state.current_decision_player
        if p == cfr_player:
            move, trajectory = _cfr_move(state, trajectory)
        else:
            move = _heuristic_move(state)
            trajectory = trajectory + ((p, move.move_type.value),)
        state = apply_action(state, move)

    return state.players[cfr_player].is_alive


def main():
    parser = argparse.ArgumentParser(description="Evaluate CFR vs heuristic")
    parser.add_argument("--games", type=int, default=1000)
    args = parser.parse_args()

    if not Path("ai/strategy.pkl").exists():
        print("No strategy found at ai/strategy.pkl — run ai/train.py first.")
        sys.exit(1)

    from ai.cfr import load
    load()
    print("Strategy loaded.")

    wins = 0
    for i in range(args.games):
        if play_game(cfr_is_p0=(i % 2 == 0)):
            wins += 1

    print(f"CFR win rate: {wins}/{args.games} = {wins/args.games:.1%}")


if __name__ == "__main__":
    main()
