"""Departmental integrations: connector records, data access for the analytics layer, imports and synchronisation.

Connector kinds
  sample      clearly labelled SYNTHETIC sample data shipped with the project (data/synthetic/...). Default source.
  csv_import  approved CSV extracts uploaded by an administrator, validated against the data contract, stored under
              backend/var/imports/<integration>/<entity>.csv with a sync-run record.
  rest_api    pull from a departmental REST API (GET <base_url>/<endpoint> -> JSON array of records), validated against the
              same contract. Ships UNCONFIGURED ("AWAITING_INTEGRATION"); no live connection is assumed or simulated.
              Credentials are never stored: config holds only the NAME of an environment variable with the token.
Exactly one integration per department is the active source; switching it clears the analytics cache.
"""
from __future__ import annotations

import io
import json
import threading
import urllib.request
from pathlib import Path

import pandas as pd
from sqlalchemy import insert, select, update

from ..core import db
from ..core.config import get_settings
from .contracts import DASHBOARD_ENTITIES, contracts, validate

DEPARTMENTS = {
    "ADMISSIONS": "Applications, offers, acceptances, new student enrolment",
    "FINANCE": "Fee charges and payments, outstanding balances, financial holds, payment completion",
    "IT": "Accounts and user access, login activity, system status, incidents, data infrastructure",
    "REGISTRAR": "Student records, registration, programmes, courses, grades, standing, progression, retention, graduation",
}
SAMPLE_LABEL = "SYNTHETIC SAMPLE DATA — demonstration only, not real university records"
_lock = threading.Lock()
_cache: dict = {}
_listeners: list = []


def on_source_change(fn):
    _listeners.append(fn)
    return fn


def seed_integrations():
    for dep in DEPARTMENTS:
        d = dep.lower()
        rows = [(f"{d}-sample", f"{dep.title()} — synthetic sample dataset", "sample", "ACTIVE", True, {"path": "data/synthetic"}),
                (f"{d}-csv", f"{dep.title()} — approved CSV extracts", "csv_import", "AWAITING_INTEGRATION", False, {}),
                (f"{d}-api", f"{dep.title()} — departmental REST API", "rest_api", "AWAITING_INTEGRATION", False,
                 {"base_url": "", "auth_env_var": f"UIAD_{dep}_API_TOKEN", "timeout_seconds": 30,
                  "endpoints": {e: e.split("/")[1] for e in DASHBOARD_ENTITIES[dep]}})]
        for iid, name, kind, status, active, cfg in rows:
            if not db.fetch_one(select(db.integrations.c.id).where(db.integrations.c.id == iid)):
                db.execute(insert(db.integrations).values(id=iid, department=dep, name=name, connector=kind, status=status,
                                                          is_active_source=active, config=cfg, entities=DASHBOARD_ENTITIES[dep],
                                                          updated_at=db.now(), updated_by="system"))


def list_integrations() -> list[dict]:
    rows = db.fetch_all(select(db.integrations).order_by(db.integrations.c.department, db.integrations.c.id))
    for r in rows:
        r["imported_entities"] = sorted(_imported(r["id"]))
        r["missing_entities"] = [e for e in r["entities"] if r["connector"] != "sample" and e not in r["imported_entities"]]
    return rows


def get_integration(iid: str) -> dict | None:
    return db.fetch_one(select(db.integrations).where(db.integrations.c.id == iid))


def import_dir(iid: str) -> Path:
    p = get_settings().var_dir / "imports" / iid
    p.mkdir(parents=True, exist_ok=True)
    return p


def _imported(iid: str) -> set[str]:
    d = get_settings().var_dir / "imports" / iid
    return {f"{p.parent.name}/{p.stem}" for p in d.glob("*/*.csv")} if d.exists() else set()


def active_source(department: str) -> dict:
    r = db.fetch_one(select(db.integrations).where((db.integrations.c.department == department) & (db.integrations.c.is_active_source == True)))  # noqa: E712
    return r or {"id": f"{department.lower()}-sample", "connector": "sample", "name": "sample"}


def department_of(entity: str) -> str:
    c = contracts().get(entity)
    if not c:
        raise KeyError(f"no data contract for {entity}")
    return c["department"]


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False, keep_default_na=False, na_values=[""])


def table(entity: str) -> pd.DataFrame:
    """The active source's copy of an entity (cached on path + modification time). Callers must not mutate it."""
    src = active_source(department_of(entity))
    path = (get_settings().data_root / "synthetic" / f"{entity}.csv") if src["connector"] == "sample" else import_dir(src["id"]) / f"{entity}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{entity} is not available from the active {department_of(entity)} source {src['id']}")
    key = (entity, str(path), path.stat().st_mtime_ns)
    with _lock:
        if key not in _cache:
            for k in [k for k in _cache if k[0] == entity]:
                del _cache[k]
            _cache[key] = _read_csv(path)
        return _cache[key]


def data_label(department: str | None = None) -> dict:
    deps = [department] if department else list(DEPARTMENTS)
    out = {}
    for d in deps:
        s = active_source(d)
        out[d] = {"source": s["id"], "connector": s["connector"],
                  "label": SAMPLE_LABEL if s["connector"] == "sample" else f"IMPORTED DATA from {s['name']} (last sync {s.get('last_sync_at')})"}
    synthetic = all(v["connector"] == "sample" for v in out.values())
    return {"is_sample_data": synthetic, "label": SAMPLE_LABEL if synthetic else "Mixed / imported departmental data — see sources",
            "sources": out}


