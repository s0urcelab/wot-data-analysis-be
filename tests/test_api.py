import io
import threading
from datetime import datetime

from PIL import Image

import badgesModifier.modifier as badge_modifier
from wotapp.database import session_scope
from wotapp.models import MasterySnapshot, Vehicle
from wotapp.util import compare_version, find_max_version


CAPTURED = datetime(2024, 6, 1, 4, 0, 0)


def _seed():
    with session_scope() as session:
        session.add_all([
            Vehicle(
                id=1,
                nation="ussr",
                vehicle_type="heavyTank",
                tier=10,
                name="IS-7",
                is_premium=0,
                is_collector=0,
                rank_delta=0,
                mastery_95=3000,
                mastery_updated_at=CAPTURED,
                created_at=CAPTURED,
            ),
            Vehicle(
                id=2,
                nation="germany",
                vehicle_type="mediumTank",
                tier=9,
                name="Leopard",
                is_premium=1,
                is_collector=0,
                rank_delta=1,
                mastery_95=1000,
                created_at=CAPTURED,
            ),
            Vehicle(
                id=3,
                nation="ussr",
                vehicle_type="heavyTank",
                tier=8,
                name="KV-2",
                is_premium=0,
                is_collector=1,
                rank_delta=0,
                mastery_95=2000,
                created_at=CAPTURED,
            ),
        ])
        session.add(MasterySnapshot(
            vehicle_id=1,
            captured_at=CAPTURED,
            mastery_95=3000,
            ace=1,
            gathered_at=CAPTURED,
        ))


def test_api_version(client):
    res = client.get("/apiVersion")
    assert res.status_code == 200
    assert res.text == "1.1"


def test_removed_routes_are_absent(client):
    assert client.get("/commentList").status_code == 404
    assert client.post("/addComment").status_code == 404


def test_tank_list_filter_sort_and_page_size(client):
    _seed()
    res = client.get("/tankList")
    body = res.json()
    assert res.status_code == 200
    assert body["data"]["total"] == 3
    assert [item["_id"] for item in body["data"]["list"]] == [1, 3, 2]
    assert body["data"]["list"][0]["type"] == "heavyTank"
    assert body["data"]["list"][0]["premium"] == 0
    assert body["data"]["list"][0]["update_date"] == "2024-06-01T04:00:00.000Z"

    filtered = client.get("/tankList", params={"nation": "germany", "premium": 1})
    assert filtered.json()["data"]["total"] == 1
    assert filtered.json()["data"]["list"][0]["name"] == "Leopard"

    ascended = client.get("/tankList", params={"sort": "mastery_95", "order": "ascend"})
    assert [item["_id"] for item in ascended.json()["data"]["list"]] == [2, 3, 1]

    page2 = client.get("/tankList", params={"page": 2, "size": 20})
    assert page2.json()["data"]["list"] == []
    assert page2.json()["data"]["total"] == 3

    rejected = client.get("/tankList", params={"size": 15})
    assert rejected.status_code == 500
    assert rejected.content == b""


def test_history_renames_date_and_keeps_ace(client):
    _seed()
    res = client.get("/history", params={"id": 1})
    assert res.status_code == 200
    item = res.json()["data"]["list"][0]
    assert item["date"] == "2024-06-01T04:00:00.000Z"
    assert item["mastery_95"] == 3000
    assert item["ace"] == 1
    assert item["gather_date"] == "2024-06-01T04:00:00.000Z"
    assert "_id" not in item
    assert "tank_id" not in item


def test_pre_data(client):
    _seed()
    data = client.get("/preData").json()["data"]
    assert data["nations"] == ["germany", "ussr"]
    assert data["types"] == ["lightTank", "mediumTank", "heavyTank", "AT-SPG", "SPG"]
    assert data["tiers"] == list(range(1, 12))
    assert data["lastUpdate"] == "2024-06-01T04:00:00.000Z"
    assert data["player"] is None


def test_bind_user_not_found(client, monkeypatch):
    monkeypatch.setattr("wotapp.routers.search_accounts", lambda nickname: [])
    res = client.post("/bindUser", json={"nickname": "nobody"})
    assert res.status_code == 200
    assert res.json() == {"errCode": 20002, "msg": "没有找到您搜索的玩家"}


def test_bind_user_rejects_short_nickname(client):
    res = client.post("/bindUser", json={"nickname": "abc"})
    assert res.status_code == 200
    assert res.json() == {"errCode": 20001, "msg": "玩家昵称至少4个字符"}


