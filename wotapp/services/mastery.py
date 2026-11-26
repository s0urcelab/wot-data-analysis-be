import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from wotapp.database import session_scope
from wotapp.models import MasterySnapshot, Vehicle
from wotapp.util import as_int, hour_bucket_utc, utc_now

logger = logging.getLogger("wotapp")

RANK_URL = "https://tbox.wot.360.cn/rank/more"
PAGE_SIZE = 40
MAX_PAGES = 100


def _upsert_snapshot(
    session: Session,
    vehicle_id: int,
    captured_at: datetime,
    level: int,
    mastery: int | None,
) -> None:
    row = session.scalar(
        select(MasterySnapshot).where(
            MasterySnapshot.vehicle_id == vehicle_id,
            MasterySnapshot.captured_at == captured_at,
        )
    )
    if row is None:
        row = MasterySnapshot(vehicle_id=vehicle_id, captured_at=captured_at)
        session.add(row)
    setattr(row, f"mastery_{level}", mastery)
    row.updated_at = captured_at
    session.flush()


def apply_mastery_row(
    session: Session,
    item: dict,
    level: int,
    rank: int,
    captured_at: datetime,
) -> None:
    tank_id = as_int(item.get("tank_id"))
    if tank_id is None:
        return
    mastery = as_int(item.get("mastery"))
    now = utc_now()
    vehicle = session.get(Vehicle, tank_id)
    if vehicle is None:
        vehicle = Vehicle(
            id=tank_id,
            name=item.get("tank_name"),
            icon_url=item.get("tank_icon"),
            is_premium=0,
            is_collector=0,
            rank_delta=0,
            created_at=now,
            updated_at=now,
        )
        session.add(vehicle)
        session.flush()
    else:
        if item.get("tank_name"):
            vehicle.name = item["tank_name"]
        if item.get("tank_icon"):
            vehicle.icon_url = item["tank_icon"]
        vehicle.updated_at = now

    setattr(vehicle, f"mastery_{level}", mastery)
    vehicle.mastery_updated_at = captured_at
    if level == 95:
        old_rank = vehicle.rank
        vehicle.rank_delta = (old_rank - rank) if old_rank is not None else 0
        vehicle.rank = rank

    _upsert_snapshot(session, tank_id, captured_at, level, mastery)


def fetch_mastery(level: int, client: httpx.Client | None = None) -> None:
    own_client = client is None
    client = client or httpx.Client(timeout=30)
    captured_at = hour_bucket_utc()
    page = 1
    try:
        while page <= MAX_PAGES:
            try:
                res = client.post(
                    RANK_URL,
                    data={
                        "percentile": level,
                        "rank_type": "default",
                        "tier": "5,6,7,8,9,10,11",
                        "sort": "mastery",
                        "page": page,
                        "size": PAGE_SIZE,
                    },
                )
                res.raise_for_status()
                body = res.json()
            except Exception:
                logger.exception("拉取击杀环失败 percentile=%s page=%s", level, page)
                return

            if not isinstance(body, dict) or body.get("errno") != 0:
                logger.error("击杀环接口返回错误 percentile=%s page=%s body=%s", level, page, body)
                return

            ranking = (body.get("data") or {}).get("ranking") or []
            if not ranking:
                logger.info("击杀环 percentile=%s 在第 %s 页结束", level, page)
                return

            logger.info("击杀环 percentile=%s page=%s count=%s", level, page, len(ranking))
            with session_scope() as session:
                for idx, item in enumerate(ranking):
                    apply_mastery_row(
                        session,
                        item,
                        level,
                        rank=(page - 1) * PAGE_SIZE + idx + 1,
                        captured_at=captured_at,
                    )
            page += 1
        logger.error("击杀环 percentile=%s 超过 %s 页，已停止", level, MAX_PAGES)
    finally:
        if own_client:
            client.close()
