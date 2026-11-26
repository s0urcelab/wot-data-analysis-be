from wotapp.models import MasterySnapshot, Vehicle
from wotapp.util import to_utc_iso


def vehicle_to_api(vehicle: Vehicle) -> dict:
    return {
        "_id": vehicle.id,
        "rank": vehicle.rank,
        "rank_delta": vehicle.rank_delta,
        "nation": vehicle.nation,
        "type": vehicle.vehicle_type,
        "role": vehicle.role,
        "tier": vehicle.tier,
        "name": vehicle.name,
        "en_name": vehicle.en_name,
        "short_name": vehicle.short_name,
        "en_short_name": vehicle.en_short_name,
        "tech_name": vehicle.tech_name,
        "premium": vehicle.is_premium,
        "collector_vehicle": vehicle.is_collector,
        "tank_icon": vehicle.icon_url,
        "mastery_65": vehicle.mastery_65,
        "mastery_85": vehicle.mastery_85,
        "mastery_95": vehicle.mastery_95,
        "insert_date": to_utc_iso(vehicle.created_at),
        "update_date": to_utc_iso(vehicle.mastery_updated_at),
    }


def snapshot_to_api(row: MasterySnapshot) -> dict:
    item: dict = {"date": to_utc_iso(row.captured_at)}
    for attr, key in (
        ("mastery_65", "mastery_65"),
        ("mastery_85", "mastery_85"),
        ("mastery_95", "mastery_95"),
        ("ace", "ace"),
    ):
        value = getattr(row, attr)
        if value is not None:
            item[key] = value
    if row.gathered_at is not None:
        item["gather_date"] = to_utc_iso(row.gathered_at)
    if row.updated_at is not None:
        item["update_date"] = to_utc_iso(row.updated_at)
    return item
