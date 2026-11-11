"""End-to-end API tests against the real saved model artifacts, in a temporary database.

Run from the backend folder:  ..\\.venv\\Scripts\\python -m pytest tests -q
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

ADMIN_PW, NEW_ADMIN_PW, MGR_PW = "Initial-Pass-123", "Changed-Pass-456", "Manager-Pass-789"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    var = tmp_path_factory.mktemp("var")
    os.environ.update({"UIAD_VAR_DIR": str(var), "UIAD_BOOTSTRAP_ADMIN_PASSWORD": ADMIN_PW, "UIAD_SEED_DEMO_USERS": "0", "UIAD_ENV": "test"})
    from app.core import config, db
    config.reset_settings(); db.reset_engine()
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c
    db.reset_engine(); config.reset_settings()


def login(c, user, pw):
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def admin(client):
    h = login(client, "admin", ADMIN_PW)
    assert client.get("/api/analytics/overview", headers=h).status_code == 403          # must change password first
    r = client.post("/api/auth/change-password", headers=h, json={"current_password": ADMIN_PW, "new_password": NEW_ADMIN_PW})
    assert r.status_code == 200, r.text
    return h


@pytest.fixture(scope="module")
def manager(client, admin):
    r = client.post("/api/admin/users", headers=admin, json={"username": "mgr", "full_name": "M", "role": "MANAGEMENT", "password": MGR_PW})
    assert r.status_code == 200, r.text
    h = login(client, "mgr", MGR_PW)
    client.post("/api/auth/change-password", headers=h, json={"current_password": MGR_PW, "new_password": MGR_PW + "x"})
    return h


# ------------------------------------------------------------------------------------------------ auth & RBAC
def test_health_and_unauthenticated(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["models_registered"] == 20
    assert client.get("/api/analytics/overview").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401


def test_weak_password_rejected(client, admin):
    r = client.post("/api/admin/users", headers=admin, json={"username": "weak", "role": "MANAGEMENT", "password": "short"})
    assert r.status_code == 422


def test_management_has_no_admin_access(client, manager):
    assert client.get("/api/admin/users", headers=manager).status_code == 403
    assert client.get("/api/admin/integrations", headers=manager).status_code == 403
    me = client.get("/api/auth/me", headers=manager).json()
    assert me["role"] == "MANAGEMENT" and "admin:users" not in me["permissions"]


def test_lockout_after_failed_logins(client, admin):
    r = client.post("/api/admin/users", headers=admin, json={"username": "lock", "role": "MANAGEMENT", "password": "Tempest-Pass-1"})
    assert r.status_code == 200, r.text
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "lock", "password": "bad-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "lock", "password": "Tempest-Pass-1"}).status_code == 423


def test_audit_log_records_actions(client, admin):
    acts = {r["action"] for r in client.get("/api/admin/audit", headers=admin).json()}
    assert {"login", "change_password", "create_user"} <= acts


# ------------------------------------------------------------------------------------------------ analytics
@pytest.mark.parametrize("path", ["/api/analytics/options", "/api/analytics/overview", "/api/analytics/enrollment",
                                  "/api/analytics/performance", "/api/analytics/performance/attention",
                                  "/api/analytics/retention?comparison=SPRING_TO_SPRING", "/api/analytics/graduation",
                                  "/api/analytics/admissions", "/api/analytics/finance", "/api/analytics/it",
                                  "/api/analytics/enrollment?school_id=SENG&gender=FEMALE"])
def test_analytics_endpoints(client, manager, path):
    r = client.get(path, headers=manager)
    assert r.status_code == 200, r.text[:300]
    assert r.json()


def test_analytics_export_csv(client, manager):
    r = client.get("/api/analytics/export/enrollment.csv", headers=manager)
    assert r.status_code == 200 and r.text.startswith("# enrollment export")


def test_invalid_retention_comparison(client, manager):
    assert client.get("/api/analytics/retention?comparison=WINTER", headers=manager).status_code == 422


# ------------------------------------------------------------------------------------------------ models & predictions
def test_model_catalogue_lists_all_tasks_with_warnings(client, manager):
    m = client.get("/api/models", headers=manager).json()
    tasks = {t["task"]: t for t in m["tasks"]}
    assert len(tasks) == 20
    assert all(t["artifact_present"] for t in tasks.values() if t["selected_model"])
    assert any("Weak discrimination" in w for w in tasks["syn_admissions_accept"]["warnings"])
    assert tasks["syn_retention_fall_to_fall_institutional"]["cohort_available"] is False


def test_model_detail_and_figure(client, manager):
    d = client.get("/api/models/syn_dropout_2y", headers=manager).json()
    assert d["evaluation"]["models"] and d["limitations"] and d["figures"]
    assert client.get(f"/api/figures/{d['figures'][0]}", headers=manager).headers["content-type"] == "image/png"
    # Path traversal must never return the database: the client normalises "../" (the request then falls to the SPA
    # index or a 404), and an encoded traversal reaching the figures route itself must be refused.
    for url in ("/api/figures/../../backend/var/uiad.db", "/api/figures/%2e%2e/%2e%2e/backend/var/uiad.db",
                "/api/figures/reports/%2e%2e/%2e%2e/backend/var/uiad.db"):
        r = client.get(url, headers=manager)
        assert b"SQLite format" not in r.content and r.headers["content-type"] != "image/png", url
        assert r.status_code == 404 or r.headers["content-type"].startswith("text/html"), url
    assert client.get("/api/figures/artifacts/artifact_manifest.json", headers=manager).status_code == 404


@pytest.mark.parametrize("task", ["syn_next_term_academic_risk", "uci_outcome3_end_of_year1", "syn_next_term_gpa",
                                  "syn_admissions_accept", "syn_retention_summer_to_summer_programme"])
def test_single_prediction_from_schema(client, manager, task):
    s = client.get(f"/api/models/{task}/schema", headers=manager).json()
    r = client.post(f"/api/predict/{task}", headers=manager, json={"rows": [s["example"]], "explain": True})
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert j["run_id"] > 0 and j["label"] and j["decision_support"] and len(j["rows"]) == 1
    row = j["rows"][0]
    if j["kind"] == "binary":
        assert 0 <= row["probability_class1"] <= 1 and row["band"] in ("HIGH", "ELEVATED", "LOW", "LIKELY", "UNLIKELY")
        assert row["predicted_class_original_threshold"] == int(row["probability_class1"] >= j["thresholds"]["original_p_class1"])
    if j["kind"] == "regression":
        assert 0 <= row["prediction"] <= 4.5
    assert row.get("top_factors")


def test_survival_prediction(client, manager):
    df = pd.read_csv(BACKEND.parent / "data/processed/modeling/synthetic/syn_dropout_survival.csv", nrows=3)
    r = client.post("/api/predict/syn_dropout_cox", headers=manager, json={"rows": df.astype(object).where(df.notna(), None).to_dict("records")})
    assert r.status_code == 200, r.text[:300]
    assert all(x["relative_hazard"] > 0 for x in r.json()["rows"])


def test_explanations_are_not_cancelled(client, manager):
    """Per-record attributions must point towards class 1 (binary) - averaging the two classes would give exact zeros."""
    s = client.get("/api/models/syn_dropout_2y/schema", headers=manager).json()
    r = client.post("/api/predict/syn_dropout_2y", headers=manager, json={"rows": [s["example"]], "explain": True})
    f = r.json()["rows"][0]["top_factors"]
    assert len(f) == 8 and max(abs(x["contribution"]) for x in f) > 1e-3


def test_survival_schema_example_is_reference_point(client, manager):
    """The form's neutral example for a Cox model = training means, so its relative hazard is 1 (the reference)."""
    for task in ("syn_dropout_cox", "syn_graduation_cox"):
        s = client.get(f"/api/models/{task}/schema", headers=manager).json()
        assert s["example"] and all(v is not None for v in s["example"].values())
        r = client.post(f"/api/predict/{task}", headers=manager, json={"rows": [s["example"]]})
        assert r.status_code == 200, r.text[:300]
        assert abs(r.json()["rows"][0]["relative_hazard"] - 1.0) < 1e-6


