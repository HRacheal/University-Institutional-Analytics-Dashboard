"""Settings (environment variables, prefix UIAD_). No secret has a usable default in production mode."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"UIAD_{name}", default)


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("ENV", "development"))            # development | production | test
    project_root: Path = PROJECT_ROOT
    dw_root: Path = field(default_factory=lambda: Path(_env("DW_ROOT", str(PROJECT_ROOT / "data_warehouse"))))
    data_root: Path = field(default_factory=lambda: Path(_env("DATA_ROOT", str(PROJECT_ROOT / "data"))))
    var_dir: Path = field(default_factory=lambda: Path(_env("VAR_DIR", str(PROJECT_ROOT / "backend" / "var"))))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", ""))
    session_hours: float = field(default_factory=lambda: float(_env("SESSION_HOURS", "8")))
    session_idle_minutes: float = field(default_factory=lambda: float(_env("SESSION_IDLE_MINUTES", "60")))
    max_failed_logins: int = field(default_factory=lambda: int(_env("MAX_FAILED_LOGINS", "5")))
    lockout_minutes: int = field(default_factory=lambda: int(_env("LOCKOUT_MINUTES", "15")))
    cors_origins: tuple = field(default_factory=lambda: tuple(o for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o))
    # first-run bootstrap admin; the password must be changed at first login
    bootstrap_admin_user: str = field(default_factory=lambda: _env("BOOTSTRAP_ADMIN_USER", "admin"))
    bootstrap_admin_password: str | None = field(default_factory=lambda: _env("BOOTSTRAP_ADMIN_PASSWORD"))
    seed_demo_users: bool = field(default_factory=lambda: _env("SEED_DEMO_USERS", "1") == "1")
    max_upload_mb: float = field(default_factory=lambda: float(_env("MAX_UPLOAD_MB", "20")))
    max_batch_rows: int = field(default_factory=lambda: int(_env("MAX_BATCH_ROWS", "20000")))

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
