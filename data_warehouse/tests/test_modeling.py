"""Tests for feature engineering, leakage prevention, splitting, training, metrics, persistence and forecasting.

Run from data_warehouse:  python -m pytest tests/test_modeling.py -q
Tests that need the built modelling datasets or trained artifacts are skipped (not failed) if those do not exist yet.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.common import RAW_UCI_FILE, UCI_EXPECTED_SHA256  # noqa: E402
from pipelines.feature_engineering.common import MODELING_DIR, MODELS_DIR, REPORTS_DIR, SYN_BANNER, load_dataset  # noqa: E402
from pipelines.feature_engineering.datasets import build_uci  # noqa: E402
from pipelines.model_training import core, forecasting, leakage  # noqa: E402
from pipelines.model_training.survival import concordance, drop_degenerate  # noqa: E402

SYN_DATASETS = ["syn_dropout_2y", "syn_next_term_performance", "syn_retention", "syn_graduation_within_window",
                "syn_graduation_survival", "syn_dropout_survival", "syn_admissions_offer", "syn_admissions_accept"]
UCI_DATASETS = ["uci_enrolment_time", "uci_end_of_year1"]
built = pytest.mark.skipif(not (MODELING_DIR / "modeling_manifest.json").exists(), reason="modelling datasets not built")
trained = pytest.mark.skipif(not (REPORTS_DIR / "model_evaluation" / "run_summary.json").exists(), reason="models not trained")


# ------------------------------------------------------------------------------------------------ data protection
def test_uci_original_unchanged():
    assert hashlib.sha256(RAW_UCI_FILE.read_bytes()).hexdigest() == UCI_EXPECTED_SHA256


def test_uci_targets_preserved_exactly():
    raw = pd.read_csv(RAW_UCI_FILE, sep=";")
    for df, card in build_uci():
        assert df["target_3class"].tolist() == raw["Target"].tolist()
        assert (df["target_dropout"] == (raw["Target"] == "Dropout").astype(int)).all()
        assert card.zone == "UCI" and "target" in card.excluded_leakage_columns


# ------------------------------------------------------------------------------------------------ features
@built
def test_panel_uses_only_past_information():
    p = pd.read_csv(MODELING_DIR / "synthetic" / "syn_student_term_panel.csv", low_memory=False)
    assert (pd.to_datetime(p["feature_max_source_date"]) <= pd.to_datetime(p["prediction_date"])).all()
    assert not p["term_id"].isin(["2026FA", "2027SP", "2027SU"]).any(), "in-progress / future terms must not enter the panel"
    assert p["grades_final"].astype(str).eq("True").all()


@built
def test_panel_feature_values_are_sane():
    p = pd.read_csv(MODELING_DIR / "synthetic" / "syn_student_term_panel.csv", low_memory=False)
    assert p["cum_course_completion_rate"].between(0, 1).all()
    assert p["fin_payment_completion_pct"].dropna().between(0, 1.5).all()
    assert (p["completed_terms"] == p["study_term_number"]).mean() > 0.99
    assert (p["cum_courses_passed"] <= p["cum_courses_registered"]).all()
    # optional Summer never counts as an interruption: a student whose only gap is a skipped Summer has 0 missed terms
    assert (p["missed_regular_terms_so_far"] >= 0).all()
    # GPA and grades are separate concepts: GPA bounded by the 4-point demonstration scale
    assert p["term_gpa"].dropna().between(0, 4).all()


@built
@pytest.mark.parametrize("name", SYN_DATASETS + UCI_DATASETS)
def test_dataset_card_target_feature_separation(name):
    zone = "UCI" if name.startswith("uci") else "SYNTHETIC"
    df, card = load_dataset(name, zone)
    feats = set(card["features_numeric"] + card["features_categorical"])
    assert not feats & set(card["targets"])
    assert card["excluded_leakage_columns"], "every dataset must document its excluded columns"
    assert set(card["features"]) <= set(df.columns)
    checks = leakage.static_checks(df, card)
    assert all(c["passed"] for c in checks), [c for c in checks if not c["passed"]]


@built
def test_zones_never_mixed():
    for name in SYN_DATASETS:
        df, _ = load_dataset(name, "SYNTHETIC")
        assert "uci_row_number" not in df.columns
    for name in UCI_DATASETS:
        df, _ = load_dataset(name, "UCI")
        assert not {"student_id", "student_programme_id", "programme_id"} & set(df.columns)


@built
def test_retention_uses_only_final_comparisons_and_excludes_completions():
    df, _ = load_dataset("syn_retention", "SYNTHETIC")
    assert (pd.to_datetime(df["label_known_date"]) <= pd.Timestamp("2026-11-10")).all()
    assert "COMPLETED_NOT_ENROLLED" not in set(df["outcome_category"])
    assert set(df["comparison_type"]) == {"FALL_TO_FALL", "SPRING_TO_SPRING", "SUMMER_TO_SUMMER"}


@built
def test_graduation_classification_uses_mature_cohorts_only():
    g, _ = load_dataset("syn_graduation_within_window", "SYNTHETIC")
    s, _ = load_dataset("syn_graduation_survival", "SYNTHETIC")
    assert set(g["graduation_record_id"]) <= set(s.loc[s["cohort_mature"].astype(str) == "True", "graduation_record_id"])
    assert (s["duration_years"] > 0).mean() > 0.99
    assert set(s["event_graduated"].unique()) <= {0, 1}


# ------------------------------------------------------------------------------------------------ missing values / preprocessing
def test_preprocessor_handles_missing_and_unseen_values():
    tr = pd.DataFrame({"a": [1.0, np.nan, 3.0, 4.0] * 10, "c": ["x", "y", None, "x"] * 10})
    te = pd.DataFrame({"a": [np.nan, 2.0], "c": ["NEVER_SEEN", None]})
    for c in (tr, te):
        c["c"] = c["c"].astype(object).where(c["c"].notna(), "MISSING")
    pre = core.make_preprocessor(["a"], ["c"], scale=True).fit(tr)
    Z = pre.transform(te)
    assert not np.isnan(Z).any()
    assert "missingindicator_a" in pre.get_feature_names_out()


def test_preprocessing_fitted_on_training_only():
    tr = pd.DataFrame({"a": np.arange(10.0), "c": ["x"] * 10})
    te = pd.DataFrame({"a": [1000.0], "c": ["x"]})
    pre = core.make_preprocessor(["a"], ["c"], scale=True).fit(tr)
    assert pre.named_transformers_["num"].named_steps["scale"].mean_[0] == pytest.approx(4.5)
    assert pre.transform(te)[0, 0] > 100     # the test value did not influence the scaler


# ------------------------------------------------------------------------------------------------ leakage checker catches injected leaks
def _toy(n=400, seed=0):
    r = np.random.default_rng(seed)
    y = r.integers(0, 2, n)
    df = pd.DataFrame({"student_id": np.repeat(np.arange(n // 4), 4), "x": r.normal(size=n), "y": y,
                       "prediction_date": pd.Timestamp("2020-01-01") + pd.to_timedelta(r.integers(0, 900, n), "D")})
    df["label_known_date"] = df["prediction_date"] + pd.Timedelta(days=200)
    df["feature_max_source_date"] = df["prediction_date"]
    card = {"zone": "SYNTHETIC", "targets": ["y"], "features_numeric": ["x"], "features_categorical": [],
            "excluded_leakage_columns": {"outcome": "final outcome"}}
    return df, card


def test_leakage_target_as_feature_detected():
    df, card = _toy()
    card["features_numeric"] = ["x", "y"]
    assert not {c["check"]: c["passed"] for c in leakage.static_checks(df, card)}["L1 target_not_in_features"]


def test_leakage_excluded_column_and_outcome_name_detected():
    df, card = _toy()
    df["outcome"] = df["y"]
    df["graduation_status_flag"] = 1
    card["features_numeric"] = ["x", "outcome", "graduation_status_flag"]
    r = {c["check"]: c["passed"] for c in leakage.static_checks(df, card)}
    assert not r["L2 excluded_not_in_features"] and not r["L3 forbidden_name_patterns"]


def test_leakage_future_source_date_detected():
    df, card = _toy()
    df.loc[5, "feature_max_source_date"] = df.loc[5, "prediction_date"] + pd.Timedelta(days=1)
    assert not {c["check"]: c["passed"] for c in leakage.static_checks(df, card)}["L5 feature_dates_before_point"]


def test_leakage_unobservable_label_detected():
    df, card = _toy()
    df.loc[0, "label_known_date"] = pd.Timestamp("2027-06-01")
    assert not {c["check"]: c["passed"] for c in leakage.static_checks(df, card)}["L6b labels_known_by_as_of"]


def test_leakage_proxy_feature_detected_by_screen():
    df, _ = _toy()
    df["proxy"] = df["y"] + np.random.default_rng(1).normal(0, 0.01, len(df))
    assert not leakage.single_feature_screen(df, df["y"], ["x", "proxy"], "classification")["passed"]
    assert leakage.single_feature_screen(df, df["y"], ["x"], "classification")["passed"]


def test_group_overlap_and_label_timing_detected():
    df, _ = _toy()
    bad = leakage.split_checks(df.iloc[:200], df.iloc[198:], "student_id", out_of_time=True)
    assert not {c["check"]: c["passed"] for c in bad}["L7 group_disjoint"]
    assert not {c["check"]: c["passed"] for c in bad}["L8 label_before_test"]


# ------------------------------------------------------------------------------------------------ splits
def test_grouped_holdout_is_disjoint_and_deterministic():
    df, _ = _toy(800)
    a = core.grouped_holdout(df, df["y"], df["student_id"])
    b = core.grouped_holdout(df, df["y"], df["student_id"])
    assert list(a[1]) == list(b[1])
    assert not set(df.loc[a[0], "student_id"]) & set(df.loc[a[1], "student_id"])
    assert 0.18 < len(a[1]) / len(df) < 0.32
    for tr, va in core.cv_splits(df, df["y"], df["student_id"]):
        assert not set(df["student_id"].iloc[tr]) & set(df["student_id"].iloc[va])


@built
def test_chronological_admissions_split():
    from pipelines.model_training.supervised import TaskSpec, _split
    df, _ = load_dataset("syn_admissions_offer", "SYNTHETIC")
    spec = TaskSpec("t", "syn_admissions_offer", "SYNTHETIC", "target_offer", group_col="applicant_id", split="chronological",
                    chrono_col="entry_academic_year_start", chrono_test_from=2025)
    tr, te = _split(df, df["target_offer"], spec)
    assert df.loc[tr, "entry_academic_year_start"].max() < df.loc[te, "entry_academic_year_start"].min()
    assert not set(df.loc[tr, "applicant_id"]) & set(df.loc[te, "applicant_id"])


# ------------------------------------------------------------------------------------------------ training, reproducibility, metrics
def _uci_small():
    df, card = build_uci()[0]
    card = card.to_json()
    X = df[card["features"]].copy()
    for c in card["features_categorical"]:
        X[c] = X[c].astype(str)
    return X.iloc[:800], df["target_dropout"].iloc[:800], card


@pytest.mark.parametrize("name", ["logistic_regression", "random_forest", "xgboost", "lightgbm", "catboost"])
def test_every_classifier_trains_and_predicts(name):
    X, y, card = _uci_small()
    est, scale = core.classifier_factory(name, y)
    p = core.build_pipeline(est, scale, card["features_numeric"], card["features_categorical"]).fit(X.iloc[:600], y.iloc[:600])
    pr = p.predict_proba(X.iloc[600:])[:, 1]
    assert pr.shape == (200,) and np.all((pr >= 0) & (pr <= 1))
    assert core.roc_auc_score(y.iloc[600:], pr) > 0.6


def test_training_is_reproducible():
    X, y, card = _uci_small()
    preds = []
    for _ in range(2):
        est, scale = core.classifier_factory("xgboost", y)
        p = core.build_pipeline(est, scale, card["features_numeric"], card["features_categorical"]).fit(X.iloc[:600], y.iloc[:600])
        preds.append(p.predict_proba(X.iloc[600:])[:, 1])
    assert np.allclose(preds[0], preds[1])


def test_regressors_train():
    X, y, card = _uci_small()
    yy = X["admission_grade"].astype(float)
    feats = [c for c in card["features_numeric"] if c != "admission_grade"]
    for name in ["linear_regression", "random_forest", "xgboost", "lightgbm"]:
        est, scale = core.regressor_factory(name)
        p = core.build_pipeline(est, scale, feats, card["features_categorical"]).fit(X.iloc[:600], yy.iloc[:600])
        assert np.isfinite(p.predict(X.iloc[600:])).all()


def test_binary_metrics_known_values():
    y = pd.Series([0, 0, 1, 1])
    m = core.binary_metrics(y, np.array([0.1, 0.6, 0.4, 0.9]), 0.5)
    assert m["confusion_matrix"] == [[1, 1], [1, 1]]
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["roc_auc"] == 0.75
    assert core.wape([10, 20], [12, 18]) == pytest.approx(4 / 30)
    r = core.regression_metrics(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0, 4.0]))
    assert r["mae"] == pytest.approx(1 / 3) and r["rmse"] == pytest.approx(np.sqrt(1 / 3))


def test_class0_threshold_maximises_class0_f1():
    from sklearn.metrics import f1_score
    rng = np.random.default_rng(0)
    y = (rng.random(400) < 0.85).astype(int)
    p1 = np.clip(0.5 * y + rng.normal(0.3, 0.2, 400), 0, 1)
    t0 = core.best_f1_threshold_class0(y, p1)
    f = lambda t: f1_score(y, core.predict_class0_threshold(p1, t), pos_label=0, zero_division=0)  # noqa: E731
    assert f(t0) == pytest.approx(max(f(t) for t in np.unique(1 - p1)))
    yhat = core.predict_class0_threshold(p1, t0)
    assert ((yhat == 0) == ((1 - p1) >= t0)).all()
    # the original class-1 threshold function is untouched
    t1 = core.best_f1_threshold(y, p1)
    g = lambda t: f1_score(y, (p1 >= t).astype(int), zero_division=0)  # noqa: E731
    assert g(t1) == pytest.approx(max(g(t) for t in np.unique(p1)))


def test_both_class_metrics_known_values():
    y = np.array([0, 0, 0, 1, 1, 1, 1, 1])
    p1 = np.array([0.1, 0.4, 0.7, 0.3, 0.6, 0.8, 0.9, 0.95])
    m = core.both_class_metrics(y, p1, (p1 >= 0.5).astype(int))
    assert m["confusion_matrix"] == [[2, 1], [1, 4]] and m["predicted_class0"] == 3
    assert m["class0"]["precision"] == pytest.approx(2 / 3) and m["class0"]["recall"] == pytest.approx(2 / 3)
    assert m["class1"]["precision"] == pytest.approx(0.8) and m["class1"]["recall"] == pytest.approx(0.8)
    assert m["class0"]["support"] == 3 and m["class1"]["support"] == 5 and m["accuracy"] == pytest.approx(0.75)
    assert m["pr_auc_class0"] == pytest.approx(core.average_precision_score(1 - y, 1 - p1))


@built
def test_dual_threshold_supplement_preserves_original_method(tmp_path, monkeypatch):
    """End-to-end on UCI data in a temporary directory: OOF predictions are saved, the original selection metric and class-1
    threshold are reproduced exactly from them, and the supplementary class-0 threshold is the class-0 F1 optimum."""
    from pipelines.feature_engineering import common
    from pipelines.model_training import supervised
    monkeypatch.setattr(core, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(core, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(core, "EXPERIMENTS_DIR", tmp_path / "experiments")
    monkeypatch.setattr(common, "EXPERIMENTS_DIR", tmp_path / "experiments")
    spec = supervised.TaskSpec("t_dual_threshold", "uci_end_of_year1", "UCI", "target_dropout", "binary",
                               ["baseline_majority", "logistic_regression", "xgboost"], None, split="stratified")
    r = supervised.run(spec)
    assert r["status"] == "TRAINED"
    assert 0 < r["seconds"] < 3600          # run duration, not a timestamp
    out = tmp_path / "reports" / "model_evaluation" / "uci" / "t_dual_threshold"
    oof, test = pd.read_csv(out / "oof_predictions.csv"), pd.read_csv(out / "test_predictions.csv")
    assert len(oof) == r["split"]["train_rows"] and len(test) == r["split"]["test_rows"]
    for m in r["models"]:
        if m["model"] == "baseline_majority":
            continue
        p = oof[f"oof_p1_{m['model']}"].values
        assert m["cv_pr_auc"] == pytest.approx(core.average_precision_score(oof["y"], p), abs=1e-6)
        assert m["threshold_from_cv"] == pytest.approx(core.best_f1_threshold(oof["y"], p), abs=1e-6)
        s = m["supplementary_class0"]
        assert s["threshold_class0"] == pytest.approx(core.best_f1_threshold_class0(oof["y"], p), abs=1e-6)
        assert s["test_at_original_threshold"]["confusion_matrix"] == m["test_confusion_matrix_tuned"]
        pt = test[f"test_p1_{m['model']}"].values
        assert s["test_at_class0_threshold"]["confusion_matrix"] == core.both_class_metrics(
            test["y"], pt, core.predict_class0_threshold(pt, s["threshold_class0"]))["confusion_matrix"]
    best = max((m for m in r["models"] if not m["model"].startswith("baseline")), key=lambda m: m["cv_pr_auc"])
    assert r["best_model"] == best["model"] and r["supplementary_class0"]["model"] == r["best_model"]
    assert r["threshold_methodology"]["selection"].startswith("unchanged")
    assert (out / f"confusion_{r['best_model']}_class0_threshold.png").exists()
    assert not (tmp_path / "experiments" / "checkpoints" / "t_dual_threshold").exists()   # cleaned up after success


def test_segmentation_leakage_checks_detect_problems():
    from pipelines.model_training.segmentation import leakage_checks
    df = pd.DataFrame({"student_id": ["a", "b"], "term_id": ["2026SP", "2026SP"], "gpa": [3.0, 2.0], "graduated_flag": [0, 1]})
    assert all(c["passed"] for c in leakage_checks(df, ["gpa"]))
    bad = {c["check"].split()[0] for c in leakage_checks(df.assign(term_id=["2026FA", "2026SP"]), ["gpa", "student_id", "graduated_flag"]) if not c["passed"]}
    assert {"S1", "S2", "S4", "S6"} <= bad


@built
def test_segmentation_end_to_end(tmp_path, monkeypatch):
    from pipelines.model_training import segmentation
    monkeypatch.setattr(core, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(core, "MODELS_DIR", tmp_path / "models")
    r = segmentation.run()
    out = tmp_path / "reports" / "feature_analysis" / "synthetic"
    assert all(c["passed"] for c in r["leakage_checks"])
    sil = {int(k): v for k, v in r["silhouette_by_k"].items()}
    assert r["chosen_k"] == max(sil, key=sil.get) and sum(r["segment_sizes"].values()) == r["n_students"]
    a = pd.read_csv(out / "segmentation_assignments.csv")
    assert len(a) == r["n_students"] and a["student_id"].is_unique and (a["label"] == SYN_BANNER).all()
    assert np.isfinite(a["anomaly_score"]).all()
    assert abs(r["isolation_forest"]["flagged"] - 0.02 * r["n_students"]) <= 2 and a["is_anomaly"].sum() == r["isolation_forest"]["flagged"]
    thr = r["anomaly_diagnostics"]["threshold_score"]
    assert (a.loc[a["is_anomaly"], "anomaly_score"] > thr - 1e-3).all() and (a.loc[~a["is_anomaly"], "anomaly_score"] <= thr + 1e-3).all()
    assert len(pd.read_csv(out / "anomaly_flagged_explanations.csv")) == r["isolation_forest"]["flagged"]
    assert -1 <= r["cluster_quality"]["silhouette_kmeans_chosen_k_full_data"] <= 1 and "ground-truth" in r["anomaly_diagnostics"]["validation_evidence"]
    assert (tmp_path / "models" / "synthetic" / "segmentation" / "kmeans_isolation_forest.joblib").exists()


def test_concordance_and_degenerate_columns():
    assert concordance([1, 2, 3], [1, 1, 1], [3, 2, 1]) == 1.0
    assert concordance([1, 2, 3], [1, 1, 1], [1, 2, 3]) == 0.0
    assert concordance([1, 2, 3, 4], [1, 1, 1, 1], [2, 1, 2, 1], strata=["a", "a", "b", "b"]) == 1.0
    X = pd.DataFrame({"a": [1.0, 2, 3, 4], "b": [1.0, 2, 3, 4], "k": [0.0] * 4, "c": [1.0, 0, 1, 5]})
    const, coll = drop_degenerate(X)
    assert const == ["k"] and coll == ["b"]


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    X, y, card = _uci_small()
    est, scale = core.classifier_factory("logistic_regression", y)
    p = core.build_pipeline(est, scale, card["features_numeric"], card["features_categorical"]).fit(X.iloc[:600], y.iloc[:600])
    monkeypatch.setattr(core, "MODELS_DIR", tmp_path / "models")
    core.save_model(p, "SYNTHETIC", "unit", "lr", {"note": "test"})
    q = joblib.load(tmp_path / "models" / "synthetic" / "unit" / "lr.joblib")
    meta = json.loads((tmp_path / "models" / "synthetic" / "unit" / "lr.meta.json").read_text(encoding="utf-8"))
    assert np.allclose(p.predict_proba(X.iloc[600:]), q.predict_proba(X.iloc[600:]))
    assert "NOT production-ready" in meta["deployment_status"] and meta["label"] == SYN_BANNER


# ------------------------------------------------------------------------------------------------ forecasting
def test_seasonal_naive_and_term_calendar():
    y = np.array([10, 20, 30, 11, 21, 31], float)
    f, lo, hi = forecasting.forecast_one("seasonal_naive", y)
    assert list(f) == [11, 21, 31] and lo is None
    assert forecasting._next_terms("2026FA") == ["2027SP", "2027SU", "2027FA"]
    assert forecasting._next_terms("2026SU") == ["2026FA", "2027SP", "2027SU"]


def test_statistical_forecasters_return_intervals():
    rng = np.random.default_rng(0)
    y = np.array([100 + 5 * t + [30, 10, -40][t % 3] + rng.normal(0, 3) for t in range(27)])
    forecasting.FIT_FAILURES.clear()
    for m in ("ets", "sarima", "arima"):
        f, lo, hi = forecasting.forecast_one(m, y)
        assert np.isfinite(f).all() and (lo <= f + 1e-6).all() and (hi >= f - 1e-6).all(), m
    assert forecasting.FIT_FAILURES == []


def test_forecast_failure_records_context():
    forecasting.FIT_FAILURES.clear()
    forecasting.forecast_one("ets", np.array([5.0, 6.0]), series="s", key="k", origin="2020FA")
    assert forecasting.FIT_FAILURES and forecasting.FIT_FAILURES[0]["series"] == "s" and forecasting.FIT_FAILURES[0]["key"] == "k"
    forecasting.FIT_FAILURES.clear()


@trained
def test_forecast_results_record_failures_and_validation():
    r = json.loads((REPORTS_DIR / "forecasting" / "forecasting_results.json").read_text())
    ff = pd.read_csv(REPORTS_DIR / "forecasting" / "fit_failures.csv")
    assert r["fit_failures"]["count"] == len(ff) == sum(r["fit_failures"]["by_method"].values())
    assert r["validation"]["selected_non_finite"] == 0 and r["validation"]["selected_negative"] == 0
    sel = pd.read_csv(REPORTS_DIR / "forecasting" / "forecasts_selected_method.csv")
    assert np.isfinite(sel["forecast"]).all() and (sel["forecast"] >= 0).all()
    best = {b["series"]: b["best_method"] for b in r["best_method_by_series"]}
    excluded = {(e["series"], e["method"]) for e in r["fit_failures"]["methods_excluded_from_selection"]}
    assert not [s for s, m in best.items() if (s, m) in excluded]


def test_forecast_failure_is_recorded_not_hidden():
    forecasting.FIT_FAILURES.clear()
    f, lo, hi = forecasting.forecast_one("ets", np.array([5.0, 6.0]))
    assert np.isnan(f).all() and len(forecasting.FIT_FAILURES) == 1


def test_insufficient_history_flagged():
    ok, why, n = forecasting.eligibility(np.r_[np.zeros(20), np.full(11, 50.0)])
    assert not ok and n == 11 and "only 11 terms" in why
    ok, why, _ = forecasting.eligibility(np.r_[np.full(28, 40.0), [40, 3, 40]])
    assert not ok and "fewer than" in why
    assert forecasting.eligibility(np.full(31, 40.0))[0]


def test_backtest_is_rolling_origin_and_chronological():
    rng = np.random.default_rng(1)
    terms = [f"T{i:02d}" for i in range(31)]
    rows = [{"k": "A", "term_id": t, "term_sequence": i, "season": ["FALL", "SPRING", "SUMMER"][i % 3],
             "value": 200 + 4 * i + [40, 0, -120][i % 3] + rng.normal(0, 4)} for i, t in enumerate(terms)]
    el, er, fi, ids = forecasting.backtest(pd.DataFrame(rows), "value", ["k"], "toy")
    assert (el["status"] == "ELIGIBLE").all()
    pos = {t: i for i, t in enumerate(ids)}
    assert (er["target_term"].map(pos) > er["origin_term"].map(pos)).all()
    assert (er["target_term"].map(pos) - er["origin_term"].map(pos) == er["horizon"]).all()
    assert set(er["method"]) == set(forecasting.ALL_METHODS)
    assert er["forecast"].notna().all()


# ------------------------------------------------------------------------------------------------ trained artifacts
@trained
def test_run_summary_has_no_failed_or_blocked_tasks():
    s = json.loads((REPORTS_DIR / "model_evaluation" / "run_summary.json").read_text())
    bad = {k: v for k, v in s["tasks"].items() if v["status"] not in ("TRAINED", "TRAINED_WITH_PH_CAVEATS")}
    assert not bad, bad


@trained
def test_saved_synthetic_models_are_labelled_and_loadable():
    metas = list((MODELS_DIR / "synthetic").rglob("*.meta.json"))
    assert metas
    for m in metas:
        meta = json.loads(m.read_text(encoding="utf-8"))
        assert meta["label"] == SYN_BANNER and "NOT production-ready" in meta["deployment_status"]
    for m in (MODELS_DIR / "uci").rglob("*.meta.json"):
        assert "RESEARCH_ONLY" in json.loads(m.read_text(encoding="utf-8"))["deployment_status"]


@trained
def test_all_leakage_checks_passed_in_training():
    for f in (REPORTS_DIR / "model_evaluation").rglob("results.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        assert all(c["passed"] for c in r["leakage_checks"]), (f, [c for c in r["leakage_checks"] if not c["passed"]])


@trained
def test_synthetic_forecast_outputs_carry_label():
    f = pd.read_csv(REPORTS_DIR / "forecasting" / "forecasts_selected_method.csv")
    assert (f["label"] == SYN_BANNER).all()
    assert f["forecast"].notna().all()
