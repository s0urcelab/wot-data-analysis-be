"""把 MongoDB 的 all_tanks、history_mastery 导入 SQLite。

用法：
  MONGO_URL=mongodb://127.0.0.1:27017/wot SQLITE_PATH=data/wot.db python scripts/migrate_mongo.py

不迁移 comments 与 tanksgg_list。可重复执行，同一主键会被覆盖为 Mongo 中的当前值。
历史记录按批读取并提交，避免把全表载入内存后逐行查询。
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from wotapp.database import get_engine, init_db, session_scope  # noqa: E402
from wotapp.migrate import import_documents  # noqa: E402
from wotapp.models import MasterySnapshot, Vehicle  # noqa: E402

BATCH = 50000
HISTORY_FIELDS = {
    "tank_id": 1,
    "insert_date": 1,
    "gather_date": 1,
    "update_date": 1,
    "mastery_65": 1,
    "mastery_85": 1,
    "mastery_95": 1,
    "ace": 1,
}


def _tune_sqlite() -> None:
    """在事务开始前放宽同步，批量写入会快很多。"""
    raw = get_engine().raw_connection()
    try:
        raw.rollback()
        cursor = raw.cursor()
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.execute("PRAGMA cache_size=-262144")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()
    finally:
        raw.close()


def main() -> None:
    url = os.environ.get("MONGO_URL")
    if not url:
        raise SystemExit("请设置 MONGO_URL，例如 mongodb://127.0.0.1:27017/wot")
    init_db()
    _tune_sqlite()
    client = MongoClient(url)
    started = time.perf_counter()
    try:
        db_name = os.environ.get("MONGO_DB")
        db = client[db_name] if db_name else client.get_default_database()
        tanks = list(db["all_tanks"].find())
        expected = db["history_mastery"].estimated_document_count()
        cursor = db["history_mastery"].find(
            {},
            HISTORY_FIELDS,
            batch_size=10000,
            no_cursor_timeout=True,
        )
        print(f"开始导入 vehicles={len(tanks)} snapshots≈{expected}", flush=True)
        done = 0
        tanks_done = False
        batch: list[dict] = []
        try:
            with session_scope() as session:
                def flush_batch() -> None:
                    nonlocal done, tanks_done
                    import_documents(session, [] if tanks_done else tanks, batch)
                    tanks_done = True
                    session.commit()
                    done += len(batch)
                    elapsed = time.perf_counter() - started
                    print(f"已处理 snapshots={done}/{expected}（{elapsed:.0f}s）", flush=True)
                    batch.clear()

                for doc in cursor:
                    batch.append(doc)
                    if len(batch) >= BATCH:
                        flush_batch()
                if batch or not tanks_done:
                    flush_batch()
        finally:
            cursor.close()
    finally:
        client.close()

    with session_scope() as session:
        vehicle_count = session.scalar(select(func.count()).select_from(Vehicle))
        snapshot_count = session.scalar(select(func.count()).select_from(MasterySnapshot))
    path = os.environ.get("SQLITE_PATH", "data/wot.db")
    elapsed = time.perf_counter() - started
    print(
        f"已导入 mongo vehicles={len(tanks)} snapshots={done}，"
        f"SQLite vehicles={vehicle_count} snapshots={snapshot_count} -> {path}（{elapsed:.0f}s）"
    )


if __name__ == "__main__":
    main()
