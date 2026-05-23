"""
Unit tests for the Coup game engine.
Run with: python -m pytest tests/
"""

import json
import pytest

from engine.coup import (
    Card, Phase, MoveType, LossContinuation,
    Move, Player, GameState, PendingAction,
    new_game, legal_actions, apply_action, is_terminal,
    REQUIRES, BLOCKS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup(
    p0_cards,
    p1_cards,
    p0_coins=2,
    p1_coins=2,
    deck=None,
    extra_players=None,
) -> GameState:
    """Build a deterministic 2-player game with specific hands."""
    state = new_game(["Alice", "Bob"], seed=0)
    state.players[0].influence = list(p0_cards)
    state.players[0].coins     = p0_coins
    state.players[1].influence = list(p1_cards)
    state.players[1].coins     = p1_coins
    if deck is not None:
        state.deck = list(deck)
    return state


def _do(state: GameState, *moves: Move) -> GameState:
    for m in moves:
        state = apply_action(state, m)
    return state


# ---------------------------------------------------------------------------
# new_game / basic structure
# ---------------------------------------------------------------------------

class TestNewGame:
    def test_two_players_start_with_2_coins_and_2_cards(self):
        s = new_game(["A", "B"], seed=1)
        for p in s.players:
            assert p.coins == 2
            assert p.num_influence == 2
            assert p.is_alive

    def test_deck_has_correct_size(self):
        s = new_game(["A", "B"], seed=1)
        assert len(s.deck) == 15 - 4  # 15 cards, 2 players × 2 cards dealt

    def test_four_players_deck_size(self):
        s = new_game(["A", "B", "C", "D"], seed=1)
        assert len(s.deck) == 15 - 8

    def test_first_player_acts(self):
        s = new_game(["A", "B"], seed=1)
        assert s.phase == Phase.ACTION_SELECTION
        assert s.active_player == 0
        assert s.current_decision_player == 0

    def test_invalid_player_count(self):
        with pytest.raises((ValueError, AssertionError)):
            new_game(["solo"])
        with pytest.raises((ValueError, AssertionError)):
            new_game(["a", "b", "c", "d", "e", "f", "g"])


# ---------------------------------------------------------------------------
# Income
# ---------------------------------------------------------------------------

class TestIncome:
    def test_income_adds_one_coin_and_advances_turn(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.DUKE, Card.CAPTAIN])
        s = _do(s, Move(MoveType.INCOME))
        assert s.players[0].coins == 3
        assert s.active_player == 1
        assert s.phase == Phase.ACTION_SELECTION

    def test_income_not_challengeable_or_blockable(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.DUKE, Card.CAPTAIN])
        s = _do(s, Move(MoveType.INCOME))
        # Turn passed directly; no pending action
        assert s.pending is None


# ---------------------------------------------------------------------------
# Foreign Aid
# ---------------------------------------------------------------------------

