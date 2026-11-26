import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("wotapp")

SHANGHAI = ZoneInfo("Asia/Shanghai")


def retry(fn, count: int):
    """同步重试。次数用尽后抛出最后一次异常。"""
    if count <= 0:
        raise ValueError("retry count 必须大于 0")
    last_error = None
    for _ in range(count):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            logger.error("操作失败，将重试: %s", exc)
    assert last_error is not None
    raise last_error


def compare_version(v1: str, v2: str) -> int:
    """逐段比较版本号。大于返回 1，小于返回 -1，相等返回 0。"""
    i = j = 0
    n, m = len(v1), len(v2)
    while i < n or j < m:
        num1 = num2 = 0
        while i < n and v1[i] != ".":
            num1 = num1 * 10 + (ord(v1[i]) - 48)
            i += 1
        while j < m and v2[j] != ".":
            num2 = num2 * 10 + (ord(v2[j]) - 48)
            j += 1
        if num1 > num2:
            return 1
        if num1 < num2:
            return -1
        i += 1
        j += 1
    return 0


def find_max_version(versions: list[str] | None) -> str | None:
    if not versions:
        return None
    max_ver = versions[0]
    for current in versions[1:]:
        if compare_version(current, max_ver) > 0:
            max_ver = current
    return max_ver


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hour_bucket_utc(now: datetime | None = None) -> datetime:
    """上海时区当前整点，存成 UTC 的 naive datetime。"""
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    else:
        current = current.astimezone(SHANGHAI)
    bucket = current.replace(minute=0, second=0, microsecond=0)
    return bucket.astimezone(timezone.utc).replace(tzinfo=None)


def to_utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    millis = value.microsecond // 1000
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def num_from_text(text: str):
    """对齐 JS 一元加号：空串为 0，无法解析为 None。"""
    cleaned = text.strip().replace(",", "")
    if cleaned == "":
        return 0
    try:
        if "." in cleaned:
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return None


def as_int(value):
    if value is None or value == "":
        return None
    return int(value)
