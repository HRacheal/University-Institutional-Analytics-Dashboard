"""Data contracts for departmental feeds, derived from the warehouse data dictionary (data/synthetic/schema/data_dictionary.csv).

A contract lists, per entity, the columns a departmental system must supply, their types, whether they are required and
any allowed values. The same contract validates CSV imports and REST API payloads, so a real system can replace the
sample data without changing the dashboard.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from ..core.config import get_settings

# entity -> department that owns it in the university (Registrar also owns the academic reference data)
DEPARTMENT_OF_DIR = {"registrar": "REGISTRAR", "reference": "REGISTRAR", "admissions": "ADMISSIONS", "finance": "FINANCE", "it": "IT"}
# entities the dashboard reads; others in the dictionary are documented but optional
DASHBOARD_ENTITIES = {
    "REGISTRAR": ["registrar/students", "registrar/student_programmes", "registrar/term_enrolments", "registrar/academic_standing",
                  "registrar/retention_cohort_members", "registrar/graduation_records", "registrar/course_enrolments",
                  "reference/academic_terms", "reference/programmes", "reference/schools", "reference/level_rules", "reference/nationalities",
                  "reference/courses"],
    "ADMISSIONS": ["admissions/applications", "admissions/applicants"],
    "FINANCE": ["finance/account_balances", "finance/charges", "finance/payments", "finance/financial_holds", "finance/registration_blocks"],
    "IT": ["it/user_accounts", "it/login_events", "it/server_status_daily", "it/incidents", "it/staff"],
}
PRIMARY_KEYS = {
    "registrar/students": ["student_id"], "registrar/student_programmes": ["student_programme_id"],
    "registrar/term_enrolments": ["term_enrolment_id"], "registrar/academic_standing": ["standing_id"],
    "registrar/retention_cohort_members": ["retention_record_id"], "registrar/graduation_records": ["graduation_record_id"],
    "registrar/course_enrolments": ["course_enrolment_id"], "reference/academic_terms": ["term_id"],
    "reference/programmes": ["programme_id"], "reference/schools": ["school_id"], "reference/level_rules": ["rule_set_id", "level"],
    "reference/nationalities": ["nationality_iso3"], "reference/courses": ["course_id"], "admissions/applications": ["application_id"],
    "admissions/applicants": ["applicant_id"], "finance/account_balances": ["student_id"], "finance/charges": ["charge_id"],
    "finance/payments": ["payment_id"], "finance/financial_holds": ["hold_id"], "finance/registration_blocks": ["block_id"],
    "it/user_accounts": ["account_id"], "it/login_events": ["login_id"], "it/server_status_daily": ["server_id", "status_date"],
    "it/incidents": ["incident_id"], "it/staff": ["staff_id"],
}
# lineage columns produced by the synthetic generator; the connector fills them for imported data
LINEAGE = {"data_source", "source_system", "generation_run_id", "verification_status", "source_reference", "verified_on", "verified_by"}


@lru_cache(maxsize=1)
def contracts() -> dict:
    d = pd.read_csv(get_settings().data_root / "synthetic" / "schema" / "data_dictionary.csv", keep_default_na=False)
    d = d[d["file"].str.startswith("data/synthetic/")]
    out = {}
    for f, g in d.groupby("file", sort=False):
        rel = f.removeprefix("data/synthetic/").removesuffix(".csv")
        folder = rel.split("/")[0]
        if folder not in DEPARTMENT_OF_DIR:
            continue
        cols = []
        for _, r in g.iterrows():
            lineage = r["column"] in LINEAGE
            cols.append({"name": r["column"], "type": r["type"], "required": bool(str(r["required"]) == "True") and not lineage,
                         "description": r["description"], "lineage": lineage,
                         "allowed_values": [] if lineage or not r["allowed_values"] else r["allowed_values"].split("|")})
        dep = DEPARTMENT_OF_DIR[folder]
        out[rel] = {"entity": rel, "department": dep, "used_by_dashboard": rel in DASHBOARD_ENTITIES.get(dep, []),
                    "primary_key": PRIMARY_KEYS.get(rel), "columns": cols}
    return out


def _check_type(s: pd.Series, typ: str) -> pd.Series:
    """True where a non-empty value does NOT parse as typ."""
    v = s[s.notna() & (s.astype(str).str.strip() != "")]
    if typ in ("int", "float"):
        num = pd.to_numeric(v, errors="coerce")
        bad = num.isna() | ~np.isfinite(num.fillna(0))
        if typ == "int":
            bad |= (num.notna() & (num % 1 != 0))
    elif typ == "bool":
        bad = ~v.astype(str).str.lower().isin(["true", "false", "1", "0"])
    elif typ in ("date", "datetime"):
        bad = pd.to_datetime(v, errors="coerce").isna()
    else:
        bad = pd.Series(False, index=v.index)
    return bad.reindex(s.index, fill_value=False)


def validate(df: pd.DataFrame, entity: str) -> dict:
    """Validate a feed against its contract. Returns a report; report['valid'] is False on any blocking problem."""
    c = contracts().get(entity)
    if c is None:
        return {"valid": False, "entity": entity, "errors": [f"unknown entity {entity}"], "warnings": []}
    errors, warnings = [], []
    names = {x["name"] for x in c["columns"]}
    missing = [x["name"] for x in c["columns"] if x["required"] and x["name"] not in df.columns]
    if missing:
        errors.append(f"missing required column(s): {missing}")
    extra = sorted(set(df.columns) - names)
    if extra:
        warnings.append(f"unexpected column(s) ignored: {extra[:20]}")
    for col in c["columns"]:
        n = col["name"]
        if n not in df.columns:
            continue
        s = df[n]
        empty = s.isna() | (s.astype(str).str.strip() == "")
        if col["required"] and empty.any():
            errors.append(f"{n}: {int(empty.sum())} empty value(s) in a required column")
        bad = _check_type(s, col["type"])
        if bad.any():
            errors.append(f"{n}: {int(bad.sum())} value(s) are not of type {col['type']} (e.g. {s[bad].astype(str).head(3).tolist()})")
        if col["allowed_values"]:
            outside = ~empty & ~s.astype(str).isin(col["allowed_values"])
            if outside.any():
                errors.append(f"{n}: {int(outside.sum())} value(s) outside {col['allowed_values']} (e.g. {s[outside].astype(str).head(3).tolist()})")
    pk = c["primary_key"]
    if pk and all(k in df.columns for k in pk):
        dup = int(df.duplicated(subset=pk).sum())
        if dup:
            errors.append(f"{'+'.join(pk)}: {dup} duplicated key value(s)")
    return {"valid": not errors, "entity": entity, "rows": int(len(df)), "columns": int(df.shape[1]), "errors": errors, "warnings": warnings}
