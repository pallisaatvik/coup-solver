"""
FastAPI server for the Coup 1v1 web game.

Stateless design: the client holds the full game state as an opaque
state_token string and sends it back on every move. The server never
stores sessions.
"""

from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.coup import (
    Card, GameState, Move, MoveType, Phase,
    apply_action, is_terminal, legal_actions, new_game,
)
from server.bot import bot_move

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")


@app.get("/")
def index():
    return FileResponse("index.html")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class NewGameRequest(BaseModel):
    seed: Optional[int] = None


class MoveRequest(BaseModel):
    state_token: str
    move: Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mask_state(state: GameState) -> Dict[str, Any]:
    """Return a display-safe dict: bot's face-down cards hidden, deck removed."""
    d = state.to_dict()
    del d["deck"]

    # Hide bot's face-down influence
    d["players"][1]["influence"] = ["hidden"] * len(state.players[1].influence)

    # Hide drawn cards only when the bot is doing the exchange
    if (
        d.get("pending")
        and d["pending"].get("drawn_cards") is not None
        and state.current_decision_player == 1
    ):
        d["pending"]["drawn_cards"] = ["hidden"] * len(state.pending.drawn_cards)

    return d


def run_bot_turns(state: GameState) -> GameState:
    """Apply bot moves until it is the human's turn or the game ends."""
    while not is_terminal(state) and state.current_decision_player == 1:
        move = bot_move(state)
        state = apply_action(state, move)
    return state


def serialize_moves(moves) -> list:
    return [
        {
            "move_type":    m.move_type.value,
            "target":       m.target,
            "block_card":   m.block_card.value if m.block_card else None,
            "card_index":   m.card_index,
            "keep_indices": m.keep_indices,
        }
        for m in moves
    ]


def deserialize_move(d: Dict[str, Any]) -> Move:
    return Move(
        move_type=MoveType(d["move_type"]),
        target=d.get("target"),
        block_card=Card(d["block_card"]) if d.get("block_card") else None,
        card_index=d.get("card_index"),
        keep_indices=d.get("keep_indices"),
    )


def build_response(state: GameState) -> Dict[str, Any]:
    moves = []
    if not is_terminal(state) and state.current_decision_player == 0:
        moves = serialize_moves(legal_actions(state))
    return {
        "display":     mask_state(state),
        "state_token": state.to_json(),
        "legal_moves": moves,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/new")
def api_new(req: NewGameRequest):
    state = new_game(["You", "Bot"], seed=req.seed)
    state = run_bot_turns(state)
    return build_response(state)


@app.post("/api/move")
def api_move(req: MoveRequest):
    state = GameState.from_json(req.state_token)
    move  = deserialize_move(req.move)
    state = apply_action(state, move)
    state = run_bot_turns(state)
    return build_response(state)
