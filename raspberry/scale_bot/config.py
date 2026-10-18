"""Configuration from a TOML file (see config.example.toml) and environment variables."""
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

SEARCH_PATHS = (Path("config.toml"), Path("/etc/scale-bot.toml"))
# Environment variables win over the file: that is how Docker passes the settings
ENVIRONMENT = {
    "TELEGRAM_TOKEN": "telegram_token",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
    "SCALE_MAC": "scale_mac",
    "DATABASE": "database",
}


@dataclass(frozen=True)
class Config:
    path: Path | None = None
    database: str = "measurements.sqlite3"
    scale_mac: str | None = None
    telegram_token: str | None = None
    telegram_chat_id: int | str | None = None


def _load_file(path):
    if path is None:
        path = next((p for p in SEARCH_PATHS if p.is_file()), None)
        if path is None:
            return Config()
    path = Path(path)
    with path.open("rb") as f:
        data = tomllib.load(f)
    telegram, scale, storage = (data.get(k, {}) for k in ("telegram", "scale", "storage"))
    return Config(
        path=path,
        database=storage.get("database") or Config.database,
        scale_mac=scale.get("mac") or None,
        telegram_token=telegram.get("token") or None,
        telegram_chat_id=telegram.get("chat_id") or None,
    )


def load_config(path=None):
    """Reads the given file or, if none, the first of config.toml and /etc/scale-bot.toml."""
    config = _load_file(path)
    config = replace(config, **{field: os.environ[var] for var, field in ENVIRONMENT.items() if os.environ.get(var)})
    return replace(config, scale_mac=config.scale_mac.upper() if config.scale_mac else None)
