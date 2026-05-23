"""
SQLite-backed game storage.
Database is created at coup_games.db in the working directory.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path("coup_games.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS games (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT    NOT NULL,
    winner     INTEGER NOT NULL,
    turns      INTEGER NOT NULL,
    history    TEXT    NOT NULL,
    snapshots  TEXT    NOT NULL,
    moves      TEXT    NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(_CREATE)


def save_game(
    winner: int,
    history: List[Dict[str, Any]],
    snapshots: List[str],
    moves: List[Dict[str, Any]],
) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    turns      = len(moves)
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO games (created_at, winner, turns, history, snapshots, moves) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                created_at,
                winner,
                turns,
                json.dumps(history),
                json.dumps(snapshots),
                json.dumps(moves),
            ),
        )
        return cur.lastrowid


def list_games() -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, winner, turns FROM games ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_game(game_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM games WHERE id = ?", (game_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["history"]   = json.loads(d["history"])
    d["snapshots"] = json.loads(d["snapshots"])
    d["moves"]     = json.loads(d["moves"])
    return d
