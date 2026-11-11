"""Build every task-specific modelling dataset (Zone A UCI and Zone B synthetic are built and stored separately).

Usage (from data_warehouse):  python -m pipelines.feature_engineering.datasets
Outputs: data/processed/modeling/{uci,synthetic}/<dataset>.csv + <dataset>.card.json (definition, features, leakage exclusions)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..common import SYNTHETIC_DIR
from .common import MODELING_DIR, DatasetCard, data_version, read_synthetic, read_uci, save_dataset
from .student_panel import PANEL_BOOL_AS_NUM, PANEL_CATEGORICAL, PANEL_LEAKAGE, PANEL_NUMERIC, build_student_term_panel

DROPOUT_HORIZON_DAYS = 730          # unofficial withdrawals are recorded up to ~1.75 years after the last attended term
ID_COLS = ["row_key", "student_id", "student_programme_id", "term_id", "prediction_date", "label_known_date"]

# ============================================================================ Zone A: UCI
UCI_CATEGORICAL = ["marital_status_code", "application_mode_code", "uci_course_code", "previous_qualification_code",
                   "nationality_code", "mother_qualification_code", "father_qualification_code", "mother_occupation_code",
                   "father_occupation_code"]
UCI_ENROLMENT_NUMERIC = ["application_order", "previous_qualification_grade", "admission_grade", "age_at_enrollment",
                         "daytime_evening_attendance", "displaced", "educational_special_needs", "gender_code",
                         "scholarship_holder", "international", "unemployment_rate", "inflation_rate", "gdp"]
UCI_YEAR1_EXTRA = ["debtor", "tuition_fees_up_to_date"] + [f"sem{s}_{k}" for s in (1, 2) for k in
                                                          ("credited", "enrolled", "evaluations", "approved", "grade", "without_evaluations")]
UCI_LEAKAGE = {"target": "the outcome itself (Graduate / Dropout / Enrolled)",
               "uci_students.outcome_at_normal_duration": "recoded copy of the target",
               "uci_students.dq_flags": "derived from semester results (data-quality flag, not an input)"}


def build_uci() -> list[tuple[pd.DataFrame, DatasetCard]]:
    u = read_uci()
    base = u[["uci_row_number"]].copy()
    base["target_3class"] = u["target"]                        # original labels preserved exactly
    base["target_dropout"] = (u["target"] == "Dropout").astype(int)
    out = []
    for name, extra, point, notes in [
        ("uci_enrolment_time", [], "At enrolment: information known when the student enrols (application, prior education, "
         "demographics, parents, macro-economic context)",
         ["Debtor and tuition-fees-up-to-date are excluded because the UCI documentation does not state when they were measured.",
          "Scholarship holder is kept as an enrolment attribute (documented with the enrolment variables)."]),
        ("uci_end_of_year1", UCI_YEAR1_EXTRA, "End of the first study year: enrolment information plus 1st- and 2nd-semester "
         "curricular-unit results and fee status", ["Semester grades are UCI 0-20 grades, not GPA."])]:
        num = UCI_ENROLMENT_NUMERIC + extra
        df = pd.concat([base, u[num + UCI_CATEGORICAL]], axis=1)
        for c in UCI_CATEGORICAL:
            df[c] = df[c].astype(str)
        excl = dict(UCI_LEAKAGE)
        if not extra:
            excl.update({c: "not available at enrolment (measured during/after the first year)" for c in UCI_YEAR1_EXTRA})
        card = DatasetCard(
            name=name, zone="UCI", task="classification", prediction_point=point,
            target_definition="target_3class = original UCI Target (Graduate / Dropout / Enrolled at the end of the normal "
                              "course duration). target_dropout = 1 if Target == Dropout, else 0.",
            targets=["target_3class", "target_dropout"], features_numeric=num, features_categorical=UCI_CATEGORICAL,
            id_columns=["uci_row_number"], excluded_leakage_columns=excl, population="All 4,424 UCI students",
            split="Stratified 75/25 train/test (seed 20261110; one row per student) with 5-fold stratified cross-validation on the training set", notes=notes)
        out.append((df, card))
    return out


# ============================================================================ Zone B: synthetic
def _panel_features():
    return PANEL_NUMERIC + PANEL_BOOL_AS_NUM, PANEL_CATEGORICAL


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in PANEL_BOOL_AS_NUM:
        df[c] = df[c].map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0})
    return df


def build_dropout(panel: pd.DataFrame, as_of: pd.Timestamp):
    p = panel[~panel["outcome_known_at_prediction"]].copy()
    p["label_known_date"] = p["prediction_date"] + pd.Timedelta(days=DROPOUT_HORIZON_DAYS)
    p = p[p["label_known_date"] <= as_of]
    p["target_dropout_2y"] = (p["outcome"].isin(["WITHDRAWN", "DISMISSED"]) &
                              (p["outcome_recorded_date"] <= p["label_known_date"])).astype(int)
    num, cat = _panel_features()
    card = DatasetCard(
        name="syn_dropout_2y", zone="SYNTHETIC", task="classification",
        prediction_point="End date of each completed term (final grades posted). Features use records dated on or before it.",
        target_definition="target_dropout_2y = 1 if this programme admission ends in WITHDRAWN or DISMISSED and the outcome is "
                          "recorded within 730 days after the prediction date; 0 otherwise (still studying, graduated, transferred, "
                          "or withdrawal recorded later). Readmission later does not change the label.",
        targets=["target_dropout_2y"], features_numeric=num, features_categorical=cat, id_columns=ID_COLS,
        excluded_leakage_columns=PANEL_LEAKAGE,
        population="Completed term enrolments whose admission outcome is not yet recorded at the prediction date and whose "
                   "2-year label horizon ends on or before the as-of date (2026-11-10).",
        split="Student-grouped holdout: 25 % of students (StratifiedGroupKFold, seed 20261110) form the untouched test set; 5-fold "
              "StratifiedGroupKFold CV on training students. Robustness: out-of-time check (train students with label known "
              "before 2022-07-01; test students with prediction date on/after 2022-07-01).",
        notes=["Current academic standing (warning/probation) is a legitimate feature: it is known at the prediction date and "
               "rows whose dismissal is already recorded are excluded.",
               "Optional Summer: a missed Summer is never a gap; summer_terms_taken counts Summers attended."])
    return p[ID_COLS + num + cat + card.targets], card


def build_next_term(panel: pd.DataFrame):
    p = panel.sort_values(["student_programme_id", "term_sequence"]).copy()
    nxt = p.groupby("student_programme_id")[["term_gpa", "standing", "prediction_date", "term_id"]].shift(-1)
    p["target_next_term_gpa"] = nxt["term_gpa"]
    p["next_term_standing"] = nxt["standing"]
    p["label_known_date"] = nxt["prediction_date"]
    p["next_term_id"] = nxt["term_id"]
    p = p[~p["outcome_known_at_prediction"] & p["target_next_term_gpa"].notna()]
    p["target_next_term_at_risk"] = p["next_term_standing"].isin(["WARNING", "PROBATION", "DISMISSED"]).astype(int)
    num, cat = _panel_features()
    card = DatasetCard(
        name="syn_next_term_performance", zone="SYNTHETIC", task="regression",
        prediction_point="End date of a completed term; predicts the student's NEXT completed and graded term in the same admission.",
        target_definition="target_next_term_gpa = credit-weighted GPA of the next completed term (demonstration 4-point scale). "
                          "target_next_term_at_risk = 1 if the standing after that term is WARNING, PROBATION or DISMISSED under the "
                          "configured synthetic standing rule (not an official policy).",
        targets=["target_next_term_gpa", "target_next_term_at_risk"], features_numeric=num, features_categorical=cat,
        id_columns=ID_COLS + ["next_term_id"],
        excluded_leakage_columns={**PANEL_LEAKAGE, "next_term_standing": "standing after the target term (defines the risk label)",
                                  "[rule] next term grades / credits / gap length": "information from the target term itself"},
        population="Completed term enrolments followed by another graded term in the same admission; outcome not yet recorded.",
        split="Student-grouped holdout: 25 % of students (StratifiedGroupKFold, seed 20261110) form the untouched test set; 5-fold "
              "StratifiedGroupKFold CV on training students. Robustness: out-of-time check (train students with label known "
              "before 2023-07-01; test students with prediction date on/after 2023-07-01).",
        notes=["Rows whose next term had only withdrawn courses (no GPA) are excluded from this task."])
    return p[ID_COLS + ["next_term_id"] + num + cat + card.targets], card


def build_retention(panel: pd.DataFrame, t: dict):
    rm = t["retention_cohort_members"]
    rm = rm[(rm["is_final"] == True) & (rm["comparison_type"] != "FIRST_YEAR_COHORT")].copy()  # noqa: E712
    rm = rm[rm["completed_before_compare"] != True]  # noqa: E712  graduates are completions, not retention cases
    te = t["term_enrolments"]
    fall_prog = te.set_index(["student_id", "term_id"])["programme_id"]
    cont = rm["outcome_category"] == "CONTINUING_SKIPPED_OPTIONAL_SUMMER"
    nprog = [fall_prog.get((s, n)) for s, n in zip(rm["student_id"], rm["next_regular_term_id"])]
    rm["target_institutional"] = (rm["institutionally_retained"].astype(str) == "True") | cont
    rm["target_programme"] = (rm["programme_retained"].astype(str) == "True") | (cont & (pd.Series(nprog, index=rm.index) == rm["base_programme_id"]))
    terms = t["academic_terms"].set_index("term_id")
    rm["label_known_date"] = np.where(cont, rm["next_regular_term_id"].map(terms["census_date"]), pd.to_datetime(rm["compare_census_date"]))
    p = panel.merge(rm[["student_id", "base_term_id", "comparison_type", "target_institutional", "target_programme",
                        "label_known_date", "outcome_category"]],
                    left_on=["student_id", "term_id"], right_on=["student_id", "base_term_id"], how="inner")
    n_before = len(p)
    p = p[~p["outcome_known_at_prediction"]]
    for c in ("target_institutional", "target_programme"):
        p[c] = p[c].astype(int)
    p["label_known_date"] = pd.to_datetime(p["label_known_date"])
    num, cat = _panel_features()
    card = DatasetCard(
        name="syn_retention", zone="SYNTHETIC", task="classification",
        prediction_point="End date of the base term (base-term grades posted), before the comparison term's census.",
        target_definition="Uses registrar/retention_cohort_members exactly. target_institutional = enrolled in ANY programme at the "
                          "census of the same season one year later; for SUMMER_TO_SUMMER, students who skipped the optional Summer but "
                          "were enrolled at the next Fall census also count as retained (continuation). target_programme = the same, "
                          "but only in the base-term programme. One model family per comparison type (FALL_TO_FALL, SPRING_TO_SPRING, SUMMER_TO_SUMMER).",
        targets=["target_institutional", "target_programme"], features_numeric=num, features_categorical=cat,
        id_columns=ID_COLS + ["comparison_type", "base_term_id"],
        excluded_leakage_columns={**PANEL_LEAKAGE, "outcome_category": "retention outcome (population audit only)"},
        population="FINAL comparisons only (comparison census on/before 2026-11-10); graduates before the comparison excluded "
                   f"(completions); rows whose admission outcome was already recorded at the base-term end excluded ({n_before - len(p)} rows).",
        split="Per comparison type, student-grouped holdout: 25 % of students (StratifiedGroupKFold, seed 20261110) form the untouched test set; 5-fold "
              "StratifiedGroupKFold CV on training students. Robustness: out-of-time check (train students with label known "
              "before 2023-07-01; test students with prediction date on/after 2023-07-01).",
        notes=["Immature (INCOMPLETE) comparisons such as Spring 2026 -> Spring 2027 are excluded.",
               "First-year cohort students are the rows with is_first_term = 1 and are reported as a subgroup."])
    return p[ID_COLS + ["comparison_type", "base_term_id", "outcome_category"] + num + cat + card.targets], card


def build_graduation(panel: pd.DataFrame, t: dict, as_of: pd.Timestamp):
    gr = t["graduation_records"].copy()
    gr["admission_date"] = pd.to_datetime(gr["admission_date"])
    gr["landmark"] = gr["admission_date"] + pd.Timedelta(days=365)
    sp = t["student_programmes"]
    path = sp[["student_id", "level", "student_programme_id"]]
    pr = panel.merge(path, on=["student_id", "level", "student_programme_id"])
    m = gr[["graduation_record_id", "student_id", "level", "landmark"]].merge(pr, on=["student_id", "level"])
    m = m[m["prediction_date"] <= m["landmark"]].sort_values("prediction_date").groupby("graduation_record_id").tail(1)
    m = m[~m["outcome_known_at_prediction"] | (m["outcome"] == "CHANGED_PROGRAMME")]
    g = gr.set_index("graduation_record_id")
    m = m.set_index("graduation_record_id")
    m["cohort_mature"] = g["cohort_mature"].astype(str) == "True"
    m["window_end_date"] = pd.to_datetime(g["window_end_date"])
    m["graduation_status"] = g["graduation_status"]
    m["target_grad_within_window"] = (g["graduation_status"] == "GRADUATED_WITHIN_WINDOW").reindex(m.index).astype(int)
    gd = pd.to_datetime(g["graduation_date"])
    # survival: time from original admission at the level to graduation; censored at exit or at the as-of date
    lastsp = sp.assign(adm=pd.to_datetime(sp["admission_date"])).sort_values("adm").groupby(["student_id", "level"]).tail(1)
    exitd = lastsp.set_index(["student_id", "level"])
    exit_date = pd.Series([pd.to_datetime(exitd.loc[(s, lv), "outcome_date"]) if exitd.loc[(s, lv), "outcome"] in ("WITHDRAWN", "DISMISSED") else pd.NaT
                           for s, lv in zip(m["student_id"], m["level"])], index=m.index)
    end = gd.reindex(m.index).fillna(exit_date).fillna(as_of)
    m["event_graduated"] = gd.reindex(m.index).notna().astype(int)
    m["duration_years"] = (end - g["admission_date"].reindex(m.index)).dt.days / 365.25
    m["prediction_date"] = m["landmark"]
    m["label_known_date"] = end            # date the event or censoring was observed (window end is used only for the mature-cohort label)
    m.loc[m["cohort_mature"], "label_known_date"] = m.loc[m["cohort_mature"], "window_end_date"]
    m["admission_date_level"] = g["admission_date"].reindex(m.index)
    m = m.reset_index()
    num, cat = _panel_features()
    ids = ID_COLS + ["graduation_record_id", "admission_date_level"]
    common_excl = {**PANEL_LEAKAGE, "graduation_status": "the graduation outcome",
                   "graduated_programme_id / graduation_term_id / time_to_degree_years": "graduation outcome fields"}
    cls = m[m["cohort_mature"]]
    card_c = DatasetCard(
        name="syn_graduation_within_window", zone="SYNTHETIC", task="classification",
        prediction_point="Landmark one year after the original admission at the level: features from the latest completed term "
                         "on the level path ending on or before that date.",
        target_definition="target_grad_within_window = 1 if the student graduated at the level on or before admission + window "
                          "(UG 6, Master's 4, Doctorate 6 years: project-configured reporting assumptions).",
        targets=["target_grad_within_window"], features_numeric=num, features_categorical=cat, id_columns=ids,
        excluded_leakage_columns=common_excl,
        population="LEVEL_ENTRY cohort members of MATURE cohorts only, still studying (no graduation/withdrawal/dismissal recorded) "
                   "at the one-year landmark and with at least one completed term by then.",
        split="Student-grouped holdout: 25 % of students (StratifiedGroupKFold) form the untouched test set; 5-fold grouped CV on training students.",
        notes=["Immature cohorts are excluded from this classification task; they are used (censored) in the survival model."])
    card_s = DatasetCard(
        name="syn_graduation_survival", zone="SYNTHETIC", task="survival",
        prediction_point=card_c.prediction_point,
        target_definition="duration_years = years from original admission at the level to graduation (event_graduated = 1) or to "
                          "censoring: exit (withdrawal/dismissal, censored) or the as-of date 2026-11-10 (still studying, censored).",
        targets=["duration_years", "event_graduated"], features_numeric=num, features_categorical=cat, id_columns=ids,
        excluded_leakage_columns=common_excl,
        population="All LEVEL_ENTRY cohort members still studying at the one-year landmark (mature and immature cohorts).",
        split="Student-grouped holdout: 25 % of students (StratifiedGroupKFold on the event indicator) form the test set; censoring handles immature cohorts.",
        notes=["Withdrawal/dismissal is treated as censoring (cause-specific hazard of graduation)."])
    keep = ids + num + cat
    return (cls[keep + card_c.targets], card_c), (m[keep + card_s.targets + ["cohort_mature", "target_grad_within_window"]], card_s)


def build_dropout_survival(panel: pd.DataFrame, t: dict, as_of: pd.Timestamp):
    first = panel.sort_values("term_sequence").groupby("student_programme_id").head(1)
    first = first[~first["outcome_known_at_prediction"]].copy()
    rec = first["outcome_recorded_date"]
    ev = first["outcome"].isin(["WITHDRAWN", "DISMISSED"])
    other = first["outcome"].isin(["GRADUATED", "CHANGED_PROGRAMME"])
    end = pd.Series(as_of, index=first.index)
    end[ev] = rec[ev]
    end[other] = rec[other]
    first["event_dropout"] = ev.astype(int)
    first["duration_years"] = (end - first["admission_date"]).dt.days / 365.25
    first["label_known_date"] = end
    num, cat = _panel_features()
    card = DatasetCard(
        name="syn_dropout_survival", zone="SYNTHETIC", task="survival",
        prediction_point="End date of the first completed term of each programme admission.",
        target_definition="duration_years = years from admission to a recorded WITHDRAWN/DISMISSED outcome (event_dropout = 1); "
                          "censored at graduation, programme change or the as-of date.",
        targets=["duration_years", "event_dropout"], features_numeric=num, features_categorical=cat, id_columns=ID_COLS,
        excluded_leakage_columns=PANEL_LEAKAGE,
        population="All programme admissions with a completed first term and no outcome recorded by its end.",
        split="Student-grouped holdout: 25 % of students (StratifiedGroupKFold on the event indicator) form the test set; censoring handles immature cohorts.")
    return first[ID_COLS + num + cat + card.targets], card


def build_admissions(t: dict):
    a = t["applications"].copy()
    terms = t["academic_terms"].set_index("term_id")
    a = a[(a["entry_term_id"].map(terms["has_enrolment_data"]) == True) & (a["decision"] != "PENDING")]  # noqa: E712
    ap = t["applicants"].set_index("applicant_id")
    a["entry_start"] = a["entry_term_id"].map(terms["start_date"])
    a["submitted_date"] = pd.to_datetime(a["submitted_date"])
    a["entry_season"] = a["entry_term_id"].map(terms["season"])
    a["entry_academic_year_start"] = a["entry_term_id"].map(terms["academic_year"]).str[:4].astype(int)
    a["gender"] = a["applicant_id"].map(ap["gender"])
    a["residency_status"] = a["applicant_id"].map(ap["residency_status"])
    a["nationality_iso3"] = a["applicant_id"].map(ap["nationality_iso3"])
    a["age_at_entry_approx"] = a["entry_start"].dt.year - a["applicant_id"].map(ap["birth_year"])
    a["lead_days_before_term"] = (a["entry_start"] - a["submitted_date"]).dt.days
    a["prior_applications_by_applicant"] = a.sort_values("submitted_date").groupby("applicant_id").cumcount()
    # programme demand context from the PREVIOUS academic year (decisions all made before the current application cycle)
    yr = a.groupby(["programme_id", "entry_academic_year_start"]).agg(n=("application_id", "count"),
                                                                    offers=("decision", lambda s: s.isin(["ADMITTED", "ADMITTED_DECLINED"]).sum()),
                                                                    acc=("decision", lambda s: (s == "ADMITTED").sum()))
    prev = yr.rename(lambda x: x, axis=0)
    a["prog_prev_year_applications"] = [prev["n"].get((p, y - 1), np.nan) for p, y in zip(a["programme_id"], a["entry_academic_year_start"])]
    a["prog_prev_year_offer_rate"] = [(prev["offers"].get((p, y - 1), np.nan) / prev["n"].get((p, y - 1), np.nan))
                                      for p, y in zip(a["programme_id"], a["entry_academic_year_start"])]
    a["prog_prev_year_yield"] = [(prev["acc"].get((p, y - 1), np.nan) / prev["offers"].get((p, y - 1), np.nan)) if prev["offers"].get((p, y - 1), 0) else np.nan
                                 for p, y in zip(a["programme_id"], a["entry_academic_year_start"])]
    a["target_offer"] = a["decision"].isin(["ADMITTED", "ADMITTED_DECLINED"]).astype(int)
    a["target_accept"] = (a["decision"] == "ADMITTED").astype(int)
    a["prediction_date"] = a["submitted_date"]
    a["label_known_date"] = pd.to_datetime(a["decision_date"])
    num = ["admission_score", "age_at_entry_approx", "lead_days_before_term", "prior_applications_by_applicant",
           "entry_academic_year_start", "prog_prev_year_applications", "prog_prev_year_offer_rate", "prog_prev_year_yield"]
    cat = ["programme_id", "school_id", "level", "entry_season", "application_type", "gender", "residency_status", "nationality_iso3"]
    ids = ["application_id", "applicant_id", "entry_term_id", "prediction_date", "label_known_date"]
    excl = {"decision": "the admissions decision (defines both targets)", "decision_date": "date of the decision (after the prediction point)",
            "enrolled": "enrolment after the decision (outcome)", "student_id": "exists only for applicants who enrolled (reveals the outcome)"}
    base = dict(zone="SYNTHETIC", task="classification", features_numeric=num, features_categorical=cat, id_columns=ids,
                excluded_leakage_columns=excl, split="Chronological by entry term: test = entry terms of academic year 2025/26 "
                                                      "onwards (2025FA, 2026SP, 2026SU, 2026FA); train = earlier entry terms; test-period applicants removed from training.")
    c1 = DatasetCard(name="syn_admissions_offer", prediction_point="Application submission date.",
                     target_definition="target_offer = 1 if the application received an offer (decision ADMITTED or ADMITTED_DECLINED).",
                     targets=["target_offer"], population="Decided applications for entry terms 2016FA-2026FA (PENDING and 2027SP excluded).",
                     notes=["Unique applicants per entry term = applications per entry term (no applicant applied twice for the same term)."], **base)
    off = a[a["target_offer"] == 1]
    c2 = DatasetCard(name="syn_admissions_accept", prediction_point="Offer decision date (features are those known at application).",
                     target_definition="target_accept = 1 if the offer was accepted (decision ADMITTED); 0 if declined (ADMITTED_DECLINED).",
                     targets=["target_accept"], population="Applications that received an offer, entry terms 2016FA-2026FA.",
                     notes=["Acceptance -> enrolment conversion is 100 % in every historical term of the synthetic data (every accepted "
                            "offer enrolled), so no acceptance-to-enrolment model is trained (no variation to learn)."], **base)
    return (a[ids + num + cat + ["target_offer"]], c1), (off[ids + num + cat + ["target_accept"]].copy(), c2)


# ============================================================================ time series
def build_time_series(t: dict) -> dict[str, pd.DataFrame]:
    terms = t["academic_terms"].set_index("term_id")
    te = t["term_enrolments"].merge(t["students"][["student_id", "gender", "nationality_iso3"]], on="student_id")
    hist = terms[terms["has_enrolment_data"] == True].sort_values("term_sequence")  # noqa: E712
    rows = []
    dims = {"TOTAL": None, "level": "level", "school_id": "school_id", "programme_id": "programme_id",
            "nationality_iso3": "nationality_iso3", "gender": "gender", "delivery_mode": "delivery_mode", "study_load": "study_load"}
    for dim, col in dims.items():
        g = te.groupby(["term_id"] + ([col] if col else [])).size()
        keys = ["ALL"] if col is None else sorted(te[col].unique())
        for k in keys:
            for tid, tr in hist.iterrows():
                v = g.get(tid if col is None else (tid, k), 0)
                rows.append({"dimension": dim, "series_key": k, "term_id": tid, "term_sequence": tr["term_sequence"],
                             "season": tr["season"], "academic_year": tr["academic_year"], "reporting_status": tr["reporting_status"],
                             "value": int(v)})
    enrol = pd.DataFrame(rows)
    ay = te.groupby("academic_year")["student_id"].nunique().rename("unduplicated_headcount").reset_index()
    ay["year_status"] = ay["academic_year"].map(t["academic_terms"].groupby("academic_year")["end_date"].max()
                                                .map(lambda d: "COMPLETE" if d <= pd.Timestamp(t["manifest"]["as_of_date"]) else "IN_PROGRESS"))
    a = t["applications"]
    a = a[a["entry_term_id"].map(terms["has_enrolment_data"]) == True]  # noqa: E712
    sp = t["student_programmes"]
    new = sp[sp["entry_type"] != "PROGRAMME_CHANGE"].groupby(["programme_id", "entry_term_id"]).size()
    adm_rows = []
    for prog in ["ALL"] + sorted(a["programme_id"].unique()):
        aa = a if prog == "ALL" else a[a["programme_id"] == prog]
        for tid, tr in hist.iterrows():
            x = aa[aa["entry_term_id"] == tid]
            n_new = int(new[new.index.get_level_values(1) == tid].sum()) if prog == "ALL" else int(new.get((prog, tid), 0))
            adm_rows.append({"programme_id": prog, "term_id": tid, "term_sequence": tr["term_sequence"], "season": tr["season"],
                             "academic_year": tr["academic_year"], "applications": len(x), "unique_applicants": x["applicant_id"].nunique(),
                             "offers": int(x["decision"].isin(["ADMITTED", "ADMITTED_DECLINED"]).sum()),
                             "acceptances": int((x["decision"] == "ADMITTED").sum()), "new_enrolments": n_new})
    adm = pd.DataFrame(adm_rows)
    adm["application_to_offer"] = adm["offers"] / adm["applications"].replace(0, np.nan)
    adm["offer_to_acceptance"] = adm["acceptances"] / adm["offers"].replace(0, np.nan)
    adm["acceptance_to_enrolment"] = adm["new_enrolments"] / adm["acceptances"].replace(0, np.nan)
    ce = t["course_enrolments"].merge(t["term_enrolments"][["term_enrolment_id", "programme_id"]], on="term_enrolment_id")
    cd = ce.groupby(["programme_id", "term_id"]).size().rename("course_registrations").reset_index()
    hc = t["term_enrolments"].groupby(["programme_id", "term_id"]).size().rename("headcount").reset_index()
    cd = cd.merge(hc, on=["programme_id", "term_id"])
    cd["registrations_per_student"] = cd["course_registrations"] / cd["headcount"]
    cd["term_sequence"] = cd["term_id"].map(terms["term_sequence"])
    return {"ts_enrolment_by_term": enrol, "ts_enrolment_by_academic_year": ay, "ts_admissions_by_term": adm,
            "ts_course_demand_by_programme": cd.sort_values(["programme_id", "term_sequence"])}


def build_segmentation_snapshot(panel: pd.DataFrame, t: dict):
    now = set(t["term_enrolments"].loc[t["term_enrolments"]["term_id"] == "2026FA", "student_id"])
    p = panel[panel["student_id"].isin(now)].sort_values("term_sequence").groupby("student_id").tail(1)
    feats = ["cumulative_gpa", "term_gpa", "progression_rate", "credits_earned_per_year", "cum_course_completion_rate",
             "warning_terms_so_far", "probation_terms_so_far", "interruptions_so_far", "summer_terms_taken", "online_share_so_far",
             "part_time_share_so_far", "fin_payment_completion_pct", "fin_outstanding_ratio", "fin_late_payment_terms", "fin_holds_so_far",
             "years_since_admission"]
    return p[["student_id", "student_programme_id", "term_id", "level", "school_id", "programme_id"] + feats], feats


# ============================================================================ main
def build_all(syn_dir: Path = SYNTHETIC_DIR, out_dir: Path = MODELING_DIR, verbose: bool = True) -> dict:
    t0 = time.time()
    summary = {"data_version": data_version(syn_dir), "datasets": {}}

    def keep(df, card):
        save_dataset(df, card, out_dir)
        summary["datasets"][card.name] = {"zone": card.zone, "rows": len(df), "features": len(card.features), "targets": card.targets}
        if verbose:
            print(f"  {card.zone:9s} {card.name:32s} rows={len(df):6d} features={len(card.features)}")

    for df, card in build_uci():
        keep(df, card)
    t = read_synthetic(syn_dir)
    as_of = pd.Timestamp(t["manifest"]["as_of_date"])
    panel = _prep(build_student_term_panel(t))
    (out_dir / "synthetic").mkdir(parents=True, exist_ok=True)
    panel.to_csv(out_dir / "synthetic" / "syn_student_term_panel.csv", index=False, lineterminator="\n", float_format="%.6f")
    summary["datasets"]["syn_student_term_panel"] = {"zone": "SYNTHETIC", "rows": len(panel), "features": len(PANEL_NUMERIC + PANEL_BOOL_AS_NUM + PANEL_CATEGORICAL)}
    keep(*build_dropout(panel, as_of))
    keep(*build_next_term(panel))
    keep(*build_retention(panel, t))
    c, s = build_graduation(panel, t, as_of)
    keep(*c)
    keep(*s)
    keep(*build_dropout_survival(panel, t, as_of))
    o, a = build_admissions(t)
    keep(*o)
    keep(*a)
    for name, df in build_time_series(t).items():
        df.to_csv(out_dir / "synthetic" / f"{name}.csv", index=False, lineterminator="\n", float_format="%.6f")
        summary["datasets"][name] = {"zone": "SYNTHETIC", "rows": len(df), "features": None}
    seg, feats = build_segmentation_snapshot(panel, t)
    seg.to_csv(out_dir / "synthetic" / "syn_segmentation_snapshot.csv", index=False, lineterminator="\n", float_format="%.6f")
    summary["datasets"]["syn_segmentation_snapshot"] = {"zone": "SYNTHETIC", "rows": len(seg), "features": len(feats)}
    summary["segmentation_features"] = feats
    summary["seconds"] = round(time.time() - t0, 1)
    (out_dir / "modeling_manifest.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


if __name__ == "__main__":
    s = build_all()
    print(f"done in {s['seconds']} s")
