"""Login, logout, current user, password change."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import insert, select, update

from ..core import db
from ..core.config import get_settings
from ..core.deps import COOKIE, current_user
from ..core.security import (PASSWORD_RULE, audit, hash_password, new_token, password_problems, session_expiry,
                             verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


def _public(u: dict) -> dict:
    return {k: u[k] for k in ("username", "full_name", "email", "role", "department", "permissions", "must_change_password")}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    s = get_settings()
    ip = request.client.host if request.client else None
    u = db.fetch_one(select(db.users).where(db.users.c.username == body.username.strip()))
    generic = HTTPException(401, "invalid username or password")
    if not u or not u["is_active"]:
        verify_password(body.password, "scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")  # timing
        audit("login", username=body.username[:80], outcome="FAILED", detail={"reason": "unknown or inactive user"}, ip=ip)
        raise generic
    if u["locked_until"] and db.aware(u["locked_until"]) > db.now():
        audit("login", username=u["username"], outcome="LOCKED", ip=ip)
        raise HTTPException(423, f"account temporarily locked after repeated failed logins; try again later")
    if not verify_password(body.password, u["password_hash"]):
        fails = (u["failed_logins"] or 0) + 1
        vals = {"failed_logins": fails}
        if fails >= s.max_failed_logins:
            vals.update(locked_until=db.now() + timedelta(minutes=s.lockout_minutes), failed_logins=0)
        db.execute(update(db.users).where(db.users.c.id == u["id"]).values(**vals))
        audit("login", username=u["username"], outcome="FAILED", detail={"reason": "wrong password", "failed_count": fails}, ip=ip)
        raise generic
    tok, th = new_token()
    db.execute(insert(db.sessions).values(token_hash=th, user_id=u["id"], created_at=db.now(), last_seen=db.now(),
                                          expires_at=session_expiry(s.session_hours), ip=ip,
                                          user_agent=(request.headers.get("user-agent") or "")[:300], revoked=False))
    db.execute(update(db.users).where(db.users.c.id == u["id"]).values(failed_logins=0, locked_until=None, last_login=db.now()))
    audit("login", username=u["username"], outcome="OK", ip=ip)
    response.set_cookie(COOKIE, tok, httponly=True, samesite="strict", secure=s.env == "production", max_age=int(s.session_hours * 3600))
    perms = (db.fetch_one(select(db.roles.c.permissions).where(db.roles.c.role == u["role"])) or {}).get("permissions", [])
    return {"token": tok, "expires_in_hours": s.session_hours,
            "user": {"username": u["username"], "full_name": u["full_name"], "email": u["email"], "role": u["role"],
                     "department": u["department"], "permissions": sorted(perms), "must_change_password": u["must_change_password"]}}


@router.post("/logout")
def logout(response: Response, user: dict = Depends(current_user)):
    db.execute(update(db.sessions).where(db.sessions.c.token_hash == user["token_hash"]).values(revoked=True))
    audit("logout", user, ip=user["ip"])
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return _public(user)


@router.post("/change-password")
def change_password(body: PasswordIn, user: dict = Depends(current_user)):
    u = db.fetch_one(select(db.users).where(db.users.c.id == user["id"]))
    if not verify_password(body.current_password, u["password_hash"]):
        audit("change_password", user, outcome="FAILED", detail={"reason": "wrong current password"}, ip=user["ip"])
        raise HTTPException(400, "current password is incorrect")
    probs = password_problems(body.new_password, user["username"])
    if body.new_password == body.current_password:
        probs.append("must differ from the current password")
    if probs:
        raise HTTPException(422, {"message": f"password {PASSWORD_RULE}", "problems": probs})
    db.execute(update(db.users).where(db.users.c.id == user["id"]).values(password_hash=hash_password(body.new_password), must_change_password=False))
    # other sessions of this user are revoked
    db.execute(update(db.sessions).where((db.sessions.c.user_id == user["id"]) & (db.sessions.c.token_hash != user["token_hash"])).values(revoked=True))
    audit("change_password", user, ip=user["ip"])
    return {"ok": True}