def test_manual_returns_immediately(client, monkeypatch):
    started = threading.Event()

    def fake_update():
        started.set()

    monkeypatch.setattr("wotapp.routers.run_daily_update", fake_update)
    res = client.get("/manual")
    assert res.status_code == 200
    assert res.text == "开始手动更新击杀环数据"
    assert started.wait(2)


def test_mod_version(client, monkeypatch):
    monkeypatch.setattr("wotapp.routers.latest_mod_version", lambda client: "1.10.0")
    res = client.get("/modVersion")
    assert res.status_code == 200
    assert res.json()["data"] == "1.10.0"


def _badge_xml(names):
    parts = ["<root>"]
    for index, name in enumerate(names):
        parts.append(
            "<SubTexture>"
            f"<name>{name}</name><x>{index * 50}</x><y>0</y><width>40</width><height>40</height>"
            "</SubTexture>"
        )
    parts.append("</root>")
    return "".join(parts).encode()


def _png_named_dds():
    buffer = io.BytesIO()
    Image.new("RGBA", (400, 80), (1, 2, 3, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_upload_and_download_badges(client, tmp_path, monkeypatch):
    monkeypatch.setattr(badge_modifier, "OUTPUT_PATH", str(tmp_path))
    xml = _badge_xml(badge_modifier.COLORS)
    res = client.post(
        "/upload",
        files={
            "dds": ("battleAtlas.dds", _png_named_dds(), "application/octet-stream"),
            "xml": ("battleAtlas.xml", xml, "text/xml"),
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["errCode"] == 0
    output_name = body["data"]
    assert (tmp_path / f"{output_name}.dds").is_file()
    assert (tmp_path / f"{output_name}.xml").read_bytes() == xml

    xml_res = client.get("/download", params={"n": output_name, "t": "xml"})
    assert xml_res.status_code == 200
    assert xml_res.headers["content-disposition"] == "attachment; filename=battleAtlas.xml"
    assert xml_res.headers["content-length"] == str(len(xml))
    assert xml_res.content == xml
    assert not (tmp_path / f"{output_name}.xml").exists()
    assert (tmp_path / f"{output_name}.dds").is_file()

    dds_res = client.get("/download", params={"n": output_name, "t": "dds"})
    assert dds_res.status_code == 200
    assert dds_res.headers["content-disposition"] == "attachment; filename=battleAtlas.dds"
    assert dds_res.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert not (tmp_path / f"{output_name}.dds").exists()
    assert client.get("/download", params={"n": output_name, "t": "dds"}).status_code == 404


def test_upload_missing_file(client):
    res = client.post("/upload", files={"xml": ("battleAtlas.xml", b"<root/>", "text/xml")})
    assert res.status_code == 200
    assert res.json() == {"errCode": 10001, "data": "未上传指定文件"}


def test_upload_rejects_bad_extension_and_file_count(client):
    bad_ext = client.post(
        "/upload",
        files={
            "dds": ("atlas.png", b"png", "application/octet-stream"),
            "xml": ("atlas.xml", b"<root/>", "text/xml"),
        },
    )
    assert bad_ext.status_code == 400
    assert bad_ext.json()["message"] == "Invalid filename"

    too_many = client.post(
        "/upload",
        files=[
            ("dds", ("a.dds", b"x", "application/octet-stream")),
            ("xml", ("a.xml", b"<root/>", "text/xml")),
            ("extra", ("b.xml", b"<root/>", "text/xml")),
            ("more", ("c.dds", b"y", "application/octet-stream")),
        ],
    )
    assert too_many.status_code == 400
    assert too_many.json()["message"] == "Reach files limit"


def test_upload_reports_modifier_failure(client, tmp_path, monkeypatch):
    monkeypatch.setattr(badge_modifier, "OUTPUT_PATH", str(tmp_path))
    res = client.post(
        "/upload",
        files={
            "dds": ("battleAtlas.dds", _png_named_dds(), "application/octet-stream"),
            "xml": ("battleAtlas.xml", _badge_xml(["badge_11"]), "text/xml"),
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["errCode"] == 10003
    assert "坐标数量(1)" in body["data"]


def test_upload_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr("wotapp.services.badges.MAX_FILE_BYTES", 4)
    res = client.post(
        "/upload",
        files={
            "dds": ("battleAtlas.dds", b"12345", "application/octet-stream"),
            "xml": ("battleAtlas.xml", b"<root/>", "text/xml"),
        },
    )
    assert res.status_code == 400
    assert res.json()["message"] == "Reach fileSize limit"


def test_find_max_version():
    assert compare_version("1.10", "1.9") == 1
    assert compare_version("1.0", "1") == 0
    assert find_max_version(["1.2", "1.10", "1.9"]) == "1.10"
    assert find_max_version([]) is None