class TestForeignAid:
    def test_unchallenged_foreign_aid_gives_2_coins(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.CAPTAIN, Card.CAPTAIN])
        s = _do(
            s,
            Move(MoveType.FOREIGN_AID),   # Alice declares
            Move(MoveType.PASS),           # Bob passes on block
        )
        assert s.players[0].coins == 4
        assert s.active_player == 1

    def test_foreign_aid_blocked_by_duke(self):
        s = _setup([Card.CAPTAIN, Card.ASSASSIN], [Card.DUKE, Card.CAPTAIN])
        s = _do(
            s,
            Move(MoveType.FOREIGN_AID),                    # Alice declares
            Move(MoveType.BLOCK, block_card=Card.DUKE),    # Bob blocks with Duke
            Move(MoveType.PASS),                            # Alice passes on challenging block
        )
        # Block stands — Alice gets nothing
        assert s.players[0].coins == 2
        assert s.active_player == 1

    def test_block_of_foreign_aid_can_be_challenged_and_exposed(self):
        s = _setup(
            [Card.CAPTAIN, Card.ASSASSIN],
            [Card.CAPTAIN, Card.CAPTAIN],  # Bob does NOT have Duke
            deck=[Card.DUKE, Card.CONTESSA],
        )
        s = _do(
            s,
            Move(MoveType.FOREIGN_AID),
            Move(MoveType.BLOCK, block_card=Card.DUKE),   # Bob bluffs Duke
            Move(MoveType.CHALLENGE),                      # Alice challenges
        )
        # Challenge succeeded — Bob (index 0 in influence) must lose an influence
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 1  # Bob

        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        # After Bob loses influence the block resolves, action should proceed
        # (continuation is RESOLVE_ACTION → Alice gets +2)
        assert s.players[0].coins == 4

    def test_block_of_foreign_aid_challenged_but_blocker_has_duke(self):
        s = _setup(
            [Card.CAPTAIN, Card.ASSASSIN],
            [Card.DUKE, Card.CAPTAIN],
            deck=[Card.CONTESSA, Card.AMBASSADOR],
        )
        s = _do(
            s,
            Move(MoveType.FOREIGN_AID),
            Move(MoveType.BLOCK, block_card=Card.DUKE),  # Bob has Duke
            Move(MoveType.CHALLENGE),                     # Alice challenges
        )
        # Bob reveals Duke → Alice must lose influence
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 0  # Alice

        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        # Block stood — Alice did not get Foreign Aid coins
        assert s.players[0].coins == 2


# ---------------------------------------------------------------------------
# Coup
# ---------------------------------------------------------------------------

class TestCoup:
    def test_coup_costs_7_coins_and_forces_influence_loss(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.DUKE, Card.CAPTAIN], p0_coins=7)
        s = _do(s, Move(MoveType.COUP, target=1))
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 1

        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        assert s.players[0].coins == 0
        assert s.players[1].num_influence == 1

    def test_coup_eliminates_player_with_one_card(self):
        s = _setup([Card.DUKE], [Card.CAPTAIN], p0_coins=7)
        s.players[0].influence = [Card.DUKE]   # give Alice 1 card
        s.players[1].influence = [Card.CAPTAIN]
        s = _do(s, Move(MoveType.COUP, target=1))
        assert s.phase == Phase.LOSE_INFLUENCE
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        assert s.phase == Phase.GAME_OVER
        assert s.winner == 0

    def test_coup_mandatory_at_10_coins(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.DUKE, Card.CAPTAIN], p0_coins=10)
        moves = legal_actions(s)
        assert all(m.move_type == MoveType.COUP for m in moves)

    def test_coup_available_at_7_coins(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.DUKE, Card.CAPTAIN], p0_coins=7)
        moves = legal_actions(s)
        assert any(m.move_type == MoveType.COUP for m in moves)

    def test_coup_unavailable_below_7_coins(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.DUKE, Card.CAPTAIN], p0_coins=6)
        moves = legal_actions(s)
        assert not any(m.move_type == MoveType.COUP for m in moves)


# ---------------------------------------------------------------------------
# Tax (Duke)
# ---------------------------------------------------------------------------

class TestTax:
    def test_unchallenged_tax_gives_3_coins(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.DUKE, Card.CAPTAIN])
        s = _do(s, Move(MoveType.TAX), Move(MoveType.PASS))
        assert s.players[0].coins == 5
        assert s.active_player == 1

    def test_tax_challenged_actor_has_duke(self):
        s = _setup(
            [Card.DUKE, Card.CAPTAIN],
            [Card.CAPTAIN, Card.CAPTAIN],
            deck=[Card.CONTESSA, Card.AMBASSADOR],
        )
        s = _do(s, Move(MoveType.TAX), Move(MoveType.CHALLENGE))
        # Alice revealed Duke; Bob must lose influence
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 1
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        # Tax proceeds after challenger loses
        assert s.players[0].coins == 5

    def test_tax_challenged_actor_bluffing(self):
        s = _setup(
            [Card.CAPTAIN, Card.ASSASSIN],  # Alice has no Duke
            [Card.CAPTAIN, Card.CAPTAIN],
        )
        s = _do(s, Move(MoveType.TAX), Move(MoveType.CHALLENGE))
        # Alice was bluffing; Alice must lose influence
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 0
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        # Tax failed; Alice did not get coins
        assert s.players[0].coins == 2