# ---------------------------------------------------------------------------------------------------- import / sync
def _record_run(iid, entity, status, user, received=None, accepted=None, report=None, error=None, started=None):
    db.execute(insert(db.sync_runs).values(integration_id=iid, started_at=started or db.now(), finished_at=db.now(), status=status,
                                           triggered_by=user, entity=entity, rows_received=received, rows_accepted=accepted,
                                           validation=report, error=error))
    db.execute(update(db.integrations).where(db.integrations.c.id == iid).values(last_sync_at=db.now(), last_sync_status=status, updated_at=db.now()))


def _store(iid: str, entity: str, df: pd.DataFrame, connector_label: str):
    df = df.copy()
    for col in ("data_source", "source_system"):
        df[col] = connector_label if col == "data_source" else iid
    p = import_dir(iid) / f"{entity}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    df.to_csv(tmp, index=False)
    tmp.replace(p)


def import_csv(iid: str, entity: str, content: bytes, user: str) -> dict:
    integ = get_integration(iid)
    if not integ or integ["connector"] != "csv_import":
        raise ValueError(f"{iid} is not a CSV-import integration")
    if entity not in integ["entities"]:
        raise ValueError(f"{entity} is not an entity of {integ['department']}")
    started = db.now()
    try:
        df = pd.read_csv(io.BytesIO(content), low_memory=False, keep_default_na=False, na_values=[""], dtype=str)
    except Exception as e:
        _record_run(iid, entity, "REJECTED", user, error=f"unreadable CSV: {e}"[:500], started=started)
        raise ValueError(f"unreadable CSV: {e}") from e
    rep = validate(df, entity)
    if not rep["valid"]:
        _record_run(iid, entity, "REJECTED", user, received=len(df), accepted=0, report=rep, started=started)
        return {"accepted": False, "validation": rep}
    _store(iid, entity, df, "IMPORTED_CSV")
    _record_run(iid, entity, "SUCCESS", user, received=len(df), accepted=len(df), report=rep, started=started)
    if not [e for e in integ["entities"] if e not in _imported(iid)]:
        db.execute(update(db.integrations).where(db.integrations.c.id == iid).values(status="READY"))
    return {"accepted": True, "validation": rep}


def sync_rest(iid: str, user: str) -> dict:
    integ = get_integration(iid)
    if not integ or integ["connector"] != "rest_api":
        raise ValueError(f"{iid} is not a REST API integration")
    cfg = integ["config"] or {}
    if not cfg.get("base_url"):
        _record_run(iid, None, "FAILED", user, error="AWAITING_INTEGRATION: base_url not configured")
        raise ValueError("awaiting integration: the departmental API base_url is not configured")
    import os
    token = os.environ.get(cfg.get("auth_env_var", ""), "")
    results = {}
    for entity, endpoint in (cfg.get("endpoints") or {}).items():
        started = db.now()
        try:
            req = urllib.request.Request(f"{cfg['base_url'].rstrip('/')}/{endpoint.lstrip('/')}",
                                         headers={"Accept": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
            with urllib.request.urlopen(req, timeout=float(cfg.get("timeout_seconds", 30))) as r:
                payload = json.loads(r.read().decode())
            df = pd.DataFrame(payload if isinstance(payload, list) else payload.get("records", [])).astype(str).replace({"None": ""})
            rep = validate(df, entity)
            if rep["valid"]:
                _store(iid, entity, df, "IMPORTED_API")
            _record_run(iid, entity, "SUCCESS" if rep["valid"] else "REJECTED", user, len(df), len(df) if rep["valid"] else 0, rep, started=started)
            results[entity] = rep
        except Exception as e:
            _record_run(iid, entity, "FAILED", user, error=repr(e)[:500], started=started)
            results[entity] = {"valid": False, "errors": [repr(e)[:300]]}
    return results


def set_active(iid: str, user: str) -> dict:
    integ = get_integration(iid)
    if not integ:
        raise ValueError("unknown integration")
    missing = [e for e in integ["entities"] if integ["connector"] != "sample" and e not in _imported(iid)]
    if missing:
        raise ValueError(f"cannot activate {iid}: entities not yet imported/synchronised: {missing}")
    with db.get_engine().begin() as c:
        c.execute(update(db.integrations).where(db.integrations.c.department == integ["department"]).values(is_active_source=False))
        c.execute(update(db.integrations).where(db.integrations.c.id == iid).values(is_active_source=True, status="ACTIVE",
                                                                                     updated_at=db.now(), updated_by=user))
    with _lock:
        _cache.clear()
    for fn in _listeners:
        fn()
    return get_integration(iid)


def update_config(iid: str, config: dict, user: str) -> dict:
    integ = get_integration(iid)
    if not integ:
        raise ValueError("unknown integration")
    if integ["connector"] != "rest_api":
        raise ValueError("only REST API integrations have editable configuration")
    allowed = {"base_url", "auth_env_var", "timeout_seconds", "endpoints"}
    bad = set(config) - allowed
    if bad:
        raise ValueError(f"unsupported configuration keys {sorted(bad)} (secrets must be supplied as environment variables)")
    if config.get("base_url") and not str(config["base_url"]).startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise ValueError("base_url must use https (plain http only for localhost testing)")
    new = {**(integ["config"] or {}), **config}
    db.execute(update(db.integrations).where(db.integrations.c.id == iid).values(config=new, updated_at=db.now(), updated_by=user))
    return get_integration(iid)


def sync_history(limit: int = 200, iid: str | None = None) -> list[dict]:
    q = select(db.sync_runs).order_by(db.sync_runs.c.id.desc()).limit(limit)
    if iid:
        q = q.where(db.sync_runs.c.integration_id == iid)
    return db.fetch_all(q)
