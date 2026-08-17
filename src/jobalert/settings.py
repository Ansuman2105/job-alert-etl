"""Configuration, loaded from environment variables only.

Nothing in this file reads a credential from disk in production — GitHub Actions
injects secrets as environment variables. `.env` is a local-development
convenience and is gitignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

load_dotenv(REPO_ROOT / ".env")


class ConfigError(RuntimeError):
    """A required setting is missing or malformed."""


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set. Locally: add it to .env. "
            f"In CI: add it under Settings -> Secrets and variables -> Actions."
        )
    return value


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    database_url: str
    llm_provider: str
    groq_api_key: str
    groq_model: str
    gemini_api_key: str
    gemini_model: str
    telegram_bot_token: str
    telegram_channel_id: str
    telegram_alert_channel_id: str
    enrich_limit: int
    publish_limit: int
    publish_batch_size: int

    @classmethod
    def load(cls) -> Settings:
        provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
        if provider not in {"groq", "gemini"}:
            raise ConfigError(f"LLM_PROVIDER must be 'groq' or 'gemini', got {provider!r}")

        return cls(
            database_url=_require("DATABASE_URL"),
            llm_provider=provider,
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
            groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip(),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip(),
            telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
            telegram_channel_id=_require("TELEGRAM_CHANNEL_ID"),
            telegram_alert_channel_id=os.getenv("TELEGRAM_ALERT_CHANNEL_ID", "").strip(),
            enrich_limit=_int("ENRICH_LIMIT", 250),
            publish_limit=_int("PUBLISH_LIMIT", 60),
            publish_batch_size=_int("PUBLISH_BATCH_SIZE", 5),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.load()


@lru_cache(maxsize=1)
def load_companies() -> dict:
    with open(CONFIG_DIR / "companies.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def load_profile() -> dict:
    with open(CONFIG_DIR / "profile.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_channels() -> dict[str, str]:
    """Map each route name to the Telegram channel it publishes to.

    profile.yaml stores the *name* of an environment variable, never the value,
    so channel IDs stay in GitHub Secrets. A route whose variable is unset falls
    back to TELEGRAM_CHANNEL_ID — that keeps a single-channel setup working and
    means a half-finished migration degrades to "everything in one place"
    rather than silently dropping jobs.
    """
    routing = load_profile().get("routing", {})
    mapping = routing.get("channels") or {}
    if not mapping:
        return {"default": _require("TELEGRAM_CHANNEL_ID")}

    fallback = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    resolved: dict[str, str] = {}
    for route, env_name in mapping.items():
        value = os.getenv(env_name, "").strip() or fallback
        if not value:
            raise ConfigError(
                f"Route {route!r} needs {env_name} (or TELEGRAM_CHANNEL_ID as a fallback). "
                f"Add it under Settings -> Secrets and variables -> Actions."
            )
        resolved[route] = value
    return resolved
