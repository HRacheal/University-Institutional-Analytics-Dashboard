"""Validate the synthetic dataset and the UCI separation; write the data-quality report.

Usage (from the data_warehouse folder):
    python -m pipelines.validation                  # full validation including reproducibility (two extra runs)
    python -m pipelines.validation --skip-repro     # faster, without the reproducibility re-runs

Independent re-implementations (plain loops written separately from the generator and from pipelines/metrics.py)
are used for GPA, standing, poor performance, holds, gaps, withdrawal rule, status history, retention membership
and rates, and graduation records and rates, so that generator or metric bugs are detected rather than repeated.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import metrics as M
from . import schema as S
from .common import CONFIG_FILE, PROCESSED_UCI_DIR, RAW_UCI_FILE, SYNTHETIC_DIR, UCI_EXPECTED_SHA256, sha256_of, write_csv, write_json



def D(x):
    """Parse an ISO date; invalid or empty values become None (they are reported by the schema checks)."""
    if not (isinstance(x, str) and x):
        return None
    try:
        return date.fromisoformat(x[:10])
    except ValueError:
        return None

FOLDER_SOURCE = {"reference": "REFERENCE_PLACEHOLDER", "admissions": "ADMISSIONS", "registrar": "REGISTRAR",
                 "finance": "FINANCE", "it": "IT", "data_warehouse": "DATA_WAREHOUSE"}


class Report:
    def __init__(self):
        self.checks = []

    def add(self, category, name, ok, detail="", count=None):
        ok = bool(ok)
        self.checks.append({"category": category, "check": name, "status": "PASS" if ok else "FAIL",
                            "detail": str(detail)[:400], "violations": count if count is not None else (0 if ok else "")})
        return ok

    @property
    def failed(self):
        return [c for c in self.checks if c["status"] == "FAIL"]

    def status_of(self, name_part: str) -> list[str]:
        return [c["status"] for c in self.checks if name_part in c["check"]]


def read_all(out: Path) -> dict[str, pd.DataFrame]:
    t = {}
    for p in sorted(out.glob("*/*.csv")):
        if p.parent.name in ("reports", "schema"):
            continue
        t[f"{p.parent.name}/{p.stem}"] = pd.read_csv(p, keep_default_na=False, na_values=[""], low_memory=False)
    return t


def read_uci() -> dict[str, pd.DataFrame]:
    return {p.stem: pd.read_csv(p, keep_default_na=False, na_values=[""], low_memory=False)
            for p in sorted(PROCESSED_UCI_DIR.glob("*.csv"))}


# ============================================================================ schema
def _type_errors(s: pd.Series, typ: str) -> int:
    v = s.dropna()
    if v.empty or typ in ("id", "str"):
        return 0
    if typ in ("int", "float"):
        num = pd.to_numeric(v, errors="coerce")
        bad = int(num.isna().sum())
        return bad + (int(((num.dropna() % 1) != 0).sum()) if typ == "int" else 0)
    if typ == "bool":
        return int((~v.astype(str).isin(["True", "False"])).sum())
    fmt = "%Y-%m-%d" if typ == "date" else "ISO8601"
    return int(pd.to_datetime(v.astype(str), format=fmt, errors="coerce").isna().sum())


def _norm(x):
    return str(int(x)) if isinstance(x, float) and x.is_integer() else str(x)


def _check_table_schema(R, cat, name, df, spec):
    cols = [c[0] for c in spec]
    if list(df.columns) != cols:
        R.add(cat, f"{name}: columns match the documented schema", False,
              f"missing={sorted(set(cols) - set(df.columns))} extra={sorted(set(df.columns) - set(cols))}")
        return
    miss, terr, enum = Counter(), Counter(), Counter()
    for c in spec:
        col, typ, req = c[0], c[1], c[2]
        if req:
            n = int(df[col].isna().sum())
            if n:
                miss[col] = n
        n = _type_errors(df[col], typ)
        if n:
            terr[col] = n
        if len(c) > 4:
            allowed = {str(a) for a in c[4]}
            n = int((~df[col].dropna().map(_norm).isin(allowed)).sum())
            if n:
                enum[col] = n
    R.add(cat, f"{name}: required fields present", not miss, dict(miss) or f"{len(df)} rows", sum(miss.values()))
    R.add(cat, f"{name}: values parse as documented types (dates, numbers, booleans)", not terr, dict(terr) or "", sum(terr.values()))
    R.add(cat, f"{name}: values within allowed domains", not enum, dict(enum) or "", sum(enum.values()))


def check_schema(t, uci, R):
    for name, spec in S.SYNTHETIC_SCHEMA.items():
        if name not in t:
            R.add("Schema", f"{name}: file exists", False)
            continue
        _check_table_schema(R, "Schema", name, t[name], spec)
    extra = sorted(set(t) - set(S.SYNTHETIC_SCHEMA))
    R.add("Schema", "every synthetic file has a documented schema", not extra, extra or f"{len(t)} files")
    uspec = {**S.UCI_SCHEMA, "uci_source_records": S.uci_source_records_schema()}
    for name, spec in uspec.items():
        if name not in uci:
            R.add("Schema", f"uci/{name}: file exists", False)
            continue
        _check_table_schema(R, "Schema (UCI)", f"uci/{name}", uci[name], spec)
    R.add("Schema", "every UCI file has a documented schema", not (set(uci) - set(uspec)), sorted(set(uci) - set(uspec)))


# ============================================================================ identifiers & relationships
PKS = {"admissions/applicants": ["applicant_id"], "admissions/applications": ["application_id"],
       "registrar/students": ["student_id"], "registrar/student_programmes": ["student_programme_id"],
       "registrar/term_enrolments": ["term_enrolment_id"], "registrar/course_enrolments": ["course_enrolment_id"],
       "registrar/academic_standing": ["standing_id"], "registrar/cohorts": ["cohort_id"],
       "registrar/cohort_members": ["cohort_id", "student_id"], "registrar/student_status_history": ["status_event_id"],
       "registrar/retention_cohort_members": ["retention_record_id"], "registrar/graduation_records": ["graduation_record_id"],
       "finance/charges": ["charge_id"], "finance/payments": ["payment_id"], "finance/financial_holds": ["hold_id"],
       "finance/registration_blocks": ["block_id"], "finance/account_balances": ["student_id"],
       "it/user_accounts": ["account_id"], "it/account_status_events": ["event_id"], "it/staff": ["staff_id"],
       "it/login_events": ["login_id"], "it/incidents": ["incident_id"], "it/server_status_daily": ["server_id", "status_date"],
       "data_warehouse/sync_runs": ["run_id"], "data_warehouse/generation_runs": ["generation_run_id"],
       "reference/programmes": ["programme_id"], "reference/courses": ["course_id"], "reference/academic_terms": ["term_id"],
       "reference/academic_years": ["academic_year"], "reference/schools": ["school_id"],
       "reference/nationalities": ["nationality_iso3"], "reference/gender_categories": ["gender"],
       "reference/delivery_modes": ["delivery_mode"], "reference/attendance_loads": ["study_load"],
       "reference/academic_standing_codes": ["standing"], "reference/student_status_codes": ["status_code"],
       "reference/level_rules": ["level"], "reference/fee_schedules": ["academic_year", "level"], "reference/roles": ["role_code"],
       "reference/servers": ["server_id"], "reference/grading_schemes": ["grading_scheme_id"], "reference/rule_sets": ["rule_set_id"]}

TERMS, PROG, STU, SP, SCH = ("reference/academic_terms", "term_id"), ("reference/programmes", "programme_id"), \
    ("registrar/students", "student_id"), ("registrar/student_programmes", "student_programme_id"), ("reference/schools", "school_id")
FKS = [("admissions/applications", "applicant_id", ("admissions/applicants", "applicant_id")),
       ("admissions/applications", "student_id", STU), ("admissions/applications", "programme_id", PROG),
       ("admissions/applications", "school_id", SCH), ("admissions/applications", "entry_term_id", TERMS),
       ("admissions/applicants", "nationality_iso3", ("reference/nationalities", "nationality_iso3")),
       ("admissions/applicants", "gender", ("reference/gender_categories", "gender")),
       ("registrar/students", "applicant_id", ("admissions/applicants", "applicant_id")),
       ("registrar/students", "nationality_iso3", ("reference/nationalities", "nationality_iso3")),
       ("registrar/students", "gender", ("reference/gender_categories", "gender")),
       ("registrar/student_programmes", "student_id", STU), ("registrar/student_programmes", "programme_id", PROG),
       ("registrar/student_programmes", "school_id", SCH), ("registrar/student_programmes", "entry_term_id", TERMS),
       ("registrar/student_programmes", "outcome_term_id", TERMS), ("registrar/student_programmes", "previous_student_programme_id", SP),
       ("registrar/student_programmes", "application_id", ("admissions/applications", "application_id")),
       ("registrar/student_programmes", "rule_set_id", ("reference/rule_sets", "rule_set_id")),
       ("registrar/term_enrolments", "student_programme_id", SP), ("registrar/term_enrolments", "student_id", STU),
       ("registrar/term_enrolments", "programme_id", PROG), ("registrar/term_enrolments", "school_id", SCH),
       ("registrar/term_enrolments", "term_id", TERMS), ("registrar/term_enrolments", "academic_year", ("reference/academic_years", "academic_year")),
       ("registrar/term_enrolments", "delivery_mode", ("reference/delivery_modes", "delivery_mode")),
       ("registrar/term_enrolments", "study_load", ("reference/attendance_loads", "study_load")),
       ("registrar/term_enrolments", "grading_scheme_id", ("reference/grading_schemes", "grading_scheme_id")),
       ("registrar/course_enrolments", "term_enrolment_id", ("registrar/term_enrolments", "term_enrolment_id")),
       ("registrar/course_enrolments", "course_id", ("reference/courses", "course_id")),
       ("registrar/course_enrolments", "delivery_mode", ("reference/delivery_modes", "delivery_mode")),
       ("registrar/academic_standing", "term_enrolment_id", ("registrar/term_enrolments", "term_enrolment_id")),
       ("registrar/academic_standing", "standing", ("reference/academic_standing_codes", "standing")),
       ("registrar/cohort_members", "cohort_id", ("registrar/cohorts", "cohort_id")),
       ("registrar/cohort_members", "student_programme_id", SP), ("registrar/cohort_members", "programme_at_entry", PROG),
       ("registrar/student_status_history", "student_programme_id", SP), ("registrar/student_status_history", "term_id", TERMS),
       ("registrar/student_status_history", "status_code", ("reference/student_status_codes", "status_code")),
       ("registrar/retention_cohort_members", "student_id", STU), ("registrar/retention_cohort_members", "base_programme_id", PROG),
       ("registrar/retention_cohort_members", "base_school_id", SCH), ("registrar/retention_cohort_members", "base_term_id", TERMS),
       ("registrar/retention_cohort_members", "compare_term_id", TERMS),
       ("registrar/retention_cohort_members", "compare_programme_id", PROG),
       ("registrar/graduation_records", "cohort_id", ("registrar/cohorts", "cohort_id")),
       ("registrar/graduation_records", "student_id", STU), ("registrar/graduation_records", "programme_at_entry", PROG),
       ("registrar/graduation_records", "school_at_entry", SCH), ("registrar/graduation_records", "graduated_programme_id", PROG),
       ("registrar/graduation_records", "graduation_term_id", TERMS),
       ("reference/programmes", "school_id", SCH), ("reference/courses", "programme_id", PROG),
       ("reference/fee_schedules", "academic_year", ("reference/academic_years", "academic_year")),
       ("reference/academic_terms", "academic_year", ("reference/academic_years", "academic_year")),
       ("finance/charges", "student_id", STU), ("finance/charges", "student_programme_id", SP), ("finance/charges", "term_id", TERMS),
       ("finance/payments", "student_id", STU), ("finance/payments", "term_id", TERMS),
       ("finance/financial_holds", "student_id", STU), ("finance/registration_blocks", "student_programme_id", SP),
       ("finance/registration_blocks", "term_id", TERMS), ("finance/account_balances", "student_id", STU),
       ("it/user_accounts", "role_code", ("reference/roles", "role_code")), ("it/staff", "role_code", ("reference/roles", "role_code")),
       ("it/login_events", "account_id", ("it/user_accounts", "account_id")), ("it/login_events", "server_id", ("reference/servers", "server_id")),
       ("it/account_status_events", "account_id", ("it/user_accounts", "account_id")),
       ("it/server_status_daily", "server_id", ("reference/servers", "server_id")), ("it/incidents", "server_id", ("reference/servers", "server_id"))]


def check_ids_and_keys(t, R):
    for tbl, cols in PKS.items():
        df = t[tbl]
        dup = int(df.duplicated(cols).sum()) + int(df[cols].isna().any(axis=1).sum())
        R.add("Identifiers", f"{tbl}.{'+'.join(cols)} unique and not null", dup == 0, f"{len(df)} rows", dup)
    sids = t["registrar/students"]["student_id"].astype(str)
    bad = int((~sids.str.match(r"^SYN-\d{6}$")).sum())
    R.add("Identifiers", "student_id format SYN-nnnnnn", bad == 0, count=bad)
    for child, ccol, (parent, pcol) in FKS:
        vals = t[child][ccol].dropna()
        bad = int((~vals.isin(set(t[parent][pcol]))).sum())
        R.add("Relationships", f"{child}.{ccol} -> {parent}.{pcol}", bad == 0, f"{len(vals)} non-null links", bad)
    runs = set(t["data_warehouse/generation_runs"]["generation_run_id"])
    bad = sum(int((~df["generation_run_id"].isin(runs)).sum()) for df in t.values())
    R.add("Relationships", "every row's generation_run_id -> data_warehouse/generation_runs", bad == 0, sorted(runs), bad)

    # attribute consistency across tables
    prog = t["reference/programmes"].set_index("programme_id")
    sp = t["registrar/student_programmes"]
    te = t["registrar/term_enrolments"]
    spi = sp.drop_duplicates("student_programme_id").set_index("student_programme_id")
    terms = t["reference/academic_terms"].drop_duplicates("term_id").set_index("term_id")
    x = te.join(spi[["student_id", "programme_id", "level"]], on="student_programme_id", rsuffix="_sp")
    bad = int(((x["student_id"] != x["student_id_sp"]) | (x["programme_id"] != x["programme_id_sp"]) | (x["level"] != x["level_sp"])).sum())
    R.add("Consistency", "term enrolment student/programme/level equal its admission record", bad == 0, count=bad)
    for name, df, pcol, scol in (("term_enrolments", te, "programme_id", "school_id"), ("student_programmes", sp, "programme_id", "school_id"),
                                 ("applications", t["admissions/applications"], "programme_id", "school_id"),
                                 ("retention_cohort_members", t["registrar/retention_cohort_members"], "base_programme_id", "base_school_id"),
                                 ("graduation_records", t["registrar/graduation_records"], "programme_at_entry", "school_at_entry")):
        bad = int((df[scol] != df[pcol].map(prog["school_id"])).sum())
        R.add("Consistency", f"{name}: school = school of its programme", bad == 0, count=bad)
    for name, df in (("term_enrolments", te), ("student_programmes", sp), ("applications", t["admissions/applications"])):
        bad = int((df["level"] != df["programme_id"].map(prog["level"])).sum())
        R.add("Consistency", f"{name}: level = level of its programme", bad == 0, count=bad)
    bad = int((te["academic_year"] != te["term_id"].map(terms["academic_year"])).sum()) + \
        int((te["term_sequence"] != te["term_id"].map(terms["term_sequence"])).sum())
    R.add("Consistency", "term enrolment academic year and sequence equal the calendar", bad == 0, count=bad)
    offered = {p: set(str(v).split("|")) for p, v in prog["delivery_modes_offered"].items()}
    bad = sum(1 for p, m in zip(te["programme_id"], te["delivery_mode"]) if m not in offered.get(p, set()))
    R.add("Consistency", "delivery mode of every term enrolment is offered by its programme", bad == 0, count=bad)
    ce = t["registrar/course_enrolments"].join(te.drop_duplicates("term_enrolment_id").set_index("term_enrolment_id")[["delivery_mode", "programme_id"]],
                                               on="term_enrolment_id", rsuffix="_te")
    cprog = t["reference/courses"].set_index("course_id")["programme_id"]
    bad = int((ce["delivery_mode"] != ce["delivery_mode_te"]).sum()) + int((ce["course_id"].map(cprog) != ce["programme_id"]).sum())
    R.add("Consistency", "course enrolments use their term's delivery mode and their programme's courses", bad == 0, count=bad)
    nat = t["reference/nationalities"].set_index("nationality_iso3")["residency_status"]
    for name in ("registrar/students", "admissions/applicants"):
        df = t[name]
        bad = int((df["residency_status"] != df["nationality_iso3"].map(nat)).sum())
        R.add("Consistency", f"{name}: residency status consistent with nationality", bad == 0, count=bad)
    stu = t["registrar/students"].merge(t["admissions/applicants"], on="applicant_id", suffixes=("", "_a"))
    bad = int(sum((stu[c] != stu[c + "_a"]).sum() for c in ("gender", "birth_year", "nationality_iso3")))
    R.add("Consistency", "student demographics equal their applicant record", bad == 0, count=bad)
    gr = t["registrar/graduation_records"]
    m = gr.merge(t["registrar/cohort_members"], on=["cohort_id", "student_id"], how="left", indicator=True)
    bad = int((m["_merge"] != "both").sum()) + int((m["programme_at_entry_x"] != m["programme_at_entry_y"]).sum())
    R.add("Consistency", "graduation records belong to LEVEL_ENTRY cohort members with the same entry programme", bad == 0, count=bad)


def check_sources(t, R, manifest):
    for name, df in t.items():
        vals = set(df["data_source"].unique()) if "data_source" in df else {"<missing>"}
        R.add("Data separation", f"{name}: data_source = SYNTHETIC", vals == {"SYNTHETIC"}, sorted(map(str, vals)))
        folder = name.split("/")[0]
        ss = set(df["source_system"].unique()) if "source_system" in df else {"<missing>"}
        R.add("Source labels", f"{name}: source_system = {FOLDER_SOURCE.get(folder)}", ss == {FOLDER_SOURCE.get(folder)}, sorted(map(str, ss)))
        if name.startswith("reference/"):
            R.add("Data separation", f"{name}: verification_status = PLACEHOLDER", set(df["verification_status"]) == {"PLACEHOLDER"})
    rid = manifest.get("generation_run_id")
    bad = sum(int((df["generation_run_id"] != rid).sum()) for df in t.values())
    R.add("Source labels", "generation_run_id on every row equals the manifest run", bad == 0, rid, bad)
    gr = t["data_warehouse/generation_runs"]
    R.add("Source labels", "generation run records version, seed and config fingerprint of the manifest",
          len(gr) == 1 and gr.iloc[0]["generator_version"] == manifest["generator_version"]
          and int(gr.iloc[0]["random_seed"]) == int(manifest["random_seed"]) and gr.iloc[0]["config_sha256"] == manifest["config_sha256"])
    for name in ("reference/schools", "reference/programmes"):
        df = t[name]
        R.add("Data separation", f"{name}: labelled as synthetic placeholders (not verified names)",
              bool(df["is_placeholder"].all() and df["display_name"].astype(str).str.contains(r"\[synthetic placeholder\]").all()))
    leak = sum(int(df[c].astype(str).str.contains(r"\bUCI-\d", regex=True).sum())
               for df in t.values() for c in df.columns if df[c].dtype == object)
    R.add("Data separation", "no UCI identifiers inside synthetic files", leak == 0, count=leak)
    R.add("Data separation", "original UCI file unchanged (SHA-256)", sha256_of(RAW_UCI_FILE) == UCI_EXPECTED_SHA256)
    us = pd.read_csv(PROCESSED_UCI_DIR / "uci_students.csv", keep_default_na=False)
    R.add("Data separation", "UCI students: 4,424 rows, data_source = UCI", len(us) == 4424 and set(us["data_source"]) == {"UCI"})
    R.add("Data separation", "UCI outcome counts 2209/1421/794 preserved",
          us["outcome_at_normal_duration"].value_counts().to_dict() == {"GRADUATED": 2209, "DROPPED_OUT": 1421, "STILL_ENROLLED": 794})
    R.add("Data separation", "180 UCI records flagged NOT_EVALUATED_BOTH_SEMESTERS",
          int((us["dq_flags"] == "NOT_EVALUATED_BOTH_SEMESTERS").sum()) == 180)
    forbidden = {"term_id", "entry_term_id", "admission_date", "graduation_date", "programme_id", "school_id", "delivery_mode",
                 "gpa", "cumulative_gpa", "term_gpa"}
    cols = set()
    for p in PROCESSED_UCI_DIR.glob("*.csv"):
        cols |= set(pd.read_csv(p, nrows=0).columns)
    R.add("Data separation", "UCI tables contain no invented dates/terms/programmes/schools/modes/GPA",
          not (cols & forbidden), sorted(cols & forbidden))
    syn_ids = set(t["registrar/students"]["student_id"])
    R.add("Data separation", "no synthetic identifiers inside UCI tables",
          not any(us[c].astype(str).isin(syn_ids).any() for c in us.columns))
    R.add("Data separation", "no synthetic file mixes UCI rows (no combined population or totals)",
          not any((df["data_source"] == "UCI").any() for df in t.values()))


# ============================================================================ calendar & terms
def check_terms(t, R, as_of: date):
    terms = t["reference/academic_terms"].sort_values("term_sequence")
    bad_order = bad_status = bad_rep = bad_ay = 0
    prev_end = None
    for r in terms.itertuples():
        s, c, e = D(r.start_date), D(r.census_date), D(r.end_date)
        if not (s < c < e) or (prev_end and s <= prev_end):
            bad_order += 1
        prev_end = e
        exp = "COMPLETED" if e <= as_of else ("IN_PROGRESS" if s <= as_of else "FUTURE")
        bad_status += exp != r.term_status
        rep = "COMPLETED_TERM" if e <= as_of else ("CENSUS_SNAPSHOT_ONLY" if c <= as_of else "FUTURE_NOT_REPORTABLE")
        bad_rep += rep != r.reporting_status or bool(r.grades_final_available) != (e <= as_of) or \
            bool(r.in_completed_reporting) != (e <= as_of) or bool(r.census_passed) != (c <= as_of)
        y = r.calendar_year if r.season == "FALL" else r.calendar_year - 1
        bad_ay += r.academic_year != f"{y}/{str(y + 1)[2:]}"
    R.add("Calendar", "term dates ordered (start < census < end) and terms do not overlap", bad_order == 0, count=bad_order)
    R.add("Calendar", "term_status consistent with the as-of date (COMPLETED iff end <= as-of; FUTURE iff start > as-of)",
          bad_status == 0, count=bad_status)
    R.add("Calendar", "reporting_status / grades_final_available / census_passed consistent with the as-of date", bad_rep == 0, count=bad_rep)
    R.add("Calendar", "academic_year labels follow Fall Y + Spring/Summer Y+1", bad_ay == 0, count=bad_ay)
    ay = t["reference/academic_years"]
    bad = 0
    for r in ay.itertuples():
        ts = terms[terms["academic_year"] == r.academic_year]
        e = D(r.end_date)
        exp = "COMPLETED" if e <= as_of else ("IN_PROGRESS" if D(r.start_date) <= as_of else "FUTURE")
        bad += r.start_date != ts["start_date"].min() or r.end_date != ts["end_date"].max() or exp != r.year_status
    R.add("Calendar", "academic years span their terms and carry a status consistent with the as-of date", bad == 0, count=bad)
    status = terms.set_index("term_id")["term_status"]
    te, ce = t["registrar/term_enrolments"], t["registrar/course_enrolments"]
    bad = int((te["grades_final"].astype(bool) != (te["term_id"].map(status) == "COMPLETED")).sum())
    R.add("Future terms", "grades_final = True exactly for completed terms (no future/in-progress term marked completed)", bad == 0, count=bad)
    bad = int(((ce["grade_status"] == "FINAL") & (ce["term_id"].map(status) != "COMPLETED")).sum()) + \
        int(((ce["grade_status"] == "IN_PROGRESS") & (ce["term_id"].map(status) == "COMPLETED")).sum())
    R.add("Future terms", "final course grades exist only in completed terms", bad == 0, count=bad)


# ============================================================================ timeline
def check_timeline(t, R, as_of: date, cfg: dict):
    terms = t["reference/academic_terms"].drop_duplicates("term_id").set_index("term_id")
    seq = terms["term_sequence"].to_dict()
    by_seq = {v: k for k, v in seq.items()}
    start = {k: D(v) for k, v in terms["start_date"].items()}
    census = {k: D(v) for k, v in terms["census_date"].items()}
    end = {k: D(v) for k, v in terms["end_date"].items()}
    status = terms["term_status"].to_dict()
    sp = t["registrar/student_programmes"]
    te = t["registrar/term_enrolments"]
    apps = t["admissions/applications"].drop_duplicates("application_id").set_index("application_id")
    rules = t["reference/level_rules"].set_index("level")
    ce = t["registrar/course_enrolments"]
    max_missed = int(cfg["academic"]["max_consecutive_missed_terms"])
    reg_seqs = sorted(seq[k] for k in terms.index if terms.loc[k, "is_regular_term"])

    sp_adm = {r.student_programme_id: D(r.admission_date) for r in sp.itertuples()}
    bad = sum(1 for r in te.itertuples() if start[r.term_id] < sp_adm[r.student_programme_id])
    R.add("Timeline", "no enrolment before admission (every enrolment term starts on/after its admission date)", bad == 0, count=bad)
    bad = sum(1 for r in sp.itertuples() if D(r.admission_date) != start[r.entry_term_id])
    R.add("Timeline", "admission_date = start of entry term", bad == 0, count=bad)
    bad = 0
    for r in sp.itertuples():
        if r.entry_type == "PROGRAMME_CHANGE":
            bad += isinstance(r.application_id, str)
            continue
        a = apps.loc[r.application_id]
        if not (D(a.submitted_date) <= D(a.decision_date) < D(r.admission_date)) or a.decision != "ADMITTED" or not a.enrolled \
                or a.entry_term_id != r.entry_term_id or a.programme_id != r.programme_id:
            bad += 1
    R.add("Timeline", "admitted application (submitted <= decided < admission, same programme/term) for every non-internal admission",
          bad == 0, count=bad)
    first_te = te.groupby("student_programme_id")["term_id"].apply(lambda s: min(s, key=seq.get))
    bad = int((first_te != sp.set_index("student_programme_id")["entry_term_id"].reindex(first_te.index)).sum())
    R.add("Timeline", "first enrolment of each admission is in its entry term (cohort census)", bad == 0, count=bad)
    R.add("Timeline", "every admission has at least one term enrolment", set(sp["student_programme_id"]) == set(te["student_programme_id"]))
    bad = 0
    for spid, g in te.groupby("student_programme_id"):
        n = g.sort_values("term_sequence")["study_term_number"].tolist()
        bad += n != list(range(1, len(n) + 1))
    R.add("Timeline", "study_term_number counts enrolled terms 1..n within each admission", bad == 0, count=bad)

    fa = sp[sp["entry_type"] == "FIRST_ADMISSION"].groupby("student_id").size()
    R.add("Timeline", "exactly one FIRST_ADMISSION per student, and it is the earliest",
          len(fa) == sp["student_id"].nunique() and (fa == 1).all() and
          (sp.sort_values(["student_id", "admission_date"]).groupby("student_id").first()["entry_type"] == "FIRST_ADMISSION").all())
    by_id = sp.drop_duplicates("student_programme_id").set_index("student_programme_id")
    needed = {"PROGRAMME_CHANGE": {"CHANGED_PROGRAMME"}, "NEXT_DEGREE": {"GRADUATED"}, "READMISSION": {"WITHDRAWN", "DISMISSED"}}
    bad = 0
    for r in sp[sp["entry_type"] != "FIRST_ADMISSION"].itertuples():
        prev = by_id.loc[r.previous_student_programme_id]
        if prev.outcome not in needed[r.entry_type] or prev.student_id != r.student_id or D(prev.outcome_date) is None                 or D(prev.outcome_date) >= D(r.admission_date):
            bad += 1
            continue
        if r.entry_type == "READMISSION" and not (D(prev.outcome_recorded_date) < D(apps.loc[r.application_id].submitted_date)):
            bad += 1
    R.add("Timeline", "programme changes / next degrees / readmissions link to a matching earlier outcome", bad == 0, count=bad)

    # programme transfers (internal programme change)
    cum = te.drop_duplicates(["student_programme_id", "term_id"]).set_index(["student_programme_id", "term_id"]).sort_index()
    bad, why = 0, Counter()
    for r in sp[sp["entry_type"] == "PROGRAMME_CHANGE"].itertuples():
        prev = by_id.loc[r.previous_student_programme_id]
        if prev.outcome_term_id not in seq:
            why["previous_outcome_missing"] += 1
            bad += 1
            continue
        nxt = next((s for s in reg_seqs if s > seq[prev.outcome_term_id]), None)
        ok = {"same_level": prev.level == r.level, "different_programme": prev.programme_id != r.programme_id,
              "entry_next_regular_term": nxt is not None and seq[r.entry_term_id] == nxt,
              "credits_le_earned": r.credits_transferred_in <= cum.loc[(prev.name, prev.outcome_term_id), "cumulative_credits_earned"],
              "old_term_completed": status[prev.outcome_term_id] == "COMPLETED"}
        for k, v in ok.items():
            why[k] += not v
        bad += not all(ok.values())
    R.add("Transfers", "programme transfers valid: same level, different programme, next regular term, credits <= earned",
          bad == 0, dict(why) if bad else f"{int((sp['entry_type'] == 'PROGRAMME_CHANGE').sum())} transfers", bad)

    last_seq = te.groupby("student_programme_id")["term_sequence"].max()
    bad = sum(1 for r in sp[sp["outcome"] != "ACTIVE"].itertuples() if last_seq.get(r.student_programme_id) != seq.get(r.outcome_term_id))
    R.add("Timeline", "no enrolment after graduation/withdrawal/dismissal/change in the same admission (outcome term = last enrolled term)",
          bad == 0, count=bad)
    dup = int(te.duplicated(["student_id", "term_id"]).sum())
    R.add("Timeline", "no simultaneous enrolment in two programmes (one enrolment per student per term)", dup == 0, count=dup)
    bad = 0
    for sid, g in sp.sort_values("admission_date").groupby("student_id"):
        rows = list(g.itertuples())
        for a, b in zip(rows, rows[1:]):
            if a.outcome == "ACTIVE" or D(a.outcome_date) is None or D(a.outcome_date) >= D(b.admission_date):
                bad += 1
    R.add("Timeline", "a student's programme admissions never overlap", bad == 0, count=bad)
    R.add("Timeline", "at most one ACTIVE programme per student", bool((sp[sp["outcome"] == "ACTIVE"].groupby("student_id").size() <= 1).all()))

    # graduation validity
    standing = t["registrar/academic_standing"].drop_duplicates(["student_programme_id", "term_id"]) \
        .set_index(["student_programme_id", "term_id"])["standing"].sort_index()
    path_start = {}
    for sid, g in sp.sort_values("admission_date").groupby("student_id"):
        for level, lg in g.groupby("level"):
            path_start[(sid, level)] = D(lg.iloc[0]["admission_date"])
    bad, reasons = 0, Counter()
    earned = ce[ce["grade_status"] == "FINAL"].groupby("student_programme_id")["credits_earned"].sum()
    creq = t["reference/programmes"].set_index("programme_id")["credits_required"]
    for r in sp[sp["outcome"] == "GRADUATED"].itertuples():
        lv = rules.loc[r.level]
        gd = D(r.outcome_date)
        checks = {
            "date_is_term_end": gd == end[r.outcome_term_id],
            "term_completed_and_not_after_as_of": status[r.outcome_term_id] == "COMPLETED" and gd <= as_of,
            "credits": r.credits_transferred_in + earned.get(r.student_programme_id, 0) >= creq[r.programme_id],
            "min_years": (gd - path_start[(r.student_id, r.level)]).days / 365.25 >= lv.min_years_to_graduate,
            "gpa": cum.loc[(r.student_programme_id, r.outcome_term_id), "cumulative_gpa"] >= lv.graduation_min_gpa,
            "not_dismissed": standing.get((r.student_programme_id, r.outcome_term_id), "GOOD") != "DISMISSED",
        }
        for k, ok in checks.items():
            reasons[k] += not ok
        bad += not all(checks.values())
    R.add("Graduation", "graduations valid: term-end date, completed term, not after as-of, credits, minimum duration, GPA",
          bad == 0, {k: v for k, v in reasons.items() if v} or f"{int((sp['outcome'] == 'GRADUATED').sum())} graduations checked", bad)
    bad = sum(1 for r in sp[sp["outcome"] != "ACTIVE"].itertuples()
              if D(r.outcome_date) != end[r.outcome_term_id] or D(r.outcome_recorded_date) < D(r.outcome_date)
              or D(r.outcome_recorded_date) > as_of)
    R.add("Timeline", "outcome dates = end of outcome term, recorded on/after it, never after the as-of date", bad == 0, count=bad)
    bad = int(((sp["outcome"] == "ACTIVE") & (sp[["outcome_term_id", "outcome_date", "outcome_recorded_date"]].notna().any(axis=1))).sum()) + \
        int(((sp["outcome"] != "ACTIVE") & (sp[["outcome_term_id", "outcome_date", "outcome_recorded_date"]].isna().any(axis=1))).sum()) + \
        int(((sp["outcome"] == "WITHDRAWN") != sp["withdrawal_type"].notna()).sum())
    R.add("Timeline", "outcome fields present exactly when an outcome exists (withdrawal type only for withdrawals)", bad == 0, count=bad)

    # gaps and the configurable missed-term withdrawal rule
    bad = too_long = 0
    for spid, g in te.sort_values("term_sequence").groupby("student_programme_id"):
        prev = None
        for r in g.itertuples():
            exp = 0 if prev is None else sum(1 for s in reg_seqs if prev < s < r.term_sequence)
            bad += exp != r.prior_gap_terms
            too_long += exp > max_missed
            prev = r.term_sequence
    R.add("Progression", "prior_gap_terms recomputes from the enrolment history", bad == 0, count=bad)
    R.add("Progression", f"no gap inside one admission exceeds the configured limit ({max_missed} regular terms)", too_long == 0, count=too_long)
    last_data = max(seq[k] for k in terms.index if terms.loc[k, "has_enrolment_data"])
    bad, why = 0, Counter()
    for r in sp.itertuples():
        ls = last_seq[r.student_programme_id]
        missed_after = [s for s in reg_seqs if ls < s <= last_data and census[by_seq[s]] <= as_of]
        if r.outcome == "WITHDRAWN" and r.withdrawal_type == "UNOFFICIAL":
            rec = D(r.outcome_recorded_date)
            k = [s for s in missed_after if census[by_seq[s]] <= rec]
            ok = len(k) == max_missed + 1 and census[by_seq[k[-1]]] == rec
            why["unofficial_not_at_census_of_missed_term_%d" % (max_missed + 1)] += not ok
        elif r.outcome == "WITHDRAWN":
            rec = D(r.outcome_recorded_date)
            k = [s for s in missed_after if start[by_seq[s]] <= rec]
            ok = bool(k) and start[by_seq[k[-1]]] == rec and len(k) <= max_missed + 1
            why["formal_not_at_start_of_unregistered_term"] += not ok
        elif r.outcome == "ACTIVE":
            ok = len(missed_after) <= max_missed
            why["active_beyond_missed_term_limit"] += not ok
        else:
            ok = True
        bad += not ok
    R.add("Progression", f"missed-term withdrawal rule (> {max_missed} regular terms -> UNOFFICIAL withdrawal at next census) recomputes",
          bad == 0, {k: v for k, v in why.items() if v} or "withdrawal dates consistent", bad)

    # future and in-progress terms
    fut = [k for k, v in status.items() if v == "FUTURE"]
    n = sum(int(t[x][c].isin(fut).sum()) for x, c in [("registrar/term_enrolments", "term_id"), ("registrar/course_enrolments", "term_id"),
                                                     ("finance/charges", "term_id"), ("registrar/academic_standing", "term_id"),
                                                     ("registrar/student_programmes", "entry_term_id"), ("registrar/cohorts", "entry_term_id"),
                                                     ("registrar/student_status_history", "term_id"),
                                                     ("registrar/graduation_records", "graduation_term_id")])
    R.add("Future terms", "no enrolments, grades, charges, standing, admissions, cohorts, events or graduations in FUTURE terms", n == 0, fut, n)
    fa_apps = t["admissions/applications"][t["admissions/applications"]["entry_term_id"].isin(fut)]
    R.add("Future terms", "future-term applications are not enrolled and are decided on/before the as-of date (or PENDING)",
          (~fa_apps["enrolled"].astype(bool)).all() and all(D(d) <= as_of for d in fa_apps["decision_date"].dropna()),
          f"{len(fa_apps)} applications for {sorted(set(fa_apps['entry_term_id']))}")
    inprog = [k for k, v in status.items() if v == "IN_PROGRESS"]
    ip = te[te["term_id"].isin(inprog)]
    R.add("Future terms", "in-progress term (census snapshot only): no final grades, GPA, standing, performance flags or graduations",
          ip["term_gpa"].isna().all() and ip["poor_performance_flag"].isna().all() and ip["credits_earned"].isna().all()
          and (ce.loc[ce["term_id"].isin(inprog), "grade_letter"] == "IP").all()
          and not t["registrar/academic_standing"]["term_id"].isin(inprog).any()
          and not sp.loc[sp["outcome"] != "ACTIVE", "outcome_term_id"].isin(inprog).any(), f"{len(ip)} in-progress enrolments")
    dates = pd.concat([pd.to_datetime(t["finance/payments"]["payment_date"], format="%Y-%m-%d", errors="coerce"),
                       pd.to_datetime(t["finance/charges"]["charge_date"], errors="coerce"),
                       pd.to_datetime(t["admissions/applications"]["submitted_date"], errors="coerce"),
                       pd.to_datetime(t["registrar/student_status_history"]["event_date"], errors="coerce"),
                       pd.to_datetime(t["it/login_events"]["event_time"], format="ISO8601", errors="coerce")])
    R.add("Future terms", "no recorded event after the as-of date", dates.max().date() <= as_of, f"latest event {dates.max()}")


# ============================================================================ status history
def check_status_history(t, R, as_of: date):
    sp, te, h = t["registrar/student_programmes"], t["registrar/term_enrolments"], t["registrar/student_status_history"]
    terms = t["reference/academic_terms"].set_index("term_id")
    gaps = te[te["prior_gap_terms"] > 0].groupby("student_programme_id").size()
    last_data = terms.index[terms["reporting_status"] == "CENSUS_SNAPSHOT_ONLY"].tolist() or [terms.index[terms["has_enrolment_data"]][-1]]
    reg = terms[terms["is_regular_term"] & (pd.to_datetime(terms["census_date"]).dt.date <= as_of) & terms["has_enrolment_data"]]
    last_seq = te.groupby("student_programme_id")["term_sequence"].max()
    hg = {k: g for k, g in h.groupby("student_programme_id")}
    bad, why = 0, Counter()
    terminal = {"GRADUATED": "GRADUATED", "DISMISSED": "DISMISSED", "CHANGED_PROGRAMME": "CHANGED_PROGRAMME", "WITHDRAWN": "WITHDRAWN"}
    for r in sp.itertuples():
        g = hg.get(r.student_programme_id)
        if g is None:
            why["no_events"] += 1
            bad += 1
            continue
        g = g.sort_values(["event_date", "status_event_id"])
        codes = g["status_code"].tolist()
        on_gap_end = r.outcome == "ACTIVE" and bool((reg["term_sequence"] > last_seq[r.student_programme_id]).any())
        exp_stop = int(gaps.get(r.student_programme_id, 0)) + int(on_gap_end or (r.outcome == "WITHDRAWN" and r.withdrawal_type == "UNOFFICIAL"))
        ok = {"admitted_first_with_admission_date": codes[0] == "ADMITTED" and g.iloc[0]["event_date"] == r.admission_date
              and g.iloc[0]["term_id"] == r.entry_term_id,
              "one_admitted_event": codes.count("ADMITTED") == 1,
              "returned_events_equal_gaps": codes.count("RETURNED") == int(gaps.get(r.student_programme_id, 0)),
              "stopped_out_events": codes.count("STOPPED_OUT") == exp_stop,
              "chronological": list(g["event_date"]) == sorted(g["event_date"]),
              "events_not_after_as_of": all(D(d) <= as_of for d in g["event_date"])}
        if r.outcome in terminal:
            ev = g[g["status_code"] == terminal[r.outcome]]
            date_ok = len(ev) == 1 and ev.iloc[0]["event_date"] == (r.outcome_recorded_date if r.outcome == "WITHDRAWN" else r.outcome_date)
            ok["terminal_event_matches_outcome"] = date_ok and codes[-1] == terminal[r.outcome]
        else:
            ok["active_has_no_terminal_event"] = not (set(codes) & set(terminal.values())) and \
                g.iloc[-1]["status_after"] == ("ON_GAP" if on_gap_end else "ACTIVE")
        for k, v in ok.items():
            why[k] += not v
        bad += not all(ok.values())
    R.add("Status history", "status history recomputes from admissions and enrolments (admission event never overwritten)",
          bad == 0, {k: v for k, v in why.items() if v} or f"{len(h)} events for {len(sp)} admissions", bad)
    _ = last_data


# ============================================================================ GPA & standing & performance
def check_gpa_and_standing(t, R, cfg: dict):
    ce = t["registrar/course_enrolments"]
    te = t["registrar/term_enrolments"].sort_values("term_sequence")
    rules = t["reference/level_rules"].set_index("level")
    ratio_min = float(cfg["reporting"]["poor_performance_pass_ratio_below"])
    letters = json.loads(t["reference/grading_schemes"].iloc[0]["letter_points"])
    bad = int(sum(1 for r in ce[ce["grade_status"] == "FINAL"].itertuples() if abs(letters[r.grade_letter] - r.grade_points) > 1e-9))
    R.add("GPA & standing", "grade points match the grading scheme", bad == 0, count=bad)
    pass_pts = rules["pass_points"].to_dict()
    lvl = t["registrar/student_programmes"].drop_duplicates("student_programme_id").set_index("student_programme_id")["level"].to_dict()
    bad = sum(1 for r in ce[ce["grade_status"] == "FINAL"].itertuples()
              if r.credits_earned != (r.credits if r.grade_points >= pass_pts[lvl[r.student_programme_id]] else 0))
    R.add("GPA & standing", "course credits earned follow the pass mark", bad == 0, count=bad)
    by_te = defaultdict(list)
    for r in ce.itertuples():
        by_te[r.term_enrolment_id].append(r)
    std_df = t["registrar/academic_standing"]
    std = std_df.drop_duplicates("term_enrolment_id").set_index("term_enrolment_id")
    credits_in = t["registrar/student_programmes"].drop_duplicates("student_programme_id").set_index("student_programme_id")["credits_transferred_in"]
    bad_gpa = bad_std = bad_cnt = bad_poor = bad_cred = 0
    for spid, g in te.groupby("student_programme_id", sort=False):
        pts = cred = 0
        earned_total = int(credits_in.get(spid, 0))
        prev = None
        mn = rules.loc[lvl[spid], "good_standing_min_gpa"]
        for r in g.itertuples():
            rows = by_te[r.term_enrolment_id]
            if not r.grades_final:
                bad_cnt += r.term_enrolment_id in std.index
                continue
            fin = [x for x in rows if x.grade_status == "FINAL"]
            tp = sum(int(round(x.grade_points * 10)) * x.credits for x in fin)
            tc = sum(x.credits for x in fin)
            te_earned = sum(int(x.credits_earned) for x in fin)
            earned_total += te_earned
            pts, cred = pts + tp, cred + tc
            tg = round(tp / (10 * tc), 4) if tc else None
            cg = round(pts / (10 * cred), 4) if cred else None
            if (tg is None) != pd.isna(r.term_gpa) or (tg is not None and abs(tg - r.term_gpa) > 1e-4) or \
                    (cg is None) != pd.isna(r.cumulative_gpa) or (cg is not None and abs(cg - r.cumulative_gpa) > 1e-4):
                bad_gpa += 1
            bad_cred += (r.credits_earned != te_earned) or (r.cumulative_credits_earned != earned_total) or (r.gpa_credits != tc)
            if tc:
                ratio = te_earned / tc
                poor = tg < mn or ratio < ratio_min
                bad_poor += (pd.isna(r.poor_performance_flag) or bool(r.poor_performance_flag) != poor
                             or abs(r.passed_credit_ratio - round(ratio, 4)) > 1e-4)
            else:
                bad_poor += not (pd.isna(r.poor_performance_flag) and pd.isna(r.passed_credit_ratio))
            if r.term_enrolment_id not in std.index:
                bad_cnt += 1
                continue
            if tg is None:
                exp = prev or "NOT_EVALUATED"           # no graded courses: standing carried forward
            elif cg >= mn:
                exp = "GOOD"
            elif prev in (None, "GOOD", "NOT_EVALUATED"):
                exp = "WARNING"
            elif prev == "WARNING":
                exp = "PROBATION"
            else:
                exp = "DISMISSED" if tg < mn else "PROBATION"
            bad_std += std.loc[r.term_enrolment_id, "standing"] != exp
            if tg is not None:
                prev = exp
    R.add("GPA & standing", "semester GPA and cumulative GPA recompute from course grades", bad_gpa == 0, count=bad_gpa)
    R.add("GPA & standing", "term and cumulative credits earned recompute from course grades (incl. transferred credits)",
          bad_cred == 0, count=bad_cred)
    R.add("GPA & standing", "academic standing (good / warning / probation / dismissed) recomputes, carried forward when ungraded",
          bad_std == 0, count=bad_std)
    R.add("GPA & standing", "exactly one standing row per completed term enrolment; none for incomplete terms",
          bad_cnt == 0 and not std_df["term_enrolment_id"].duplicated().any(), count=bad_cnt)
    R.add("GPA & standing", "poor-performance flag and pass ratio recompute with the configured rule", bad_poor == 0, count=bad_poor)
    dis = t["registrar/student_programmes"]
    dismissed = set(dis.loc[dis["outcome"] == "DISMISSED", "student_programme_id"])
    std_dis = set(std_df.loc[std_df["standing"] == "DISMISSED", "student_programme_id"])
    R.add("GPA & standing", "DISMISSED outcome <=> DISMISSED standing", dismissed == std_dis, f"{len(dismissed)} dismissals")


def check_cohorts(t, R):
    sp = t["registrar/student_programmes"].sort_values(["student_id", "admission_date"])
    te = t["registrar/term_enrolments"]
    m = t["registrar/cohort_members"].merge(t["registrar/cohorts"], on="cohort_id")
    inst = m[m["cohort_type"] == "INSTITUTIONAL"]
    first = sp.groupby("student_id").first()
    R.add("Cohorts", "every student is in exactly one INSTITUTIONAL cohort",
          inst["student_id"].is_unique and set(inst["student_id"]) == set(sp["student_id"]))
    j = inst.set_index("student_id").join(first[["student_programme_id", "entry_term_id"]], rsuffix="_first")
    bad = int(((j["student_programme_id"] != j["student_programme_id_first"]) | (j["entry_term_id"] != j["entry_term_id_first"])).sum())
    R.add("Cohorts", "INSTITUTIONAL cohort = first admission term", bad == 0, count=bad)
    lvl = m[m["cohort_type"] == "LEVEL_ENTRY"]
    firstlvl = sp.groupby(["student_id", "level"]).first().reset_index()
    R.add("Cohorts", "exactly one LEVEL_ENTRY membership per student per level (first admission at that level)",
          not lvl.duplicated(["student_id", "level"]).any() and len(lvl) == len(firstlvl) and
          set(zip(lvl["student_id"], lvl["student_programme_id"])) == set(zip(firstlvl["student_id"], firstlvl["student_programme_id"])))
    ft = te[te["study_term_number"] == 1].drop_duplicates("student_programme_id").set_index("student_programme_id")
    bad = int(sum((m.set_index("student_programme_id")[a] != ft[b].reindex(m["student_programme_id"]).values).sum()
                  for a, b in [("delivery_mode_at_entry", "delivery_mode"), ("study_load_at_entry", "study_load")]))
    R.add("Cohorts", "frozen entry attributes equal the census-term enrolment", bad == 0, count=bad)
    sizes = t["registrar/cohort_members"].groupby("cohort_id").size()
    c = t["registrar/cohorts"].set_index("cohort_id")
    R.add("Cohorts", "size_at_census equals member count", bool((c["size_at_census"] == sizes.reindex(c.index)).all()))


def check_finance(t, R, as_of: date, cfg_threshold=100.0):
    ch, pay, holds = t["finance/charges"], t["finance/payments"], t["finance/financial_holds"]
    te, terms = t["registrar/term_enrolments"], t["reference/academic_terms"].drop_duplicates("term_id").set_index("term_id")
    keys = set(zip(te["student_programme_id"], te["term_id"]))
    bad = int(sum((a, b) not in keys for a, b in zip(ch["student_programme_id"], ch["term_id"])))
    R.add("Finance", "every charge belongs to an actual term enrolment", bad == 0, count=bad)
    tu = ch[ch["charge_type"] == "TUITION"]
    R.add("Finance", "every term enrolment is billed tuition", keys == set(zip(tu["student_programme_id"], tu["term_id"])))
    R.add("Finance", "charge amounts: positive fees, negative scholarships",
          bool(((ch["charge_type"] == "SCHOLARSHIP") == (ch["amount"] < 0)).all()))
    chg = defaultdict(list)
    for r in ch.itertuples():
        chg[r.student_id].append((D(r.due_date), r.amount))
    pays = defaultdict(list)
    unreadable = 0
    for r in pay.itertuples():
        if D(r.payment_date) is None:
            unreadable += 1                    # reported by the schema date checks; cannot be placed in time
            continue
        pays[r.student_id].append((D(r.payment_date), r.amount))
    check_dates = defaultdict(set)
    for r in tu.itertuples():
        check_dates[r.student_id].add(D(r.due_date) + timedelta(days=30))

    def pdue(sid, d):
        return round(sum(a for dd, a in chg[sid] if dd < d) - sum(a for dd, a in pays[sid] if dd <= d), 2)

    expected = []
    for sid in sorted(set(ch["student_id"])):
        pts = sorted({x for x in check_dates[sid] if x <= as_of} | {d for d, _ in pays[sid]})
        placed = None
        for d in pts:
            b = pdue(sid, d)
            if placed is None and d in check_dates[sid] and b > cfg_threshold:
                placed = d
            elif placed is not None and b <= cfg_threshold:
                expected.append((sid, placed, d))
                placed = None
        if placed is not None:
            expected.append((sid, placed, None))
    got = [(r.student_id, D(r.placed_date), D(r.released_date) if isinstance(r.released_date, str) else None) for r in holds.itertuples()]
    R.add("Finance", "financial holds recompute from charges and payments", sorted(expected, key=str) == sorted(got, key=str),
          f"{len(got)} holds", abs(len(expected) - len(got)))
    R.add("Finance", "hold status_as_of consistent with release date",
          bool(((holds["status_as_of"] == "ACTIVE") == holds["released_date"].isna()).all()))
    iv = defaultdict(list)
    for sid, p, r in got:
        iv[sid].append((p, r))
    active = lambda sid, d: any(p <= d and (r is None or r > d) for p, r in iv[sid])  # noqa: E731
    bad = sum(1 for r in te.itertuples() if active(r.student_id, D(terms.loc[r.term_id, "start_date"]) - timedelta(days=7)))
    R.add("Finance", "no registration while a financial hold is active", bad == 0, count=bad)
    blocks = t["finance/registration_blocks"]
    bad = sum(1 for r in blocks.itertuples() if not active(r.student_id, D(r.registration_date)))
    R.add("Finance", "every registration block coincides with an active hold", bad == 0, f"{len(blocks)} blocks", bad)
    enrolled_blocked = set(zip(blocks["student_id"], blocks["term_id"])) & set(zip(te["student_id"], te["term_id"]))
    R.add("Finance", "blocked students are not enrolled in the blocked term", not enrolled_blocked, count=len(enrolled_blocked))
    b = t["finance/account_balances"].drop_duplicates("student_id").set_index("student_id")
    tot_c = ch.groupby("student_id")["amount"].sum().reindex(b.index).fillna(0).round(2)
    tot_p = pay.groupby("student_id")["amount"].sum().reindex(b.index).fillna(0).round(2)
    pd_exp = pd.Series({sid: max(pdue(sid, as_of), 0) if pdue(sid, as_of) > 0 else pdue(sid, as_of) for sid in b.index})
    ok_bal = (abs(b["total_charged"] - tot_c) < 0.01) & (abs(b["total_paid"] - tot_p) < 0.01) & \
        (abs(b["outstanding_balance"] - (b["total_charged"] - b["total_paid"])) < 0.01)
    R.add("Finance", "account balances = charges - payments", bool(ok_bal.all()), count=int((~ok_bal).sum()))
    bad = int((abs(b["past_due_balance"] - pd_exp.reindex(b.index)) > 0.01).sum())
    R.add("Finance", "past-due balances recompute at the as-of date", bad == 0, count=bad)
    act = {sid for sid, p, r in got if r is None}
    bad = int((b["has_active_hold"].astype(bool) != b.index.isin(act)).sum())
    R.add("Finance", "has_active_hold flag equals the recomputed active holds", bad == 0, count=bad)
    pdates = pd.to_datetime(pay["payment_date"], format="%Y-%m-%d", errors="coerce")
    R.add("Finance", "payments are positive and validly dated on/before the as-of date",
          bool((pay["amount"] > 0).all() and pdates.notna().all() and pdates.max().date() <= as_of), count=unreadable)


def check_it(t, R, as_of: date):
    acc, ev, logins = t["it/user_accounts"], t["it/account_status_events"], t["it/login_events"]
    iv = defaultdict(list)
    for aid, g in ev.sort_values(["event_date", "event"]).groupby("account_id"):
        cur = None
        for r in g.itertuples():
            if r.event in ("ACTIVATED", "REACTIVATED"):
                cur = D(r.event_date)
            else:
                iv[aid].append((cur, D(r.event_date)))
                cur = None
        if cur:
            iv[aid].append((cur, None))
    lg = logins[logins["success"].astype(bool)]
    bad = 0
    for aid, ts in zip(lg["account_id"], lg["event_time"]):
        d = D(ts)
        bad += not any(a <= d and (b is None or d < b) for a, b in iv[aid])
    R.add("IT", "successful logins only while the account is active", bad == 0, f"{len(lg)} successful logins", bad)
    sa = acc[acc["account_type"] == "STUDENT"].set_index("person_id")
    first_start = t["registrar/student_programmes"].groupby("student_id")["admission_date"].min()
    bad = int((pd.to_datetime(sa["created_date"]) > pd.to_datetime(first_start.reindex(sa.index))).sum())
    R.add("IT", "student account created before the first term starts", bad == 0, count=bad)
    R.add("IT", "one account per student", sa.index.is_unique and set(sa.index) == set(t["registrar/students"]["student_id"]))
    st = t["it/server_status_daily"]
    R.add("IT", "server status uptime and downtime agree", bool((abs((100 - st["uptime_pct"]) / 100 * 1440 - st["downtime_minutes"]) < 0.1).all()))
    R.add("IT", "one incident per non-operational server day", len(t["it/incidents"]) == int((st["status"] != "OPERATIONAL").sum()))
    runs = t["data_warehouse/sync_runs"]
    outage = set(st.loc[(st["status"] == "OUTAGE") & st["server_id"].isin(["srv-dw-01", "srv-db-01"]), "status_date"])
    R.add("Data warehouse", "sync runs fail exactly on ETL/database outage days",
          set(runs.loc[runs["status"] == "FAILED", "run_date"]) == outage, f"{int((runs['status'] == 'FAILED').sum())} failed runs")


# ============================================================================ retention & graduation (independent)
class _Status:
    """Independent status-at-census implementation (validator copy)."""

    def __init__(self, t):
        terms = t["reference/academic_terms"].drop_duplicates("term_id").set_index("term_id")
        self.census = {k: D(v) for k, v in terms["census_date"].items()}
        self.enr = {(r.student_id, r.term_id): (r.programme_id, r.level) for r in t["registrar/term_enrolments"].itertuples()}
        self.by_student = defaultdict(list)
        for r in t["registrar/student_programmes"].itertuples():
            self.by_student[r.student_id].append(r)

    def __call__(self, sid, term):
        if (sid, term) in self.enr:
            return ("ENROLLED",) + self.enr[(sid, term)]
        c = self.census[term]
        progs = [p for p in self.by_student[sid] if D(p.admission_date) <= c]
        if any(p.outcome == "GRADUATED" and D(p.outcome_date) <= c for p in progs):
            return "COMPLETED", None, None
        if any(p.outcome == "ACTIVE" or D(p.outcome_date) > c for p in progs):
            return "ON_GAP", None, None
        return "LEFT", None, None


def check_retention(t, R, as_of: date, m: dict):
    terms = t["reference/academic_terms"].drop_duplicates("term_id").set_index("term_id")
    status = _Status(t)
    key = {(r.season, r.calendar_year): k for k, r in terms.iterrows()}
    nxt = lambda term: key.get((terms.loc[term, "season"], terms.loc[term, "calendar_year"] + 1))  # noqa: E731
    final_term = lambda c: c is not None and D(terms.loc[c, "census_date"]) <= as_of and bool(terms.loc[c, "has_enrolment_data"])  # noqa: E731
    seq_sorted = terms.sort_values("term_sequence")

    def classify(sid, cmp_, prog, lvl):
        """Outcome at the comparison census; optional Summer skipped by a student enrolled next Fall = continuing."""
        st, p2, l2 = status(sid, cmp_)
        cat = {"COMPLETED": "COMPLETED_NOT_ENROLLED", "ON_GAP": "STOPPED_OUT", "LEFT": "LEFT"}.get(st) or (
            "RETAINED_SAME_PROGRAMME" if p2 == prog else "RETAINED_PROGRAMME_TRANSFER" if l2 == lvl else "RETAINED_NEXT_LEVEL")
        cont = None
        if terms.loc[cmp_, "season"] == "SUMMER":
            later = seq_sorted[(seq_sorted["term_sequence"] > terms.loc[cmp_, "term_sequence"]) & seq_sorted["is_regular_term"]]
            nr = later.index[0] if len(later) and final_term(later.index[0]) else None
            cont = nr is not None and status(sid, nr)[0] == "ENROLLED"
            if st in ("ON_GAP", "LEFT") and cont:
                cat = "CONTINUING_SKIPPED_OPTIONAL_SUMMER"
        return st, cat, cont
    expected = {}
    mem = t["registrar/cohort_members"].merge(t["registrar/cohorts"][["cohort_id", "cohort_type", "entry_term_id"]], on="cohort_id")
    pers = {"FALL": "FALL_TO_FALL", "SPRING": "SPRING_TO_SPRING", "SUMMER": "SUMMER_TO_SUMMER"}
    for r in mem[mem["cohort_type"] == "INSTITUTIONAL"].itertuples():
        expected[("FIRST_YEAR_COHORT", r.entry_term_id, r.student_id)] = (nxt(r.entry_term_id), r.programme_at_entry, r.level_at_entry)
    for r in t["registrar/term_enrolments"].itertuples():
        expected[(pers[terms.loc[r.term_id, "season"]], r.term_id, r.student_id)] = (nxt(r.term_id), r.programme_id, r.level)
    rm = t["registrar/retention_cohort_members"]
    got = {(r.comparison_type, r.base_term_id, r.student_id): r for r in rm.itertuples()}
    R.add("Retention", "retention membership = every INSTITUTIONAL cohort member + every base-term enrolment (no more, no less)",
          set(got) == set(expected) and len(rm) == len(expected), f"{len(expected)} expected, {len(rm)} found",
          len(set(got) ^ set(expected)) + abs(len(rm) - len(got)))
    bad, why = 0, Counter()
    calc = []
    for k, (cmp_, prog, lvl) in expected.items():
        fin = final_term(cmp_)
        r = got.get(k)
        if r is None:
            if fin:
                calc.append((k[0], k[1], classify(k[2], cmp_, prog, lvl)[1]))
            continue
        ok = {"compare_term": (r.compare_term_id if isinstance(r.compare_term_id, str) else None) == cmp_,
              "base_attributes": r.base_programme_id == prog and r.base_level == lvl, "is_final": bool(r.is_final) == fin}
        cat = None
        if fin:
            st, cat, cont = classify(k[2], cmp_, prog, lvl)
            ok["summer_continuation_flag"] = (cont is None and pd.isna(r.continued_next_regular_term)) or                 (cont is not None and not pd.isna(r.continued_next_regular_term) and bool(r.continued_next_regular_term) == cont)
            ok["outcome"] = r.outcome_category == cat and bool(r.institutionally_retained) == (st == "ENROLLED") and \
                bool(r.programme_retained) == (cat == "RETAINED_SAME_PROGRAMME") and bool(r.completed_before_compare) == (st == "COMPLETED")
            exp_label = "FINAL_CENSUS_SNAPSHOT" if terms.loc[cmp_, "reporting_status"] == "CENSUS_SNAPSHOT_ONLY" else "FINAL"
            ok["label"] = r.reporting_label == exp_label
            calc.append((k[0], k[1], cat))
        else:
            ok["no_outcome_when_incomplete"] = pd.isna(r.outcome_category) and r.reporting_label.startswith("INCOMPLETE")
        for kk, v in ok.items():
            why[kk] += not v
        bad += not all(ok.values())
    R.add("Retention", "retention outcomes recompute independently (retained same programme / transfer / completed / stopped out / left)",
          bad == 0, {k: v for k, v in why.items() if v} or f"{len(calc)} final member outcomes", bad)
    rr = m["retention_rates"]
    agg = defaultdict(Counter)
    for ctype, base, cat in calc:
        agg[(ctype, base)][cat] += 1
    allr = rr[(rr["group_by"] == "ALL") & (rr["is_final"] == True)]  # noqa: E712
    bad = 0
    for r in allr.itertuples():
        c = agg[(r.comparison_type, r.base_term_id)]
        n = sum(c.values())
        comp = c["COMPLETED_NOT_ENROLLED"]
        ret = c["RETAINED_SAME_PROGRAMME"] + c["RETAINED_PROGRAMME_TRANSFER"] + c["RETAINED_NEXT_LEVEL"]
        elig = n - comp
        exp_rate = round(ret / elig, 4) if elig else None
        if str(r.compare_term_id).endswith("SU") and elig:
            bad += abs(round((ret + c["CONTINUING_SKIPPED_OPTIONAL_SUMMER"]) / elig, 4) - float(r.summer_continuation_rate)) > 1e-4
        bad += (n != r.denominator or comp != r.completed or ret != r.institutionally_retained or
                c["RETAINED_SAME_PROGRAMME"] != r.programme_retained or
                (exp_rate is not None and abs(exp_rate - float(r.institutional_retention_rate)) > 1e-4))
    R.add("Retention", "retention rates recompute: retained / (cohort - completed); programme retention; completions separate",
          bad == 0 and len(allr) == len(agg), f"{len(allr)} final comparisons", bad)
    fin = rr[rr["is_final"] == True]  # noqa: E712
    s = fin["institutionally_retained"] + fin["completed"] + fin["continuing_skipped_optional_summer"] + fin["stopped_out"] + fin["left"]
    R.add("Retention", "retained + completed + continuing (optional summer) + stopped out + left = denominator (100 %)", bool((s == fin["denominator"]).all()))
    summer = rm[rm["compare_term_id"].astype(str).str.endswith("SU") & (rm["is_final"] == True)]  # noqa: E712
    bad = int(((summer["outcome_category"].isin(["STOPPED_OUT", "LEFT"])) & (summer["continued_next_regular_term"] == True)).sum()) +         int((rm.loc[~rm["compare_term_id"].astype(str).str.endswith("SU"), "outcome_category"] == "CONTINUING_SKIPPED_OPTIONAL_SUMMER").sum())  # noqa: E712
    R.add("Retention", "optional Summer: students enrolled the following Fall are never classified as stopped out or left",
          bad == 0, f"{int((summer['outcome_category'] == 'CONTINUING_SKIPPED_OPTIONAL_SUMMER').sum())} continuing summer non-enrollees", bad)
    R.add("Retention", "programme retained <= institutionally retained; retained excludes graduates",
          bool((fin["programme_retained"] <= fin["institutionally_retained"]).all()) and
          not ((rm["institutionally_retained"] == True) & (rm["completed_before_compare"] == True)).any())  # noqa: E712
    tot = fin[fin["group_by"] == "ALL"].set_index("comparison_id")["denominator"]
    grp = fin[fin["group_by"] != "ALL"].groupby(["comparison_id", "group_by"])["denominator"].sum()
    R.add("Retention", "filtered groups (level, school, programme, mode, load) add up to the whole comparison",
          bool(all(v == tot.loc[k[0]] for k, v in grp.items())))
    inc = rr[rr["is_final"] == False]  # noqa: E712
    R.add("Retention", "incomplete comparisons publish no rate", "institutional_retention_rate" not in inc or inc["institutional_retention_rate"].isna().all(),
          f"{inc['comparison_id'].nunique()} incomplete comparisons")
    fy = allr[(allr["comparison_type"] == "FIRST_YEAR_COHORT") & (allr["base_term_id"] == "2025FA")]
    R.add("Retention", "first-year Fall 2025 -> Fall 2026 cohort retention is FINAL_CENSUS_SNAPSHOT (Fall 2026 census passed, term in progress)",
          len(fy) == 1 and fy.iloc[0]["reporting_label"] == "FINAL_CENSUS_SNAPSHOT",
          fy[["denominator", "institutional_retention_rate", "programme_retention_rate"]].to_dict("records"))
    s26 = rr[(rr["base_term_id"].isin(["2026SP", "2026SU"])) & (rr["group_by"] == "ALL")]
    R.add("Retention", "Spring 2026 -> Spring 2027 and Summer 2026 -> Summer 2027 are INCOMPLETE (future terms)",
          len(s26) >= 2 and not s26["is_final"].astype(bool).any())
    fut = set(terms.index[terms["term_status"] == "FUTURE"])
    leaks = int(rm.loc[rm["is_final"] == True, "compare_term_id"].isin(fut).sum())  # noqa: E712
    R.add("Retention", "no FINAL retention is measured in a future term", leaks == 0, count=leaks)
    cr = m["cohort_retention_multi_year"]
    f = cr[cr["is_final"] == True]  # noqa: E712
    R.add("Retention", "multi-year cohort retention: enrolled + completed + on gap + left = cohort size",
          bool(((f["enrolled"] + f["completed"] + f["on_gap"] + f["left"]) == f["denominator"]).all()))


def check_graduation(t, R, as_of: date, m: dict):
    terms = t["reference/academic_terms"].drop_duplicates("term_id").set_index("term_id")
    rules = t["reference/level_rules"].set_index("level")
    sp, te = t["registrar/student_programmes"], t["registrar/term_enrolments"]
    inprog = set(terms.index[terms["reporting_status"] == "CENSUS_SNAPSHOT_ONLY"])
    enrolled_now = set(te.loc[te["term_id"].isin(inprog), "student_programme_id"])
    by = defaultdict(list)
    for r in sp.itertuples():
        by[(r.student_id, r.level)].append(r)
    mem = t["registrar/cohort_members"].merge(t["registrar/cohorts"][["cohort_id", "cohort_type", "entry_term_id"]], on="cohort_id")
    lvl = mem[mem["cohort_type"] == "LEVEL_ENTRY"]
    gr = t["registrar/graduation_records"]
    got = {(r.cohort_id, r.student_id): r for r in gr.itertuples()}
    R.add("Graduation", "one graduation record per LEVEL_ENTRY cohort member", len(gr) == len(lvl) and set(got) == set(zip(lvl["cohort_id"], lvl["student_id"])),
          f"{len(lvl)} members, {len(gr)} records")
    bad, why = 0, Counter()
    agg = defaultdict(lambda: [0, 0])
    for r in lvl.itertuples():
        g = got.get((r.cohort_id, r.student_id))
        if g is None:
            continue
        s = D(terms.loc[r.entry_term_id, "start_date"])
        w = int(rules.loc[r.level_at_entry, "graduation_window_years"])
        wend = date(s.year + w, s.month, s.day)
        mature = wend <= as_of
        path = sorted(by[(r.student_id, r.level_at_entry)], key=lambda p: p.admission_date)
        grads = [p for p in path if p.outcome == "GRADUATED"]
        if grads:
            gd = D(grads[0].outcome_date)
            stt = "GRADUATED_WITHIN_WINDOW" if gd <= wend else "GRADUATED_AFTER_WINDOW"
        else:
            gd = None
            stt = ("ENROLLED_NOT_GRADUATED" if path[-1].student_programme_id in enrolled_now else
                   "STOPPED_OUT_NOT_GRADUATED" if path[-1].outcome == "ACTIVE" else "LEFT_NOT_GRADUATED")
        ok = {"window": int(g.window_years) == w and D(g.window_end_date) == wend,
              "same_maturity_rule_all_levels": bool(g.cohort_mature) == mature and bool(g.counts_in_final_rate) == mature,
              "admission": D(g.admission_date) == s and g.entry_term_id == r.entry_term_id,
              "status": g.graduation_status == stt,
              "graduation_date": (D(g.graduation_date) if isinstance(g.graduation_date, str) else None) == gd,
              "not_after_as_of": gd is None or gd <= as_of,
              "min_duration": gd is None or (gd - s).days / 365.25 >= rules.loc[r.level_at_entry, "min_years_to_graduate"],
              "time_to_degree": gd is None or abs(round((gd - s).days / 365.25, 3) - g.time_to_degree_years) < 1e-6,
              "basis_label": g.window_basis == "PROJECT_CONFIGURED_REPORTING_ASSUMPTION"}
        for k, v in ok.items():
            why[k] += not v
        bad += not all(ok.values())
        if mature:
            agg[r.level_at_entry][0] += 1
            agg[r.level_at_entry][1] += stt == "GRADUATED_WITHIN_WINDOW"
    R.add("Graduation", "graduation records recompute independently (window, maturity, status, dates, time-to-degree)",
          bad == 0, {k: v for k, v in why.items() if v} or f"{len(gr)} records", bad)
    rates = m["graduation_rates"]
    lv = rates[rates["aggregation"] == "MATURE_COHORTS_BY_LEVEL"].set_index("level")
    bad = 0
    detail = {}
    for level in ("UNDERGRADUATE", "MASTERS", "DOCTORATE"):
        n, k = agg[level]
        detail[level] = f"{k}/{n}" + (f" = {k / n:.1%}" if n else "")
        if n == 0:
            bad += level in lv.index
            continue
        bad += level not in lv.index or int(lv.loc[level, "denominator"]) != n or abs(float(lv.loc[level, "graduation_rate"]) - round(k / n, 4)) > 1e-4
    R.add("Graduation", "final graduation rates recompute (UG 6 y, Master's 4 y, Doctorate 6 y; mature cohorts only)", bad == 0, detail, bad)
    coh = rates[rates["aggregation"] == "COHORT"]
    R.add("Graduation", "immature cohorts publish no final graduation rate",
          coh.loc[coh["is_final"] == False, "graduation_rate"].isna().all() if "graduation_rate" in coh else True)  # noqa: E712
    w = rules["graduation_window_years"].to_dict()
    R.add("Graduation", "configured windows are UG 6, Master's 4, Doctorate 6 years (project-configured reporting assumptions)",
          w == {"UNDERGRADUATE": 6, "MASTERS": 4, "DOCTORATE": 6} and
          set(rules["window_basis"]) == {"PROJECT_CONFIGURED_REPORTING_ASSUMPTION"}, w)
    grads_sp = set(sp.loc[sp["outcome"] == "GRADUATED", "student_programme_id"])
    R.add("Graduation", "graduates are kept separate from enrolled students (no enrolment in a graduated admission after graduation)",
          not te["student_programme_id"].isin(grads_sp & set(te.loc[te["term_id"].isin(inprog), "student_programme_id"])).any()
          and gr.loc[~gr["graduation_status"].str.startswith("GRADUATED"), "graduation_date"].isna().all()
          and gr.loc[gr["graduation_status"].str.startswith("GRADUATED"), "graduation_date"].notna().all())
    ttd = m["time_to_degree"]
    R.add("Graduation", "time-to-degree summary covers every graduation record with a graduation date",
          int(ttd["graduates"].sum()) == int(gr["graduation_date"].notna().sum()))


def check_aggregates(t, R, m: dict):
    te = t["registrar/term_enrolments"]
    eb = m["enrolment_by_term"]
    a = eb.groupby("term_id")["headcount"].sum()
    b = te.groupby("term_id").size()
    R.add("Enrolment", "enrolment by term x school x programme x level x mode x load x gender x residency x nationality sums to headcount",
          a.reindex(b.index).fillna(0).astype(int).equals(b.astype(int)) and int(eb["headcount"].sum()) == len(te))
    terms = t["reference/academic_terms"].set_index("term_id")
    R.add("Enrolment", "the in-progress term is labelled CENSUS_SNAPSHOT_ONLY in enrolment outputs",
          set(eb.loc[eb["term_id"].map(terms["term_status"]) == "IN_PROGRESS", "reporting_status"]) <= {"CENSUS_SNAPSHOT_ONLY"})
    ay = m["enrolment_by_academic_year"]
    tot = ay[ay["level"] == "ALL"].set_index("academic_year")["unduplicated_headcount"]
    R.add("Enrolment", "academic-year unduplicated headcount recomputes", tot.astype(int).equals(te.groupby("academic_year")["student_id"].nunique().reindex(tot.index).astype(int)))
    pf = m["performance_by_term"]
    status = terms["term_status"]
    R.add("Performance", "performance outputs use completed terms only", set(pf["term_id"].map(status)) <= {"COMPLETED"})
    ce = t["registrar/course_enrolments"]
    ce = ce[ce["grade_status"] == "FINAL"].merge(te[["term_enrolment_id", "level"]], on="term_enrolment_id")
    exp = ce.groupby(["term_id", "level"]).apply(
        lambda g: (g["grade_points"].mul(10).round().astype(int) * g["credits"]).sum() / (10 * g["credits"].sum()), include_groups=False)
    p = pf[pf["aggregation"] == "level"].set_index(["term_id", "level"])["credit_weighted_term_gpa"]
    diff = (pd.to_numeric(p, errors="coerce") - exp.reindex(p.index)).abs().fillna(1.0)
    R.add("Performance", "credit-weighted term GPA by term and level recomputes from course grades", bool((diff < 1e-3).all()), count=int((diff >= 1e-3).sum()))
    sc = [c for c in pf.columns if c.startswith("standing_")]
    R.add("Performance", "standing counts add up to completed enrolments", bool((pf[sc].sum(axis=1) == pf["completed_enrolments"]).all()))


def check_reproducibility(R, out: Path):
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        from .synthetic.generate import generate
        m1 = generate(Path(a))
        m2 = generate(Path(b), overrides={"meta.random_seed": 12345})
    cur = json.loads((out / "manifest.json").read_text())
    same = {k: v["sha256"] for k, v in m1["files"].items()} == {k: v["sha256"] for k, v in cur["files"].items()}
    R.add("Reproducibility", "same seed reproduces every exported file byte-for-byte", same, f"{len(m1['files'])} files")
    diff = sum(m1["files"][k]["sha256"] != m2["files"][k]["sha256"] for k in m1["files"])
    R.add("Reproducibility", "a different seed produces different files", diff > 0, f"{diff} files differ")
    R.add("Reproducibility", "original UCI file unchanged after regeneration", sha256_of(RAW_UCI_FILE) == UCI_EXPECTED_SHA256)


# ============================================================================ run
def run_validation(out: Path, repro: bool = False) -> tuple[Report, dict | None, dict]:
    import tomllib
    out = Path(out)
    manifest = json.loads((out / "manifest.json").read_text())
    as_of = date.fromisoformat(manifest["as_of_date"])
    cfg = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    t = read_all(out)
    uci = read_uci()
    R = Report()

    def guarded(fn, *args):
        try:
            return fn(*args)
        except Exception as e:  # a crash in a check group is itself a failed check, never a silent abort
            R.add("Validator", f"{fn.__name__} completed without error", False, f"{type(e).__name__}: {e}")
            return None

    guarded(check_schema, t, uci, R)
    guarded(check_ids_and_keys, t, R)
    guarded(check_sources, t, R, manifest)
    guarded(check_terms, t, R, as_of)
    guarded(check_timeline, t, R, as_of, cfg)
    guarded(check_status_history, t, R, as_of)
    guarded(check_gpa_and_standing, t, R, cfg)
    guarded(check_cohorts, t, R)
    guarded(check_finance, t, R, as_of, float(cfg["finance"]["hold_threshold"]))
    guarded(check_it, t, R, as_of)
    m = guarded(M.compute_aggregates, out)
    if m:
        guarded(check_retention, t, R, as_of, m)
        guarded(check_graduation, t, R, as_of, m)
        guarded(check_aggregates, t, R, m)
    if repro:
        guarded(check_reproducibility, R, out)
    return R, m, {"t": t, "uci": uci, "manifest": manifest, "cfg": cfg}


# ============================================================================ report
def summary(t, m, uci) -> dict:
    sp = t["registrar/student_programmes"]
    rr, gr = m["retention_rates"], m["graduation_rates"]
    allr = rr[(rr["group_by"] == "ALL") & (rr["is_final"] == True)]  # noqa: E712

    def ret(ctype, base):
        x = allr[(allr["comparison_type"] == ctype) & (allr["base_term_id"] == base)]
        return None if x.empty else x.iloc[0][["denominator", "completed", "eligible_to_return", "institutionally_retained",
                                               "programme_retained", "stopped_out", "left", "institutional_retention_rate",
                                               "programme_retention_rate", "reporting_label"]].to_dict()

    lv = gr[gr["aggregation"] == "MATURE_COHORTS_BY_LEVEL"]
    return {
        "rows": {k: int(len(v)) for k, v in t.items()},
        "uci_rows": {k: int(len(v)) for k, v in uci.items()},
        "students": int(len(t["registrar/students"])),
        "admissions_by_entry_type": sp["entry_type"].value_counts().to_dict(),
        "outcomes_by_level": {lvl: g["outcome"].value_counts().to_dict() for lvl, g in sp.groupby("level")},
        "first_year_retention_2025FA_to_2026FA": ret("FIRST_YEAR_COHORT", "2025FA"),
        "fall_to_fall_2025FA_to_2026FA": ret("FALL_TO_FALL", "2025FA"),
        "spring_to_spring_2025SP_to_2026SP": ret("SPRING_TO_SPRING", "2025SP"),
        "summer_to_summer_2025SU_to_2026SU": ret("SUMMER_TO_SUMMER", "2025SU"),
        "final_graduation_rates": {r.level: {"window_years": int(r.window_years), "denominator": int(r.denominator),
                                             "graduated_within_window": int(r.graduated_within_window), "rate": float(r.graduation_rate)}
                                   for r in lv.itertuples()},
        "final_cohort_entry_range": {lvl: [g["entry_term_id"].min(), g["entry_term_id"].max()]
                                     for lvl, g in gr[(gr["aggregation"] == "COHORT") & (gr["is_final"] == True)].groupby("level")},  # noqa: E712
        "time_to_degree": m["time_to_degree"].set_index("level").to_dict("index"),
        "headcount_by_term_first_last": {k: int(v) for k, v in t["registrar/term_enrolments"].groupby("term_id").size()
                                         .loc[["2016FA", "2025FA", "2026FA"]].items()},
    }


METHODOLOGY = """
**Status at a census date** (priority order): ENROLLED (term enrolment in that term, any programme) > COMPLETED (graduated
on/before the census, not enrolled) > ON_GAP (an admission still open: stopped out) > LEFT (withdrawn/dismissed, not readmitted).

