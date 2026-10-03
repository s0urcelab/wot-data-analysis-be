from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from pymongo import MongoClient

from db import init_database, connect

SHANGHAI = ZoneInfo("Asia/Shanghai")
MIGRATION_NAME = "mongo_to_sqlite_v1"
TANK_COLUMNS = (
    "tank_id", "nation", "type", "role", "tier", "name", "en_name", "short_name", "en_short_name",
    "tech_name", "premium", "collector_vehicle", "tank_icon", "rank", "rank_delta", "mastery_65",
    "mastery_85", "mastery_95", "official_present", "tankgg_present", "listed", "created_at", "updated_at",
)


def epoch(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value / 1000) if value > 10_000_000_000 else int(value)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return default
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    return default


def snapshot_day(value: Any) -> str:
    timestamp = epoch(value, 0)
    return datetime.fromtimestamp(timestamp, timezone.utc).astimezone(SHANGHAI).date().isoformat()


def integer(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _value(primary: dict, fallback: dict, key: str):
    value = primary.get(key)
    return value if value is not None and value != "" else fallback.get(key)


def import_tanks(connection, database, now: int) -> dict:
    catalog = {}
    for document in database["tanksgg_list"].find({}):
        tank_id = integer(document.get("_id"))
        if tank_id is not None:
            catalog[tank_id] = {"tankgg_present": 1, "gg": document}
    for document in database["all_tanks"].find({}):
        tank_id = integer(document.get("_id"))
        if tank_id is None:
            continue
        entry = catalog.setdefault(tank_id, {"tankgg_present": 0, "gg": {}})
        entry["official_present"] = 1
        entry["listed"] = 1
        entry["main"] = document

    rows = []
    for tank_id, entry in catalog.items():
        main = entry.get("main", {})
        gg = entry.get("gg", {})
        created = min(filter(None, [epoch(main.get("insert_date")), epoch(gg.get("insert_date"))]), default=now)
        updated = max(filter(None, [epoch(main.get("update_date")), epoch(main.get("insert_date")), epoch(gg.get("insert_date"))]), default=created)
        row = {
            "tank_id": tank_id,
            "nation": _value(main, gg, "nation"),
            "type": _value(main, gg, "type"),
            "role": _value(main, gg, "role"),
            "tier": integer(_value(main, gg, "tier")),
            "name": _value(main, gg, "name"),
            "en_name": _value(main, gg, "en_name"),
            "short_name": _value(main, gg, "short_name"),
            "en_short_name": _value(main, gg, "en_short_name"),
            "tech_name": _value(main, gg, "tech_name"),
            "premium": integer(main.get("premium"), 0) or 0,
            "collector_vehicle": integer(main.get("collector_vehicle"), 0) or 0,
            "tank_icon": main.get("tank_icon"),
            "rank": integer(main.get("rank")),
            "rank_delta": integer(main.get("rank_delta"), 0) or 0,
            "mastery_65": integer(main.get("mastery_65")),
            "mastery_85": integer(main.get("mastery_85")),
            "mastery_95": integer(main.get("mastery_95")),
            "official_present": entry.get("official_present", 0),
            "tankgg_present": entry.get("tankgg_present", 0),
            "listed": entry.get("listed", 0),
            "created_at": created,
            "updated_at": updated,
        }
        rows.append(tuple(row.get(column) for column in TANK_COLUMNS))
    marks = ",".join("?" for _ in TANK_COLUMNS)
    connection.executemany(
        f"INSERT INTO tanks ({','.join(TANK_COLUMNS)}) VALUES ({marks})", rows
    )
    return {"tanks": len(rows)}


def _ensure_tank(connection, tank_id: int, timestamp: int) -> None:
    connection.execute(
        """INSERT OR IGNORE INTO tanks(tank_id,premium,collector_vehicle,listed,created_at,updated_at)
           VALUES(?,0,0,1,?,?)""", (tank_id, timestamp, timestamp)
    )
    connection.execute("UPDATE tanks SET listed=1 WHERE tank_id=?", (tank_id,))


def import_history(connection, database, now: int) -> dict:
    day_runs = {}
    day_bounds = {}
    raw_records = 0
    fields = ("mastery_65", "mastery_85", "mastery_95", "ace")
    statement = """INSERT INTO mastery_observations
        (run_id,tank_id,mastery_65,mastery_85,mastery_95,ace,gather_date)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(run_id,tank_id) DO UPDATE SET
          mastery_65=COALESCE(excluded.mastery_65,mastery_observations.mastery_65),
          mastery_85=COALESCE(excluded.mastery_85,mastery_observations.mastery_85),
          mastery_95=COALESCE(excluded.mastery_95,mastery_observations.mastery_95),
          ace=COALESCE(excluded.ace,mastery_observations.ace),
          gather_date=COALESCE(excluded.gather_date,mastery_observations.gather_date)"""
    batch = []
    cursor = database["history_mastery"].find({}).sort("_id", 1).batch_size(5000)
    for document in cursor:
        raw_records += 1
        mongo_time = document.get("insert_date") or document.get("gather_date")
        stamp = epoch(mongo_time, now) or now
        day = snapshot_day(mongo_time)
        tank_id = integer(document.get("tank_id"))
        if tank_id is None:
            continue
        if day not in day_runs:
            start = stamp
            run_cursor = connection.execute(
                "INSERT INTO collection_runs(snapshot_day,started_at,finished_at,status,source) VALUES(?,?,?,?,?)",
                (day, start, start, "complete", "legacy-mongo"),
            )
            day_runs[day] = run_cursor.lastrowid
            day_bounds[day] = [stamp, stamp]
        day_bounds[day][0] = min(day_bounds[day][0], stamp)
        day_bounds[day][1] = max(day_bounds[day][1], stamp)
        _ensure_tank(connection, tank_id, stamp)
        batch.append((
            day_runs[day], tank_id,
            integer(document.get(fields[0])), integer(document.get(fields[1])),
            integer(document.get(fields[2])), integer(document.get("ace")),
            epoch(document.get("gather_date")),
        ))
        if len(batch) >= 5000:
            connection.executemany(statement, batch)
            batch.clear()
    if batch:
        connection.executemany(statement, batch)
    for day, (started, finished) in day_bounds.items():
        connection.execute(
            "UPDATE collection_runs SET started_at=?,finished_at=? WHERE run_id=?",
            (started, finished, day_runs[day]),
        )
    imported_rows = connection.execute("SELECT COUNT(*) FROM mastery_observations").fetchone()[0]
    return {"history_documents": raw_records, "snapshot_days": len(day_runs),
            "daily_observations": imported_rows, "merged_history_rows": raw_records - imported_rows}


def migrate(mongo_uri: str, database_name: str, sqlite_path: str, replace: bool = False) -> dict:
    mongo = MongoClient(mongo_uri, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000)
    database = mongo[database_name]
    database.command("ping")
    init_database(sqlite_path)
    connection = connect(sqlite_path)
    try:
        marker = connection.execute("SELECT value FROM migration_state WHERE name=?", (MIGRATION_NAME,)).fetchone()
        existing = connection.execute("SELECT COUNT(*) FROM mastery_observations").fetchone()[0]
        if (marker or existing) and not replace:
            raise RuntimeError("SQLite database already contains an import; pass --replace only for a deliberate fresh migration")
        connection.execute("BEGIN IMMEDIATE")
        if replace:
            connection.execute("DELETE FROM mastery_observations")
            connection.execute("DELETE FROM collection_runs")
            connection.execute("DELETE FROM tanks")
            connection.execute("DELETE FROM migration_state WHERE name=?", (MIGRATION_NAME,))
        now = int(datetime.now(timezone.utc).timestamp())
        tank_counts = import_tanks(connection, database, now)
        history_counts = import_history(connection, database, now)
        report = {**tank_counts, **history_counts}
        connection.execute(
            "INSERT INTO migration_state(name,value) VALUES(?,?)",
            (MIGRATION_NAME, datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(f"SQLite integrity check failed: integrity={integrity}, fk_errors={len(fk_errors)}")
        return report
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
        mongo.close()


def main():
    parser = argparse.ArgumentParser(description="One-time migration from the existing MongoDB database to SQLite")
    parser.add_argument("--mongo-uri", default=os.environ.get("MONGODB_URI"), help="Mongo connection URI; defaults to MONGODB_URI")
    parser.add_argument("--mongo-db", default=os.environ.get("MONGODB_DATABASE", "wot"))
    parser.add_argument("--sqlite", default=os.environ.get("DATABASE_PATH", str(Path(__file__).resolve().parent / "wot.sqlite3")))
    parser.add_argument("--replace", action="store_true", help="replace imported SQLite data; this deletes current SQLite app data")
    args = parser.parse_args()
    if not args.mongo_uri:
        parser.error("--mongo-uri or MONGODB_URI is required")
    report = migrate(args.mongo_uri, args.mongo_db, args.sqlite, args.replace)
    print("Migration complete")
    for key, value in report.items():
        print(f"{key}: {value}")
    print(f"sqlite: {Path(args.sqlite).resolve()}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Migration failed: {error}", file=sys.stderr)
        raise

