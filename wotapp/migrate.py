import logging
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from wotapp.models import MasterySnapshot, Vehicle
from wotapp.util import as_int

logger = logging.getLogger("wotapp")

# 与 SQLAlchemy SQLite DATETIME 的存储格式一致，保证重复导入时能对上同一行。
_DT_FORMAT = (
    "{year:04d}-{month:02d}-{day:02d} "
    "{hour:02d}:{minute:02d}:{second:02d}.{microsecond:06d}"
)


def as_utc_naive(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _sqlite_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _DT_FORMAT.format(
        year=value.year,
        month=value.month,
        day=value.day,
        hour=value.hour,
        minute=value.minute,
        second=value.second,
        microsecond=value.microsecond,
    )


def upsert_vehicle_from_mongo(session: Session, doc: dict) -> None:
    vid = as_int(doc.get("_id"))
    if vid is None:
        logger.warning("跳过缺少 _id 的车辆文档")
        return
    vehicle = session.get(Vehicle, vid)
    if vehicle is None:
        vehicle = Vehicle(id=vid, is_premium=0, is_collector=0, rank_delta=0)
        session.add(vehicle)

    vehicle.nation = doc.get("nation")
    vehicle.vehicle_type = doc.get("type")
    vehicle.role = doc.get("role")
    vehicle.tier = as_int(doc.get("tier"))
    vehicle.name = doc.get("name")
    vehicle.en_name = doc.get("en_name")
    vehicle.short_name = doc.get("short_name")
    vehicle.en_short_name = doc.get("en_short_name")
    vehicle.tech_name = doc.get("tech_name")
    premium = doc.get("premium")
    vehicle.is_premium = int(premium) if premium is not None else 0
    collector = doc.get("collector_vehicle")
    vehicle.is_collector = int(collector) if collector is not None else 0
    vehicle.icon_url = doc.get("tank_icon")
    vehicle.rank = as_int(doc.get("rank"))
    vehicle.rank_delta = as_int(doc.get("rank_delta")) or 0
    vehicle.mastery_65 = as_int(doc.get("mastery_65"))
    vehicle.mastery_85 = as_int(doc.get("mastery_85"))
    vehicle.mastery_95 = as_int(doc.get("mastery_95"))
    vehicle.mastery_updated_at = as_utc_naive(doc.get("update_date"))
    vehicle.created_at = as_utc_naive(doc.get("insert_date"))
    vehicle.updated_at = as_utc_naive(doc.get("update_date") or doc.get("insert_date"))


def _blank_snapshot(vehicle_id: int, captured_at: str) -> dict:
    return {
        "vehicle_id": vehicle_id,
        "captured_at": captured_at,
        "mastery_65": None,
        "mastery_85": None,
        "mastery_95": None,
        "ace": None,
        "gathered_at": None,
        "updated_at": None,
        "has_65": 0,
        "has_85": 0,
        "has_95": 0,
        "has_ace": 0,
        "has_gather": 0,
        "has_update": 0,
    }


def _apply_snapshot_fields(row: dict, doc: dict) -> None:
    # 只覆盖文档里真正有的字段，避免同一时点的残缺记录把已写入的分位清掉。
    if "mastery_65" in doc:
        row["mastery_65"] = as_int(doc.get("mastery_65"))
        row["has_65"] = 1
    if "mastery_85" in doc:
        row["mastery_85"] = as_int(doc.get("mastery_85"))
        row["has_85"] = 1
    if "mastery_95" in doc:
        row["mastery_95"] = as_int(doc.get("mastery_95"))
        row["has_95"] = 1
    if "ace" in doc:
        row["ace"] = as_int(doc.get("ace"))
        row["has_ace"] = 1
    if "gather_date" in doc:
        row["gathered_at"] = _sqlite_dt(as_utc_naive(doc.get("gather_date")))
        row["has_gather"] = 1
    if "update_date" in doc:
        row["updated_at"] = _sqlite_dt(as_utc_naive(doc.get("update_date")))
        row["has_update"] = 1


def _ensure_vehicles(session: Session, vehicle_ids: set[int]) -> None:
    if not vehicle_ids:
        return
    existing: set[int] = set()
    ids = list(vehicle_ids)
    for offset in range(0, len(ids), 500):
        chunk = ids[offset:offset + 500]
        existing.update(session.scalars(select(Vehicle.id).where(Vehicle.id.in_(chunk))))
    missing = vehicle_ids - existing
    if not missing:
        return
    session.execute(
        insert(Vehicle),
        [
            {"id": vid, "is_premium": 0, "is_collector": 0, "rank_delta": 0}
            for vid in missing
        ],
    )


def _write_snapshots(session: Session, rows: list[dict]) -> None:
    conn = session.connection()
    conn.exec_driver_sql("DROP TABLE IF EXISTS _incoming_snap")
    conn.exec_driver_sql(
        """
        CREATE TEMP TABLE _incoming_snap (
            vehicle_id INTEGER NOT NULL,
            captured_at DATETIME NOT NULL,
            mastery_65 INTEGER,
            mastery_85 INTEGER,
            mastery_95 INTEGER,
            ace INTEGER,
            gathered_at DATETIME,
            updated_at DATETIME,
            has_65 INTEGER NOT NULL,
            has_85 INTEGER NOT NULL,
            has_95 INTEGER NOT NULL,
            has_ace INTEGER NOT NULL,
            has_gather INTEGER NOT NULL,
            has_update INTEGER NOT NULL
        )
        """
    )
    raw = conn.connection.dbapi_connection
    cursor = raw.cursor()
    try:
        cursor.executemany(
            """
            INSERT INTO _incoming_snap (
                vehicle_id, captured_at, mastery_65, mastery_85, mastery_95, ace,
                gathered_at, updated_at, has_65, has_85, has_95, has_ace, has_gather, has_update
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["vehicle_id"],
                    row["captured_at"],
                    row["mastery_65"],
                    row["mastery_85"],
                    row["mastery_95"],
                    row["ace"],
                    row["gathered_at"],
                    row["updated_at"],
                    row["has_65"],
                    row["has_85"],
                    row["has_95"],
                    row["has_ace"],
                    row["has_gather"],
                    row["has_update"],
                )
                for row in rows
            ],
        )
    finally:
        cursor.close()
    conn.exec_driver_sql(
        "CREATE INDEX ix_incoming_snap_key ON _incoming_snap (vehicle_id, captured_at)"
    )
    conn.exec_driver_sql(
        """
        UPDATE mastery_snapshots
        SET
            mastery_65 = CASE WHEN _incoming_snap.has_65 THEN _incoming_snap.mastery_65 ELSE mastery_snapshots.mastery_65 END,
            mastery_85 = CASE WHEN _incoming_snap.has_85 THEN _incoming_snap.mastery_85 ELSE mastery_snapshots.mastery_85 END,
            mastery_95 = CASE WHEN _incoming_snap.has_95 THEN _incoming_snap.mastery_95 ELSE mastery_snapshots.mastery_95 END,
            ace = CASE WHEN _incoming_snap.has_ace THEN _incoming_snap.ace ELSE mastery_snapshots.ace END,
            gathered_at = CASE WHEN _incoming_snap.has_gather THEN _incoming_snap.gathered_at ELSE mastery_snapshots.gathered_at END,
            updated_at = CASE WHEN _incoming_snap.has_update THEN _incoming_snap.updated_at ELSE mastery_snapshots.updated_at END
        FROM _incoming_snap
        WHERE mastery_snapshots.vehicle_id = _incoming_snap.vehicle_id
          AND mastery_snapshots.captured_at = _incoming_snap.captured_at
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO mastery_snapshots (
            vehicle_id, captured_at, mastery_65, mastery_85, mastery_95, ace, gathered_at, updated_at
        )
        SELECT
            vehicle_id,
            captured_at,
            CASE WHEN has_65 THEN mastery_65 END,
            CASE WHEN has_85 THEN mastery_85 END,
            CASE WHEN has_95 THEN mastery_95 END,
            CASE WHEN has_ace THEN ace END,
            CASE WHEN has_gather THEN gathered_at END,
            CASE WHEN has_update THEN updated_at END
        FROM _incoming_snap
        WHERE NOT EXISTS (
            SELECT 1 FROM mastery_snapshots
            WHERE mastery_snapshots.vehicle_id = _incoming_snap.vehicle_id
              AND mastery_snapshots.captured_at = _incoming_snap.captured_at
        )
        """
    )
    conn.exec_driver_sql("DROP TABLE IF EXISTS _incoming_snap")


def _import_snapshots(session: Session, history: Iterable[dict]) -> None:
    # 同一时点的多条记录按到达顺序合并，再整批写入。
    merged: dict[tuple[int, str], dict] = {}
    skipped = 0
    for doc in history:
        vehicle_id = as_int(doc.get("tank_id"))
        captured_at = _sqlite_dt(as_utc_naive(
            doc.get("insert_date") or doc.get("gather_date") or doc.get("update_date")
        ))
        if vehicle_id is None or captured_at is None:
            skipped += 1
            if skipped <= 5:
                logger.warning("跳过无法定位的历史记录 %s", doc.get("_id"))
            continue
        key = (vehicle_id, captured_at)
        row = merged.get(key)
        if row is None:
            row = _blank_snapshot(vehicle_id, captured_at)
            merged[key] = row
        _apply_snapshot_fields(row, doc)
    if skipped > 5:
        logger.warning("另有 %s 条历史记录因缺少坦克或时间被跳过", skipped - 5)
    if not merged:
        return
    _ensure_vehicles(session, {vehicle_id for vehicle_id, _ in merged})
    _write_snapshots(session, list(merged.values()))


def import_documents(session: Session, tanks: Iterable[dict], history: Iterable[dict]) -> None:
    for doc in tanks:
        upsert_vehicle_from_mongo(session, doc)
    session.flush()
    _import_snapshots(session, history)
