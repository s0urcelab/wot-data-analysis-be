import httpx

from wotapp.config import get_settings
from wotapp.util import find_max_version


def latest_mod_version(client: httpx.Client) -> str | None:
    res = client.get(get_settings().mod_version_url)
    res.raise_for_status()
    body = res.json()
    names = [
        item["name"]
        for item in body.get("paths") or []
        if item.get("path_type") == "Dir" and item.get("name")
    ]
    return find_max_version(names)
