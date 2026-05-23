"""
Endpoint tests for the Coup FastAPI server.
Uses TestClient (no running server needed).
"""

import json
import pytest
from fastapi.testclient import TestClient

from server.main import app
from engine.coup import Card, GameState, Phase, new_game

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_game_response(seed=42):
    return client.post("/api/new", json={"seed": seed}).json()


def move(state_token, move_type, **kwargs):
    payload = {"move_type": move_type, "target": None,
               "block_card": None, "card_index": None, "keep_indices": None}
    payload.update(kwargs)
    return client.post("/api/move", json={"state_token": state_token, "move": payload}).json()


# ---------------------------------------------------------------------------
# /api/new
# ---------------------------------------------------------------------------

class TestNewGame:
    def test_returns_200(self):
        r = client.post("/api/new", json={})
        assert r.status_code == 200

    def test_response_has_required_keys(self):
        d = new_game_response()
        assert "display" in d
        assert "state_token" in d
        assert "legal_moves" in d

    def test_state_token_is_valid_json(self):
        d = new_game_response()
        parsed = json.loads(d["state_token"])
        assert "players" in parsed
        assert "phase" in parsed

    def test_starts_at_action_selection(self):
        d = new_game_response()
        assert d["display"]["phase"] == "action_selection"

    def test_human_player_is_index_0(self):
        d = new_game_response()
        assert d["display"]["players"][0]["name"] == "You"

    def test_bot_player_is_index_1(self):
        d = new_game_response()
        assert d["display"]["players"][1]["name"] == "Bot"

    def test_both_players_start_with_2_coins(self):
        d = new_game_response()
        for p in d["display"]["players"]:
            assert p["coins"] == 2

    def test_bot_influence_is_masked(self):
        d = new_game_response()
        for card in d["display"]["players"][1]["influence"]:
            assert card == "hidden"

    def test_human_influence_is_visible(self):
        d = new_game_response()
        for card in d["display"]["players"][0]["influence"]:
            assert card != "hidden"

    def test_deck_not_in_display(self):
        d = new_game_response()
        assert "deck" not in d["display"]

    def test_legal_moves_present_on_human_turn(self):
        d = new_game_response()
        assert len(d["legal_moves"]) > 0

    def test_seed_produces_deterministic_result(self):
        d1 = new_game_response(seed=7)
        d2 = new_game_response(seed=7)
        assert d1["display"]["players"][0]["influence"] == d2["display"]["players"][0]["influence"]

    def test_different_seeds_can_differ(self):
        d1 = new_game_response(seed=1)
        d2 = new_game_response(seed=99)
        # Not guaranteed to differ, but overwhelmingly likely with different seeds
        # Just check we get valid responses for both
        assert d1["display"]["phase"] == "action_selection"
        assert d2["display"]["phase"] == "action_selection"


# ---------------------------------------------------------------------------
# /api/move — basic actions
# ---------------------------------------------------------------------------

class TestMoveIncome:
    def test_income_adds_coin_to_human(self):
        d = new_game_response(seed=1)
        token = d["state_token"]
        d2 = move(token, "income")
        # Human goes from 2 to 3 coins
        assert d2["display"]["players"][0]["coins"] == 3

    def test_income_advances_past_human_turn(self):
        d = new_game_response(seed=1)
        d2 = move(d["state_token"], "income")
        # After human income + bot response, it's either human's turn again
        # or human must respond to bot's action
        assert d2["display"]["phase"] in (
            "action_selection", "await_challenge", "await_block", "await_block_challenge"
        )

    def test_response_has_all_keys(self):
        d = new_game_response()
        d2 = move(d["state_token"], "income")
        assert "display" in d2
        assert "state_token" in d2
        assert "legal_moves" in d2

    def test_state_token_changes_after_move(self):
        d = new_game_response(seed=5)
        d2 = move(d["state_token"], "income")
        assert d["state_token"] != d2["state_token"]

    def test_history_grows_after_move(self):
        d = new_game_response(seed=1)
        d2 = move(d["state_token"], "income")
        assert len(d2["display"]["history"]) > len(d["display"]["history"])

    def test_human_income_appears_in_log(self):
        d = new_game_response(seed=1)
        d2 = move(d["state_token"], "income")
        descs = [e["desc"] for e in d2["display"]["history"]]
        assert any("Income" in desc for desc in descs)


