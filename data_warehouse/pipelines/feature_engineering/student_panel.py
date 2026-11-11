"""Student-term feature panel (Zone B, synthetic).

One row per COMPLETED term enrolment (grades final). The prediction point of a row is the END DATE of that term:
every feature uses only records dated on or before it. In-progress (Fall 2026) and future terms never enter the panel.
`feature_max_source_date` records the latest source date used for each row so the leakage checker can verify it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STANDING_ORDER = {"NOT_EVALUATED": 0, "GOOD": 0, "WARNING": 1, "PROBATION": 2, "DISMISSED": 3}


def _streak(flags: pd.Series) -> pd.Series:
    """Length of the current run of True values (resets on False)."""
    out, run = [], 0
    for f in flags:
        run = run + 1 if f else 0
        out.append(run)
    return pd.Series(out, index=flags.index)


def _asof_sum(rows: pd.DataFrame, events: pd.DataFrame, date_col: str, value_col: str, name: str,
              strictly_before: bool = False) -> pd.Series:
    """Per row: sum of `value_col` over the student's events dated <= row date (or < when strictly_before)."""
    ev = events[["student_id", date_col, value_col]].dropna(subset=[date_col]).sort_values(date_col)
    ev = ev.groupby(["student_id", date_col], as_index=False)[value_col].sum()
    ev["cum"] = ev.groupby("student_id")[value_col].cumsum()
    ev = ev.sort_values(date_col, kind="stable")
    left = rows[["row_key", "student_id", "prediction_date"]].sort_values("prediction_date")
    m = pd.merge_asof(left, ev[["student_id", date_col, "cum"]].rename(columns={date_col: "prediction_date"}),
                      on="prediction_date", by="student_id", direction="backward", allow_exact_matches=not strictly_before)
    return m.set_index("row_key")["cum"].fillna(0.0).rename(name)


