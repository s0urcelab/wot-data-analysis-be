import httpx
from bs4 import BeautifulSoup

from wotapp.util import num_from_text

_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def build_player(pid: int, pn: str) -> dict:
    with httpx.Client(timeout=30, headers=_HEADERS) as client:
        summary_res = client.get(
            "https://wotgame.cn/wotup/profile/summary/",
            params={"spa_id": pid, "battle_type": "random", "wtr_disabled": 1},
        )
        summary_res.raise_for_status()
        summary = summary_res.json()["data"]

        wotbox_res = client.get(
            "https://wotbox.ouj.com/wotbox/index.php",
            params={"r": "default/index", "pn": pn},
        )
        wotbox_res.raise_for_status()
        html = wotbox_res.text

    soup = BeautifulSoup(html, "html.parser")
    eff_node = soup.select_one(".power .num")
    delta_node = soup.select_one(".power .float-num")
    return {
        "battTotal": summary.get("battles_count"),
        "winRate": summary.get("wins_ratio"),
        "wgr": summary.get("global_rating"),
        "eff": num_from_text(eff_node.get_text() if eff_node else ""),
        "effDelta": num_from_text(delta_node.get_text() if delta_node else ""),
    }


def search_accounts(nickname: str) -> list:
    with httpx.Client(timeout=30, headers=_HEADERS) as client:
        res = client.get(
            "https://wotgame.cn/zh-cn/community/accounts/search/",
            params={"name": nickname},
        )
        res.raise_for_status()
        body = res.json()
    return body.get("response") or []


def fetch_garage(player_id: int) -> list[dict]:
    payload = {
        "battle_type": "random",
        "only_in_garage": False,
        "spa_id": player_id,
        "premium": [0, 1],
        "collector_vehicle": [0, 1],
        "nation": [],
        "role": [],
        "type": [],
        "tier": [],
        "language": "zh-cn",
    }
    with httpx.Client(timeout=30, headers=_HEADERS) as client:
        res = client.post(
            "https://wotgame.cn/wotup/profile/vehicles/list/",
            json=payload,
        )
        res.raise_for_status()
        block = res.json()["data"]
    parameters = block["parameters"]
    return [dict(zip(parameters, row)) for row in block["data"]]
