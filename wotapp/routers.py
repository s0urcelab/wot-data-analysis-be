import asyncio
import json
import logging
import os
import threading
import traceback
from datetime import datetime

import httpx
from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile

from wotapp.database import get_db
from wotapp.jobs import run_daily_update
from wotapp.models import MasterySnapshot, Vehicle
from wotapp.serialize import snapshot_to_api, vehicle_to_api
from wotapp.services.badges import PayloadTooLarge, download_path, intake_error, read_upload, run_modifier
from wotapp.services.mods import latest_mod_version
from wotapp.services.player import build_player, fetch_garage, search_accounts
from wotapp.util import to_utc_iso

logger = logging.getLogger("wotapp")

router = APIRouter()

VEHICLE_TYPES = ["lightTank", "mediumTank", "heavyTank", "AT-SPG", "SPG"]
TIERS = list(range(1, 12))
ALLOWED_PAGE_SIZES = {20, 40, 100}

SORT_COLUMNS = {
    "mastery_65": Vehicle.mastery_65,
    "mastery_85": Vehicle.mastery_85,
    "mastery_95": Vehicle.mastery_95,
    "rank": Vehicle.rank,
    "rank_delta": Vehicle.rank_delta,
    "tier": Vehicle.tier,
    "name": Vehicle.name,
    "nation": Vehicle.nation,
    "type": Vehicle.vehicle_type,
    "premium": Vehicle.is_premium,
    "collector_vehicle": Vehicle.is_collector,
    "update_date": Vehicle.mastery_updated_at,
    "insert_date": Vehicle.created_at,
}


class UTF8JSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def ok(data):
    return {"errCode": 0, "data": data}


@router.get("/apiVersion")
def api_version():
    return Response(content="1.1", media_type="text/plain")


@router.get("/manual")
def manual_gather():
    threading.Thread(target=run_daily_update, daemon=True).start()
    return Response(content="开始手动更新击杀环数据", media_type="text/plain")


@router.get("/preData")
def pre_data(
    pid: int | None = None,
    pn: str | None = None,
    db: Session = Depends(get_db),
):
    nations = db.scalars(
        select(Vehicle.nation)
        .where(Vehicle.nation.is_not(None), Vehicle.nation != "")
        .distinct()
        .order_by(Vehicle.nation)
    ).all()
    last_update = db.scalar(select(func.max(Vehicle.mastery_updated_at)))
    player = None
    if pid and pn:
        player = build_player(pid, pn)
    return ok({
        "nations": list(nations),
        "types": VEHICLE_TYPES,
        "tiers": TIERS,
        "lastUpdate": to_utc_iso(last_update) if isinstance(last_update, datetime) else None,
        "player": player,
    })


@router.post("/bindUser")
def bind_user(body: dict = Body(...)):
    nickname = body.get("nickname")
    if not isinstance(nickname, str):
        return JSONResponse(status_code=422, content={"errCode": 422, "msg": "nickname 必须是字符串"})
    if len(nickname) < 4:
        return {"errCode": 20001, "msg": "玩家昵称至少4个字符"}
    match_list = search_accounts(nickname)
    if not match_list:
        return {"errCode": 20002, "msg": "没有找到您搜索的玩家"}
    return ok(match_list)


@router.get("/tankList")
def tank_list(
    nation: str | None = None,
    type: str | None = None,
    tier: int | None = None,
    premium: int | None = None,
    collector_vehicle: int | None = None,
    page: int = 1,
    size: int = 20,
    sort: str | None = None,
    order: str | None = None,
    player_id: int | None = None,
    db: Session = Depends(get_db),
):
    if size not in ALLOWED_PAGE_SIZES:
        return Response(status_code=500)
    page = max(page, 1)

    player_map: dict[int, dict] = {}
    filters = []
    if player_id is not None:
        garage = fetch_garage(player_id)
        if garage:
            ids = []
            for row in garage:
                vid = row.get("vehicle_cd")
                if vid is None:
                    continue
                vid = int(vid)
                ids.append(vid)
                player_map[vid] = row
            filters.append(Vehicle.id.in_(ids))

    if nation is not None:
        filters.append(Vehicle.nation == nation)
    if type is not None:
        filters.append(Vehicle.vehicle_type == type)
    if tier is not None:
        filters.append(Vehicle.tier == tier)
    if premium is not None:
        filters.append(Vehicle.is_premium == premium)
    if collector_vehicle is not None:
        filters.append(Vehicle.is_collector == collector_vehicle)

    if sort and order and sort in SORT_COLUMNS:
        column = SORT_COLUMNS[sort]
        ordering = column.asc().nulls_first() if order == "ascend" else column.desc().nulls_last()
    else:
        ordering = Vehicle.mastery_95.desc().nulls_last()

    total = db.scalar(select(func.count()).select_from(Vehicle).where(*filters)) or 0
    rows = db.scalars(
        select(Vehicle)
        .where(*filters)
        .order_by(ordering, Vehicle.id)
        .offset((page - 1) * size)
        .limit(size)
    ).all()

    items = []
    for vehicle in rows:
        item = vehicle_to_api(vehicle)
        matched = player_map.get(vehicle.id)
        if matched is not None:
            item["pl"] = {
                "mastery": matched.get("markOfMastery"),
                "moe": matched.get("marksOnGun"),
            }
        items.append(item)

    return ok({"list": items, "total": total})


@router.get("/history")
def single_tank_history(
    id: int = Query(...),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(MasterySnapshot)
        .where(MasterySnapshot.vehicle_id == id)
        .order_by(MasterySnapshot.captured_at, MasterySnapshot.id)
    ).all()
    return ok({"list": [snapshot_to_api(row) for row in rows]})


@router.get("/modVersion")
def mod_version():
    with httpx.Client(timeout=30) as client:
        version = latest_mod_version(client)
    return ok(version)


@router.post("/upload")
async def upload_badges(request: Request):
    form = await request.form()
    try:
        files = [(key, value) for key, value in form.multi_items() if isinstance(value, UploadFile)]
        for field, item in files:
            logger.info("UPLOAD: %s %s", field, item.filename)
        reason = intake_error([(field, item.filename) for field, item in files])
        if reason:
            return UTF8JSONResponse(status_code=400, content={"message": reason})

        dds = xml = None
        for field, item in files:
            if field == "dds":
                dds = item
            elif field == "xml":
                xml = item
        if dds is None or xml is None:
            return {"errCode": 10001, "data": "未上传指定文件"}

        try:
            dds_bytes = await read_upload(dds)
            xml_bytes = await read_upload(xml)
        except PayloadTooLarge:
            return UTF8JSONResponse(status_code=400, content={"message": "Reach fileSize limit"})

        try:
            output_name = await asyncio.to_thread(
                run_modifier,
                dds.filename or "upload.dds",
                dds_bytes,
                xml.filename or "upload.xml",
                xml_bytes,
            )
        except Exception:
            return {"errCode": 10003, "data": traceback.format_exc()}
        return ok(output_name)
    finally:
        await form.close()


@router.get("/download")
def download_badges(n: str = Query(...), t: str = Query(...)):
    path = download_path(n, t)
    if path is None:
        return Response(status_code=404)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename=battleAtlas.{t}"},
        background=BackgroundTask(os.remove, path),
    )
