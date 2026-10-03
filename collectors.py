from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

import requests

from db import get_db

LOGGER = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
TANKGG_API = "https://tankgg.src.moe/api"
OFFICIAL_URLS = {
    "en": "https://worldoftanks.asia/wotpbe/tankopedia/api/vehicles/by_filters/",
    "zh-cn": "https://wotgame.cn/wotpbe/tankopedia/api/vehicles/by_filters/",
}
RANK_URL = "https://tbox.wot.360.cn/rank/more"
TYPE_MAP = {"light": "lightTank", "medium": "mediumTank", "heavy": "heavyTank", "td": "AT-SPG", "spg": "SPG"}


def now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "wot-data-analysis/2.0"})
    return session


def _request_json(session: requests.Session, url: str, **kwargs) -> dict:
    response = session.get(url, timeout=(8, 45), **kwargs)
    response.raise_for_status()
    return response.json()


def _official_rows(session: requests.Session, language: str) -> Dict[int, dict]:
    response = session.post(
        OFFICIAL_URLS[language],
        data={"filter[premium]": "0,1", "filter[language]": language},
        timeout=(8, 60),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "ok":
        raise RuntimeError("Official vehicle catalogue returned an unsuccessful response")
    data = payload.get("data") or {}
    parameters = data.get("parameters") or []
    rows = {}
    for values in data.get("data") or []:
        record = dict(zip(parameters, values))
        vehicle_id = record.get("vehicle_cd")
        if vehicle_id is not None:
            rows[int(vehicle_id)] = record
    return rows


def _tankgg_detail(session: requests.Session, version: str, slug: str) -> dict:
    return _request_json(session, f"{TANKGG_API}/{version}/tank/{slug}")


def _tankgg_rows(session: requests.Session) -> Dict[int, dict]:
    versions = _request_json(session, f"{TANKGG_API}/versions").get("data") or {}
    version = versions.get("current_wg")
    if not version:
        raise RuntimeError("tanks.gg did not provide its current game version")
    tanks = _request_json(session, f"{TANKGG_API}/list").get("data", {}).get("tanks") or []
    result: Dict[int, dict] = {}
    batch_size = 20
    for offset in range(0, len(tanks), batch_size):
        batch = tanks[offset:offset + batch_size]
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            responses = list(executor.map(lambda item: _tankgg_detail(session, version, item["slug"]), batch))
        for payload in responses:
            vehicle = (payload.get("data") or {}).get("tank") or {}
            tank_id = vehicle.get("tank_id")
            if tank_id is None:
                continue
            result[int(tank_id)] = {
                "nation": vehicle.get("nation"),
                "type": TYPE_MAP.get(vehicle.get("type"), "unknown"),
                "role": vehicle.get("vehicle_role"),
                "tier": vehicle.get("tier"),
                "name": vehicle.get("name"),
                "en_name": vehicle.get("name"),
                "short_name": vehicle.get("short_name"),
                "en_short_name": vehicle.get("short_name"),
                "tech_name": vehicle.get("id"),
            }
        if offset + batch_size < len(tanks):
            time.sleep(3)
    return result


def _prefer_new_value(current: dict, incoming: Mapping[str, Any]) -> dict:
    merged = dict(current)
    for key, value in incoming.items():
        if value is not None and value != "":
            merged[key] = value
    return merged


def refresh_catalog(connection=None) -> dict:
    connection = connection or get_db()
    session = http_session()
    en_rows = _official_rows(session, "en")
    zh_rows = _official_rows(session, "zh-cn")
    tankgg_rows = _tankgg_rows(session)
    vehicle_ids = set(en_rows) | set(zh_rows) | set(tankgg_rows)
    timestamp = now_epoch()
    written = 0
    for tank_id in vehicle_ids:
        en = en_rows.get(tank_id, {})
        zh = zh_rows.get(tank_id, en)
        gg = tankgg_rows.get(tank_id, {})
        record = {
            **gg,
            "nation": zh.get("nation") or en.get("nation") or gg.get("nation"),
            "type": zh.get("type") or en.get("type") or gg.get("type"),
            "role": zh.get("role") or en.get("role") or gg.get("role"),
            "tier": zh.get("tier") or en.get("tier") or gg.get("tier"),
            "name": zh.get("name") or gg.get("name"),
            "en_name": en.get("name") or gg.get("en_name"),
            "short_name": zh.get("short_mark") or gg.get("short_name"),
            "en_short_name": en.get("short_mark") or gg.get("en_short_name"),
            "tech_name": gg.get("tech_name"),
            "premium": zh.get("premium", en.get("premium", 0)),
            "collector_vehicle": zh.get("collector_vehicle", en.get("collector_vehicle", 0)),
            "official_present": int(tank_id in en_rows or tank_id in zh_rows),
            "tankgg_present": int(tank_id in tankgg_rows),
            "listed": int(tank_id in en_rows or tank_id in zh_rows),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        existing = connection.execute("SELECT * FROM tanks WHERE tank_id = ?", (tank_id,)).fetchone()
        if existing:
            old = dict(existing)
            record = _prefer_new_value(old, record)
            record["created_at"] = old["created_at"]
            record["rank"] = old["rank"]
            record["rank_delta"] = old["rank_delta"]
            for column in ("mastery_65", "mastery_85", "mastery_95", "tank_icon"):
                record[column] = old[column]
            record["listed"] = int(bool(old["listed"]) or bool(record["listed"]))
        connection.execute(
            """INSERT INTO tanks (
                tank_id,nation,type,role,tier,name,en_name,short_name,en_short_name,tech_name,
                premium,collector_vehicle,tank_icon,rank,rank_delta,mastery_65,mastery_85,mastery_95,
                official_present,tankgg_present,listed,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(tank_id) DO UPDATE SET
                nation=excluded.nation,type=excluded.type,role=excluded.role,tier=excluded.tier,
                name=excluded.name,en_name=excluded.en_name,short_name=excluded.short_name,
                en_short_name=excluded.en_short_name,tech_name=excluded.tech_name,
                premium=excluded.premium,collector_vehicle=excluded.collector_vehicle,
                official_present=excluded.official_present,tankgg_present=excluded.tankgg_present,
                listed=excluded.listed,updated_at=excluded.updated_at""",
            (tank_id, record.get("nation"), record.get("type"), record.get("role"), record.get("tier"),
             record.get("name"), record.get("en_name"), record.get("short_name"), record.get("en_short_name"),
             record.get("tech_name"), int(record.get("premium") or 0), int(record.get("collector_vehicle") or 0),
             record.get("tank_icon"), record.get("rank"), record.get("rank_delta", 0), record.get("mastery_65"),
             record.get("mastery_85"), record.get("mastery_95"), record.get("official_present", 0),
             record.get("tankgg_present", 0), record.get("listed", 0), record.get("created_at", timestamp), timestamp),
        )
        written += 1
    LOGGER.info("Merged official and tanks.gg catalogues: %d vehicles", written)
    return {"vehicles": written}


def fetch_rankings(session: requests.Session, percentile: int) -> List[dict]:
    page = 1
    result = []
    while page <= 500:
        response = session.post(
            RANK_URL,
            data={"percentile": percentile, "rank_type": "default", "tier": "5,6,7,8,9,10,11",
                  "sort": "mastery", "page": page, "size": 40},
            timeout=(8, 60),
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errno") != 0:
            raise RuntimeError(f"Ranking source failed for {percentile}%")
        ranking = ((payload.get("data") or {}).get("ranking") or [])
        if not ranking:
            return result
        for offset, item in enumerate(ranking):
            item = dict(item)
            item["_rank"] = (page - 1) * 40 + offset + 1
            result.append(item)
        page += 1
    raise RuntimeError(f"Ranking source exceeded 500 pages for {percentile}%")


def collect_mastery(run_id: int, connection=None) -> dict:
    connection = connection or get_db()
    session = http_session()
    collected: Dict[int, dict] = {}
    totals = {}
    for percentile in (65, 85, 95):
        ranking = fetch_rankings(session, percentile)
        totals[percentile] = len(ranking)
        field = f"mastery_{percentile}"
        for item in ranking:
            tank_id = int(item["tank_id"])
            record = collected.setdefault(tank_id, {"tank_id": tank_id})
            record[field] = item.get("mastery")
            record["name"] = item.get("tank_name")
            record["tank_icon"] = item.get("tank_icon")
            if percentile == 95:
                record["rank"] = item["_rank"]

    timestamp = now_epoch()
    connection.execute("BEGIN IMMEDIATE")
    try:
        previous_ranks = {
            row["tank_id"]: row["rank"]
            for row in connection.execute("SELECT tank_id, rank FROM tanks WHERE rank IS NOT NULL")
        }
        for tank_id, record in collected.items():
            current = connection.execute("SELECT * FROM tanks WHERE tank_id = ?", (tank_id,)).fetchone()
            old_rank = previous_ranks.get(tank_id)
            if record.get("rank") is not None:
                record["rank_delta"] = old_rank - record["rank"] if old_rank is not None else 0
            if current is None:
                connection.execute(
                    """INSERT INTO tanks(tank_id,name,tank_icon,premium,collector_vehicle,listed,
                       mastery_65,mastery_85,mastery_95,rank,rank_delta,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (tank_id, record.get("name"), record.get("tank_icon"), 1, 0, 1,
                     record.get("mastery_65"), record.get("mastery_85"), record.get("mastery_95"),
                     record.get("rank"), record.get("rank_delta", 0), timestamp, timestamp),
                )
            else:
                assignments = ["listed=1", "updated_at=?"]
                values: List[Any] = [timestamp]
                for field in ("name", "tank_icon"):
                    if record.get(field) is not None:
                        assignments.append(f"{field}=?")
                        values.append(record[field])
                for field in ("mastery_65", "mastery_85", "mastery_95"):
                    if record.get(field) is not None:
                        assignments.append(f"{field}=?")
                        values.append(record[field])
                if record.get("rank") is not None:
                    assignments.extend(["rank_delta=?", "rank=?"])
                    values.extend([record["rank_delta"], record["rank"]])
                values.append(tank_id)
                connection.execute(f"UPDATE tanks SET {','.join(assignments)} WHERE tank_id=?", values)
            connection.execute(
                """INSERT INTO mastery_observations(run_id,tank_id,mastery_65,mastery_85,mastery_95,rank,rank_delta)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(run_id,tank_id) DO UPDATE SET
                   mastery_65=COALESCE(excluded.mastery_65,mastery_observations.mastery_65),
                   mastery_85=COALESCE(excluded.mastery_85,mastery_observations.mastery_85),
                   mastery_95=COALESCE(excluded.mastery_95,mastery_observations.mastery_95),
                   rank=COALESCE(excluded.rank,mastery_observations.rank),
                   rank_delta=COALESCE(excluded.rank_delta,mastery_observations.rank_delta)""",
                (run_id, tank_id, record.get("mastery_65"), record.get("mastery_85"), record.get("mastery_95"), record.get("rank"), record.get("rank_delta")),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"tanks": len(collected), "by_percentile": totals}


def execute_collection(app, include_catalog: bool = True, source: str = "live") -> dict:
    from db import connect
    from flask import current_app

    with app.app_context():
        connection = connect()
        started = now_epoch()
        day = datetime.now(SHANGHAI).date().isoformat()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "INSERT INTO collection_runs(snapshot_day,started_at,status,source) VALUES(?,?,?,?)",
                (day, started, "running", source),
            )
            run_id = cursor.lastrowid
            connection.commit()
            catalog_result = refresh_catalog(connection) if include_catalog else {}
            mastery_result = collect_mastery(run_id, connection)
            connection.execute(
                "UPDATE collection_runs SET finished_at=?,status='complete' WHERE run_id=?",
                (now_epoch(), run_id),
            )
            connection.commit()
            return {"run_id": run_id, **catalog_result, **mastery_result}
        except Exception as error:
            connection.rollback()
            LOGGER.exception("Collection run failed")
            connection.execute(
                "UPDATE collection_runs SET finished_at=?,status='failed' WHERE run_id=?",
                (now_epoch(), locals().get("run_id")),
            )
            connection.commit()
            raise error
        finally:
            connection.close()



