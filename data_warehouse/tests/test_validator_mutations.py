"""Mutation tests: deliberately introduce errors into a small generated sample and assert the validator catches them.

Run from the data_warehouse folder:  python -m pytest -q
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from pipelines.common import write_csv
from pipelines.synthetic.generate import generate
from pipelines.validation import run_validation


def _read(d: Path, rel: str) -> pd.DataFrame:
    return pd.read_csv(d / f"{rel}.csv", keep_default_na=False, na_values=[""], low_memory=False)


def _write(d: Path, rel: str, df: pd.DataFrame):
    write_csv(df, d / f"{rel}.csv")


@pytest.fixture(scope="module")
def base(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("base")
    generate(d, overrides={"meta.target_students": 300})
    return d


def test_clean_sample_passes_every_check(base):
    R, _, _ = run_validation(base)
    assert not R.failed, R.failed


# ---------------------------------------------------------------- mutations: (description, function(dir), expected failing checks)
def m_graduation_after_as_of(d):
    sp = _read(d, "registrar/student_programmes")
    i = sp.index[sp["outcome"] == "GRADUATED"][0]
    sp.loc[i, ["outcome_date", "outcome_recorded_date"]] = "2027-05-10"
    _write(d, "registrar/student_programmes", sp)


def m_graduation_before_minimum_duration(d):
    sp = _read(d, "registrar/student_programmes")
    te = _read(d, "registrar/term_enrolments")
    g = sp[sp["outcome"] == "GRADUATED"].iloc[0]
    first = te[te["student_programme_id"] == g["student_programme_id"]].sort_values("term_sequence").iloc[0]
    terms = _read(d, "reference/academic_terms").set_index("term_id")
    sp.loc[g.name, "outcome_term_id"] = first["term_id"]
    sp.loc[g.name, "outcome_date"] = terms.loc[first["term_id"], "end_date"]
    _write(d, "registrar/student_programmes", sp)


def m_invalid_delivery_mode(d):
    te = _read(d, "registrar/term_enrolments")
    te.loc[0, "delivery_mode"] = "HYBRID"
    _write(d, "registrar/term_enrolments", te)


def m_mode_not_offered(d):
    p = _read(d, "reference/programmes")
    face_only = set(p.loc[~p["delivery_modes_offered"].str.contains("ONLINE"), "programme_id"])
    te = _read(d, "registrar/term_enrolments")
    i = te.index[te["programme_id"].isin(face_only)][0]
    te.loc[i, "delivery_mode"] = "ONLINE"
    _write(d, "registrar/term_enrolments", te)


def m_wrong_school(d):
    te = _read(d, "registrar/term_enrolments")
    te.loc[0, "school_id"] = "SART" if te.loc[0, "school_id"] != "SART" else "SBUS"
    _write(d, "registrar/term_enrolments", te)


def m_tampered_gpa(d):
    te = _read(d, "registrar/term_enrolments")
    i = te.index[te["term_gpa"].notna()][0]
    te.loc[i, "term_gpa"] = round(min(4.0, te.loc[i, "term_gpa"] + 0.3) if te.loc[i, "term_gpa"] < 3.7 else te.loc[i, "term_gpa"] - 0.3, 4)
    _write(d, "registrar/term_enrolments", te)


def m_enrolment_after_graduation(d):
    sp, te = _read(d, "registrar/student_programmes"), _read(d, "registrar/term_enrolments")
    terms = _read(d, "reference/academic_terms").set_index("term_id")
    g = sp[(sp["outcome"] == "GRADUATED") & (sp["outcome_term_id"] < "2025")].iloc[0]
    row = te[(te["student_programme_id"] == g["student_programme_id"]) & (te["term_id"] == g["outcome_term_id"])].iloc[0].copy()
    nxt = terms.index[terms["term_sequence"] == terms.loc[g["outcome_term_id"], "term_sequence"] + 1][0]
    taken = set(te.loc[te["student_id"] == g["student_id"], "term_id"])
    if nxt in taken:
        nxt = terms.index[terms["term_sequence"] == terms.loc[g["outcome_term_id"], "term_sequence"] + 2][0]
    row["term_enrolment_id"], row["term_id"], row["term_sequence"] = "SYN-TE-MUTANT", nxt, terms.loc[nxt, "term_sequence"]
    row["academic_year"] = terms.loc[nxt, "academic_year"]
    _write(d, "registrar/term_enrolments", pd.concat([te, row.to_frame().T], ignore_index=True))


def m_missing_required_field(d):
    s = _read(d, "registrar/students")
    s.loc[3, "gender"] = None
    _write(d, "registrar/students", s)


def m_uci_row_in_synthetic(d):
    s = _read(d, "registrar/students")
    s.loc[0, "data_source"] = "UCI"
    _write(d, "registrar/students", s)


def m_uci_identifier_leak(d):
    h = _read(d, "registrar/student_status_history")
    h.loc[0, "rule_reference"] = "copied from UCI-000123"
    _write(d, "registrar/student_status_history", h)


def m_future_term_completed(d):
    t = _read(d, "reference/academic_terms")
    t.loc[t["term_id"] == "2027SP", "term_status"] = "COMPLETED"
    _write(d, "reference/academic_terms", t)


def m_in_progress_term_graded(d):
    te = _read(d, "registrar/term_enrolments")
    i = te.index[te["term_id"] == "2026FA"][0]
    te.loc[i, ["grades_final", "term_gpa"]] = [True, 3.0]
    _write(d, "registrar/term_enrolments", te)


def m_retention_graduate_counted_as_retained(d):
    rm = _read(d, "registrar/retention_cohort_members")
    i = rm.index[rm["outcome_category"] == "COMPLETED_NOT_ENROLLED"][0]
    rm.loc[i, ["outcome_category", "institutionally_retained", "status_at_compare"]] = ["RETAINED_SAME_PROGRAMME", True, "ENROLLED"]
    _write(d, "registrar/retention_cohort_members", rm)


def m_retention_member_dropped(d):
    rm = _read(d, "registrar/retention_cohort_members")
    i = rm.index[(rm["comparison_type"] == "FIRST_YEAR_COHORT") & (rm["outcome_category"] == "LEFT")][0]
    _write(d, "registrar/retention_cohort_members", rm.drop(index=i))


def m_graduation_status_tampered(d):
    gr = _read(d, "registrar/graduation_records")
    i = gr.index[(gr["cohort_mature"] == True) & (gr["graduation_status"] == "LEFT_NOT_GRADUATED")][0]  # noqa: E712
    gr.loc[i, "graduation_status"] = "GRADUATED_WITHIN_WINDOW"
    _write(d, "registrar/graduation_records", gr)


def m_doctorate_window_changed(d):
    lr = _read(d, "reference/level_rules")
    lr.loc[lr["level"] == "DOCTORATE", "graduation_window_years"] = 7
    _write(d, "reference/level_rules", lr)


def m_duplicate_id(d):
    ch = _read(d, "finance/charges")
    _write(d, "finance/charges", pd.concat([ch, ch.iloc[[5]]], ignore_index=True))


def m_invalid_foreign_key(d):
    ce = _read(d, "registrar/course_enrolments")
    ce.loc[0, "course_id"] = "XXX999"
    _write(d, "registrar/course_enrolments", ce)


def m_invalid_date(d):
    p = _read(d, "finance/payments")
    p.loc[0, "payment_date"] = "2025-02-30"
    _write(d, "finance/payments", p)


def m_enrolment_before_admission(d):
    sp = _read(d, "registrar/student_programmes")
    sp.loc[0, "admission_date"] = "2026-10-01"
    _write(d, "registrar/student_programmes", sp)


def m_overlapping_programmes(d):
    sp = _read(d, "registrar/student_programmes")
    i = sp.index[sp["outcome"].isin(["CHANGED_PROGRAMME", "GRADUATED"]) & sp["student_id"].duplicated(keep=False)][0]
    sp.loc[i, ["outcome", "outcome_term_id", "outcome_date", "outcome_recorded_date"]] = ["ACTIVE", None, None, None]
    _write(d, "registrar/student_programmes", sp)


def m_invalid_transfer(d):
    sp = _read(d, "registrar/student_programmes")
    idx = sp.index[sp["entry_type"] == "PROGRAMME_CHANGE"]
    if len(idx) == 0:
        pytest.skip("no programme change in sample")
    sp.loc[idx[0], "credits_transferred_in"] = 999
    _write(d, "registrar/student_programmes", sp)


def m_balance_tampered(d):
    b = _read(d, "finance/account_balances")
    b.loc[0, "total_paid"] = b.loc[0, "total_paid"] + 50
    _write(d, "finance/account_balances", b)


def m_hold_deleted(d):
    h = _read(d, "finance/financial_holds")
    _write(d, "finance/financial_holds", h.iloc[1:])


def m_standing_tampered(d):
    s = _read(d, "registrar/academic_standing")
    i = s.index[s["standing"] == "WARNING"][0]
    s.loc[i, "standing"] = "GOOD"
    _write(d, "registrar/academic_standing", s)


def m_poor_performance_flipped(d):
    te = _read(d, "registrar/term_enrolments")
    i = te.index[te["poor_performance_flag"].notna()][0]
    te.loc[i, "poor_performance_flag"] = not bool(te.loc[i, "poor_performance_flag"])
    _write(d, "registrar/term_enrolments", te)


def m_admission_event_removed(d):
    h = _read(d, "registrar/student_status_history")
    _write(d, "registrar/student_status_history", h.drop(index=h.index[h["status_code"] == "ADMITTED"][0]))


def m_withdrawal_rule_date(d):
    sp = _read(d, "registrar/student_programmes")
    idx = sp.index[sp["withdrawal_type"] == "UNOFFICIAL"]
    if len(idx) == 0:
        pytest.skip("no unofficial withdrawal in sample")
    rec = pd.Timestamp(sp.loc[idx[0], "outcome_recorded_date"])
    sp.loc[idx[0], "outcome_recorded_date"] = str((rec - pd.DateOffset(years=1)).date())
    _write(d, "registrar/student_programmes", sp)


def m_residency_inconsistent(d):
    s = _read(d, "registrar/students")
    s.loc[0, "residency_status"] = "INTERNATIONAL" if s.loc[0, "residency_status"] == "DOMESTIC" else "DOMESTIC"
    _write(d, "registrar/students", s)


def m_unknown_nationality(d):
    s = _read(d, "registrar/students")
    s.loc[0, "nationality_iso3"] = "QQQ"
    _write(d, "registrar/students", s)


def m_summer_continuer_marked_stopped_out(d):
    rm = _read(d, "registrar/retention_cohort_members")
    idx = rm.index[rm["outcome_category"] == "CONTINUING_SKIPPED_OPTIONAL_SUMMER"]
    if len(idx) == 0:
        pytest.skip("no optional-summer continuer in sample")
    rm.loc[idx[0], "outcome_category"] = "STOPPED_OUT"
    _write(d, "registrar/retention_cohort_members", rm)


MUTATIONS = [
    (m_graduation_after_as_of, ["graduations valid", "outcome dates = end of outcome term"]),
    (m_graduation_before_minimum_duration, ["graduations valid"]),
    (m_invalid_delivery_mode, ["registrar/term_enrolments: values within allowed domains", "registrar/term_enrolments.delivery_mode ->"]),
    (m_mode_not_offered, ["delivery mode of every term enrolment is offered"]),
    (m_wrong_school, ["term_enrolments: school = school of its programme"]),
    (m_tampered_gpa, ["semester GPA and cumulative GPA recompute"]),
    (m_enrolment_after_graduation, ["no enrolment after graduation"]),
    (m_missing_required_field, ["registrar/students: required fields present"]),
    (m_uci_row_in_synthetic, ["registrar/students: data_source = SYNTHETIC", "no synthetic file mixes UCI rows"]),
    (m_uci_identifier_leak, ["no UCI identifiers inside synthetic files"]),
    (m_future_term_completed, ["term_status consistent with the as-of date"]),
    (m_in_progress_term_graded, ["grades_final = True exactly for completed terms", "in-progress term"]),
    (m_retention_graduate_counted_as_retained, ["retention outcomes recompute", "retention rates recompute"]),
    (m_retention_member_dropped, ["retention membership", "retention rates recompute"]),
    (m_graduation_status_tampered, ["graduation records recompute", "final graduation rates recompute"]),
    (m_doctorate_window_changed, ["configured windows", "graduation records recompute"]),
    (m_duplicate_id, ["finance/charges.charge_id unique"]),
    (m_invalid_foreign_key, ["registrar/course_enrolments.course_id ->"]),
    (m_invalid_date, ["finance/payments: values parse as documented types"]),
    (m_enrolment_before_admission, ["no enrolment before admission", "admission_date = start of entry term"]),
    (m_overlapping_programmes, ["admissions never overlap"]),
    (m_invalid_transfer, ["programme transfers valid"]),
    (m_balance_tampered, ["account balances = charges - payments"]),
    (m_hold_deleted, ["financial holds recompute"]),
    (m_standing_tampered, ["academic standing (good / warning / probation / dismissed) recomputes"]),
    (m_poor_performance_flipped, ["poor-performance flag"]),
    (m_admission_event_removed, ["status history recomputes"]),
    (m_withdrawal_rule_date, ["missed-term withdrawal rule"]),
    (m_residency_inconsistent, ["registrar/students: residency status consistent with nationality"]),
    (m_unknown_nationality, ["registrar/students.nationality_iso3 ->"]),
    (m_summer_continuer_marked_stopped_out, ["optional Summer", "retention outcomes recompute"]),
]


@pytest.mark.parametrize("mutate,expected", MUTATIONS, ids=[f.__name__[2:] for f, _ in MUTATIONS])
def test_validator_detects_deliberate_error(base, tmp_path, mutate, expected):
    d = tmp_path / "mutant"
    shutil.copytree(base, d)
    mutate(d)
    R, _, _ = run_validation(d)
    crashed = [c for c in R.failed if c["category"] == "Validator"]
    assert not crashed, f"validator crashed instead of reporting: {crashed}"
    for name in expected:
        statuses = R.status_of(name)
        assert statuses, f"no check named like {name!r}"
        assert "FAIL" in statuses, f"{mutate.__name__}: check {name!r} did not fail"