# ---------------------------------------------------------------------------
# Assassinate
# ---------------------------------------------------------------------------

class TestAssassinate:
    def test_assassinate_costs_3_coins_and_forces_loss(self):
        s = _setup(
            [Card.ASSASSIN, Card.DUKE],
            [Card.DUKE, Card.CAPTAIN],
            p0_coins=3,
        )
        s = _do(
            s,
            Move(MoveType.ASSASSINATE, target=1),  # Alice declares
            Move(MoveType.PASS),                    # Bob passes challenge
            Move(MoveType.PASS),                    # Bob passes block
        )
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 1
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        assert s.players[0].coins == 0
        assert s.players[1].num_influence == 1

    def test_assassinate_challenged_actor_has_assassin(self):
        s = _setup(
            [Card.ASSASSIN, Card.DUKE],
            [Card.DUKE, Card.CAPTAIN],
            p0_coins=3,
            deck=[Card.CONTESSA, Card.AMBASSADOR],
        )
        s = _do(
            s,
            Move(MoveType.ASSASSINATE, target=1),
            Move(MoveType.CHALLENGE),               # Bob challenges
        )
        # Alice reveals Assassin → Bob loses influence (challenge failed)
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 1
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        # Action continues; Bob must now decide to block or not
        assert s.phase == Phase.AWAIT_BLOCK
        assert s.current_decision_player == 1
        s = _do(s, Move(MoveType.PASS))
        # Assassination fires
        assert s.phase == Phase.LOSE_INFLUENCE
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        assert s.players[1].num_influence == 0
        assert s.phase == Phase.GAME_OVER

    def test_assassinate_challenged_actor_bluffing(self):
        s = _setup(
            [Card.DUKE, Card.CAPTAIN],  # Alice has no Assassin
            [Card.DUKE, Card.CAPTAIN],
            p0_coins=3,
        )
        s = _do(
            s,
            Move(MoveType.ASSASSINATE, target=1),
            Move(MoveType.CHALLENGE),
        )
        # Alice was bluffing; Alice loses influence; coins already spent
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 0
        assert s.players[0].coins == 0  # coins deducted at declaration

    def test_assassinate_blocked_by_contessa(self):
        s = _setup(
            [Card.ASSASSIN, Card.DUKE],
            [Card.CONTESSA, Card.DUKE],
            p0_coins=3,
        )
        s = _do(
            s,
            Move(MoveType.ASSASSINATE, target=1),
            Move(MoveType.PASS),                          # Bob passes challenge
            Move(MoveType.BLOCK, block_card=Card.CONTESSA),  # Bob blocks
            Move(MoveType.PASS),                          # Alice passes on block challenge
        )
        # Block stands; Bob keeps both cards
        assert s.players[1].num_influence == 2
        assert s.active_player == 1

    def test_contessa_block_challenged_and_bob_is_bluffing(self):
        s = _setup(
            [Card.ASSASSIN, Card.DUKE],
            [Card.DUKE, Card.CAPTAIN],   # Bob has no Contessa
            p0_coins=3,
            deck=[Card.CONTESSA, Card.AMBASSADOR],
        )
        s = _do(
            s,
            Move(MoveType.ASSASSINATE, target=1),
            Move(MoveType.PASS),                          # Bob passes challenge
            Move(MoveType.BLOCK, block_card=Card.CONTESSA),  # Bob bluffs Contessa
            Move(MoveType.CHALLENGE),                     # Alice challenges
        )
        # Bob was bluffing → Bob loses influence
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 1
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        # Block failed; assassination fires → Bob must lose again
        assert s.phase == Phase.LOSE_INFLUENCE
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        assert s.phase == Phase.GAME_OVER
        assert s.winner == 0

    def test_contessa_block_challenged_but_bob_has_contessa(self):
        s = _setup(
            [Card.ASSASSIN, Card.DUKE],
            [Card.CONTESSA, Card.CAPTAIN],
            p0_coins=3,
            deck=[Card.AMBASSADOR, Card.AMBASSADOR],
        )
        s = _do(
            s,
            Move(MoveType.ASSASSINATE, target=1),
            Move(MoveType.PASS),
            Move(MoveType.BLOCK, block_card=Card.CONTESSA),
            Move(MoveType.CHALLENGE),  # Alice challenges
        )
        # Bob reveals Contessa → Alice loses influence
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 0
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        # Block stands; Alice's assassination failed
        assert s.players[1].num_influence == 2
        assert s.active_player == 1


