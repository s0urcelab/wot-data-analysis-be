"""把 MongoDB 的 all_tanks、history_mastery 导入 SQLite。

用法：
  MONGO_URL=mongodb://127.0.0.1:27017/wot SQLITE_PATH=data/wot.db python scripts/migrate_mongo.py

不迁移 comments 与 tanksgg_list。可重复执行，同一主键会被覆盖为 Mongo 中的当前值。
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from wotapp.database import init_db, session_scope  # noqa: E402
from wotapp.migrate import import_documents  # noqa: E402


def main() -> None:
    url = os.environ.get("MONGO_URL")
    if not url:
        raise SystemExit("请设置 MONGO_URL，例如 mongodb://127.0.0.1:27017/wot")
    init_db()
    client = MongoClient(url)
    db_name = os.environ.get("MONGO_DB")
    db = client[db_name] if db_name else client.get_default_database()
    tanks = list(db["all_tanks"].find())
    history = list(db["history_mastery"].find())
    with session_scope() as session:
        import_documents(session, tanks, history)
    print(f"已导入 vehicles={len(tanks)} snapshots={len(history)} -> {os.environ.get('SQLITE_PATH', 'data/wot.db')}")


if __name__ == "__main__":
    main()