def build_student_term_panel(t: dict) -> pd.DataFrame:
    terms = t["academic_terms"].set_index("term_id")
    progs = t["programmes"].set_index("programme_id")
    te = t["term_enrolments"].copy()
    ce = t["course_enrolments"]
    sp = t["student_programmes"].copy()
    sp["admission_date"] = pd.to_datetime(sp["admission_date"])
    sp["outcome_recorded_date"] = pd.to_datetime(sp["outcome_recorded_date"])

    # ---------------------------------------------------------------- course-level counts per term enrolment
    ce = ce.assign(final=ce["grade_status"] == "FINAL", wd=ce["grade_letter"] == "W")
    ce = ce.assign(passed=ce["final"] & (ce["credits_earned"].fillna(0) > 0), failed=ce["final"] & (ce["credits_earned"].fillna(0) == 0))
    cc = ce.groupby("term_enrolment_id").agg(courses_registered=("course_enrolment_id", "count"), courses_graded=("final", "sum"),
                                             courses_passed=("passed", "sum"), courses_failed=("failed", "sum"),
                                             courses_withdrawn=("wd", "sum"))
    avg_pts = ce[ce["final"]].groupby("term_enrolment_id")["grade_points"].mean().rename("term_mean_grade_points")
    te = te.join(cc, on="term_enrolment_id").join(avg_pts, on="term_enrolment_id")
    for c in ("courses_registered", "courses_graded", "courses_passed", "courses_failed", "courses_withdrawn"):
        te[c] = te[c].fillna(0).astype(int)

    std = t["academic_standing"].set_index("term_enrolment_id")["standing"]
    te["standing"] = te["term_enrolment_id"].map(std)
    te["season"] = te["term_id"].map(terms["season"])
    te["term_end"] = te["term_id"].map(terms["end_date"])
    te = te[te["grades_final"] == True].sort_values(["student_programme_id", "term_sequence"]).copy()  # noqa: E712

    # ---------------------------------------------------------------- cumulative academic history within the admission
    g = te.groupby("student_programme_id", sort=False)
    te["completed_terms"] = g.cumcount() + 1
    for c in ("courses_registered", "courses_passed", "courses_failed", "courses_withdrawn", "credits_attempted"):
        te[f"cum_{c}"] = g[c].cumsum()
    te["cum_course_completion_rate"] = te["cum_courses_passed"] / te["cum_courses_registered"].replace(0, np.nan)
    te["term_course_completion_rate"] = te["courses_passed"] / te["courses_registered"].replace(0, np.nan)
    te["credit_completion_rate_cum"] = (te["cumulative_credits_earned"] - te["student_programme_id"].map(
        sp.set_index("student_programme_id")["credits_transferred_in"])) / te["cum_credits_attempted"].replace(0, np.nan)
    te["warning_terms_so_far"] = g["standing"].transform(lambda s: (s == "WARNING").cumsum())
    te["probation_terms_so_far"] = g["standing"].transform(lambda s: (s == "PROBATION").cumsum())
    te["poor_performance_terms_so_far"] = g["poor_performance_flag"].transform(lambda s: (s == True).cumsum())  # noqa: E712
    te["standing_level"] = te["standing"].map(STANDING_ORDER).fillna(0)
    te["max_standing_level_so_far"] = g["standing_level"].cummax()
    graded = te["term_gpa"].notna()
    te["prev_term_gpa"] = te["term_gpa"].where(graded).groupby(te["student_programme_id"]).transform(lambda s: s.ffill().shift(1))
    te["gpa_change_vs_prev"] = te["term_gpa"] - te["prev_term_gpa"]
    decl = (te["gpa_change_vs_prev"] < 0)
    te["consecutive_gpa_declines"] = decl.groupby(te["student_programme_id"]).transform(_streak)
    te["prev_cumulative_gpa"] = g["cumulative_gpa"].shift(1)
    te["summer_terms_taken"] = g["season"].transform(lambda s: (s == "SUMMER").cumsum())
    te["interruptions_so_far"] = g["prior_gap_terms"].transform(lambda s: (s > 0).cumsum())
    te["missed_regular_terms_so_far"] = g["prior_gap_terms"].cumsum()
    te["online_share_so_far"] = g["delivery_mode"].transform(lambda s: (s == "ONLINE").cumsum()) / te["completed_terms"]
    te["part_time_share_so_far"] = g["study_load"].transform(lambda s: (s == "PART_TIME").cumsum()) / te["completed_terms"]
    # consecutive regular terms enrolled (Summer is optional: it neither breaks nor extends the streak)
    reg = te["season"] != "SUMMER"
    r = te[reg]
    seg = (r["prior_gap_terms"] > 0).groupby(r["student_programme_id"]).cumsum()
    te["regular_streak"] = np.nan
    te.loc[reg, "regular_streak"] = r.groupby([r["student_programme_id"], seg]).cumcount() + 1
    te["regular_streak"] = te.groupby("student_programme_id")["regular_streak"].ffill().fillna(0)

    # ---------------------------------------------------------------- admission & demographic features
    spi = sp.set_index("student_programme_id")
    stu = t["students"].set_index("student_id")
    apps = t["applications"].set_index("application_id")
    te["admission_date"] = te["student_programme_id"].map(spi["admission_date"])
    te["entry_term_id"] = te["student_programme_id"].map(spi["entry_term_id"])
    te["entry_season"] = te["entry_term_id"].map(terms["season"])
    te["entry_academic_year_start"] = te["entry_term_id"].map(terms["academic_year"]).str[:4].astype(int)
    te["entry_type"] = te["student_programme_id"].map(spi["entry_type"])
    te["credits_transferred_in"] = te["student_programme_id"].map(spi["credits_transferred_in"])
    te["scholarship_pct"] = te["student_programme_id"].map(spi["scholarship_pct"])
    app_id = te["student_programme_id"].map(spi["application_id"])
    te["application_type"] = app_id.map(apps["application_type"]).fillna("INTERNAL_PROGRAMME_CHANGE")
    te["admission_score"] = app_id.map(apps["admission_score"])
    te["application_lead_days"] = (te["admission_date"] - pd.to_datetime(app_id.map(apps["submitted_date"]))).dt.days
    te["decision_to_start_days"] = (te["admission_date"] - pd.to_datetime(app_id.map(apps["decision_date"]))).dt.days
    te["gender"] = te["student_id"].map(stu["gender"])
    te["residency_status"] = te["student_id"].map(stu["residency_status"])
    te["nationality_iso3"] = te["student_id"].map(stu["nationality_iso3"])
    te["age_at_admission_approx"] = te["admission_date"].dt.year - te["student_id"].map(stu["birth_year"])
    sps = sp.sort_values(["student_id", "admission_date"])
    te["prior_admissions"] = te["student_programme_id"].map(pd.Series(sps.groupby("student_id").cumcount().values,
                                                                       index=sps["student_programme_id"].values))
    te["credits_required"] = te["programme_id"].map(progs["credits_required"])
    te["progression_rate"] = te["cumulative_credits_earned"] / te["credits_required"]
    te["years_since_admission"] = (te["term_end"] - te["admission_date"]).dt.days / 365.25
    te["credits_earned_per_year"] = te["cumulative_credits_earned"] / te["years_since_admission"].clip(lower=0.25)
    te["term_season"] = te["season"]
    te["is_first_term"] = te["study_term_number"] == 1

    # ---------------------------------------------------------------- rows, keys, outcome knowledge at prediction point
    te["prediction_date"] = te["term_end"]
    te["row_key"] = te["term_enrolment_id"]
    te["outcome"] = te["student_programme_id"].map(spi["outcome"])
    te["outcome_term_id"] = te["student_programme_id"].map(spi["outcome_term_id"])
    te["outcome_recorded_date"] = te["student_programme_id"].map(spi["outcome_recorded_date"])
    te["outcome_known_at_prediction"] = te["outcome_recorded_date"].notna() & (te["outcome_recorded_date"] <= te["prediction_date"])

    # ---------------------------------------------------------------- financial features as of prediction date
    ch = t["charges"].assign(charge_date=lambda d: pd.to_datetime(d["charge_date"]), due_date=lambda d: pd.to_datetime(d["due_date"]))
    pay = t["payments"].assign(payment_date=lambda d: pd.to_datetime(d["payment_date"]))
    rows = te[["row_key", "student_id", "prediction_date"]]
    fin = pd.concat([
        _asof_sum(rows, ch, "charge_date", "amount", "fin_total_charged"),
        _asof_sum(rows, pay, "payment_date", "amount", "fin_total_paid"),
        _asof_sum(rows, ch, "due_date", "amount", "fin_charges_due", strictly_before=True),
    ], axis=1)
    # late or partial scheduled payment per term (known on the term's due date)
    net = ch.groupby(["student_id", "term_id"]).agg(net=("amount", "sum"), due=("due_date", "max")).reset_index()
    sched = pay[pay["payment_type"] == "SCHEDULED"].merge(net[["student_id", "term_id", "due"]], on=["student_id", "term_id"])
    on_time = sched[sched["payment_date"] <= sched["due"]].groupby(["student_id", "term_id"])["amount"].sum()
    net["paid_by_due"] = net.set_index(["student_id", "term_id"]).index.map(on_time).fillna(0)
    net["late"] = ((net["net"] - net["paid_by_due"]) > 0.5).astype(float)
    fin = fin.join(_asof_sum(rows, net, "due", "late", "fin_late_payment_terms", strictly_before=True))
    holds = t["financial_holds"].assign(placed=lambda d: pd.to_datetime(d["placed_date"]), rel=lambda d: pd.to_datetime(d["released_date"]))
    fin = fin.join(_asof_sum(rows, holds.assign(one=1.0), "placed", "one", "fin_holds_so_far"))
    hm = rows.merge(holds[["student_id", "placed", "rel"]], on="student_id")
    act = hm[(hm["placed"] <= hm["prediction_date"]) & (hm["rel"].isna() | (hm["rel"] > hm["prediction_date"]))]
    fin["fin_active_hold"] = fin.index.isin(set(act["row_key"]))
    blocks = t["registration_blocks"].assign(d=lambda x: pd.to_datetime(x["registration_date"]), one=1.0)
    fin = fin.join(_asof_sum(rows, blocks, "d", "one", "fin_registration_blocks_so_far"))
    fin["fin_outstanding_balance"] = fin["fin_total_charged"] - fin["fin_total_paid"]
    fin["fin_past_due_amount"] = (fin["fin_charges_due"] - fin["fin_total_paid"]).clip(lower=0)
    fin["fin_payment_completion_pct"] = (fin["fin_total_paid"] / fin["fin_total_charged"].where(fin["fin_total_charged"] > 0)).clip(upper=1.5)
    fin["fin_outstanding_ratio"] = fin["fin_outstanding_balance"] / fin["fin_total_charged"].where(fin["fin_total_charged"] > 0)
    te = te.join(fin.drop(columns=["fin_charges_due"]), on="row_key")

    # ---------------------------------------------------------------- programme / institutional context at the term
    allte = t["term_enrolments"]
    head = allte.groupby(["programme_id", "term_id"]).size()
    inst = allte.groupby("term_id").size()
    intake = sp.groupby(["programme_id", "entry_term_id"]).size()
    prev_same = {k: terms.index[(terms["season"] == terms.loc[k, "season"]) & (terms["calendar_year"] == terms.loc[k, "calendar_year"] - 1)]
                 for k in terms.index}
    prev_same = {k: (v[0] if len(v) else None) for k, v in prev_same.items()}
    te["prog_headcount"] = [head.get((p, k), 0) for p, k in zip(te["programme_id"], te["term_id"])]
    te["prog_headcount_prev_year"] = [head.get((p, prev_same[k]), np.nan) if prev_same[k] else np.nan for p, k in zip(te["programme_id"], te["term_id"])]
    te["prog_headcount_growth_yoy"] = te["prog_headcount"] / te["prog_headcount_prev_year"] - 1
    te["prog_new_intake"] = [intake.get((p, k), 0) for p, k in zip(te["programme_id"], te["term_id"])]
    te["inst_headcount"] = te["term_id"].map(inst)
    te["inst_headcount_growth_yoy"] = te["inst_headcount"] / te["term_id"].map(lambda k: inst.get(prev_same[k], np.nan) if prev_same[k] else np.nan) - 1
    te["inst_returning_students"] = te["inst_headcount"] - te["term_id"].map(sp.groupby("entry_term_id").size()).fillna(0)

    a = t["applications"].assign(sub=lambda d: pd.to_datetime(d["submitted_date"]), dec=lambda d: pd.to_datetime(d["decision_date"]))
    a["offer"] = a["decision"].isin(["ADMITTED", "ADMITTED_DECLINED"])
    a["accept"] = a["decision"] == "ADMITTED"
    rm = t["retention_cohort_members"]
    rm = rm[(rm["comparison_type"].isin(["FALL_TO_FALL", "SPRING_TO_SPRING"])) & (rm["is_final"] == True)].copy()  # noqa: E712
    rm["compare_census_date"] = pd.to_datetime(rm["compare_census_date"])
    gr = t["graduation_records"].assign(wend=lambda d: pd.to_datetime(d["window_end_date"]))
    ctx = {}
    for p, d in te[["programme_id", "prediction_date"]].drop_duplicates().itertuples(index=False):
        ap = a[(a["programme_id"] == p) & (a["sub"] > d - pd.Timedelta(days=365)) & (a["sub"] <= d)]
        de = a[(a["programme_id"] == p) & (a["dec"] > d - pd.Timedelta(days=365)) & (a["dec"] <= d)]
        r = rm[(rm["base_programme_id"] == p) & (rm["compare_census_date"] <= d) & (rm["compare_census_date"] > d - pd.Timedelta(days=730))]
        r = r[r["completed_before_compare"] != True]  # noqa: E712
        gg = gr[(gr["programme_at_entry"] == p) & (gr["wend"] <= d)]
        ctx[(p, d)] = (len(ap), int(de["offer"].sum()), int(de["accept"].sum()),
                       r["institutionally_retained"].astype(bool).mean() if len(r) else np.nan,
                       (gg["graduation_status"] == "GRADUATED_WITHIN_WINDOW").mean() if len(gg) else np.nan,
                       int(de["accept"].sum()) / len(de) if len(de) else np.nan,
                       max([r["compare_census_date"].max() if len(r) else pd.NaT, gg["wend"].max() if len(gg) else pd.NaT,
                            ap["sub"].max() if len(ap) else pd.NaT, de["dec"].max() if len(de) else pd.NaT], key=lambda x: x if pd.notna(x) else pd.Timestamp.min))
    keys = list(zip(te["programme_id"], te["prediction_date"]))
    for i, name in enumerate(["prog_applications_12m", "prog_offers_12m", "prog_acceptances_12m", "prog_hist_retention_rate_2y",
                              "prog_hist_grad_rate_mature", "prog_decision_acceptance_rate_12m", "_ctx_max_date"]):
        te[name] = [ctx[k][i] for k in keys]

    # ---------------------------------------------------------------- latest source date used (for the leakage checker)
    lp = pd.merge_asof(te[["row_key", "student_id", "prediction_date"]].sort_values("prediction_date"),
                       pay[["student_id", "payment_date"]].sort_values("payment_date").rename(columns={"payment_date": "prediction_date"})
                       .assign(last_payment=lambda d: d["prediction_date"]),
                       on="prediction_date", by="student_id", direction="backward").set_index("row_key")["last_payment"]
    te["feature_max_source_date"] = pd.concat([te["term_end"], te["_ctx_max_date"].replace(pd.Timestamp.min, pd.NaT),
                                               te["row_key"].map(lp)], axis=1).max(axis=1)
    te = te.drop(columns=["_ctx_max_date", "term_end", "standing_level"])
    return te.reset_index(drop=True)