# ---------------------------------------------------------------------------
# Steal (Captain)
# ---------------------------------------------------------------------------

class TestSteal:
    def test_unchallenged_steal_transfers_2_coins(self):
        s = _setup(
            [Card.CAPTAIN, Card.DUKE],
            [Card.DUKE, Card.CAPTAIN],
            p1_coins=3,
        )
        s = _do(
            s,
            Move(MoveType.STEAL, target=1),
            Move(MoveType.PASS),   # Bob passes challenge
            Move(MoveType.PASS),   # Bob passes block
        )
        assert s.players[0].coins == 4
        assert s.players[1].coins == 1

    def test_steal_from_zero_coin_player(self):
        s = _setup(
            [Card.CAPTAIN, Card.DUKE],
            [Card.DUKE, Card.CAPTAIN],
            p1_coins=0,
        )
        s = _do(
            s,
            Move(MoveType.STEAL, target=1),
            Move(MoveType.PASS),
            Move(MoveType.PASS),
        )
        assert s.players[0].coins == 2  # stole 0
        assert s.players[1].coins == 0

    def test_steal_from_one_coin_player(self):
        s = _setup(
            [Card.CAPTAIN, Card.DUKE],
            [Card.DUKE, Card.CAPTAIN],
            p1_coins=1,
        )
        s = _do(
            s,
            Move(MoveType.STEAL, target=1),
            Move(MoveType.PASS),
            Move(MoveType.PASS),
        )
        assert s.players[0].coins == 3
        assert s.players[1].coins == 0

    def test_steal_blocked_by_captain(self):
        s = _setup(
            [Card.CAPTAIN, Card.DUKE],
            [Card.CAPTAIN, Card.DUKE],
        )
        s = _do(
            s,
            Move(MoveType.STEAL, target=1),
            Move(MoveType.PASS),
            Move(MoveType.BLOCK, block_card=Card.CAPTAIN),
            Move(MoveType.PASS),
        )
        assert s.players[0].coins == 2  # nothing stolen
        assert s.players[1].coins == 2

    def test_steal_blocked_by_ambassador(self):
        s = _setup(
            [Card.CAPTAIN, Card.DUKE],
            [Card.AMBASSADOR, Card.DUKE],
        )
        s = _do(
            s,
            Move(MoveType.STEAL, target=1),
            Move(MoveType.PASS),
            Move(MoveType.BLOCK, block_card=Card.AMBASSADOR),
            Move(MoveType.PASS),
        )
        assert s.players[0].coins == 2

    def test_steal_challenged_actor_bluffing(self):
        s = _setup(
            [Card.DUKE, Card.ASSASSIN],  # no Captain
            [Card.DUKE, Card.CAPTAIN],
        )
        s = _do(
            s,
            Move(MoveType.STEAL, target=1),
            Move(MoveType.CHALLENGE),
        )
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 0


