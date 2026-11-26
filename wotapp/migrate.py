import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from wotapp.models import MasterySnapshot, Vehicle
from wotapp.util import as_int

logger = logging.getLogger("wotapp")


def as_utc_naive(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


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


def ensure_vehicle(session: Session, vehicle_id: int) -> None:
    if session.get(Vehicle, vehicle_id) is None:
        session.add(Vehicle(
            id=vehicle_id,
            is_premium=0,
            is_collector=0,
            rank_delta=0,
        ))
        session.flush()


def upsert_snapshot_from_mongo(session: Session, doc: dict) -> None:
    vehicle_id = as_int(doc.get("tank_id"))
    captured_at = as_utc_naive(doc.get("insert_date") or doc.get("gather_date") or doc.get("update_date"))
    if vehicle_id is None or captured_at is None:
        logger.warning("跳过无法定位的历史记录 %s", doc.get("_id"))
        return
    ensure_vehicle(session, vehicle_id)
    row = session.scalar(
        select(MasterySnapshot).where(
            MasterySnapshot.vehicle_id == vehicle_id,
            MasterySnapshot.captured_at == captured_at,
        )
    )
    if row is None:
        row = MasterySnapshot(vehicle_id=vehicle_id, captured_at=captured_at)
        session.add(row)
        session.flush()
    # 只覆盖文档里真正有的字段，避免同一时点的残缺记录把已写入的分位清掉
    for attr, key in (
        ("mastery_65", "mastery_65"),
        ("mastery_85", "mastery_85"),
        ("mastery_95", "mastery_95"),
        ("ace", "ace"),
    ):
        if key in doc:
            setattr(row, attr, as_int(doc.get(key)))
    if "gather_date" in doc:
        row.gathered_at = as_utc_naive(doc.get("gather_date"))
    if "update_date" in doc:
        row.updated_at = as_utc_naive(doc.get("update_date"))


def import_documents(session: Session, tanks: list[dict], history: list[dict]) -> None:
    for doc in tanks:
        upsert_vehicle_from_mongo(session, doc)
    session.flush()
    for doc in history:
        upsert_snapshot_from_mongo(session, doc)