def test_prediction_input_validation(client, manager):
    r = client.post("/api/predict/syn_next_term_academic_risk", headers=manager, json={"rows": [{"foo": 1}]})
    assert r.status_code == 422 and r.json()["details"]["missing_columns"]
    s = client.get("/api/models/syn_next_term_gpa/schema", headers=manager).json()
    bad = {**s["example"], "term_gpa": "not-a-number"}
    assert client.post("/api/predict/syn_next_term_gpa", headers=manager, json={"rows": [bad]}).status_code == 422
    assert client.post("/api/predict/forecasting", headers=manager, json={"rows": [{}]}).status_code in (404, 503)
    assert client.post("/api/predict/nope", headers=manager, json={"rows": [{}]}).status_code == 404


def test_csv_batch_prediction_and_download(client, manager):
    task = "syn_dropout_2y"
    tpl = client.get(f"/api/models/{task}/template.csv", headers=manager).text
    df = pd.read_csv(io.StringIO(tpl))
    df = pd.concat([df] * 5, ignore_index=True)
    df["record_id"] = [f"r{i}" for i in range(5)]
    df.loc[2, df.columns[1]] = None                                   # missing value handled by the saved imputer
    r = client.post(f"/api/predict/{task}/batch", headers=manager, files={"file": ("in.csv", df.to_csv(index=False), "text/csv")})
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert j["summary"]["n"] == 5 and [x["id"] for x in j["rows"]] == [f"r{i}" for i in range(5)]
    d = client.get(f"/api/predictions/{j['run_id']}/download", headers=manager)
    assert d.status_code == 200 and "DEMONSTRATION" in d.text.splitlines()[0] and "record_id" in d.text
    assert client.post(f"/api/predict/{task}/batch", headers=manager, files={"file": ("x.txt", "a,b", "text/plain")}).status_code == 422
    assert client.post(f"/api/predict/{task}/batch", headers=manager, files={"file": ("e.csv", "", "text/csv")}).status_code == 422


