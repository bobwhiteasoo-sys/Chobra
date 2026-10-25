"""Settings from environment variables. No secrets have defaults that look real."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("CHOBRA_DATABASE_URL", "postgresql+psycopg://chobra_app@127.0.0.1:54329/chobra"))
    owner_database_url: str = field(default_factory=lambda: _env("CHOBRA_OWNER_DATABASE_URL", "postgresql+psycopg://chobra_owner@127.0.0.1:54329/chobra"))
    auth_mode: str = field(default_factory=lambda: _env("CHOBRA_AUTH_MODE", "dev"))
    oidc_issuer: str = field(default_factory=lambda: _env("CHOBRA_OIDC_ISSUER", ""))
    oidc_client_id: str = field(default_factory=lambda: _env("CHOBRA_OIDC_CLIENT_ID", ""))
    oidc_client_secret: str = field(default_factory=lambda: _env("CHOBRA_OIDC_CLIENT_SECRET", ""))
    oidc_redirect_uri: str = field(default_factory=lambda: _env("CHOBRA_OIDC_REDIRECT_URI", "http://localhost:3100/api/v1/auth/oidc/callback"))
    oidc_allow_insecure_localhost: bool = field(default_factory=lambda: _env("CHOBRA_OIDC_ALLOW_INSECURE_LOCALHOST", "0") == "1")
    public_url: str = field(default_factory=lambda: _env("CHOBRA_PUBLIC_URL", "http://localhost:3100"))
    secure_cookies: bool = field(default_factory=lambda: _env("CHOBRA_SECURE_COOKIES", "0") == "1")
    session_idle_hours: int = field(default_factory=lambda: int(_env("CHOBRA_SESSION_IDLE_HOURS", "12")))
    session_max_days: int = field(default_factory=lambda: int(_env("CHOBRA_SESSION_MAX_DAYS", "7")))
    signing_key: str = field(default_factory=lambda: _env("CHOBRA_SIGNING_KEY", ""))
    secrets_key: str = field(default_factory=lambda: _env("CHOBRA_SECRETS_KEY", ""))
    objects_dir: Path = field(default_factory=lambda: Path(_env("CHOBRA_OBJECTS_DIR", str(ROOT / ".objects"))))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY", ""))
    telegram_bot_token: str = field(default_factory=lambda: _env("CHOBRA_TELEGRAM_BOT_TOKEN", ""))
    telegram_bot_username: str = field(default_factory=lambda: _env("CHOBRA_TELEGRAM_BOT_USERNAME", "chobraAI"))
    telegram_polling: bool = field(default_factory=lambda: _env("CHOBRA_TELEGRAM_POLLING", "0") == "1")
    access_recheck_seconds: int = 10
    sse_heartbeat_seconds: int = 15
    workspace_concurrent_runs: int = 4

    @property
    def dev_auth(self) -> bool:
        return self.auth_mode == "dev"


settings = Settings()