# ---------------------------------------------------------------------------
# Exchange (Ambassador)
# ---------------------------------------------------------------------------

class TestExchange:
    def test_unchallenged_exchange_lets_player_swap_cards(self):
        s = _setup(
            [Card.AMBASSADOR, Card.DUKE],
            [Card.DUKE, Card.CAPTAIN],
            deck=[Card.CONTESSA, Card.ASSASSIN],
        )
        s = _do(
            s,
            Move(MoveType.EXCHANGE),
            Move(MoveType.PASS),   # Bob passes challenge
        )
        # Alice now has 4 cards to pick 2 from: Ambassador, Duke, Contessa, Assassin
        assert s.phase == Phase.EXCHANGE_SELECTION
        assert s.current_decision_player == 0
        # Keep Contessa and Assassin (indices 2,3 in combined list)
        s = _do(s, Move(MoveType.KEEP, keep_indices=[2, 3]))
        assert set(s.players[0].influence) == {Card.CONTESSA, Card.ASSASSIN}
        assert s.active_player == 1

    def test_exchange_challenged_actor_bluffing(self):
        s = _setup(
            [Card.DUKE, Card.CAPTAIN],   # no Ambassador
            [Card.DUKE, Card.CAPTAIN],
        )
        s = _do(
            s,
            Move(MoveType.EXCHANGE),
            Move(MoveType.CHALLENGE),
        )
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 0

    def test_exchange_challenged_actor_has_ambassador(self):
        s = _setup(
            [Card.AMBASSADOR, Card.DUKE],
            [Card.CAPTAIN, Card.CAPTAIN],
            deck=[Card.CONTESSA, Card.ASSASSIN, Card.DUKE],
        )
        s = _do(
            s,
            Move(MoveType.EXCHANGE),
            Move(MoveType.CHALLENGE),
        )
        # Alice reveals Ambassador; Bob loses influence
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 1
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        # Exchange continues
        assert s.phase == Phase.EXCHANGE_SELECTION


# ---------------------------------------------------------------------------
# Multi-player turn order
# ---------------------------------------------------------------------------

class TestTurnOrder:
    def test_turns_advance_in_order(self):
        s = new_game(["A", "B", "C"], seed=42)
        assert s.active_player == 0
        s = _do(s, Move(MoveType.INCOME))
        assert s.active_player == 1
        s = _do(s, Move(MoveType.INCOME))
        assert s.active_player == 2
        s = _do(s, Move(MoveType.INCOME))
        assert s.active_player == 0

    def test_dead_player_skipped(self):
        s = new_game(["A", "B", "C"], seed=42)
        # Give A enough coins to coup B immediately
        s.players[0].coins = 7
        s.players[1].influence = [Card.DUKE]   # one card so one reveal kills B
        s = _do(s, Move(MoveType.COUP, target=1))
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        assert not s.players[1].is_alive
        # Next active player should be C (index 2), not B
        assert s.active_player == 2


# ---------------------------------------------------------------------------
# Challenge order (3-player: all non-actors respond in turn order)
# ---------------------------------------------------------------------------