PANEL_NUMERIC = [
    "term_sequence", "study_term_number", "completed_terms", "credits_attempted", "credits_earned", "term_gpa", "cumulative_gpa",
    "cumulative_credits_earned", "passed_credit_ratio", "term_mean_grade_points", "courses_registered", "courses_passed",
    "courses_failed", "courses_withdrawn", "cum_courses_registered", "cum_courses_passed", "cum_courses_failed",
    "cum_courses_withdrawn", "cum_credits_attempted", "cum_course_completion_rate", "term_course_completion_rate",
    "credit_completion_rate_cum", "warning_terms_so_far", "probation_terms_so_far", "poor_performance_terms_so_far",
    "max_standing_level_so_far", "prev_term_gpa", "gpa_change_vs_prev", "consecutive_gpa_declines", "prev_cumulative_gpa",
    "summer_terms_taken", "interruptions_so_far", "missed_regular_terms_so_far", "prior_gap_terms", "online_share_so_far",
    "part_time_share_so_far", "regular_streak", "entry_academic_year_start", "credits_transferred_in", "scholarship_pct",
    "admission_score", "application_lead_days", "decision_to_start_days", "age_at_admission_approx", "prior_admissions",
    "progression_rate", "years_since_admission", "credits_earned_per_year",
    "fin_total_charged", "fin_total_paid", "fin_outstanding_balance", "fin_past_due_amount", "fin_payment_completion_pct",
    "fin_outstanding_ratio", "fin_late_payment_terms", "fin_holds_so_far", "fin_registration_blocks_so_far",
    "prog_headcount", "prog_headcount_growth_yoy", "prog_new_intake", "inst_headcount", "inst_headcount_growth_yoy",
    "inst_returning_students", "prog_applications_12m", "prog_offers_12m", "prog_acceptances_12m",
    "prog_hist_retention_rate_2y", "prog_hist_grad_rate_mature", "prog_decision_acceptance_rate_12m"]
