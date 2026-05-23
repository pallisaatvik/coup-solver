"""
FastAPI server for the Coup 1v1 web game.

Stateless design: the client holds the full game state as an opaque
state_token string and sends it back on every move. The server never
stores sessions.
"""

import json
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.coup import (
    Card, GameState, Move, MoveType, Phase,
    apply_action, is_terminal, legal_actions, new_game,
)
from server.bot import bot_move
from server import storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    yield

app = FastAPI(lifespan=lifespan)
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


class SaveGameRequest(BaseModel):
    snapshots: List[str]       # state_token strings; [0] = initial state
    moves:     List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mask_state(state: GameState) -> Dict[str, Any]:
    """Return a display-safe dict: bot's face-down cards hidden, deck removed."""
    d = state.to_dict()
    del d["deck"]
    d["players"][1]["influence"] = ["hidden"] * len(state.players[1].influence)
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
# Game endpoints
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


# ---------------------------------------------------------------------------
# Storage endpoints
# ---------------------------------------------------------------------------

@app.post("/api/game/save")
def api_save_game(req: SaveGameRequest):
    if not req.snapshots:
        raise HTTPException(status_code=400, detail="snapshots must not be empty")
    final_state = GameState.from_json(req.snapshots[-1])
    if not is_terminal(final_state):
        raise HTTPException(status_code=400, detail="game is not over yet")
    winner  = 0 if final_state.players[0].is_alive else 1
    history = [h.to_dict() for h in final_state.history]
    game_id = storage.save_game(winner, history, req.snapshots, req.moves)
    return {"id": game_id}


@app.get("/api/games")
def api_list_games():
    return storage.list_games()


@app.get("/api/game/{game_id}")
def api_get_game(game_id: int):
    record = storage.get_game(game_id)
    if record is None:
        raise HTTPException(status_code=404, detail="game not found")
    return record
