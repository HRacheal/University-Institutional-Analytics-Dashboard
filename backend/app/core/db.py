"""Application database (users, roles, sessions, audit log, prediction history, integrations, sync runs, settings).

SQLAlchemy Core: SQLite by default (backend/var/uiad.db), PostgreSQL by setting UIAD_DATABASE_URL.
Institutional data is NOT stored here: it comes from the departmental connectors (see app/integrations).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text,
                        create_engine, event, insert, select)
from sqlalchemy.engine import Engine

from .config import get_settings

metadata = MetaData()

roles = Table("roles", metadata,
              Column("role", String(40), primary_key=True),
              Column("description", String(200), nullable=False),
              Column("permissions", JSON, nullable=False),
              Column("is_system", Boolean, nullable=False, default=False))

users = Table("users", metadata,
              Column("id", Integer, primary_key=True),
              Column("username", String(80), unique=True, nullable=False),
              Column("full_name", String(160), nullable=False, default=""),
              Column("email", String(200), nullable=False, default=""),
              Column("password_hash", String(300), nullable=False),
              Column("role", String(40), ForeignKey("roles.role"), nullable=False),
              Column("department", String(40), nullable=True),
              Column("is_active", Boolean, nullable=False, default=True),
              Column("must_change_password", Boolean, nullable=False, default=False),
              Column("failed_logins", Integer, nullable=False, default=0),
              Column("locked_until", DateTime(timezone=True), nullable=True),
              Column("created_at", DateTime(timezone=True), nullable=False),
              Column("last_login", DateTime(timezone=True), nullable=True))

sessions = Table("sessions", metadata,
                 Column("token_hash", String(64), primary_key=True),
                 Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                 Column("created_at", DateTime(timezone=True), nullable=False),
                 Column("last_seen", DateTime(timezone=True), nullable=False),
                 Column("expires_at", DateTime(timezone=True), nullable=False),
                 Column("ip", String(64), nullable=True),
                 Column("user_agent", String(300), nullable=True),
                 Column("revoked", Boolean, nullable=False, default=False))

audit_log = Table("audit_log", metadata,
                  Column("id", Integer, primary_key=True),
                  Column("ts", DateTime(timezone=True), nullable=False),
                  Column("username", String(80), nullable=True),
                  Column("role", String(40), nullable=True),
                  Column("action", String(80), nullable=False),
                  Column("target", String(200), nullable=True),
                  Column("outcome", String(20), nullable=False, default="OK"),
                  Column("detail", JSON, nullable=True),
                  Column("ip", String(64), nullable=True))

prediction_runs = Table("prediction_runs", metadata,
                        Column("id", Integer, primary_key=True),
                        Column("ts", DateTime(timezone=True), nullable=False),
                        Column("username", String(80), nullable=False),
                        Column("task", String(80), nullable=False),
                        Column("model", String(80), nullable=False),
                        Column("mode", String(20), nullable=False),          # single | batch | cohort
                        Column("n_rows", Integer, nullable=False),
                        Column("input_name", String(200), nullable=True),
                        Column("summary", JSON, nullable=True),
                        Column("result_file", String(300), nullable=True))

integrations = Table("integrations", metadata,
                     Column("id", String(60), primary_key=True),
                     Column("department", String(20), nullable=False),     # ADMISSIONS | FINANCE | IT | REGISTRAR
                     Column("name", String(160), nullable=False),
                     Column("connector", String(30), nullable=False),      # sample | csv_import | rest_api
                     Column("status", String(30), nullable=False),         # ACTIVE | AWAITING_INTEGRATION | DISABLED | ERROR
                     Column("is_active_source", Boolean, nullable=False, default=False),
                     Column("config", JSON, nullable=False),               # never secrets; secrets are env var NAMES
                     Column("entities", JSON, nullable=False),
                     Column("last_sync_at", DateTime(timezone=True), nullable=True),
                     Column("last_sync_status", String(30), nullable=True),
                     Column("updated_at", DateTime(timezone=True), nullable=False),
                     Column("updated_by", String(80), nullable=True))

sync_runs = Table("sync_runs", metadata,
                  Column("id", Integer, primary_key=True),
                  Column("integration_id", String(60), ForeignKey("integrations.id"), nullable=False),
                  Column("started_at", DateTime(timezone=True), nullable=False),
                  Column("finished_at", DateTime(timezone=True), nullable=True),
                  Column("status", String(20), nullable=False),            # RUNNING | SUCCESS | FAILED | REJECTED
                  Column("triggered_by", String(80), nullable=True),
                  Column("entity", String(80), nullable=True),
                  Column("rows_received", Integer, nullable=True),
                  Column("rows_accepted", Integer, nullable=True),
                  Column("validation", JSON, nullable=True),
                  Column("error", Text, nullable=True))

settings_table = Table("settings", metadata,
                       Column("key", String(80), primary_key=True),
                       Column("value", JSON, nullable=False),
                       Column("updated_at", DateTime(timezone=True), nullable=False),
                       Column("updated_by", String(80), nullable=True))

_engine: Engine | None = None


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt):
    """SQLite returns naive datetimes; everything is stored in UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().db_url
        kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        _engine = create_engine(url, future=True, json_serializer=lambda o: json.dumps(o, default=str), **kw)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _fk(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
    return _engine


def reset_engine():                            # tests
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def init_db():
    metadata.create_all(get_engine())


def fetch_all(stmt) -> list[dict]:
    with get_engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(stmt)]


def fetch_one(stmt) -> dict | None:
    with get_engine().connect() as c:
        r = c.execute(stmt).first()
        return dict(r._mapping) if r else None


def execute(stmt):
    with get_engine().begin() as c:
        return c.execute(stmt)


__all__ = ["roles", "users", "sessions", "audit_log", "prediction_runs", "integrations", "sync_runs", "settings_table",
           "get_engine", "init_db", "fetch_all", "fetch_one", "execute", "now", "aware", "insert", "select", "Float"]
