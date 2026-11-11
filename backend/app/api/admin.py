"""Administration: users, roles, audit log, settings, departmental integrations and synchronisation."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, insert, select, update

from ..analytics.common import clean
from ..core import db
from ..core.deps import require
from ..core.security import PASSWORD_RULE, PERMISSIONS, audit, hash_password, password_problems
from ..integrations import registry
from ..integrations.contracts import contracts

router = APIRouter(prefix="/api/admin", tags=["admin"])
DEPTS = (None, "ADMISSIONS", "FINANCE", "IT", "REGISTRAR", "MANAGEMENT")


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    full_name: str = Field("", max_length=160)
    email: str = Field("", max_length=200)
    role: str
    department: Optional[str] = None
    password: str = Field(min_length=1, max_length=200)


class UserPatch(BaseModel):
    full_name: Optional[str] = Field(None, max_length=160)
    email: Optional[str] = Field(None, max_length=200)
    role: Optional[str] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None


class ResetIn(BaseModel):
    new_password: str = Field(min_length=1, max_length=200)


class RoleIn(BaseModel):
    role: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z][A-Z0-9_]+$")
    description: str = Field(min_length=1, max_length=200)
    permissions: list[str]


class SettingIn(BaseModel):
    value: object


def _user_public(u: dict) -> dict:
    return {k: u[k] for k in ("id", "username", "full_name", "email", "role", "department", "is_active", "must_change_password",
                              "created_at", "last_login", "locked_until")}


def _check_role(role: str):
    if not db.fetch_one(select(db.roles.c.role).where(db.roles.c.role == role)):
        raise HTTPException(422, f"unknown role {role}")


# ------------------------------------------------------------------------------------------------ users
@router.get("/users")
def list_users(user=Depends(require("admin:users"))):
    return clean([_user_public(u) for u in db.fetch_all(select(db.users).order_by(db.users.c.username))])


@router.post("/users")
def create_user(body: UserIn, user=Depends(require("admin:users"))):
    _check_role(body.role)
    if body.department not in DEPTS:
        raise HTTPException(422, "invalid department")
    if db.fetch_one(select(db.users.c.id).where(db.users.c.username == body.username)):
        raise HTTPException(409, "username already exists")
    probs = password_problems(body.password, body.username)
    if probs:
        raise HTTPException(422, {"message": f"password {PASSWORD_RULE}", "problems": probs})
    db.execute(insert(db.users).values(username=body.username, full_name=body.full_name, email=body.email, role=body.role,
                                       department=body.department, password_hash=hash_password(body.password), is_active=True,
                                       must_change_password=True, failed_logins=0, created_at=db.now()))
    audit("create_user", user, target=body.username, detail={"role": body.role}, ip=user["ip"])
    return {"ok": True}


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, user=Depends(require("admin:users"))):
    u = db.fetch_one(select(db.users).where(db.users.c.id == uid))
    if not u:
        raise HTTPException(404, "user not found")
    vals = body.model_dump(exclude_none=True)
    if "role" in vals:
        _check_role(vals["role"])
    if "department" in vals and vals["department"] not in DEPTS:
        raise HTTPException(422, "invalid department")
    if u["id"] == user["id"] and (vals.get("is_active") is False or vals.get("role", "ADMIN") != "ADMIN"):
        raise HTTPException(422, "you cannot deactivate or demote your own account")
    if u["role"] == "ADMIN" and (vals.get("is_active") is False or vals.get("role", "ADMIN") != "ADMIN"):
        others = db.fetch_all(select(db.users.c.id).where((db.users.c.role == "ADMIN") & (db.users.c.is_active == True) & (db.users.c.id != uid)))  # noqa: E712
        if not others:
            raise HTTPException(422, "at least one active administrator must remain")
    if vals:
        db.execute(update(db.users).where(db.users.c.id == uid).values(**vals))
    if vals.get("is_active") is False or "role" in vals:
        db.execute(update(db.sessions).where(db.sessions.c.user_id == uid).values(revoked=True))
    audit("update_user", user, target=u["username"], detail=vals, ip=user["ip"])
    return {"ok": True}


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, body: ResetIn, user=Depends(require("admin:users"))):
    u = db.fetch_one(select(db.users).where(db.users.c.id == uid))
    if not u:
        raise HTTPException(404, "user not found")
    probs = password_problems(body.new_password, u["username"])
    if probs:
        raise HTTPException(422, {"message": f"password {PASSWORD_RULE}", "problems": probs})
    db.execute(update(db.users).where(db.users.c.id == uid).values(password_hash=hash_password(body.new_password), must_change_password=True,
                                                                  failed_logins=0, locked_until=None))
    db.execute(update(db.sessions).where(db.sessions.c.user_id == uid).values(revoked=True))
    audit("reset_password", user, target=u["username"], ip=user["ip"])
    return {"ok": True}


# ------------------------------------------------------------------------------------------------ roles
@router.get("/roles")
def list_roles(user=Depends(require("admin:roles"))):
    return {"roles": db.fetch_all(select(db.roles).order_by(db.roles.c.role)), "permissions": PERMISSIONS}


@router.post("/roles")
def upsert_role(body: RoleIn, user=Depends(require("admin:roles"))):
    bad = [p for p in body.permissions if p not in PERMISSIONS]
    if bad:
        raise HTTPException(422, f"unknown permissions {bad}")
    r = db.fetch_one(select(db.roles).where(db.roles.c.role == body.role))
    if r and r["is_system"]:
        raise HTTPException(422, "system roles cannot be modified")
    vals = {"description": body.description, "permissions": sorted(set(body.permissions))}
    if r:
        db.execute(update(db.roles).where(db.roles.c.role == body.role).values(**vals))
    else:
        db.execute(insert(db.roles).values(role=body.role, is_system=False, **vals))
    audit("upsert_role", user, target=body.role, detail=vals, ip=user["ip"])
    return {"ok": True}


@router.delete("/roles/{role}")
def delete_role(role: str, user=Depends(require("admin:roles"))):
    r = db.fetch_one(select(db.roles).where(db.roles.c.role == role))
    if not r:
        raise HTTPException(404, "role not found")
    if r["is_system"]:
        raise HTTPException(422, "system roles cannot be deleted")
    if db.fetch_one(select(db.users.c.id).where(db.users.c.role == role)):
        raise HTTPException(422, "role is assigned to users")
    db.execute(delete(db.roles).where(db.roles.c.role == role))
    audit("delete_role", user, target=role, ip=user["ip"])
    return {"ok": True}


# ------------------------------------------------------------------------------------------------ audit & settings
@router.get("/audit")
def audit_log(limit: int = Query(300, ge=1, le=2000), action: Optional[str] = None, username: Optional[str] = None,
              user=Depends(require("admin:audit"))):
    q = select(db.audit_log).order_by(desc(db.audit_log.c.id)).limit(limit)
    if action:
        q = q.where(db.audit_log.c.action == action)
    if username:
        q = q.where(db.audit_log.c.username == username)
    return clean(db.fetch_all(q))


@router.get("/settings")
def get_settings_(user=Depends(require("admin:settings"))):
    from ..core.config import get_settings
    s = get_settings()
    return clean({"stored": db.fetch_all(select(db.settings_table)),
                  "runtime": {"env": s.env, "session_hours": s.session_hours, "session_idle_minutes": s.session_idle_minutes,
                              "max_failed_logins": s.max_failed_logins, "lockout_minutes": s.lockout_minutes,
                              "max_upload_mb": s.max_upload_mb, "max_batch_rows": s.max_batch_rows,
                              "database": "postgresql" if s.database_url.startswith("postgres") else "sqlite",
                              "note": "Runtime settings come from UIAD_* environment variables and need a restart to change."}})


@router.put("/settings/{key}")
def put_setting(key: str, body: SettingIn, user=Depends(require("admin:settings"))):
    if key not in ("institution_name", "dashboard_notice", "risk_review_note"):
        raise HTTPException(422, "unsupported setting key")
    if db.fetch_one(select(db.settings_table.c.key).where(db.settings_table.c.key == key)):
        db.execute(update(db.settings_table).where(db.settings_table.c.key == key).values(value=body.value, updated_at=db.now(), updated_by=user["username"]))
    else:
        db.execute(insert(db.settings_table).values(key=key, value=body.value, updated_at=db.now(), updated_by=user["username"]))
    audit("update_setting", user, target=key, ip=user["ip"])
    return {"ok": True}


# ------------------------------------------------------------------------------------------------ integrations
@router.get("/integrations")
def integrations(user=Depends(require("admin:integrations"))):
    return clean({"integrations": registry.list_integrations(), "departments": registry.DEPARTMENTS, "data": registry.data_label()})


@router.get("/integrations/contracts")
def integration_contracts(user=Depends(require("admin:integrations"))):
    return contracts()


@router.post("/integrations/{iid}/import")
async def integration_import(iid: str, entity: str = Form(...), file: UploadFile = File(...), user=Depends(require("admin:integrations"))):
    from ..core.config import get_settings
    content = await file.read()
    if len(content) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "file too large")
    try:
        res = registry.import_csv(iid, entity, content, user["username"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit("integration_import", user, target=f"{iid}:{entity}", outcome="OK" if res["accepted"] else "REJECTED",
          detail={"file": file.filename}, ip=user["ip"])
    return clean(res)


@router.post("/integrations/{iid}/sync")
def integration_sync(iid: str, user=Depends(require("admin:sync"))):
    try:
        res = registry.sync_rest(iid, user["username"])
    except ValueError as e:
        audit("integration_sync", user, target=iid, outcome="FAILED", detail={"error": str(e)}, ip=user["ip"])
        raise HTTPException(422, str(e))
    audit("integration_sync", user, target=iid, ip=user["ip"])
    return clean(res)


@router.post("/integrations/{iid}/activate")
def integration_activate(iid: str, user=Depends(require("admin:integrations"))):
    try:
        res = registry.set_active(iid, user["username"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit("integration_activate", user, target=iid, ip=user["ip"])
    return clean(res)


@router.put("/integrations/{iid}/config")
def integration_config(iid: str, config: dict, user=Depends(require("admin:integrations"))):
    try:
        res = registry.update_config(iid, config, user["username"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit("integration_config", user, target=iid, detail={"keys": sorted(config)}, ip=user["ip"])
    return clean(res)


@router.get("/sync-runs")
def sync_runs(limit: int = Query(200, ge=1, le=1000), integration: Optional[str] = None, user=Depends(require("admin:sync"))):
    return clean(registry.sync_history(limit, integration))
