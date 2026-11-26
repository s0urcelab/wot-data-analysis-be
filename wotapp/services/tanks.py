import logging

import httpx
from sqlalchemy.orm import Session

from wotapp.models import Vehicle
from wotapp.util import as_int, retry, utc_now

logger = logging.getLogger("wotapp")

ASIA_URL = "https://worldoftanks.asia/wotpbe/tankopedia/api/vehicles/by_filters/"
CN_URL = "https://wotgame.cn/wotpbe/tankopedia/api/vehicles/by_filters/"

_IDENTITY_FIELDS = (
    "nation",
    "vehicle_type",
    "role",
    "tier",
    "name",
    "en_name",
    "short_name",
    "en_short_name",
    "tech_name",
    "is_premium",
    "is_collector",
)


def parse_official_data(payload: dict) -> dict[int, dict]:
    parameters = payload["parameters"]
    result = {}
    for item in payload["data"]:
        obj = dict(zip(parameters, item))
        vid = as_int(obj.get("vehicle_cd"))
        if vid is None:
            continue
        obj["_id"] = vid
        result[vid] = obj
    return result


def fetch_official_pair(client: httpx.Client) -> tuple[dict[int, dict], dict[int, dict]]:
    asia_res = client.post(
        ASIA_URL,
        data={"filter[premium]": "0,1", "filter[language]": "en"},
    )
    cn_res = client.post(
        CN_URL,
        data={"filter[premium]": "0,1", "filter[language]": "zh-cn"},
    )
    asia_res.raise_for_status()
    cn_res.raise_for_status()
    asia_body = asia_res.json()
    cn_body = cn_res.json()
    if asia_body.get("status") != "ok" or cn_body.get("status") != "ok":
        raise RuntimeError("拉取官方百科失败")
    return parse_official_data(asia_body["data"]), parse_official_data(cn_body["data"])


def identity_from_official(official: dict, asia_item: dict | None) -> dict:
    en_source = asia_item or official
    return {
        "nation": official.get("nation"),
        "vehicle_type": official.get("type"),
        "role": official.get("role"),
        "tier": as_int(official.get("tier")),
        "name": official.get("name"),
        "en_name": en_source.get("name"),
        "short_name": official.get("short_mark"),
        "en_short_name": en_source.get("short_mark"),
        "tech_name": official.get("tech_name") or en_source.get("tech_name"),
        "is_premium": int(official.get("premium") or 0),
        "is_collector": int(official.get("collector_vehicle") or 0),
    }


def apply_identity(vehicle: Vehicle, fields: dict) -> None:
    for key in _IDENTITY_FIELDS:
        value = fields.get(key)
        if value is None:
            continue
        setattr(vehicle, key, value)


def refresh_vehicles(session: Session, client: httpx.Client | None = None) -> None:
    """用亚服 + 国服百科插入新车，并更新已有车的身份字段。不改击杀环、排名和图标。"""
    own_client = client is None
    client = client or httpx.Client(timeout=30)
    try:
        try:
            asia, cn = retry(lambda: fetch_official_pair(client), 3)
        except Exception:
            logger.exception("拉取官方百科失败，跳过身份字段刷新")
            return

        now = utc_now()
        ids = set(asia) | set(cn)
        for vid in ids:
            asia_item = asia.get(vid)
            official = cn.get(vid) or asia_item or {}
            fields = identity_from_official(official, asia_item)
            vehicle = session.get(Vehicle, vid)
            if vehicle is None:
                vehicle = Vehicle(
                    id=vid,
                    is_premium=0,
                    is_collector=0,
                    rank_delta=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(vehicle)
            apply_identity(vehicle, fields)
            vehicle.updated_at = now
        logger.info("官方百科已合并 %s 辆车", len(ids))
    finally:
        if own_client:
            client.close()
