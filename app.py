from __future__ import annotations

import logging
import os
import re
import threading
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request

from collectors import execute_collection, refresh_catalog
from db import connect, get_db, init_app

LOGGER = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
COLLECTION_LOCK = threading.Lock()
SORT_FIELDS = {
    "tank_id": "tank_id", "rank": "rank", "rank_delta": "rank_delta", "nation": "nation",
    "type": "type", "role": "role", "tier": "tier", "name": "name", "en_name": "en_name",
    "premium": "premium", "collector_vehicle": "collector_vehicle", "mastery_65": "mastery_65",
    "mastery_85": "mastery_85", "mastery_95": "mastery_95",
}


def _error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _iso_utc(epoch: Optional[int]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(int(epoch), timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _int_arg(name: str, default: Optional[int] = None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer")


def _deep_find(payload: Any, key: str):
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for child in payload.values():
            found = _deep_find(child, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for child in payload:
            found = _deep_find(child, key)
            if found is not None:
                return found
    return None


def _player_summary(player_id: int, nickname: str):
    headers = {"X-Requested-With": "XMLHttpRequest", "User-Agent": "wot-data-analysis/2.0"}
    summary_response = requests.get(
        "https://wotgame.cn/wotup/profile/summary/",
        params={"spa_id": player_id, "battle_type": "random", "wtr_disabled": 1},
        headers=headers, timeout=(5, 15),
    )
    summary_response.raise_for_status()
    payload = summary_response.json()
    result = {
        "battles_count": _deep_find(payload, "battles_count"),
        "wins_ratio": _deep_find(payload, "wins_ratio"),
        "global_rating": _deep_find(payload, "global_rating"),
    }
    html_response = requests.get(
        "https://wotbox.ouj.com/wotbox/index.php",
        params={"r": "default/index", "pn": nickname}, headers=headers, timeout=(5, 15),
    )
    html_response.raise_for_status()
    soup = BeautifulSoup(html_response.text, "html.parser")
    eff = soup.select_one(".power .num")
    delta = soup.select_one(".power .float-num")
    result["efficiency"] = eff.get_text(strip=True) if eff else None
    result["efficiency_delta"] = delta.get_text(strip=True) if delta else None
    return result


def _player_vehicles(player_id: int) -> Dict[int, dict]:
    response = requests.post(
        "https://wotgame.cn/wotup/profile/vehicles/list/",
        json={"battle_type": "random", "only_in_garage": False, "spa_id": player_id,
              "premium": [0, 1], "collector_vehicle": [0, 1], "nation": [], "role": [],
              "type": [], "tier": [], "language": "zh-cn"},
        headers={"X-Requested-With": "XMLHttpRequest"}, timeout=(5, 25),
    )
    response.raise_for_status()
    payload = response.json()
    container = (payload.get("data") or {}).get("data") or {}
    parameters = container.get("parameters") or []
    result = {}
    for row in container.get("data") or []:
        item = dict(zip(parameters, row))
        try:
            tank_id = int(item["vehicle_cd"])
        except (KeyError, TypeError, ValueError):
            continue
        result[tank_id] = {"mastery": item.get("markOfMastery"), "marks_on_gun": item.get("marksOnGun")}
    return result


def _latest_complete_run(connection, day: str):
    return connection.execute(
        "SELECT run_id,finished_at FROM collection_runs WHERE snapshot_day=? AND status='complete' "
        "ORDER BY finished_at DESC,run_id DESC LIMIT 1", (day,),
    ).fetchone()


def _collection_job(app, catalog_only: bool, source: str):
    if not COLLECTION_LOCK.acquire(blocking=False):
        LOGGER.warning("Collection already running; skipped %s", source)
        return
    try:
        if catalog_only:
            with app.app_context():
                connection = connect()
                try:
                    refresh_catalog(connection)
                finally:
                    connection.close()
        else:
            execute_collection(app, include_catalog=False, source=source)
    except Exception:
        LOGGER.exception("Scheduled collection failed")
    finally:
        COLLECTION_LOCK.release()


def create_app(config: Optional[dict] = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        DATABASE_PATH=os.environ.get("DATABASE_PATH", str(Path(__file__).resolve().parent / "wot.sqlite3")),
        MOD_VERSION_URL=os.environ.get("MOD_VERSION_URL", "http://host.docker.internal:7003/wot/?json"),
        ENABLE_SCHEDULER=os.environ.get("ENABLE_SCHEDULER", "true").lower() in {"1", "true", "yes"},
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    )
    if config:
        app.config.update(config)
    init_app(app)

    @app.get("/api/v1/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/v1/meta")
    def meta():
        connection = get_db()
        nations = connection.execute(
            "SELECT DISTINCT nation FROM tanks WHERE listed=1 AND nation IS NOT NULL ORDER BY nation"
        ).fetchall()
        latest = connection.execute(
            "SELECT MAX(finished_at) AS last_updated FROM collection_runs WHERE status='complete'"
        ).fetchone()
        data = {
            "nations": [row["nation"] for row in nations],
            "types": ["lightTank", "mediumTank", "heavyTank", "AT-SPG", "SPG"],
            "tiers": list(range(1, 12)),
            "last_updated": _iso_utc(latest["last_updated"] if latest else None),
        }
        player_id = request.args.get("player_id")
        nickname = request.args.get("nickname")
        if player_id and nickname:
            try:
                data["player"] = _player_summary(int(player_id), nickname)
            except (ValueError, requests.RequestException) as error:
                LOGGER.warning("Could not load player summary: %s", error)
                data["player"] = None
        return jsonify({"data": data})

    @app.get("/api/v1/tanks")
    def list_tanks():
        try:
            page = _int_arg("page", 1)
            page_size = _int_arg("page_size", 20)
            if page < 1 or page_size not in {20, 40, 100}:
                return _error("invalid_pagination", "page must be positive and page_size one of 20, 40, 100", 400)
            filters = ["listed=1"]
            values = []
            for field in ("nation", "type"):
                value = request.args.get(field)
                if value:
                    filters.append(f"{field}=?")
                    values.append(value)
            for field in ("tier", "premium", "collector_vehicle"):
                value = _int_arg(field)
                if value is not None:
                    if field in {"premium", "collector_vehicle"} and value not in {0, 1}:
                        return _error("invalid_filter", f"{field} must be 0 or 1", 400)
                    filters.append(f"{field}=?")
                    values.append(value)
            player_id = _int_arg("player_id")
            player_tanks = None
            if player_id is not None:
                player_tanks = _player_vehicles(player_id)
                if not player_tanks:
                    return jsonify({"items": [], "pagination": {"page": page, "page_size": page_size, "total": 0}})
                ids = list(player_tanks)
                filters.append("tank_id IN (" + ",".join("?" for _ in ids) + ")")
                values.extend(ids)
            sort = request.args.get("sort", "mastery_95")
            column = SORT_FIELDS.get(sort)
            if column is None:
                return _error("invalid_sort", "unsupported sort field", 400)
            order = "ASC" if request.args.get("order", "desc").lower() == "asc" else "DESC"
            where = " AND ".join(filters)
            connection = get_db()
            total = connection.execute(f"SELECT COUNT(*) FROM tanks WHERE {where}", values).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM tanks WHERE {where} ORDER BY {column} {order},tank_id ASC LIMIT ? OFFSET ?",
                [*values, page_size, (page - 1) * page_size],
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["is_premium"] = bool(item.pop("premium"))
                item["is_collector_vehicle"] = bool(item.pop("collector_vehicle"))
                item["id"] = item.pop("tank_id")
                for key in ("created_at", "updated_at", "official_present", "tankgg_present", "listed"):
                    item.pop(key, None)
                if player_tanks is not None and player_tanks:
                    item["player_stats"] = player_tanks.get(item["id"])
                items.append(item)
            return jsonify({"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}})
        except ValueError as error:
            return _error("invalid_parameter", str(error), 400)
        except requests.RequestException as error:
            LOGGER.warning("Player vehicle request failed: %s", error)
            return _error("player_data_unavailable", "Could not load the player's vehicle data", 502)

    @app.get("/api/v1/tanks/<int:tank_id>/history")
    def tank_history(tank_id: int):
        rows = get_db().execute(
            """SELECT r.snapshot_day,r.finished_at,o.mastery_65,o.mastery_85,o.mastery_95,o.ace
               FROM mastery_observations o JOIN collection_runs r ON r.run_id=o.run_id
               WHERE o.tank_id=? AND r.status='complete'
               ORDER BY r.snapshot_day ASC,r.finished_at ASC,r.run_id ASC""", (tank_id,),
        ).fetchall()
        return jsonify({"tank_id": tank_id, "items": [
            {"date": row["snapshot_day"], "collected_at": _iso_utc(row["finished_at"]),
             "mastery_65": row["mastery_65"], "mastery_85": row["mastery_85"],
             "mastery_95": row["mastery_95"], "ace": row["ace"]}
            for row in rows
        ]})

    @app.get("/api/v1/today-changes")
    def today_changes():
        threshold = request.args.get("threshold", "95")
        if threshold not in {"65", "85", "95"}:
            return _error("invalid_threshold", "threshold must be 65, 85, or 95", 400)
        try:
            comparison_day = date.fromisoformat(request.args["date"]) if request.args.get("date") else datetime.now(SHANGHAI).date()
            page = _int_arg("page", 1)
            page_size = _int_arg("page_size", 100)
            if page < 1 or page_size not in {20, 40, 100}:
                return _error("invalid_pagination", "page must be positive and page_size one of 20, 40, 100", 400)
        except ValueError as error:
            return _error("invalid_parameter", str(error), 400)
        previous_day = comparison_day - timedelta(days=1)
        connection = get_db()
        current_run = _latest_complete_run(connection, comparison_day.isoformat())
        previous_run = _latest_complete_run(connection, previous_day.isoformat())
        if current_run is None or previous_run is None:
            return jsonify({"date": comparison_day.isoformat(), "compared_to": previous_day.isoformat(),
                            "threshold": int(threshold), "items": [],
                            "pagination": {"page": page, "page_size": page_size, "total": 0}})
        field = f"mastery_{threshold}"
        rows = connection.execute(
            f"""SELECT t.*,cur.{field} AS current_value,prev.{field} AS previous_value,
                       (cur.{field}-prev.{field}) AS delta
                FROM mastery_observations cur
                JOIN mastery_observations prev ON prev.tank_id=cur.tank_id AND prev.run_id=?
                JOIN tanks t ON t.tank_id=cur.tank_id
                WHERE cur.run_id=? AND cur.{field} IS NOT NULL AND prev.{field} IS NOT NULL
                  AND cur.{field} != prev.{field}
                ORDER BY ABS(cur.{field}-prev.{field}) DESC,t.tank_id ASC""",
            (previous_run["run_id"], current_run["run_id"]),
        ).fetchall()
        items = []
        start = (page - 1) * page_size
        for row in rows[start:start + page_size]:
            item = dict(row)
            item["id"] = item.pop("tank_id")
            item["is_premium"] = bool(item.pop("premium"))
            item["is_collector_vehicle"] = bool(item.pop("collector_vehicle"))
            for key in ("created_at", "updated_at", "official_present", "tankgg_present", "listed"):
                item.pop(key, None)
            items.append(item)
        return jsonify({"date": comparison_day.isoformat(), "compared_to": previous_day.isoformat(),
                        "threshold": int(threshold), "items": items,
                        "pagination": {"page": page, "page_size": page_size, "total": len(rows)}})

    @app.post("/api/v1/players/search")
    def search_players():
        body = request.get_json(silent=True) or {}
        nickname = str(body.get("nickname", "")).strip()
        if len(nickname) < 4:
            return _error("nickname_too_short", "nickname must contain at least 4 characters", 400)
        try:
            response = requests.get(
                "https://wotgame.cn/zh-cn/community/accounts/search/", params={"name": nickname},
                headers={"X-Requested-With": "XMLHttpRequest"}, timeout=(5, 20),
            )
            response.raise_for_status()
            return jsonify({"items": _deep_find(response.json(), "response") or []})
        except (requests.RequestException, ValueError) as error:
            LOGGER.warning("Player lookup failed: %s", error)
            return _error("player_search_unavailable", "Player lookup service is unavailable", 502)

    @app.get("/api/v1/players/<int:player_id>/summary")
    def player_summary(player_id: int):
        nickname = request.args.get("nickname", "")
        if not nickname:
            return _error("nickname_required", "nickname is required", 400)
        try:
            return jsonify({"player_id": player_id, "summary": _player_summary(player_id, nickname)})
        except (requests.RequestException, ValueError) as error:
            LOGGER.warning("Player summary request failed: %s", error)
            return _error("player_data_unavailable", "Player summary service is unavailable", 502)

    @app.post("/api/v1/collections/run")
    def start_collection():
        if not COLLECTION_LOCK.acquire(blocking=False):
            return _error("collection_in_progress", "A collection is already running", 409)
        def run():
            try:
                execute_collection(app, include_catalog=True, source="manual")
            except Exception:
                LOGGER.exception("Manual collection failed")
            finally:
                COLLECTION_LOCK.release()
        threading.Thread(target=run, name="manual-collection", daemon=True).start()
        return jsonify({"status": "accepted"}), 202

    @app.get("/api/v1/plugin/version")
    def plugin_version():
        url = app.config["MOD_VERSION_URL"]
        try:
            response = requests.get(url, timeout=(4, 10))
            response.raise_for_status()
            folders = [item.get("name", "") for item in response.json().get("paths", [])
                       if item.get("path_type") == "Dir"]
            key = lambda value: tuple(int(part) for part in re.findall(r"\d+", value))
            return jsonify({"version": max(folders, key=key) if folders else None})
        except (requests.RequestException, ValueError) as error:
            LOGGER.warning("Plugin version lookup failed: %s", error)
            return _error("version_service_unavailable", "Plugin version service is unavailable", 502)

    if app.config["ENABLE_SCHEDULER"]:
        scheduler = BackgroundScheduler(timezone=SHANGHAI)
        scheduler.add_job(lambda: _collection_job(app, True, "scheduled-catalog"), "cron",
                          hour=8, minute=0, id="catalog-refresh", replace_existing=True, max_instances=1, coalesce=True)
        scheduler.add_job(lambda: _collection_job(app, False, "scheduled"), "cron",
                          hour=12, minute=0, id="daily-mastery", replace_existing=True, max_instances=1, coalesce=True)
        scheduler.start()
        app.extensions["scheduler"] = scheduler

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "7001")), debug=False)