class TestMoveForeignAid:
    def test_foreign_aid_enters_await_block_or_resolves(self):
        d = new_game_response(seed=1)
        d2 = move(d["state_token"], "foreign_aid")
        # Either bot blocks (unlikely) or human gets to respond, or it resolves
        assert d2["display"]["phase"] in (
            "action_selection", "await_challenge", "await_block",
            "await_block_challenge", "lose_influence"
        )

    def test_foreign_aid_in_log(self):
        d = new_game_response(seed=1)
        d2 = move(d["state_token"], "foreign_aid")
        descs = [e["desc"] for e in d2["display"]["history"]]
        assert any("Foreign Aid" in desc for desc in descs)


class TestMoveCoup:
    def _state_with_coins(self, coins):
        d = new_game_response(seed=42)
        state = GameState.from_json(d["state_token"])
        state.players[0].coins = coins
        return state.to_json()

    def test_coup_deducts_7_coins(self):
        token = self._state_with_coins(7)
        d = move(token, "coup", target=1)
        assert d["display"]["players"][0]["coins"] == 0

    def test_coup_puts_bot_in_lose_influence(self):
        token = self._state_with_coins(7)
        d = move(token, "coup", target=1)
        # Bot must lose influence — bot loop handles it automatically
        # so we won't see lose_influence for the bot; check bot lost a card
        bot_influence = d["display"]["players"][1]["influence"]
        assert len(bot_influence) == 1  # started with 2, lost 1

    def test_coup_not_available_below_7_coins(self):
        d = new_game_response(seed=1)
        # Human starts with 2 coins — coup should not be in legal moves
        assert not any(m["move_type"] == "coup" for m in d["legal_moves"])

    def test_coup_mandatory_at_10_coins(self):
        d = new_game_response(seed=42)
        state = GameState.from_json(d["state_token"])
        state.players[0].coins = 10
        token = state.to_json()
        # Manually get legal moves by checking what the server says for a move request
        # We need to ask the server what's legal — post a dummy move won't work.
        # Instead, import legal_actions directly and verify.
        from engine.coup import legal_actions
        state2 = GameState.from_json(token)
        moves = legal_actions(state2)
        assert all(m.move_type.value == "coup" for m in moves)


class TestMoveTax:
    def test_tax_appears_in_log(self):
        d = new_game_response(seed=1)
        d2 = move(d["state_token"], "tax")
        descs = [e["desc"] for e in d2["display"]["history"]]
        assert any("Tax" in desc or "Duke" in desc for desc in descs)

    def test_after_tax_human_may_need_to_respond_or_coins_increase(self):
        d = new_game_response(seed=1)
        d2 = move(d["state_token"], "tax")
        # Either tax resolved (+3 coins) or bot challenged (lose_influence for human)
        # Just check valid state
        assert d2["display"]["phase"] in (
            "action_selection", "await_challenge", "await_block",
            "await_block_challenge", "lose_influence", "game_over"
        )


# ---------------------------------------------------------------------------
# Multi-step flows (challenge / block)
# ---------------------------------------------------------------------------

class TestChallengeFlow:
    def _get_state_awaiting_challenge(self):
        """Return a state_token where it's human's turn to challenge the bot's action."""
        for seed in range(100):
            d = new_game_response(seed=seed)
            d2 = move(d["state_token"], "income")
            if d2["display"]["phase"] == "await_challenge" and \
               d2["display"]["current_decision_player"] == 0:
                return d2["state_token"]
        pytest.skip("Could not find a seed where bot claims a challengeable action")

    def test_pass_on_challenge_is_valid(self):
        token = self._get_state_awaiting_challenge()
        d = move(token, "pass")
        assert d["display"]["phase"] in (
            "action_selection", "await_block", "await_block_challenge",
            "lose_influence", "exchange_selection", "game_over"
        )

    def test_challenge_is_valid(self):
        token = self._get_state_awaiting_challenge()
        d = move(token, "challenge")
        # Challenge resolves — either someone loses influence or game is over
        assert d["display"]["phase"] in (
            "action_selection", "lose_influence", "await_block",
            "await_block_challenge", "game_over"
        )


class TestBlockFlow:
    def _get_state_awaiting_block(self):
        """Return a state_token where human can block bot's action."""
        for seed in range(200):
            d = new_game_response(seed=seed)
            d2 = move(d["state_token"], "income")
            if d2["display"]["phase"] == "await_block" and \
               d2["display"]["current_decision_player"] == 0:
                return d2["state_token"], d2["legal_moves"]
        pytest.skip("Could not find seed where human can block bot")

    def test_pass_on_block_is_valid(self):
        token, _ = self._get_state_awaiting_block()
        d = move(token, "pass")
        assert d["display"]["phase"] in (
            "action_selection", "await_challenge", "await_block_challenge",
            "lose_influence", "game_over"
        )

    def test_block_move_is_legal(self):
        _, legal = self._get_state_awaiting_block()
        assert any(m["move_type"] == "block" for m in legal)


