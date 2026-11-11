"""Password hashing (scrypt), session tokens, permissions and the audit trail."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from sqlalchemy import insert

from . import db

# -------------------------------------------------------------------------------------------------- permissions / roles
PERMISSIONS = {
    "analytics:read": "View institutional dashboards (enrolment, performance, retention, graduation, admissions, finance)",
    "student_level:read": "View student-level predictions and anomaly lists (pseudonymous IDs; every access is audited)",
    "predictions:run": "Run model predictions (single record, CSV batch, cohort scoring)",
    "predictions:history": "View prediction history and download prediction results",
    "models:read": "View model information, evaluation reports and restoration status",
    "reports:export": "Generate and download reports and data exports",
    "admin:users": "Create, edit, deactivate users and reset passwords",
    "admin:roles": "Create roles and assign permissions",
    "admin:integrations": "Configure departmental data integrations and import approved CSV data",
    "admin:sync": "Monitor and trigger data synchronisation",
    "admin:settings": "Manage system settings",
    "admin:audit": "Review system activity and audit logs",
}
SYSTEM_ROLES = {
    "ADMIN": ("System administrator: all permissions", sorted(PERMISSIONS)),
    "MANAGEMENT": ("Management user: institutional analytics, reports and AI predictions; no administrative privileges",
                   ["analytics:read", "student_level:read", "predictions:run", "predictions:history", "models:read", "reports:export"]),
}

# -------------------------------------------------------------------------------------------------- passwords
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
PASSWORD_RULE = "at least 10 characters with upper- and lower-case letters and a digit"


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:
        return False


def password_problems(pw: str, username: str = "") -> list[str]:
    out = []
    if len(pw) < 10:
        out.append("must be at least 10 characters")
    if not re.search(r"[a-z]", pw) or not re.search(r"[A-Z]", pw):
        out.append("must contain upper- and lower-case letters")
    if not re.search(r"\d", pw):
        out.append("must contain a digit")
    if username and username.lower() in pw.lower():
        out.append("must not contain the username")
    return out


# -------------------------------------------------------------------------------------------------- session tokens
def new_token() -> tuple[str, str]:
    t = secrets.token_urlsafe(32)
    return t, token_hash(t)


def token_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def session_expiry(hours: float):
    return db.now() + timedelta(hours=hours)


# -------------------------------------------------------------------------------------------------- audit trail
def audit(action: str, user: dict | None = None, target: str | None = None, outcome: str = "OK", detail: dict | None = None,
          ip: str | None = None, username: str | None = None):
    db.execute(insert(db.audit_log).values(ts=db.now(), username=(user or {}).get("username", username), role=(user or {}).get("role"),
                                           action=action, target=target, outcome=outcome, detail=detail, ip=ip))