**Retention comparisons** (`registrar/retention_cohort_members.csv`, rates in `reports/metrics/retention_rates.csv`):

| Comparison | Eligible cohort (denominator) | Measured at |
|---|---|---|
| FIRST_YEAR_COHORT | INSTITUTIONAL cohort: students whose *first ever* admission is the base term, frozen at its census | census of the same season one year later (e.g. Fall 2025 -> Fall 2026) |
| FALL_TO_FALL | everyone enrolled at the Fall census | next Fall census |
| SPRING_TO_SPRING | everyone enrolled at the Spring census | next Spring census |
| SUMMER_TO_SUMMER | everyone enrolled at the Summer census | next Summer census |

* **Optional Summer**: a student not enrolled at a Summer comparison census but enrolled at the next Fall census is
  CONTINUING_SKIPPED_OPTIONAL_SUMMER, never stopped out, withdrawn or left (this includes programme transfers taking effect
  in the Fall). Summer comparisons publish the strict re-enrolment rate and a **summer continuation rate**
  = (retained + continuing) / (cohort - completed).
* **Who returned**: enrolled in the comparison term (institutional retention, any programme). **Programme retention** counts only
  students enrolled in the same programme; internal transfers count as institutionally retained (RETAINED_PROGRAMME_TRANSFER),
  graduates who started the next degree level count as RETAINED_NEXT_LEVEL.