class TestChallengeOrder3Player:
    def test_challenge_goes_around_in_turn_order(self):
        s = new_game(["A", "B", "C"], seed=42)
        # Give A a Duke so she can Tax
        s.players[0].influence = [Card.DUKE, Card.CAPTAIN]
        s = _do(s, Move(MoveType.TAX))
        # Should be B's turn to respond (player 1)
        assert s.phase == Phase.AWAIT_CHALLENGE
        assert s.current_decision_player == 1
        s = _do(s, Move(MoveType.PASS))
        # Then C (player 2)
        assert s.current_decision_player == 2
        s = _do(s, Move(MoveType.PASS))
        # No more challengers → Tax resolves
        assert s.players[0].coins == 5


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_roundtrip_new_game(self):
        s = new_game(["Alice", "Bob"], seed=7)
        s2 = GameState.from_json(s.to_json())
        assert s2.to_dict() == s.to_dict()

    def test_roundtrip_mid_game(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.DUKE, Card.CAPTAIN])
        s = apply_action(s, Move(MoveType.TAX))
        s2 = GameState.from_json(s.to_json())
        assert s2.to_dict() == s.to_dict()
        assert s2.phase == Phase.AWAIT_CHALLENGE

    def test_json_is_valid_json(self):
        s = new_game(["A", "B"], seed=1)
        parsed = json.loads(s.to_json())
        assert "players" in parsed
        assert "phase" in parsed


# ---------------------------------------------------------------------------
# legal_actions edge cases
# ---------------------------------------------------------------------------

class TestLegalActions:
    def test_assassinate_requires_3_coins(self):
        s = _setup([Card.ASSASSIN, Card.DUKE], [Card.DUKE, Card.CAPTAIN], p0_coins=2)
        moves = legal_actions(s)
        assert not any(m.move_type == MoveType.ASSASSINATE for m in moves)

    def test_assassinate_available_at_3_coins(self):
        s = _setup([Card.ASSASSIN, Card.DUKE], [Card.DUKE, Card.CAPTAIN], p0_coins=3)
        moves = legal_actions(s)
        assert any(m.move_type == MoveType.ASSASSINATE for m in moves)

    def test_steal_always_available_against_alive_opponents(self):
        s = _setup([Card.CAPTAIN, Card.DUKE], [Card.DUKE, Card.CAPTAIN])
        moves = legal_actions(s)
        assert any(m.move_type == MoveType.STEAL for m in moves)

    def test_reveal_options_match_hand_size(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.DUKE, Card.CAPTAIN], p0_coins=7)
        s = apply_action(s, Move(MoveType.COUP, target=1))
        # Bob must reveal; he has 2 cards → 2 reveal options
        assert s.phase == Phase.LOSE_INFLUENCE
        assert s.current_decision_player == 1
        moves = legal_actions(s)
        assert len(moves) == 2
        assert all(m.move_type == MoveType.REVEAL for m in moves)

    def test_exchange_keep_options_count(self):
        s = _setup(
            [Card.AMBASSADOR, Card.DUKE],
            [Card.CAPTAIN, Card.CAPTAIN],
            deck=[Card.CONTESSA, Card.ASSASSIN],
        )
        s = _do(s, Move(MoveType.EXCHANGE), Move(MoveType.PASS))
        assert s.phase == Phase.EXCHANGE_SELECTION
        moves = legal_actions(s)
        # combined = 4 cards, keep 2 → C(4,2) = 6 options
        assert len(moves) == 6


# ---------------------------------------------------------------------------
# Game over / winner
# ---------------------------------------------------------------------------

class TestGameOver:
    def test_is_terminal_false_at_start(self):
        s = new_game(["A", "B"], seed=1)
        assert not is_terminal(s)

    def test_is_terminal_true_when_one_player_remains(self):
        s = _setup([Card.DUKE], [Card.CAPTAIN], p0_coins=7)
        s.players[0].influence = [Card.DUKE]
        s.players[1].influence = [Card.CAPTAIN]
        s = _do(s, Move(MoveType.COUP, target=1))
        s = _do(s, Move(MoveType.REVEAL, card_index=0))
        assert is_terminal(s)
        assert s.winner == 0

    def test_no_winner_during_game(self):
        s = new_game(["A", "B"], seed=1)
        assert s.winner is None

    def test_history_records_moves(self):
        s = _setup([Card.DUKE, Card.CAPTAIN], [Card.DUKE, Card.CAPTAIN])
        s = _do(s, Move(MoveType.INCOME))
        assert len(s.history) == 1
        assert "Income" in s.history[0].desc
