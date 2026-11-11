"""Request dependencies: current user from the session token, permission checks."""
from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update

from . import db
from .config import get_settings
from .security import token_hash

COOKIE = "uiad_session"


def _token(request: Request) -> str | None:
    h = request.headers.get("Authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return request.cookies.get(COOKIE)


def current_user(request: Request) -> dict:
    tok = _token(request)
    if not tok:
        raise HTTPException(401, "not authenticated")
    th = token_hash(tok)
    row = db.fetch_one(select(db.sessions, db.users.c.username, db.users.c.role, db.users.c.full_name, db.users.c.is_active,
                              db.users.c.must_change_password, db.users.c.department, db.users.c.email)
                       .join(db.users, db.users.c.id == db.sessions.c.user_id).where(db.sessions.c.token_hash == th))
    s = get_settings()
    now = db.now()
    if (not row or row["revoked"] or not row["is_active"] or db.aware(row["expires_at"]) <= now
            or db.aware(row["last_seen"]) + timedelta(minutes=s.session_idle_minutes) <= now):
        raise HTTPException(401, "session expired or invalid")
    db.execute(update(db.sessions).where(db.sessions.c.token_hash == th).values(last_seen=now))
    perms = db.fetch_one(select(db.roles.c.permissions).where(db.roles.c.role == row["role"]))
    return {"id": row["user_id"], "username": row["username"], "role": row["role"], "full_name": row["full_name"],
            "email": row["email"], "department": row["department"], "must_change_password": row["must_change_password"],
            "permissions": sorted((perms or {}).get("permissions") or []), "token_hash": th,
            "ip": request.client.host if request.client else None}


def require(*perms: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if user["must_change_password"]:
            raise HTTPException(403, "password change required before using the dashboard")
        missing = [p for p in perms if p not in user["permissions"]]
        if missing:
            from .security import audit
            audit("permission_denied", user, target=",".join(missing), outcome="DENIED", ip=user["ip"])
            raise HTTPException(403, f"missing permission: {', '.join(missing)}")
        return user
    return dep
