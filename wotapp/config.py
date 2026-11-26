import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    sqlite_path: str
    mod_version_url: str
    scheduler_enabled: bool
    cors_origins: tuple[str, ...]


def get_settings() -> Settings:
    default_db = Path("data") / "wot.db"
    flag = os.environ.get("SCHEDULER_ENABLED", "1").lower()
    return Settings(
        sqlite_path=os.environ.get("SQLITE_PATH", str(default_db)),
        mod_version_url=os.environ.get(
            "MOD_VERSION_URL",
            "http://host.docker.internal:7003/wot/?json",
        ),
        scheduler_enabled=flag not in ("0", "false", "no"),
        cors_origins=("https://wot.src.moe",),
    )