* **Graduates** (COMPLETED_NOT_ENROLLED) are never counted as retained; they are reported separately as completions and removed
  from the rate denominator: `retention_rate = retained / (cohort - completed)`. The unadjusted rate `retained / cohort` is also published.
* **Incomplete comparisons** (comparison census after the as-of date, e.g. Spring 2026 -> Spring 2027) are labelled INCOMPLETE and publish no rate.
  Fall 2026 is in progress: its census has passed, so Fall 2025 -> Fall 2026 is published as **FINAL_CENSUS_SNAPSHOT**
  (census headcount only; no Fall 2026 grades, standing or graduations exist).
* Retention is computed person by person from enrolment and outcome records, **never from differences between total headcounts**.

**Graduation** (`registrar/graduation_records.csv`, rates in `reports/metrics/graduation_rates.csv`):
* Cohort: LEVEL_ENTRY (first admission at the level). Original admission date/term are kept; programme changes stay in the same cohort.
* Graduated within window = graduation date <= entry-term start + window (UG 6, Master's 4, Doctorate 6 years).
  These windows are **project-configured reporting assumptions** requested for this dashboard, not verified university policy.
* Same maturity rule for every level: a cohort is **mature** only when the window end is on/before the as-of date and every term
  ending in the window is completed. Only mature cohorts enter final rates; others are labelled "INCOMPLETE: graduation window still open".
* Time to degree = (graduation date - original admission date) / 365.25, plus enrolled terms and missed regular terms.
"""

ASSUMPTIONS = """
* Every school, programme, course, calendar date, fee, grading scale, GPA threshold, standing rule, withdrawal rule and window is a
  **PLACEHOLDER** (`verification_status = PLACEHOLDER`, names suffixed "[synthetic placeholder]"). Verified values go to EXTERNAL_REFERENCE.
* Calendar: Fall 09-01 / census 09-15 / end 12-20; Spring 01-15 / 01-29 / 05-10; Summer 05-25 / 06-05 / 08-10 (placeholders).
* As-of date 2026-11-10: terms ending on/before it are COMPLETED_TERM; Fall 2026 is CENSUS_SNAPSHOT_ONLY; Spring/Summer 2027 are
  FUTURE_NOT_REPORTABLE (only 320 pending/decided applications exist for Spring 2027).
* Missed-term withdrawal (rule `SYN-WD-MISSED-TERMS`, configurable `academic.max_consecutive_missed_terms = 3`): a **synthetic business rule**.
  More than 3 consecutive missed regular terms records an UNOFFICIAL withdrawal at the census of the next missed term. It only fills the
  outcome fields of that admission and adds a status-history event; the admission record and history are never overwritten.
* GPA: demonstration 4-point scale, credit-weighted from final course grades (W excluded). Standing: CGPA >= minimum -> GOOD; otherwise
  WARNING -> PROBATION -> DISMISSED (dismissal only if the term GPA is also below the minimum). Terms without graded courses carry the
  previous standing forward (NOT_EVALUATED before the first graded term). Minimums UG 2.0, Master's/Doctorate 3.0 (placeholders).
* Poor performance (synthetic rule): term GPA below the level minimum or less than 50 % of graded credits passed.
* Home country is the placeholder code `ZZZ` ("Home country (placeholder - not configured)").
"""

LIMITATIONS = """
* All institutional records are **synthetic**; patterns are plausible, not empirical, and must not be presented as real results.
* UCI records cannot support term-based retention, graduation within 4/6 years, delivery mode, school/programme, or official GPA;
  they cover only the first study year and an outcome at normal duration. They remain a separate analytical zone.
* Placeholder names and rules have not been confirmed by the university; all thresholds are configurable.
* Doctorate research progress is simplified to research-credit registration; no thesis milestones, supervisors or examinations.
* No course sections, instructors, timetables, financial aid packages or refunds are modelled; finance amounts are demonstration values.
* IT data covers only the 180 days up to the as-of date; login events are sampled behaviour, not real system logs.
* Fall 2026 retention is a census snapshot; it can change if late withdrawals were modelled (they are not).
* Doctorate cohorts after Summer 2020 and UG cohorts after Summer 2020 / Master's after Summer 2022 are not yet mature.
"""


def write_report(R: Report, m, ctx, out: Path, seconds: float):
    t, uci, manifest = ctx["t"], ctx["uci"], ctx["manifest"]
    stats = summary(t, m, uci) if m else {}
    rep = out / "reports"
    rep.mkdir(exist_ok=True)
    write_json({"passed": len(R.checks) - len(R.failed), "failed": len(R.failed), "checks": R.checks, "summary": stats},
               rep / "data_quality_report.json")
    us = uci.get("uci_students", pd.DataFrame())
    cats = Counter(c["category"] for c in R.checks)
    fails = Counter(c["category"] for c in R.failed)
    L = ["# Data Quality Report: institutional analytics dataset", "",
         "> **Synthetic institutional records are DEMONSTRATION DATA, NOT REAL UNIVERSITY RECORDS.** UCI records are real public data "
         "kept in a separate zone. The two populations are never combined.", "",
         f"- Generation run `{manifest.get('generation_run_id')}` · generator `{manifest['generator_version']}` · seed `{manifest['random_seed']}` "
         f"· as-of date `{manifest['as_of_date']}`",
         f"- Validation: **{len(R.checks) - len(R.failed)} checks passed, {len(R.failed)} failed** ({seconds:.0f} s)", "",
         "## 1. UCI coverage (Zone A, real public data)", "",
         f"- Source: `data/raw/data.csv` (UCI *Predict Students' Dropout and Academic Success*), SHA-256 `{UCI_EXPECTED_SHA256[:16]}...` verified unchanged.",
         f"- Processed tables: " + ", ".join(f"`{k}` ({v:,} rows)" for k, v in stats.get("uci_rows", {}).items()),
         f"- {len(us):,} students; outcomes at normal duration: " + ", ".join(f"{k} {v:,}" for k, v in us["outcome_at_normal_duration"].value_counts().items()) if len(us) else "",
         "- Covers: demographics, nationality, application mode/order, previous qualification, admission grade, first-year semester units and "
         "0-20 grades (not GPA), scholarship/debtor/fees flags, macro-economic context, outcome at normal duration.",
         "- Not covered (never invented): calendar terms, admission/graduation dates, schools, university programmes, delivery mode, "
         "official GPA, multi-year enrolment, retention terms.", "",
         "## 2. Existing synthetic coverage (before this revision, generator 1.0.0)", "",
         "- 5,000 synthetic students 2016FA-2026FA: admissions/applications, programme admissions, term and course enrolments, grades, GPA, "
         "standing, cohorts, charges/payments/holds, IT accounts/logins/servers, data-warehouse sync log.",
         "- Retention/graduation were computed only in report outputs (no member-level records).", "",
         "## 3. Missing features found by the audit", "",
         "| Gap | Impact |", "|---|---|",
         "| `school_id`, `academic_year` missing on term enrolments | enrolment by school / academic year needed joins |",
         "| no reference tables for academic years, nationalities, genders, delivery modes, attendance loads, status codes | unvalidated codes |",
         "| 728 completed term enrolments (all courses withdrawn) had no standing row | incomplete standing history |",
         "| no poor-performance flag | performance module incomplete |",
         "| no student status history | stop-out / return / withdrawal events not traceable |",
         "| no retention cohort membership, no programme retention, graduates not removed from the denominator | retention not auditable |",
         "| no graduation records (eligibility, maturity, status per student) | graduation module not auditable |",
         "| Doctorate window labelled UNCONFIRMED; withdrawal rule not documented as a business rule | labelling |",
         "| no generation-run id / source system on rows; no documented schema or data dictionary | lineage |", "",
         "## 4. Features generated or corrected (generator 1.1.0)", "",
         "- **Corrected**: Doctorate 6-year window relabelled *project-configured reporting assumption* (same maturity rule as UG/Master's); "
         "term `reporting_status` (COMPLETED_TERM / CENSUS_SNAPSHOT_ONLY / FUTURE_NOT_REPORTABLE); missed-term withdrawal documented as "
         "configurable synthetic rule `SYN-WD-MISSED-TERMS`; standing written for every completed term (carried forward when ungraded).",
         "- **Added fields**: `term_enrolments.school_id`, `academic_year`, `passed_credit_ratio`, `poor_performance_flag`; `applications.school_id`; "
         "`display_name` / `is_placeholder` on schools and programmes; `source_system` + `generation_run_id` on every synthetic row.",
         "- **Added tables**: `reference/academic_years`, `nationalities`, `gender_categories`, `delivery_modes`, `attendance_loads`, "
         "`academic_standing_codes`, `student_status_codes`; `registrar/student_status_history`, `retention_cohort_members`, "
         "`graduation_records`; `data_warehouse/generation_runs`; `schema/data_dictionary.csv`.",
         "- **Metric outputs** (`reports/metrics/`): retention_rates, cohort_retention_multi_year, graduation_rates, time_to_degree, "
         "enrolment_by_term, enrolment_by_academic_year, performance_by_term.", "",
         "## 5. Final record counts", "", "| File | Rows |", "|---|---:|"]
    L += [f"| `{k}` | {v:,} |" for k, v in stats.get("rows", {}).items()]
    L += ["", "## 6. Checks passed and failed", "", "| Category | Checks | Failed |", "|---|---:|---:|"]
    L += [f"| {c} | {n} | {fails.get(c, 0)} |" for c, n in cats.items()]
    L += ["", "<details><summary>All checks</summary>", "", "| Category | Check | Result | Detail |", "|---|---|---|---|"]
    L += [f"| {c['category']} | {c['check']} | {'PASS' if c['status'] == 'PASS' else '**FAIL**'} | {str(c['detail']).replace('|', '/')} |"
          for c in R.checks]
    L += ["", "</details>", "", "Key results (synthetic only):", "", "```json", json.dumps({k: v for k, v in stats.items() if k not in ("rows", "uci_rows")},
                                                                                     indent=2, default=str), "```", "",
          "## 7. Limitations", LIMITATIONS, "## 8. Retention and graduation methodology", METHODOLOGY,
          "## 9. Assumptions and placeholder policies", ASSUMPTIONS,
          "## 10. Machine learning status", "",
          "**No machine-learning model has been trained, selected, tuned or evaluated.** The pipelines only process, generate and validate data; "
          "no dashboard development has started.", ""]
    (rep / "data_quality_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=SYNTHETIC_DIR)
    ap.add_argument("--skip-repro", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    R, m, ctx = run_validation(a.out, repro=not a.skip_repro)
    if m:
        for name, df in m.items():
            write_csv(df, a.out / "reports" / "metrics" / f"{name}.csv")
    write_report(R, m, ctx, a.out, time.time() - t0)
    for c in R.checks:
        print(f"{c['status']}  [{c['category']}] {c['check']}" + (f"  -> {c['detail']}" if c["status"] == "FAIL" else ""))
    print(f"\n{len(R.checks) - len(R.failed)} passed, {len(R.failed)} failed")
    sys.exit(1 if R.failed else 0)


if __name__ == "__main__":
    main()
