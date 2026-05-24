from engine.coup import GameState


def info_set_key(state: GameState, player: int, trajectory: tuple) -> tuple:
    p   = state.players[player]
    opp = state.players[1 - player]
    return (
        tuple(sorted(c.value for c in p.influence)),
        p.coins,
        opp.coins,
        len(opp.influence),
        tuple(sorted(c.value for c in p.revealed)),
        tuple(sorted(c.value for c in opp.revealed)),
        state.phase.value,
        state.pending.action_type if state.pending else None,
        state.pending.blocker_card.value if (state.pending and state.pending.blocker_card) else None,
        trajectory,
    )
