from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
API_BASE_URL = "https://api.sx.bet"
TARGET_REPOSITORY = "https://github.com/aimidas1/transactions_sxbet.git"
TARGET_REPOSITORY_SLUG = "aimidas1/transactions_sxbet"


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    root: Path
    api_key: str
    github_token: str | None
    db_path: Path
    data_root: Path
    api_base_url: str = API_BASE_URL
    market_page_size: int = 100
    trade_page_size: int = 300
    market_hash_group_size: int = 40
    interval_seconds: int = 3600
    request_timeout: int = 60


def get_settings(require_github: bool = False) -> Settings:
    _load_dotenv()
    api_key = os.getenv("sxbet_apikey") or os.getenv("SX_BET_API")
    if not api_key:
        raise RuntimeError("Missing sxbet_apikey (or compatible SX_BET_API) in the environment")

    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("pat")
    if require_github and not github_token:
        raise RuntimeError("Missing GitHub token in GITHUB_TOKEN, GH_TOKEN or pat")

    return Settings(
        root=ROOT,
        api_key=api_key,
        github_token=github_token,
        db_path=ROOT / "sxbet.db",
        data_root=ROOT / "data" / "sxbet",
    )