def test_cohort_prediction_and_history(client, manager, admin):
    r = client.post("/api/predict/syn_next_term_academic_risk/cohort", headers=manager)
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert j["summary"]["n"] > 1000 and j["rows"][0]["id"].startswith("SYN-") and j["cohort_rule"]
    assert client.post("/api/predict/syn_retention_fall_to_fall_institutional/cohort", headers=manager).status_code == 422
    runs = client.get("/api/predictions", headers=manager).json()["runs"]
    assert {x["mode"] for x in runs} >= {"single", "batch", "cohort"}
    # another user's runs are not downloadable by a management user
    other = client.post("/api/predict/syn_next_term_gpa", headers=admin,
                        json={"rows": [client.get("/api/models/syn_next_term_gpa/schema", headers=admin).json()["example"]]}).json()
    assert client.get(f"/api/predictions/{other['run_id']}/download", headers=manager).status_code == 404


# ------------------------------------------------------------------------------------------------ forecasting, segmentation, admin
def test_forecasts(client, manager):
    f = client.get("/api/forecasts", headers=manager).json()
    assert len(f["series_families"]) == 13 and f["validation"]["selected_non_finite"] == 0
    assert all(x["forecast"] is not None and x["forecast"] >= 0 for x in f["selected_forecasts"])
    h = client.get("/api/forecasts/history?series=enrolment_headcount:TOTAL", headers=manager).json()
    assert len(h["history"]) > 10


def test_segmentation(client, manager):
    s = client.get("/api/segmentation", headers=manager).json()
    assert sum(s["segment_sizes"].values()) == s["n_students"] and s["limitations"]
    assert any("not evidence" in x.lower() or "not evidence" in x for x in s["limitations"])


def test_admin_integrations_and_roles(client, admin):
    i = client.get("/api/admin/integrations", headers=admin).json()
    assert {x["department"] for x in i["integrations"]} == {"ADMISSIONS", "FINANCE", "IT", "REGISTRAR"}
    rest = next(x for x in i["integrations"] if x["connector"] == "rest_api")
    assert client.post(f"/api/admin/integrations/{rest['id']}/sync", headers=admin).status_code == 422     # awaiting integration
    assert client.put(f"/api/admin/integrations/{rest['id']}/config", headers=admin, json={"password": "x"}).status_code == 422
    r = client.post("/api/admin/roles", headers=admin, json={"role": "ANALYST", "description": "read only", "permissions": ["analytics:read"]})
    assert r.status_code == 200
    assert client.post("/api/admin/roles", headers=admin, json={"role": "ADMIN", "description": "x", "permissions": []}).status_code == 422
    assert client.get("/api/admin/sync-runs", headers=admin).status_code == 200
