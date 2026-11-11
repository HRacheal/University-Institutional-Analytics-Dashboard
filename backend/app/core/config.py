"""Settings (environment variables, prefix UIAD_). No secret has a usable default in production mode."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"UIAD_{name}", default)


def _is_prod() -> bool:
    return (_env("ENV", "development") or "").lower() == "production"


def normalize_database_url(url: str) -> str:
    """Hosting providers (e.g. Render) hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the psycopg 3 driver name."""
    url = (url or "").strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("ENV", "development"))            # development | production | test
    project_root: Path = PROJECT_ROOT
    dw_root: Path = field(default_factory=lambda: Path(_env("DW_ROOT", str(PROJECT_ROOT / "data_warehouse"))))
    data_root: Path = field(default_factory=lambda: Path(_env("DATA_ROOT", str(PROJECT_ROOT / "data"))))
    var_dir: Path = field(default_factory=lambda: Path(_env("VAR_DIR", str(PROJECT_ROOT / "backend" / "var"))))
    database_url: str = field(default_factory=lambda: normalize_database_url(_env("DATABASE_URL", "")))
    session_hours: float = field(default_factory=lambda: float(_env("SESSION_HOURS", "8")))
    session_idle_minutes: float = field(default_factory=lambda: float(_env("SESSION_IDLE_MINUTES", "60")))
    max_failed_logins: int = field(default_factory=lambda: int(_env("MAX_FAILED_LOGINS", "5")))
    lockout_minutes: int = field(default_factory=lambda: int(_env("LOCKOUT_MINUTES", "15")))
    cors_origins: tuple = field(default_factory=lambda: tuple(o for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o))
    # first-run bootstrap admin; the password must be changed at first login
    bootstrap_admin_user: str = field(default_factory=lambda: _env("BOOTSTRAP_ADMIN_USER", "admin"))
    bootstrap_admin_password: str | None = field(default_factory=lambda: _env("BOOTSTRAP_ADMIN_PASSWORD"))
    # The demo MANAGEMENT account is never created in production (its random password could only be delivered via a file).
    seed_demo_users: bool = field(default_factory=lambda: not _is_prod() and _env("SEED_DEMO_USERS", "1") == "1")
    max_upload_mb: float = field(default_factory=lambda: float(_env("MAX_UPLOAD_MB", "20")))
    max_batch_rows: int = field(default_factory=lambda: int(_env("MAX_BATCH_ROWS", "20000")))
    # Interactive API docs (/api/docs, /api/openapi.json): off by default in production.
    api_docs: bool = field(default_factory=lambda: _env("API_DOCS", "0" if _is_prod() else "1") == "1")
    # Failed sign-ins allowed per client IP within the window before HTTP 429 (in addition to the per-account lockout).
    login_rate_limit: int = field(default_factory=lambda: int(_env("LOGIN_RATE_LIMIT", "20")))
    login_rate_window_minutes: float = field(default_factory=lambda: float(_env("LOGIN_RATE_WINDOW_MINUTES", "15")))
    # Headers set by a trusted edge proxy that carry the real client IP, first present wins (e.g. on Render, which sits
    # behind Cloudflare: "True-Client-IP,CF-Connecting-IP"). Leave empty when not behind such a proxy: clients could
    # otherwise forge them. X-Forwarded-For is deliberately not used here because its leftmost entry is client-supplied.
    # Accounts exported with `python -m app.core.accounts export`, imported at startup if their usernames are new
    # (on Render: a Secret File at /etc/secrets/uiad_accounts.json). A missing file is skipped.
    import_accounts_file: str = field(default_factory=lambda: _env("IMPORT_ACCOUNTS_FILE", "") or "")
    client_ip_headers: list[str] = field(default_factory=lambda: [h.strip() for h in (_env("CLIENT_IP_HEADERS", "") or "").split(",") if h.strip()])

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.var_dir / 'uiad.db').as_posix()}"

    @property
    def frontend_dist(self) -> Path:
        return self.project_root / "frontend" / "dist"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.var_dir.mkdir(parents=True, exist_ok=True)
    return _settings


def reset_settings():                       # tests
    global _settings
    _settings = None
