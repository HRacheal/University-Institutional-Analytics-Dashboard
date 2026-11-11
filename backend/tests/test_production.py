"""Production-mode behaviour: first-run admin, no demo account or credentials file, security headers, hidden API docs,
secure cookies, login rate limiting, database URL handling and ADMIN/MANAGEMENT separation. Uses temporary databases.

Run from the backend folder:  ..\\.venv\\Scripts\\python -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

STRONG = "Prod-Bootstrap-Pass-91"
NEW = "Prod-Changed-Pass-92"
MGR = "Prod-Manager-Pass-93"


def _reset():
    from app.core import config, db, ratelimit
    db.reset_engine(); config.reset_settings(); ratelimit.reset_login_limiter()


@pytest.fixture
def env(tmp_path, monkeypatch):
    def apply(**kw):
        base = {"UIAD_ENV": "production", "UIAD_VAR_DIR": str(tmp_path / "var"), "UIAD_SEED_DEMO_USERS": "1"}
        base.update(kw)
        for k in ("UIAD_BOOTSTRAP_ADMIN_PASSWORD", "UIAD_DATABASE_URL", "UIAD_API_DOCS", "UIAD_LOGIN_RATE_LIMIT", "UIAD_CLIENT_IP_HEADERS", "UIAD_IMPORT_ACCOUNTS_FILE"):
            monkeypatch.delenv(k, raising=False)
        for k, v in base.items():
            monkeypatch.setenv(k, v)
        _reset()
        return tmp_path / "var"
    yield apply
    _reset()


def _client():
    from fastapi.testclient import TestClient
    from app.main import create_app
    return TestClient(create_app(), base_url="https://testserver")


def test_production_refuses_to_start_without_bootstrap_password(env):
    env()
    from app.core.bootstrap import BootstrapError
    with pytest.raises(BootstrapError, match="UIAD_BOOTSTRAP_ADMIN_PASSWORD"):
        with _client():
            pass


def test_production_rejects_weak_bootstrap_password(env):
    env(UIAD_BOOTSTRAP_ADMIN_PASSWORD="short")
    from app.core.bootstrap import BootstrapError
    with pytest.raises(BootstrapError, match="too weak"):
        with _client():
            pass


def test_production_first_run_headers_docs_cookie_and_rbac(env):
    var = env(UIAD_BOOTSTRAP_ADMIN_PASSWORD=STRONG)
    with _client() as c:
        # no credentials file, no demo MANAGEMENT account even though UIAD_SEED_DEMO_USERS=1
        assert not (var / "initial_credentials.txt").exists()
        from sqlalchemy import select
        from app.core import db
        assert [u["username"] for u in db.fetch_all(select(db.users))] == ["admin"]

        r = c.get("/api/health")
        assert r.status_code == 200 and r.json()["models_registered"] == 20
        h = r.headers
        assert "default-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]
        assert "script-src 'self';" in h["content-security-policy"]
        assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
        assert h["strict-transport-security"].startswith("max-age=")
        assert h["cache-control"] == "no-store"
        assert c.get("/api/docs").status_code == 404 and c.get("/api/openapi.json").status_code == 404

        r = c.post("/api/auth/login", json={"username": "admin", "password": STRONG})
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        a = {"Authorization": f"Bearer {r.json()['token']}"}
        assert c.get("/api/analytics/overview", headers=a).status_code == 403            # must change password first
        assert c.post("/api/auth/change-password", headers=a, json={"current_password": STRONG, "new_password": NEW}).status_code == 200

        # ADMIN and MANAGEMENT stay separate
        assert c.post("/api/admin/users", headers=a, json={"username": "mgr", "full_name": "M", "role": "MANAGEMENT", "password": MGR}).status_code == 200
        m = {"Authorization": f"Bearer {c.post('/api/auth/login', json={'username': 'mgr', 'password': MGR}).json()['token']}"}
        assert c.post("/api/auth/change-password", headers=m, json={"current_password": MGR, "new_password": MGR + "x"}).status_code == 200
        assert c.get("/api/analytics/overview", headers=m).status_code == 200
        for path in ("/api/admin/users", "/api/admin/audit", "/api/admin/settings", "/api/admin/roles"):
            assert c.get(path, headers=m).status_code == 403, path
            assert c.get(path, headers=a).status_code == 200, path


def test_bootstrap_password_ignored_once_admin_exists(env):
    env(UIAD_BOOTSTRAP_ADMIN_PASSWORD=STRONG)
    with _client():
        pass
    env()                                                   # second start, variable removed: must start normally
    with _client() as c:
        assert c.get("/api/health").status_code == 200


def test_login_rate_limit_per_address(env):
    env(UIAD_BOOTSTRAP_ADMIN_PASSWORD=STRONG, UIAD_LOGIN_RATE_LIMIT="3")
    with _client() as c:
        for _ in range(3):
            assert c.post("/api/auth/login", json={"username": "admin", "password": "wrong-Pass-1"}).status_code == 401
        r = c.post("/api/auth/login", json={"username": "admin", "password": STRONG})          # even the right password
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
        assert c.post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code == 429


def test_limiter_window_and_keys():
    from app.core.ratelimit import FailedLoginLimiter
    lim = FailedLoginLimiter(limit=2, window_seconds=0.2)
    lim.record_failure("1.1.1.1"); lim.record_failure("1.1.1.1")
    assert lim.retry_after("1.1.1.1") > 0 and lim.retry_after("2.2.2.2") == 0
    import time
    time.sleep(0.25)
    assert lim.retry_after("1.1.1.1") == 0


def test_development_keeps_docs_and_no_hsts(env):
    env(UIAD_ENV="development", UIAD_BOOTSTRAP_ADMIN_PASSWORD=STRONG)
    with _client() as c:
        assert c.get("/api/docs").status_code == 200
        assert "strict-transport-security" not in c.get("/api/health").headers


@pytest.mark.parametrize("raw, expected", [
    ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
    ("postgresql://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
    ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
    ("", ""),
])
def test_database_url_normalised(raw, expected):
    from app.core.config import normalize_database_url
    assert normalize_database_url(raw) == expected


def test_rate_limit_uses_trusted_client_ip_header_only_when_configured(env):
    env(UIAD_BOOTSTRAP_ADMIN_PASSWORD=STRONG, UIAD_LOGIN_RATE_LIMIT="2", UIAD_CLIENT_IP_HEADERS="True-Client-IP,CF-Connecting-IP")
    with _client() as c:
        bad = {"username": "nobody", "password": "x"}
        for _ in range(2):
            assert c.post("/api/auth/login", json=bad, headers={"True-Client-IP": "203.0.113.5"}).status_code == 401
        assert c.post("/api/auth/login", json=bad, headers={"True-Client-IP": "203.0.113.5"}).status_code == 429
        # a different real client is unaffected; a forged X-Forwarded-For does not change the key
        assert c.post("/api/auth/login", json=bad, headers={"True-Client-IP": "203.0.113.6"}).status_code == 401
        assert c.post("/api/auth/login", json=bad, headers={"True-Client-IP": "203.0.113.5", "X-Forwarded-For": "1.2.3.4"}).status_code == 429
        assert c.post("/api/auth/login", json=bad, headers={"CF-Connecting-IP": "198.51.100.9"}).status_code == 401


def test_client_ip_headers_ignored_when_not_configured(env):
    env(UIAD_BOOTSTRAP_ADMIN_PASSWORD=STRONG, UIAD_LOGIN_RATE_LIMIT="2")
    with _client() as c:
        bad = {"username": "nobody", "password": "x"}
        for i in range(2):
            assert c.post("/api/auth/login", json=bad, headers={"True-Client-IP": f"203.0.113.{i}"}).status_code == 401
        assert c.post("/api/auth/login", json=bad, headers={"True-Client-IP": "203.0.113.99"}).status_code == 429


# ------------------------------------------------------------------------------------------- account migration
def _make_source_db(tmp_path):
    """A 'local' installation with an ADMIN and a MANAGEMENT account whose passwords were already changed."""
    import sqlite3
    from datetime import datetime, timezone
    from app.core import db
    from app.core.security import SYSTEM_ROLES, hash_password
    src = tmp_path / "local.db"
    from sqlalchemy import create_engine, insert
    eng = create_engine(f"sqlite:///{src}")
    db.metadata.create_all(eng)
    now = datetime.now(timezone.utc)
    with eng.begin() as c:
        for role, (desc, perms) in SYSTEM_ROLES.items():
            c.execute(insert(db.roles).values(role=role, description=desc, permissions=perms, is_system=True))
        c.execute(insert(db.users).values(username="admin", full_name="Local Admin", email="", password_hash=hash_password(NEW), role="ADMIN",
                                          is_active=True, must_change_password=False, failed_logins=0, created_at=now, last_login=now))
        c.execute(insert(db.users).values(username="manager", full_name="Local Manager", email="", password_hash=hash_password(MGR), role="MANAGEMENT",
                                          department="REGISTRAR", is_active=True, must_change_password=False, failed_logins=2, created_at=now))
    eng.dispose()
    return src


def _export(src, out):
    from app.core.accounts import main
    assert main(["export", "--db", str(src), "--out", str(out)]) == 0


def test_account_export_is_read_only_and_never_prints_hashes(tmp_path, capsys):
    import hashlib, json
    src = _make_source_db(tmp_path)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    _export(src, tmp_path / "accounts.json")
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before                    # source database untouched
    printed = capsys.readouterr().out
    data = json.loads((tmp_path / "accounts.json").read_text())
    assert [u["username"] for u in data["users"]] == ["admin", "manager"]
    assert all(u["password_hash"] not in printed and "scrypt$" not in printed for u in data["users"])


def test_migrated_accounts_sign_in_without_bootstrap_password(env, tmp_path, caplog):
    import logging
    src = _make_source_db(tmp_path)
    acc = tmp_path / "accounts.json"
    _export(src, acc)
    caplog.set_level(logging.INFO)
    var = env(UIAD_IMPORT_ACCOUNTS_FILE=str(acc))                     # production, NO bootstrap password
    with _client() as c:
        from sqlalchemy import select
        from app.core import db
        users = db.fetch_all(select(db.users).order_by(db.users.c.username))
        assert [(u["username"], u["role"], u["is_active"], u["must_change_password"]) for u in users] == \
            [("admin", "ADMIN", True, False), ("manager", "MANAGEMENT", True, False)]
        assert users[1]["department"] == "REGISTRAR" and users[1]["failed_logins"] == 0
        assert not (var / "initial_credentials.txt").exists()
        # same credentials work; no forced password change because it was already done locally
        a = {"Authorization": f"Bearer {c.post('/api/auth/login', json={'username': 'admin', 'password': NEW}).json()['token']}"}
        m = {"Authorization": f"Bearer {c.post('/api/auth/login', json={'username': 'manager', 'password': MGR}).json()['token']}"}
        assert c.get("/api/admin/users", headers=a).status_code == 200
        assert c.get("/api/analytics/overview", headers=m).status_code == 200
        for path in ("/api/admin/users", "/api/admin/audit", "/api/admin/settings"):
            assert c.get(path, headers=m).status_code == 403
        assert "predictions:run" in c.get("/api/auth/me", headers=m).json()["permissions"]
        audit = db.fetch_all(select(db.audit_log).where(db.audit_log.c.action == "account_import"))
        assert len(audit) == 1 and "scrypt$" not in str(audit)
    assert "scrypt$" not in caplog.text and "created=['admin', 'manager']" in caplog.text

    # restart with the file still configured: no duplicates; a password changed online is never overwritten
    env(UIAD_IMPORT_ACCOUNTS_FILE=str(acc))
    with _client() as c:
        a = {"Authorization": f"Bearer {c.post('/api/auth/login', json={'username': 'admin', 'password': NEW}).json()['token']}"}
        assert c.post("/api/auth/change-password", headers=a, json={"current_password": NEW, "new_password": "Online-Changed-77"}).status_code == 200
        assert len(db.fetch_all(select(db.users))) == 2
    env(UIAD_IMPORT_ACCOUNTS_FILE=str(acc))
    with _client() as c:
        assert len(db.fetch_all(select(db.users))) == 2
        assert c.post("/api/auth/login", json={"username": "admin", "password": "Online-Changed-77"}).status_code == 200
        assert c.post("/api/auth/login", json={"username": "admin", "password": NEW}).status_code == 401

    # secret file removed afterwards: starts normally
    env(UIAD_IMPORT_ACCOUNTS_FILE=str(tmp_path / "gone.json"))
    with _client() as c:
        assert c.get("/api/health").status_code == 200


def test_import_rejects_malformed_file_and_unknown_role(env, tmp_path):
    import json
    from app.core.accounts import AccountImportError
    src = _make_source_db(tmp_path)
    acc = tmp_path / "accounts.json"
    _export(src, acc)
    data = json.loads(acc.read_text())
    data["users"][1]["role"] = "SUPERUSER"
    bad = tmp_path / "bad_role.json"; bad.write_text(json.dumps(data))
    env(UIAD_IMPORT_ACCOUNTS_FILE=str(bad))
    with pytest.raises(AccountImportError, match="SUPERUSER"):
        with _client():
            pass
    from sqlalchemy import select
    from app.core import db
    assert db.fetch_all(select(db.users)) == []                       # all-or-nothing: admin was not half-imported
    data["users"][1]["role"] = "MANAGEMENT"; data["users"][1]["password_hash"] = "plaintext"
    bad.write_text(json.dumps(data))
    env(UIAD_IMPORT_ACCOUNTS_FILE=str(bad))
    with pytest.raises(AccountImportError, match="hash format"):
        with _client():
            pass


def test_export_refuses_unignored_path_in_repository(tmp_path):
    import shutil, subprocess
    if not shutil.which("git") or subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=BACKEND,
                                                 capture_output=True).returncode != 0:
        pytest.skip("not running inside a git checkout (e.g. the Docker image): nothing could be committed")
    from app.core.accounts import main
    src = _make_source_db(tmp_path)
    assert main(["export", "--db", str(src), "--out", str(BACKEND / "app" / "accounts_leak.json")]) == 2
    assert not (BACKEND / "app" / "accounts_leak.json").exists()
