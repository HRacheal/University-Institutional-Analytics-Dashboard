"""Automated leakage checks, run before any model is trained. A failed check stops training of that task.

Checks
  L1 target_not_in_features        no target column is a feature
  L2 excluded_not_in_features      no column listed as a leakage exclusion is a feature (names matched exactly and as tokens)
  L3 forbidden_name_patterns       no feature name contains an outcome word (outcome, graduat*, retained, withdraw* (except
                                   withdrew_during_term / courses_withdrawn), dismiss*, exit_reason, decision, enrolled flag)
  L4 zone_purity                   a dataset contains only one data zone (no UCI column in synthetic data and vice versa)
  L5 feature_dates_before_point    for panel datasets: feature_max_source_date <= prediction_date for every row
  L6 no_unreportable_terms         no row is based on an in-progress or future term (2026FA grades, 2027SP, 2027SU)
  L7 group_disjoint                no student (or applicant) appears in both training and test sets
  L8 label_before_test             (out-of-time splits) every training label was known before the first test prediction date
  L9 single_feature_screen         no single feature alone predicts the target almost perfectly (AUC > 0.97 or |r| > 0.97);
                                   a hit is investigated and reported, not silently ignored
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

FORBIDDEN = re.compile(r"(^|_)(outcome|graduat\w*|retained|retention_outcome|withdrawal_type|dismiss\w*|exit_reason|decision$|"
                       r"enrolled$|status_at_compare|completed_before_compare|continued_next)", re.I)
# Reviewed exceptions (name matches a pattern but the value is known at the prediction point and is not the outcome):
#   withdrew_during_term / courses_withdrawn: course withdrawals in a COMPLETED term, not the final programme withdrawal
#   prog_hist_*: programme history from cohorts whose outcome was already observed before the prediction date
#   decision_to_start_days: admission-decision lead time
#   sem1_enrolled / sem2_enrolled (UCI): number of curricular units the student enrolled in, not an enrolment-status outcome
ALLOWED_DESPITE_PATTERN = {"withdrew_during_term", "courses_withdrawn", "cum_courses_withdrawn", "prog_hist_grad_rate_mature",
                           "prog_hist_retention_rate_2y", "decision_to_start_days", "sem1_enrolled", "sem2_enrolled"}
UCI_ONLY = {"uci_row_number", "sem1_grade", "admission_grade", "uci_course_code"}
SYN_ONLY = {"student_programme_id", "term_gpa", "cumulative_gpa", "programme_id"}
UNREPORTABLE_TERMS = {"2026FA", "2027SP", "2027SU"}


def _features(card: dict) -> list[str]:
    return card["features_numeric"] + card["features_categorical"]


def static_checks(df: pd.DataFrame, card: dict) -> list[dict]:
    feats = set(_features(card))
    res = []

    def add(cid, ok, detail):
        res.append({"check": cid, "passed": bool(ok), "detail": detail})

    hit = feats & set(card["targets"])
    add("L1 target_not_in_features", not hit, f"targets {card['targets']}; overlap {sorted(hit)}")
    excl_tokens = set()
    for k in card["excluded_leakage_columns"]:
        if k.startswith("[rule]"):        # descriptive rule (enforced by L5/L6), not a column name
            continue
        excl_tokens |= {x.strip().split(".")[-1] for x in re.split(r"[/,]", k)}
    hit = feats & excl_tokens
    add("L2 excluded_not_in_features", not hit, f"{len(card['excluded_leakage_columns'])} exclusions; overlap {sorted(hit)}")
    hit = sorted(f for f in feats if FORBIDDEN.search(f) and f not in ALLOWED_DESPITE_PATTERN)
    add("L3 forbidden_name_patterns", not hit, f"suspicious feature names {hit}")
    cols = set(df.columns)
    wrong = cols & (SYN_ONLY if card["zone"] == "UCI" else UCI_ONLY)
    add("L4 zone_purity", not wrong, f"zone {card['zone']}; foreign columns {sorted(wrong)}")
    if "feature_max_source_date" in df:
        bad = int((pd.to_datetime(df["feature_max_source_date"]) > pd.to_datetime(df["prediction_date"])).sum())
        add("L5 feature_dates_before_point", bad == 0, f"{bad} rows with a source date after the prediction date")
    elif "prediction_date" in df and card["zone"] == "SYNTHETIC":
        add("L5 feature_dates_before_point", True, "row-level source dates not tracked; features are application-time attributes "
                                                     "and previous-academic-year aggregates by construction")
    if "term_id" in df:
        bad = int(df["term_id"].isin(UNREPORTABLE_TERMS).sum())
        add("L6 no_unreportable_terms", bad == 0, f"{bad} rows based on in-progress/future terms")
    if "label_known_date" in df and card["zone"] == "SYNTHETIC":
        bad = int((pd.to_datetime(df["label_known_date"]) > pd.Timestamp("2026-11-10")).sum())
        add("L6b labels_known_by_as_of", bad == 0, f"{bad} rows whose label is not yet observable at 2026-11-10")
    return res


def split_checks(train: pd.DataFrame, test: pd.DataFrame, group_col: str | None, out_of_time: bool = False) -> list[dict]:
    res = []
    if group_col:
        ov = set(train[group_col]) & set(test[group_col])
        res.append({"check": "L7 group_disjoint", "passed": not ov, "detail": f"{len(ov)} {group_col} values in both train and test"})
    if out_of_time:
        first_test = pd.to_datetime(test["prediction_date"]).min()
        bad = int((pd.to_datetime(train["label_known_date"]) >= first_test).sum())
        res.append({"check": "L8 label_before_test", "passed": bad == 0,
                    "detail": f"first test prediction {first_test.date()}; {bad} training labels known on/after it"})
    return res


def single_feature_screen(X: pd.DataFrame, y: pd.Series, numeric: list[str], kind: str, limit: float = 0.97) -> dict:
    hits, top = [], []
    for c in numeric:
        v = pd.to_numeric(X[c], errors="coerce")
        m = v.notna()
        if m.sum() < 50 or v[m].nunique() < 2:
            continue
        if kind == "classification" and y[m].nunique() == 2:
            s = roc_auc_score(y[m], v[m]); s = max(s, 1 - s)
        elif kind == "regression":
            s = abs(np.corrcoef(v[m], y[m])[0, 1])
        else:
            continue
        top.append((c, round(float(s), 4)))
        if s > limit:
            hits.append(c)
    top.sort(key=lambda x: -x[1])
    return {"check": "L9 single_feature_screen", "passed": not hits,
            "detail": f"features above {limit}: {hits}; strongest: {top[:5]}", "strongest": top[:10]}
