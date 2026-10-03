from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS tanks (
    tank_id INTEGER PRIMARY KEY,
    nation TEXT, type TEXT, role TEXT, tier INTEGER,
    name TEXT, en_name TEXT, short_name TEXT, en_short_name TEXT, tech_name TEXT,
    premium INTEGER NOT NULL DEFAULT 0 CHECK (premium IN (0, 1)),
    collector_vehicle INTEGER NOT NULL DEFAULT 0 CHECK (collector_vehicle IN (0, 1)),
    tank_icon TEXT,
    rank INTEGER, rank_delta INTEGER NOT NULL DEFAULT 0,
    mastery_65 INTEGER, mastery_85 INTEGER, mastery_95 INTEGER,
    official_present INTEGER NOT NULL DEFAULT 0 CHECK (official_present IN (0, 1)),
    tankgg_present INTEGER NOT NULL DEFAULT 0 CHECK (tankgg_present IN (0, 1)),
    listed INTEGER NOT NULL DEFAULT 0 CHECK (listed IN (0, 1)),
    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_day TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'partial', 'failed')),
    source TEXT NOT NULL DEFAULT 'live'
);
CREATE INDEX IF NOT EXISTS idx_collection_runs_day_status
    ON collection_runs (snapshot_day, status, finished_at DESC);
CREATE TABLE IF NOT EXISTS mastery_observations (
    run_id INTEGER NOT NULL REFERENCES collection_runs(run_id) ON DELETE CASCADE,
    tank_id INTEGER NOT NULL REFERENCES tanks(tank_id),
    mastery_65 INTEGER, mastery_85 INTEGER, mastery_95 INTEGER,
    rank INTEGER, rank_delta INTEGER, ace INTEGER, gather_date INTEGER,
    PRIMARY KEY (run_id, tank_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_observations_tank_run
    ON mastery_observations (tank_id, run_id);
CREATE INDEX IF NOT EXISTS idx_observations_run_mastery95
    ON mastery_observations (run_id, mastery_95 DESC, tank_id);
CREATE TABLE IF NOT EXISTS migration_state (
    name TEXT PRIMARY KEY, value TEXT NOT NULL
);
"""

def database_path() -> Path:
    configured = current_app.config.get("DATABASE_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent / "wot.sqlite3"

def connect(path: Optional[str | Path] = None) -> sqlite3.Connection:
    db_path = Path(path) if path is not None else database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect()
    return g.db

def close_db(_error=None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()

def init_database(path: Optional[str | Path] = None) -> None:
    connection = connect(path)
    try:
        connection.executescript(SCHEMA)
    finally:
        connection.close()

def init_app(app) -> None:
    with app.app_context():
        init_database()
    app.teardown_appcontext(close_db)
