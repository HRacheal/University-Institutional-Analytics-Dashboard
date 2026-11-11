"""Move existing dashboard accounts (with their password hashes) from one database to another, e.g. local -> Render.

Export (local, read-only; the source database is opened with SQLite mode=ro and never written):
    cd backend
    ..\\.venv\\Scripts\\python -m app.core.accounts export            # -> var/render_accounts.json (git-ignored)

Import (server start): set UIAD_IMPORT_ACCOUNTS_FILE to the file (on Render: a Secret File, /etc/secrets/uiad_accounts.json).
At startup, before the administrator check, every exported account whose username does not exist yet is inserted with
the same password hash, role and status. Existing usernames are never overwritten or duplicated. A missing file is
skipped, so the Secret File can be deleted after the first successful start.

Password hashes are scrypt strings that carry their own parameters and salt, so they verify identically on any platform.
Nothing in this module prints or logs a hash or password; only usernames, roles and outcomes.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FORMAT = "uiad-accounts/1"
USER_FIELDS = ("username", "full_name", "email", "department", "role", "is_active", "must_change_password", "created_at",
               "last_login", "password_hash")
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
log = logging.getLogger("uiad.accounts")


class AccountImportError(RuntimeError):
    """The account file is unreadable or malformed; startup stops rather than half-importing."""


# ------------------------------------------------------------------------------------------------------------- helpers
def _valid_hash(h) -> bool:
    if not isinstance(h, str):
        return False
    parts = h.split("$")
    return len(parts) == 6 and parts[0] == "scrypt" and all(p.isdigit() for p in parts[1:4]) and all(parts[4:])


def _iso(v) -> str | None:
    if v in (None, ""):
        return None
    dt = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _dt(v) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


# -------------------------------------------------------------------------------------------------------------- export
def export_accounts(db_path: Path, usernames: list[str] | None = None) -> dict:
    """Read accounts from a SQLite database file without modifying it."""
    db_path = Path(db_path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    con = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        roles = {r["role"]: sorted(json.loads(r["permissions"])) for r in con.execute("SELECT role, permissions FROM roles")}
        rows = [dict(r) for r in con.execute(f"SELECT {', '.join(USER_FIELDS)} FROM users ORDER BY id")]
    finally:
        con.close()
    if usernames:
        missing = sorted(set(usernames) - {r["username"] for r in rows})
        if missing:
            raise ValueError(f"not in the database: {', '.join(missing)}")
        rows = [r for r in rows if r["username"] in usernames]
    users = []
    for r in rows:
        if not _valid_hash(r["password_hash"]):
            raise ValueError(f"account {r['username']!r} has an unrecognised password hash format")
        users.append({**r, "is_active": bool(r["is_active"]), "must_change_password": bool(r["must_change_password"]),
                      "created_at": _iso(r["created_at"]), "last_login": _iso(r["last_login"]),
                      "role_permissions": roles.get(r["role"], [])})
    return {"format": FORMAT, "exported_at": datetime.now(timezone.utc).isoformat(), "users": users}


def _git_tracked_or_unignored(path: Path) -> bool:
    """True if the path is inside a git work tree and NOT ignored (i.e. could be committed)."""
    try:
        r = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=path.parent, capture_output=True, timeout=10)
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path.parent, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return inside.returncode == 0 and r.returncode == 1


# -------------------------------------------------------------------------------------------------------------- import
def load_account_file(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        raise AccountImportError(f"cannot read account file {path}: {type(ex).__name__}") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("users"), list):
        raise AccountImportError(f"account file {path} is not a {FORMAT} export")
    seen = set()
    for u in data["users"]:
        if not isinstance(u, dict) or not all(k in u for k in USER_FIELDS):
            raise AccountImportError("account file has an incomplete account entry")
        if not isinstance(u["username"], str) or not _USERNAME.match(u["username"]) or u["username"] in seen:
            raise AccountImportError("account file has an invalid or duplicated username")
        if not _valid_hash(u["password_hash"]):
            raise AccountImportError(f"account {u['username']!r}: unrecognised password hash format")
        seen.add(u["username"])
    return data


def import_accounts(path: Path) -> dict:
    """Insert exported accounts that do not exist yet. Returns {"created": [...], "skipped": [...], "conflicts": [...]}."""
    from sqlalchemy import insert, select

    from . import db
    data = load_account_file(path)
    roles = {r["role"]: sorted(r["permissions"] or []) for r in db.fetch_all(select(db.roles))}
    unknown = sorted({u["role"] for u in data["users"]} - set(roles))
    if unknown:
        raise AccountImportError(f"account file uses roles that do not exist here: {', '.join(unknown)}")
    out = {"created": [], "skipped": [], "conflicts": [], "permission_differences": []}
    with db.get_engine().begin() as c:                                   # all or nothing
        for u in data["users"]:
            existing = c.execute(select(db.users.c.password_hash).where(db.users.c.username == u["username"])).first()
            if existing is not None:
                (out["skipped"] if existing[0] == u["password_hash"] else out["conflicts"]).append(u["username"])
                continue
            c.execute(insert(db.users).values(
                username=u["username"], full_name=u["full_name"] or "", email=u["email"] or "", department=u["department"],
                role=u["role"], password_hash=u["password_hash"], is_active=bool(u["is_active"]),
                must_change_password=bool(u["must_change_password"]), failed_logins=0, locked_until=None,
                created_at=_dt(u["created_at"]) or db.now(), last_login=_dt(u["last_login"])))
            out["created"].append(u["username"])
            if sorted(u.get("role_permissions") or []) != roles[u["role"]]:
                out["permission_differences"].append(u["role"])
    return out


def import_from_settings() -> dict | None:
    """Called by bootstrap. Logs usernames and outcomes only."""
    from .config import get_settings
    from .security import audit
    path = get_settings().import_accounts_file
    if not path:
        return None
    if not Path(path).exists():
        log.info("account import: %s not present, nothing to import", path)
        return None
    res = import_accounts(Path(path))
    log.info("account import: created=%s already_present=%s", res["created"], res["skipped"])
    if res["conflicts"]:
        log.warning("account import: %s already exist here with a different password; left unchanged", res["conflicts"])
    if res["permission_differences"]:
        log.warning("account import: role permissions differ from the exporting system for %s; this server's role "
                    "definitions apply", sorted(set(res["permission_differences"])))
    if res["created"] or res["conflicts"]:
        audit("account_import", username="system", target=",".join(res["created"]) or None,
              detail={"created": res["created"], "already_present": res["skipped"], "conflicts": res["conflicts"]})
    return res


# ----------------------------------------------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    from .config import get_settings
    ap = argparse.ArgumentParser(prog="python -m app.core.accounts", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="export accounts (read-only) to a JSON file for UIAD_IMPORT_ACCOUNTS_FILE")
    ex.add_argument("--db", type=Path, default=None, help="SQLite database (default: UIAD_VAR_DIR/uiad.db)")
    ex.add_argument("--out", type=Path, default=None, help="output file (default: UIAD_VAR_DIR/render_accounts.json)")
    ex.add_argument("--users", default=None, help="comma-separated usernames (default: all accounts)")
    a = ap.parse_args(argv)
    s = get_settings()
    src = a.db or (s.var_dir / "uiad.db")
    out = (a.out or (s.var_dir / "render_accounts.json")).resolve()
    if _git_tracked_or_unignored(out):
        print(f"refusing to write {out}: it is inside the repository and not git-ignored (choose a path under backend/var "
              "or outside the project)", file=sys.stderr)
        return 2
    data = export_accounts(src, [u.strip() for u in a.users.split(",")] if a.users else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    print(f"exported {len(data['users'])} account(s) from {src} (opened read-only) to {out}:")
    for u in data["users"]:
        print(f"  {u['username']:<20} {u['role']:<12} active={u['is_active']} must_change_password={u['must_change_password']}")
    print("The file contains password hashes: do not commit, e-mail or paste it. Upload it to Render as the Secret File "
          "'uiad_accounts.json', then delete the local copy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