# ---------------------------------------------------------------------------
# Lose influence (human forced to reveal)
# ---------------------------------------------------------------------------

class TestLoseInfluence:
    def _get_state_awaiting_reveal(self):
        """Force a state where human must reveal (give human a Coup target)."""
        for seed in range(200):
            d = new_game_response(seed=seed)
            state = GameState.from_json(d["state_token"])
            # Give bot enough coins to coup and make it the bot's turn
            # Easiest: set bot coins=7 and make a new state where bot acts first
            state.players[1].coins = 7
            state.active_player = 1
            state.current_decision_player = 1
            state.phase = Phase.ACTION_SELECTION
            from server.main import run_bot_turns, build_response
            state2 = run_bot_turns(state)
            resp = build_response(state2)
            if resp["display"]["phase"] == "lose_influence" and \
               resp["display"]["current_decision_player"] == 0:
                return resp["state_token"], resp["legal_moves"]
        pytest.skip("Could not construct lose_influence state for human")

    def test_reveal_moves_are_card_indexed(self):
        token, legal = self._get_state_awaiting_reveal()
        assert all(m["move_type"] == "reveal" for m in legal)
        assert all(m["card_index"] is not None for m in legal)

    def test_revealing_removes_card_from_influence(self):
        token, legal = self._get_state_awaiting_reveal()
        before = len(GameState.from_json(token).players[0].influence)
        d = move(token, "reveal", card_index=legal[0]["card_index"])
        after = len(d["display"]["players"][0]["influence"])
        assert after == before - 1

    def test_game_over_after_last_card_revealed(self):
        token, legal = self._get_state_awaiting_reveal()
        state = GameState.from_json(token)
        # If human has 1 card, revealing it ends the game
        if len(state.players[0].influence) == 1:
            d = move(token, "reveal", card_index=0)
            assert d["display"]["phase"] == "game_over"
        else:
            pytest.skip("Human has 2 cards in this state")


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------

class TestMasking:
    def test_bot_cards_always_hidden_during_game(self):
        d = new_game_response(seed=3)
        token = d["state_token"]
        # Play several moves and verify bot influence is always masked
        for _ in range(5):
            if not d["legal_moves"]:
                break
            first_move = d["legal_moves"][0]
            d = move(token, first_move["move_type"],
                     target=first_move.get("target"),
                     card_index=first_move.get("card_index"),
                     keep_indices=first_move.get("keep_indices"))
            token = d["state_token"]
            for card in d["display"]["players"][1]["influence"]:
                assert card == "hidden", f"Bot card leaked: {card}"

    def test_deck_never_in_display(self):
        d = new_game_response(seed=5)
        assert "deck" not in d["display"]
        d2 = move(d["state_token"], "income")
        assert "deck" not in d2["display"]

    def test_human_cards_visible(self):
        d = new_game_response(seed=9)
        for card in d["display"]["players"][0]["influence"]:
            assert card != "hidden"

    def test_state_token_contains_real_bot_cards(self):
        d = new_game_response(seed=2)
        real_state = GameState.from_json(d["state_token"])
        for card in real_state.players[1].influence:
            assert card != "hidden"
            assert hasattr(card, 'value')  # it's a Card enum


# ---------------------------------------------------------------------------
# Game over
# ---------------------------------------------------------------------------

class TestGameOver:
    def _play_to_end(self, seed=0, max_moves=200):
        d = new_game_response(seed=seed)
        for _ in range(max_moves):
            if d["display"]["phase"] == "game_over":
                return d
            if not d["legal_moves"]:
                break
            first = d["legal_moves"][0]
            d = move(d["state_token"], first["move_type"],
                     target=first.get("target"),
                     card_index=first.get("card_index"),
                     keep_indices=first.get("keep_indices"))
        return d

    def test_game_eventually_ends(self):
        d = self._play_to_end(seed=7)
        assert d["display"]["phase"] == "game_over"

    def test_no_legal_moves_when_game_over(self):
        d = self._play_to_end(seed=7)
        assert d["legal_moves"] == []

    def test_exactly_one_player_has_influence_at_game_over(self):
        d = self._play_to_end(seed=7)
        alive = [p for p in d["display"]["players"] if len(p["influence"]) > 0]
        assert len(alive) == 1
