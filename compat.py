"""Temporary adapters for the existing frontend; v1 remains the source of data."""

from datetime import datetime, timezone
from urllib.parse import urlencode

from flask import jsonify, request

from db import get_db


def _number(value):
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", "") or 0)
    except (TypeError, ValueError):
        return None


def register_compat_routes(app):
    def call_v1(endpoint, params=None, **route_values):
        # Reuse the v1 handler without an HTTP round trip or duplicated queries.
        if params is None:
            response = app.make_response(app.view_functions[endpoint](**route_values))
        else:
            environ = request.environ.copy()
            environ["QUERY_STRING"] = urlencode(params)
            with app.request_context(environ):
                response = app.make_response(app.view_functions[endpoint](**route_values))
        return response.get_json(), response.status_code

    def success(data):
        return jsonify({"errCode": 0, "data": data})

    def failure(payload, data, code=50001):
        error = payload.get("error", {})
        messages = {
            "nickname_too_short": "玩家昵称至少4个字符",
            "player_search_unavailable": "玩家查找服务暂时不可用，请稍后重试",
            "player_data_unavailable": "玩家车辆数据暂时不可用，请稍后重试",
            "version_service_unavailable": "插件版本服务暂时不可用，请稍后重试",
        }
        return jsonify({"errCode": code, "msg": messages.get(error.get("code"), error.get("message", "请求失败")),
                        "data": data})

    @app.get("/tankList")
    @app.get("/api/tankList")
    def legacy_tank_list():
        params = request.args.to_dict()
        params["page_size"] = params.pop("size", "20")
        params["order"] = {"ascend": "asc", "descend": "desc"}.get(params.get("order"), params.get("order", "desc"))
        if params.get("sort") == "_id":
            params["sort"] = "tank_id"
        payload, status = call_v1("list_tanks", params)
        if status >= 400:
            return failure(payload, {"list": [], "total": 0})
        items = []
        for original in payload["items"]:
            item = dict(original)
            item["_id"] = item.pop("id")
            item["premium"] = int(item.pop("is_premium"))
            item["collector_vehicle"] = int(item.pop("is_collector_vehicle"))
            player = item.pop("player_stats", None)
            if player is not None:
                item["pl"] = {"mastery": player.get("mastery"), "moe": player.get("marks_on_gun")}
            items.append(item)
        return success({"list": items, "total": payload["pagination"]["total"]})

    @app.get("/preData")
    @app.get("/api/preData")
    def legacy_pre_data():
        params = {"player_id": request.args.get("pid", ""), "nickname": request.args.get("pn", "")}
        payload, status = call_v1("meta", params)
        if status >= 400:
            return failure(payload, {"nations": [], "types": [], "tiers": [], "lastUpdate": None, "player": None})
        data = dict(payload["data"])
        data["lastUpdate"] = data.pop("last_updated")
        if data["lastUpdate"] is None:
            # Migrated catalogues may have update times but no completed history yet.
            epoch = get_db().execute("SELECT MAX(updated_at) FROM tanks WHERE listed=1").fetchone()[0]
            if epoch is not None:
                data["lastUpdate"] = datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        player = data.get("player")
        data["player"] = None if player is None else {
            "battTotal": player.get("battles_count"), "winRate": player.get("wins_ratio"),
            "wgr": player.get("global_rating"), "eff": _number(player.get("efficiency")),
            "effDelta": _number(player.get("efficiency_delta")),
        }
        return success(data)

    @app.post("/bindUser")
    @app.post("/api/bindUser")
    def legacy_bind_user():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("nickname"), str):
            return failure({"error": {"message": "nickname 必须是字符串"}}, [], 20001)
        payload, status = call_v1("search_players")
        if status >= 400:
            code = 20001 if payload.get("error", {}).get("code") == "nickname_too_short" else 20003
            return failure(payload, [], code)
        if not payload["items"]:
            return jsonify({"errCode": 20002, "msg": "没有找到您搜索的玩家", "data": []})
        return success(payload["items"])

    @app.get("/history")
    @app.get("/api/history")
    def legacy_history():
        try:
            tank_id = int(request.args.get("id", ""))
            if tank_id < 0:
                raise ValueError
        except ValueError:
            return failure({"error": {"message": "id 必须是非负整数"}}, {"list": []}, 40001)
        payload, status = call_v1("tank_history", tank_id=tank_id)
        if status >= 400:
            return failure(payload, {"list": []})
        return success({"list": [{"date": item["date"], "mastery_65": item["mastery_65"],
                                  "mastery_85": item["mastery_85"], "mastery_95": item["mastery_95"],
                                  "ace": item["ace"]} for item in payload["items"]]})

    @app.get("/modVersion")
    @app.get("/api/modVersion")
    def legacy_mod_version():
        payload, status = call_v1("plugin_version")
        if status >= 400:
            return failure(payload, "未知")
        return success(payload["version"])
