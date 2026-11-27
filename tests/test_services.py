from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from wotapp.database import session_scope
from wotapp.models import MasterySnapshot, Vehicle
from wotapp.services.mastery import apply_mastery_row, fetch_mastery
from wotapp.services.player import build_player
from wotapp.services.tanks import refresh_vehicles


def _official_body(name, short):
    return {
        "status": "ok",
        "data": {
            "parameters": [
                "vehicle_cd",
                "nation",
                "type",
                "tier",
                "name",
                "short_mark",
                "premium",
                "collector_vehicle",
                "role",
                "tech_name",
            ],
            "data": [[1, "ussr", "heavyTank", 10, name, short, 1, 0, "heavy", "R45"]],
        },
    }


def test_build_player_parses_summary_and_wotbox(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if "profile/summary" in str(request.url):
            return httpx.Response(200, json={
                "data": {"battles_count": 10, "wins_ratio": 52.1, "global_rating": 8000},
            })
        return httpx.Response(
            200,
            text='<div class="power"><span class="num">1,234</span><span class="float-num">+12</span></div>',
        )

    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("wotapp.services.player.httpx.Client", factory)
    assert build_player(5, "tester") == {
        "battTotal": 10,
        "winRate": 52.1,
        "wgr": 8000,
        "eff": 1234,
        "effDelta": 12,
    }


def test_refresh_updates_identity_and_keeps_mastery(db):
    with session_scope() as session:
        session.add(Vehicle(
            id=1,
            name="旧名",
            is_premium=0,
            is_collector=0,
            rank_delta=2,
            rank=5,
            mastery_95=1234,
            icon_url="icon",
        ))

    def handler(request: httpx.Request) -> httpx.Response:
        raw = request.content.decode()
        if "zh-cn" in raw:
            body = _official_body("中文", "中")
        else:
            body = _official_body("English", "EN")
        return httpx.Response(200, json=body)

    with session_scope() as session:
        refresh_vehicles(session, httpx.Client(transport=httpx.MockTransport(handler)))

    with session_scope() as session:
        vehicle = session.get(Vehicle, 1)
        assert vehicle.name == "中文"
        assert vehicle.en_name == "English"
        assert vehicle.short_name == "中"
        assert vehicle.en_short_name == "EN"
        assert vehicle.nation == "ussr"
        assert vehicle.vehicle_type == "heavyTank"
        assert vehicle.tier == 10
        assert vehicle.is_premium == 1
        assert vehicle.tech_name == "R45"
        assert vehicle.mastery_95 == 1234
        assert vehicle.rank == 5
        assert vehicle.rank_delta == 2
        assert vehicle.icon_url == "icon"


def test_apply_mastery_updates_rank_and_merges_snapshot(db):
    captured = datetime(2024, 6, 1, 4, 0, 0)
    with session_scope() as session:
        session.add(Vehicle(
            id=8,
            name="旧",
            is_premium=0,
            is_collector=0,
            rank=10,
            rank_delta=0,
        ))
        session.flush()
        apply_mastery_row(
            session,
            {"tank_id": 8, "tank_name": "榜单名", "tank_icon": "ico", "mastery": 2000},
            level=95,
            rank=4,
            captured_at=captured,
        )
        apply_mastery_row(
            session,
            {"tank_id": 8, "tank_name": "榜单名", "tank_icon": "ico", "mastery": 1000},
            level=65,
            rank=1,
            captured_at=captured,
        )

    with session_scope() as session:
        vehicle = session.get(Vehicle, 8)
        assert vehicle.rank == 4
        assert vehicle.rank_delta == 6
        assert vehicle.mastery_95 == 2000
        assert vehicle.mastery_65 == 1000
        assert vehicle.name == "榜单名"
        assert vehicle.icon_url == "ico"
        snap = session.scalar(select(MasterySnapshot).where(MasterySnapshot.vehicle_id == 8))
        assert snap.mastery_95 == 2000
        assert snap.mastery_65 == 1000
        assert snap.captured_at == captured


def test_fetch_mastery_inserts_stub_and_stops_on_empty_page(db):
    pages = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        pages["n"] += 1
        ranking = []
        if pages["n"] == 1:
            ranking = [{
                "tank_id": 7,
                "tank_name": "新车",
                "tank_icon": "i",
                "mastery": 1500,
            }]
        return httpx.Response(200, json={"errno": 0, "data": {"ranking": ranking}})

    fetch_mastery(95, httpx.Client(transport=httpx.MockTransport(handler)))

    with session_scope() as session:
        vehicle = session.get(Vehicle, 7)
        assert vehicle.name == "新车"
        assert vehicle.icon_url == "i"
        assert vehicle.mastery_95 == 1500
        assert vehicle.rank == 1
        assert vehicle.rank_delta == 0
        assert vehicle.nation is None
        snap = session.scalar(select(MasterySnapshot).where(MasterySnapshot.vehicle_id == 7))
        assert snap.mastery_95 == 1500
    assert pages["n"] == 2


def test_fetch_mastery_stops_when_errno_is_not_zero(db):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errno": 1, "data": {}})

    fetch_mastery(85, httpx.Client(transport=httpx.MockTransport(handler)))
    with session_scope() as session:
        assert session.get(Vehicle, 1) is None


def test_import_preserves_vehicle_history_and_partial_rows(db):
    from wotapp.migrate import import_documents

    when = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    tanks = [{
        "_id": 9,
        "nation": "usa",
        "type": "mediumTank",
        "role": "support",
        "tier": 8,
        "name": "潘兴",
        "en_name": "Pershing",
        "short_name": "Pershing",
        "en_short_name": "Pershing",
        "tech_name": "A35_Pershing",
        "premium": 1,
        "collector_vehicle": 0,
        "tank_icon": "icon",
        "rank": 4,
        "rank_delta": -1,
        "mastery_65": 100,
        "mastery_85": 200,
        "mastery_95": 300,
        "insert_date": when,
        "update_date": when,
    }]
    history = [
        {
            "tank_id": 9,
            "insert_date": when,
            "mastery_95": 300,
            "ace": 2,
            "gather_date": when,
            "update_date": when,
        },
        {"tank_id": 9, "insert_date": when, "mastery_65": 11},
        {"tank_id": 42, "insert_date": when, "mastery_65": 10},
    ]
    with session_scope() as session:
        import_documents(session, tanks, history)

    with session_scope() as session:
        vehicle = session.get(Vehicle, 9)
        assert vehicle.name == "潘兴"
        assert vehicle.vehicle_type == "mediumTank"
        assert vehicle.is_premium == 1
        assert vehicle.mastery_95 == 300
        assert vehicle.rank == 4
        assert vehicle.rank_delta == -1
        assert vehicle.icon_url == "icon"
        assert vehicle.created_at == when.replace(tzinfo=None)
        snap = session.scalar(select(MasterySnapshot).where(MasterySnapshot.vehicle_id == 9))
        assert snap.ace == 2
        assert snap.mastery_95 == 300
        assert snap.mastery_65 == 11
        orphan = session.get(Vehicle, 42)
        assert orphan is not None
        orphan_snap = session.scalar(select(MasterySnapshot).where(MasterySnapshot.vehicle_id == 42))
        assert orphan_snap.mastery_65 == 10

    with session_scope() as session:
        import_documents(session, [], [{
            "tank_id": 9,
            "insert_date": when,
            "mastery_85": 77,
        }])

    with session_scope() as session:
        snaps = session.scalars(
            select(MasterySnapshot).where(MasterySnapshot.vehicle_id == 9)
        ).all()
        assert len(snaps) == 1
        assert snaps[0].mastery_85 == 77
        assert snaps[0].mastery_65 == 11
        assert snaps[0].mastery_95 == 300
        assert snaps[0].ace == 2
