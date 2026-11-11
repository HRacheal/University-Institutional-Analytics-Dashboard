"""First-run setup: system roles, bootstrap administrator, optional demo management user, default integrations.

No password is hard-coded. Unless UIAD_BOOTSTRAP_ADMIN_PASSWORD is set, random initial passwords are generated and
written once to backend/var/initial_credentials.txt (git-ignored); both accounts must change their password at first login.

Accounts exported from another installation are imported first (UIAD_IMPORT_ACCOUNTS_FILE, see accounts.py), so a
migrated administrator satisfies the check below and no new administrator is created.

Production (UIAD_ENV=production): no credentials file is ever written and no demo account is created. If no administrator
exists yet (none imported either), UIAD_BOOTSTRAP_ADMIN_PASSWORD must be set (as a hosting secret) and meet the password rule, otherwise startup
fails with an explanatory error. Once an administrator exists, the variable is ignored and can be removed.
"""
from __future__ import annotations

import secrets
import string

from sqlalchemy import insert, select, update

from . import db
from .config import get_settings
from .security import PASSWORD_RULE, SYSTEM_ROLES, hash_password, password_problems


class BootstrapError(RuntimeError):
    """Raised at startup when production cannot create its first administrator safely."""


def _random_password() -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(alphabet) for _ in range(14))
        if any(c.islower() for c in p) and any(c.isupper() for c in p) and any(c.isdigit() for c in p):
            return p


def bootstrap() -> dict:
    s = get_settings()
    db.init_db()
    for role, (desc, perms) in SYSTEM_ROLES.items():
        if db.fetch_one(select(db.roles).where(db.roles.c.role == role)):
            db.execute(update(db.roles).where(db.roles.c.role == role).values(permissions=perms, description=desc, is_system=True))
        else:
            db.execute(insert(db.roles).values(role=role, description=desc, permissions=perms, is_system=True))
    from .accounts import import_from_settings
    import_from_settings()                      # migrated accounts first, so an imported administrator counts below
    created = {}
    if not db.fetch_one(select(db.users.c.id).where(db.users.c.role == "ADMIN")):
        if s.is_production:
            if not s.bootstrap_admin_password:
                raise BootstrapError("No administrator exists yet. Either import existing accounts (UIAD_IMPORT_ACCOUNTS_FILE "
                                     "pointing to a file from `python -m app.core.accounts export`; currently "
                                     f"{'not set' if not s.import_accounts_file else 'set, but the file is missing or has no ADMIN account'}) "
                                     "or set UIAD_BOOTSTRAP_ADMIN_PASSWORD as a secret environment variable for the first start "
                                     "(no credentials file is written in production).")
            probs = password_problems(s.bootstrap_admin_password, s.bootstrap_admin_user)
            if probs:
                raise BootstrapError(f"UIAD_BOOTSTRAP_ADMIN_PASSWORD is too weak: it must be {PASSWORD_RULE} "
                                     f"({'; '.join(probs)}).")
        pw = s.bootstrap_admin_password or _random_password()
        db.execute(insert(db.users).values(username=s.bootstrap_admin_user, full_name="System Administrator", email="", password_hash=hash_password(pw),
                                           role="ADMIN", is_active=True, must_change_password=True, failed_logins=0, created_at=db.now()))
        created[s.bootstrap_admin_user] = ("ADMIN", None if s.bootstrap_admin_password else pw)
        if s.seed_demo_users and not db.fetch_one(select(db.users.c.id).where(db.users.c.username == "manager")):
            mp = _random_password()
            db.execute(insert(db.users).values(username="manager", full_name="Demo Management User", email="", password_hash=hash_password(mp),
                                               role="MANAGEMENT", is_active=True, must_change_password=True, failed_logins=0, created_at=db.now()))
            created["manager"] = ("MANAGEMENT", mp)
    if created and any(v[1] for v in created.values()) and not s.is_production:
        f = s.var_dir / "initial_credentials.txt"
        lines = ["# Initial credentials (generated once). Each account must change its password at first login.",
                 "# Delete this file after the first login."]
        lines += [f"{u}\t{r}\t{p}" for u, (r, p) in created.items() if p]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    from ..integrations.registry import seed_integrations
    seed_integrations()
    return {"created_users": sorted(created)}