PANEL_BOOL_AS_NUM = ["poor_performance_flag", "withdrew_during_term", "fin_active_hold", "is_first_term"]
PANEL_CATEGORICAL = ["programme_id", "school_id", "level", "term_season", "entry_season", "entry_type", "application_type",
                     "delivery_mode", "study_load", "gender", "residency_status", "nationality_iso3", "standing"]

# Columns that reveal outcomes after the prediction point: never used as features in any synthetic task.
PANEL_LEAKAGE = {
    "outcome": "final outcome of the admission (determined after the prediction point)",
    "outcome_term_id": "term of the final outcome", "outcome_recorded_date": "date the outcome was recorded",
    "outcome_known_at_prediction": "population filter only (rows with an already-known outcome are excluded)",
    "withdrawal_type": "type of the final withdrawal", "exit_reason": "reason for the final exit",
    "graduation_status / graduation_date / graduated_within_window": "graduation outcome fields (registrar/graduation_records)",
    "institutionally_retained / programme_retained / outcome_category / status_at_compare / completed_before_compare / continued_next_regular_term":
        "retention outcome fields (registrar/retention_cohort_members)",
    "[rule] student_status_history events after the prediction date": "future status events",
    "[rule] term enrolments, grades, standing, charges, payments and holds dated after the prediction date": "future records",
}
