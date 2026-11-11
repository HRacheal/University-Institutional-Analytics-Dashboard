"""ML service: model catalogue, evaluation, single / CSV-batch / current-cohort predictions, prediction history.

Every prediction comes from a saved artifact listed in data_warehouse/artifacts/artifact_manifest.json, loaded once and
cached by pipelines.model_registry.ModelRegistry (SHA-256 checked, saved preprocessing pipeline, saved thresholds).
Nothing here trains or refits a model, and no prediction is hard-coded.

Risk bands (binary tasks) are derived only from the saved decision threshold and the training base rate:
  HIGH      the model predicts the adverse outcome at the ORIGINAL saved threshold
  ELEVATED  not predicted adverse, but the adverse probability is at or above the training base rate
  LOW       adverse probability below the training base rate
For tasks without an adverse direction (admissions offer / acceptance) the band is LIKELY / UNLIKELY at the threshold.
"""
from __future__ import annotations

import io
import json
import logging
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import desc, insert, select

from ..core import db
from ..core.config import get_settings

log = logging.getLogger("uiad.ml")

_dw = str(get_settings().dw_root)
if _dw not in sys.path:
    sys.path.insert(0, _dw)

from pipelines.model_registry.loader import ArtifactError, InputValidationError, ModelRegistry  # noqa: E402

AS_OF = "2026-11-10"
SYN_LABEL = "SYNTHETIC DEMONSTRATION MODEL — trained on synthetic data; not valid for decisions about real students"
UCI_LABEL = ("UCI RESEARCH MODEL — trained on the public UCI (Portugal) dataset; describes that dataset, not this university")
DECISION_SUPPORT = ("Decision support only: a prediction must never by itself trigger an action about an individual student "
                    "or applicant. Review with an advisor and the full record.")

# class 1 meaning per task and whether class 1 is the adverse outcome (None = no adverse direction)
CLASS1 = {
    "uci_dropout_enrolment_time": ("dropout", True), "uci_dropout_end_of_year1": ("dropout", True),
    "syn_dropout_2y": ("dropout within 2 years", True), "syn_next_term_academic_risk": ("academic warning/probation/dismissal next term", True),
    "syn_graduation_within_window": ("graduates within the reporting window", False),
    "syn_admissions_offer": ("receives an offer", None), "syn_admissions_accept": ("accepts the offer", None),
}
for _ct in ("fall_to_fall", "spring_to_spring", "summer_to_summer"):
    for _t in ("institutional", "programme"):
        CLASS1[f"syn_retention_{_ct}_{_t}"] = (f"retained ({_t})", False)

MODULE_LIMITATIONS = {
    "academic_risk": ["Most models are trained on SYNTHETIC data; UCI models describe a public Portuguese dataset, not this university.",
                      "Risk scores identify students who may benefit from support; they are not judgements about individuals."],
    "retention": ["Retention models have weak discrimination (see each model's test ROC-AUC): most students are retained, so the "
                  "models separate retained and not-retained students only modestly.",
                  "Lowering the threshold raises recall of not-retained students but adds many false positives (see the "
                  "supplementary class-0 threshold results).",
                  "Model estimates are separate from the official retention rates on the Retention page."],
    "graduation": ["Cox survival models show proportional-hazards caveats for several covariates: hazard ratios are average effects.",
                   "Graduation-within-window models are trained on mature cohorts only."],
    "admissions": ["Admissions models learn historical decisions; they may reproduce past patterns and are NOT fair or valid "
                   "screening tools.",
                   "Gender and nationality are model inputs and require a fairness review before any operational use.",
                   "Acceptance prediction has weak discrimination."],
    "forecasting": ["Forecasts are for planning; prediction intervals (especially ETS) showed under-coverage in backtests.",
                    "Forecasts beyond the configured calendar (after 2027SU) are extrapolations."],
    "segmentation": ["Cluster structure is weak (low silhouette): segments are descriptive groupings, not natural types.",
                     "Anomaly flags mark statistically unusual records only; they are NOT evidence of error, fraud or misconduct."],
}

# current-cohort scoring: which panel rows each task may score (must match the task's training population)
COHORT_RULES = {
    "syn_dropout_2y": {"base": "latest", "note": "each open admission's latest completed term (grades final), outcome not recorded by the as-of date"},
    "syn_next_term_academic_risk": {"base": "latest", "note": "each open admission's latest completed term; predicts the next graded term"},
    "syn_next_term_gpa": {"base": "latest", "note": "each open admission's latest completed term; predicts the next term GPA"},
    "syn_retention_spring_to_spring_institutional": {"base": "2026SP", "note": "base term Spring 2026, comparison census Spring 2027"},
    "syn_retention_spring_to_spring_programme": {"base": "2026SP", "note": "base term Spring 2026, comparison census Spring 2027"},
    "syn_retention_summer_to_summer_institutional": {"base": "2026SU", "note": "base term Summer 2026, comparison census Summer 2027"},
    "syn_retention_summer_to_summer_programme": {"base": "2026SU", "note": "base term Summer 2026, comparison census Summer 2027"},
}
COHORT_UNAVAILABLE = {
    "syn_retention_fall_to_fall_institutional": "No open Fall base term: Fall 2026 grades are not final, and the Fall 2025 -> Fall 2026 outcome is already observed.",
    "syn_retention_fall_to_fall_programme": "No open Fall base term: Fall 2026 grades are not final, and the Fall 2025 -> Fall 2026 outcome is already observed.",
}
BAND_RULE = ("HIGH = adverse outcome predicted at the original saved threshold; ELEVATED = not predicted adverse but adverse "
             "probability >= training base rate; LOW = below the base rate. Offer/acceptance: LIKELY/UNLIKELY at the threshold.")
ID_COLUMNS = ("record_id", "student_id", "applicant_id", "application_id", "student_programme_id")

_registry: ModelRegistry | None = None
_rlock = threading.Lock()
_results_cache: dict = {}


def registry() -> ModelRegistry:
    global _registry
    with _rlock:
        if _registry is None:
            _registry = ModelRegistry(root=get_settings().dw_root)
        return _registry


def _dw() -> Path:
    return get_settings().dw_root


def _clean(o):
    from ..analytics.common import clean
    return clean(o)


def results(task: str) -> dict:
    """Saved evaluation results.json of a task (read once)."""
    if task not in _results_cache:
        e = registry().tasks.get(task) or {}
        p = _dw() / e["results"] if e.get("results") else None
        _results_cache[task] = json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else {}
    return _results_cache[task]


def _base_rate(task: str) -> float | None:
    cd = (results(task).get("class_distribution") or {}).get("train") or {}
    n0, n1 = float(cd.get("0", 0)), float(cd.get("1", 0))
    return n1 / (n0 + n1) if n0 + n1 else None


def _auto_warnings(task: str) -> list[str]:
    e = registry().tasks[task]
    m = e.get("test_metrics_selected") or {}
    w = []
    auc = m.get("test_roc_auc") if m.get("test_roc_auc") is not None else m.get("test_roc_auc_ovr_macro")
    if auc is not None and auc < 0.70:
        w.append(f"Weak discrimination: test ROC-AUC {auc:.3f} (0.5 = chance). Treat individual scores with great caution.")
    elif auc is not None and auc < 0.80:
        w.append(f"Moderate discrimination: test ROC-AUC {auc:.3f}.")
    if e.get("status") == "TRAINED_WITH_PH_CAVEATS":
        w.append("Proportional-hazards assumption is questionable for some covariates (see the model's PH check).")
    feats = (e.get("features_numeric") or []) + (e.get("features_categorical") or [])
    sens = [f for f in feats if f in ("gender", "nationality_iso3", "nationality", "residency_status", "age_at_entry", "marital_status")]
    if sens:
        w.append(f"Uses sensitive attributes {sens}: fairness review required before any operational use.")
    return w


def catalogue() -> list[dict]:
    out = []
    reg = registry()
    for t, e in reg.tasks.items():
        c1 = CLASS1.get(t)
        out.append(_clean({
            "task": t, "module": e.get("module"), "kind": e.get("kind"), "zone": e.get("zone"), "batch": e.get("batch"),
            "title": results(t).get("title") or e.get("prediction_meaning") or t,
            "prediction_meaning": e.get("prediction_meaning"), "status": e.get("status"),
            "selected_model": e.get("selected_model"), "models": list((e.get("models") or {}).keys()),
            "class1_meaning": c1[0] if c1 else None, "class1_is_adverse": c1[1] if c1 else None,
            "test_metrics": e.get("test_metrics_selected"), "thresholds": e.get("thresholds"),
            "label": UCI_LABEL if e.get("zone") == "UCI" else SYN_LABEL,
            "artifact_present": reg.available(t) if e.get("selected_model") else None,
            "predictable": e.get("kind") in ("binary", "multiclass", "regression", "survival") and bool(e.get("selected_model")),
            "cohort_available": t in COHORT_RULES, "cohort_note": (COHORT_RULES.get(t) or {}).get("note") or COHORT_UNAVAILABLE.get(t),
            "warnings": _auto_warnings(t) if e.get("selected_model") else [],
        }))
    return out


def task_detail(task: str) -> dict:
    reg = registry()
    if task not in reg.tasks:
        raise ArtifactError(f"unknown task {task!r}")
    e = reg.tasks[task]
    r = results(task)
    keep = ("title", "target_definition", "prediction_point", "population", "n_rows", "n_features", "split", "class_distribution",
            "target_summary", "models", "selection_rule", "best_model", "best_vs_linear_baseline", "persistence_baseline",
            "threshold_methodology", "supplementary_class0", "subgroups", "out_of_time", "shap_model", "shap_top15", "linear_top10",
            "leakage_checks", "excluded_leakage_columns", "concordance_train", "concordance_test", "hazard_ratios", "ph_check",
            "ph_possible_violations", "events", "censored", "covariates", "covariate_note")
    ev = {k: r[k] for k in keep if k in r}
    for m in ev.get("models", []) if isinstance(ev.get("models"), list) else []:
        for k in [k for k in m if k.startswith("test_classification_report")]:
            m.pop(k)
    figs = sorted(str(p.relative_to(_dw())).replace("\\", "/") for p in (_dw() / "reports" / "model_evaluation").glob(f"*/{task}/*.png"))
    figs += sorted(str(p.relative_to(_dw())).replace("\\", "/") for p in (_dw() / "reports" / "feature_analysis").glob(f"*/{task}_*.png"))
    cat = next(c for c in catalogue() if c["task"] == task)
    return _clean({**cat, "evaluation": ev, "figures": figs, "limitations": MODULE_LIMITATIONS.get(e.get("module"), []),
                   "decision_support": DECISION_SUPPORT, "features_numeric": e.get("features_numeric"),
                   "features_categorical": e.get("features_categorical")})


# ------------------------------------------------------------------------------------------------ input schema / template
def input_schema(task: str) -> dict:
    """Required columns, their types, allowed categorical values (from the saved encoder) and a typical example row."""
    reg = registry()
    e = reg.tasks.get(task)
    if not e:
        raise ArtifactError(f"unknown task {task!r}")
    if not e.get("selected_model"):
        raise ArtifactError(f"task {task!r} has no predictive model")
    lm = reg.get(task)
    if e["kind"] == "survival":
        from pipelines.model_training.survival import COX_NUMERIC
        o = lm.obj
        means = o.get("means")
        mean_of = (lambda c: float(means[c]) if means is not None and c in means and np.isfinite(means[c]) else None)
        cols = [{"name": c, "type": "number", "median": mean_of(c)} for c in COX_NUMERIC] + \
               [{"name": "level", "type": "category", "values": [str(v) for v in o["levels"]]}]
        example = {c["name"]: c.get("median") if c["type"] == "number" else (c["values"][0] if c.get("values") else None) for c in cols}
        return _clean({"task": task, "columns": cols, "id_columns": list(ID_COLUMNS), "example": example,
                       "note": "Example = training means of the saved model (the reference point: relative hazard about 1) and the first level; "
                               "a neutral starting point, not a real student."})
    cats = {}
    try:
        prep = lm.obj.named_steps["prep"]
        enc = prep.named_transformers_["cat"].named_steps["onehot"]
        cats = {c: [str(v) for v in vals if str(v) != "MISSING"] for c, vals in zip(lm.categorical, enc.categories_)}
        med = dict(zip(lm.numeric, prep.named_transformers_["num"].named_steps["impute"].statistics_))
    except Exception:          # pragma: no cover - non-pipeline model
        med = {}
    cols = [{"name": c, "type": "number", "median": float(med[c]) if c in med and np.isfinite(med[c]) else None} for c in lm.numeric]
    cols += [{"name": c, "type": "category", "values": cats.get(c, [])} for c in lm.categorical]
    example = {c["name"]: c.get("median") if c["type"] == "number" else (c["values"][0] if c.get("values") else None) for c in cols}
    return _clean({"task": task, "columns": cols, "id_columns": list(ID_COLUMNS), "example": example,
                   "note": "Example = training medians of the saved imputer and the first known category: a neutral starting point, not a real student."})


def template_csv(task: str) -> bytes:
    s = input_schema(task)
    df = pd.DataFrame([{"record_id": "example-1", **(s["example"] or {c["name"]: "" for c in s["columns"]})}])
    return df.to_csv(index=False).encode()


# ------------------------------------------------------------------------------------------------ prediction core
def _bands(task: str, out: dict) -> list[str] | None:
    if out.get("kind") != "binary" or "threshold_original" not in out:
        return None
    c1 = CLASS1.get(task)
    p1, thr = np.asarray(out["p_class1"]), float(out["threshold_original"])
    if not c1 or c1[1] is None:
        return np.where(p1 >= thr, "LIKELY", "UNLIKELY").tolist()
    base = _base_rate(task)
    if c1[1]:      # class 1 adverse
        adverse_pred, p_adv, base_adv = p1 >= thr, p1, base
    else:          # class 0 adverse (not retained / not graduated)
        adverse_pred, p_adv, base_adv = p1 < thr, 1 - p1, (1 - base) if base is not None else None
    band = np.where(adverse_pred, "HIGH", np.where(base_adv is not None and (p_adv >= (base_adv or 0)), "ELEVATED", "LOW"))
    return band.tolist()


def _rows(task: str, out: dict, ids: list | None) -> list[dict]:
    n = out["n"]
    rows = []
    bands = _bands(task, out)
    c1 = CLASS1.get(task)
    for i in range(n):
        r = {"row": i + 1}
        if ids is not None:
            r["id"] = ids[i]
        k = out["kind"]
        if k == "binary":
            p1 = float(out["p_class1"][i])
            r["probability_class1"] = p1
            if c1 and c1[1] is not None:
                r["probability_adverse"] = p1 if c1[1] else 1 - p1
            if "pred_original" in out:
                r["predicted_class_original_threshold"] = int(out["pred_original"][i])
            if "pred_supplementary_class0" in out:
                r["predicted_class_supplementary_threshold"] = int(out["pred_supplementary_class0"][i])
            if bands:
                r["band"] = bands[i]
        elif k == "multiclass":
            r["predicted_label"] = out["pred_label"][i]
            r.update({f"probability_{lab}": float(out["proba"][i][j]) for j, lab in enumerate(out["labels"])})
        elif k == "regression":
            r["prediction"] = float(out["prediction"][i])
        elif k == "survival":
            r["relative_hazard"] = float(out["relative_hazard"][i])
            r["linear_predictor"] = float(out["linear_predictor"][i])
            r["level"] = out["level"][i]
        rows.append(r)
    return rows


def predict_frame(task: str, df: pd.DataFrame, explain: bool = False) -> dict:
    reg = registry()
    e = reg.tasks.get(task)
    if not e:
        raise ArtifactError(f"unknown task {task!r}")
    if not e.get("selected_model"):
        raise ArtifactError(f"task {task!r} has no predictive model")
    if e["kind"] not in ("binary", "multiclass", "regression", "survival"):
        raise ArtifactError(f"task {task!r} ({e['kind']}) is not served by the prediction endpoint")
    lm = reg.get(task)
    id_col = next((c for c in ID_COLUMNS if c in df.columns), None)
    ids = df[id_col].astype(str).tolist() if id_col else None
    t0 = time.time()
    out = lm.predict(df)
    rows = _rows(task, out, ids)
    if explain and e["kind"] in ("binary", "multiclass", "regression") and len(df) <= 20:
        try:
            ex = lm.explain(df)
            for r, x in zip(rows, ex):
                r["top_factors"] = x
        except Exception as ex_:                       # explanations are optional; the error is reported
            log.warning("explain failed for %s: %r", task, ex_)
            out["warnings"] = list(out.get("warnings", [])) + [f"explanations unavailable: {ex_!r}"[:200]]
    m = e.get("test_metrics_selected") or {}
    summary = {"n": out["n"]}
    if e["kind"] == "binary":
        p = np.asarray(out["p_class1"])
        summary.update({"mean_probability_class1": float(p.mean()), "threshold_original": out.get("threshold_original"),
                        "threshold_supplementary_class0": out.get("threshold_supplementary_class0")})
        if "pred_original" in out:
            summary["predicted_class1_original"] = int(np.sum(out["pred_original"]))
        b = _bands(task, out)
        if b:
            summary["bands"] = pd.Series(b).value_counts().to_dict()
    elif e["kind"] == "multiclass":
        summary["predicted_labels"] = pd.Series(out["pred_label"]).value_counts().to_dict()
    elif e["kind"] == "regression":
        pr = np.asarray(out["prediction"])
        summary.update({"mean_prediction": float(pr.mean()), "min": float(pr.min()), "max": float(pr.max()),
                        "typical_error_rmse_test": m.get("test_rmse")})
    elif e["kind"] == "survival":
        summary["median_relative_hazard"] = float(np.median(out["relative_hazard"]))
    return _clean({"task": task, "model": lm.name, "kind": e["kind"], "loaded_via": getattr(lm, "loaded_via", None),
                   "label": UCI_LABEL if e.get("zone") == "UCI" else SYN_LABEL, "decision_support": DECISION_SUPPORT,
                   "class1_meaning": (CLASS1.get(task) or (None,))[0], "thresholds": e.get("thresholds"),
                   "test_metrics": m, "warnings": list(out.get("warnings", [])) + _auto_warnings(task),
                   "interpretation": out.get("interpretation"), "imputed_missing": out.get("imputed_missing"),
                   "band_rule": BAND_RULE if e["kind"] == "binary" else None,
                   "seconds": round(time.time() - t0, 3), "summary": summary, "rows": rows})


def read_csv_upload(content: bytes, name: str) -> pd.DataFrame:
    s = get_settings()
    if len(content) > s.max_upload_mb * 1024 * 1024:
        raise InputValidationError(f"file larger than {s.max_upload_mb} MB")
    if not name.lower().endswith(".csv"):
        raise InputValidationError("only .csv files are accepted")
    try:
        df = pd.read_csv(io.BytesIO(content), keep_default_na=False, na_values=[""], low_memory=False)
    except Exception as ex:
        raise InputValidationError(f"could not parse CSV: {ex}") from ex
    if df.empty:
        raise InputValidationError("the CSV has no data rows")
    if len(df) > s.max_batch_rows:
        raise InputValidationError(f"{len(df)} rows exceeds the batch limit of {s.max_batch_rows}")
    return df


# ------------------------------------------------------------------------------------------------ current-cohort scoring
_panel: pd.DataFrame | None = None


def _panel_rows() -> pd.DataFrame:
    global _panel
    if _panel is None:
        from pipelines.feature_engineering.common import MODELING_DIR
        _panel = pd.read_csv(MODELING_DIR / "synthetic" / "syn_student_term_panel.csv", low_memory=False,
                             keep_default_na=False, na_values=[""])
    return _panel


def cohort_frame(task: str) -> pd.DataFrame:
    if task not in COHORT_RULES:
        raise InputValidationError(COHORT_UNAVAILABLE.get(task, f"current-cohort scoring is not defined for {task}"))
    from ..integrations import registry as integ
    if integ.active_source("REGISTRAR").get("connector") != "sample":
        raise InputValidationError("current-cohort scoring uses the feature panel built from the SYNTHETIC sample data; it is "
                                   "disabled while another Registrar source is active (features would not match the records). "
                                   "Use CSV batch prediction with features extracted from the active source.")
    rule = COHORT_RULES[task]
    p = _panel_rows()
    sp = integ.table("registrar/student_programmes")[["student_programme_id", "outcome_recorded_date"]]
    # outcome dates come from the active Registrar source (authoritative), not the panel's copy
    p = p.drop(columns=["outcome_recorded_date"], errors="ignore").merge(sp, on="student_programme_id", how="left")
    rec = pd.to_datetime(p["outcome_recorded_date"], errors="coerce")
    if rule["base"] == "latest":
        p = p[rec.isna() | (rec > pd.Timestamp(AS_OF))]          # admission still open at the as-of date
        p = p.sort_values("prediction_date").groupby("student_programme_id").tail(1)
    else:
        p = p[p["term_id"] == rule["base"]]
        p = p[rec.loc[p.index].isna() | (rec.loc[p.index] > pd.to_datetime(p["prediction_date"]))]   # population rule
    return p.reset_index(drop=True)


# ------------------------------------------------------------------------------------------------ history
def _pred_dir() -> Path:
    d = get_settings().var_dir / "predictions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def record_run(user: dict, task: str, res: dict, mode: str, input_name: str | None, extra_cols: pd.DataFrame | None = None) -> int:
    with db.get_engine().begin() as c:
        rid = c.execute(insert(db.prediction_runs).values(ts=db.now(), username=user["username"], task=task, model=res["model"],
                                                          mode=mode, n_rows=res["summary"]["n"], input_name=(input_name or "")[:200],
                                                          summary=res["summary"])).inserted_primary_key[0]
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "top_factors"} for r in res["rows"]])
    if extra_cols is not None:
        df = pd.concat([extra_cols.reset_index(drop=True), df], axis=1)
    header = [f"# {res['label']}", f"# {DECISION_SUPPORT}", f"# task={task} model={res['model']} run={rid} generated={db.now().isoformat()}"]
    path = _pred_dir() / f"run_{rid}.csv"
    path.write_text("\n".join(header) + "\n" + df.to_csv(index=False), encoding="utf-8")
    db.execute(db.prediction_runs.update().where(db.prediction_runs.c.id == rid).values(result_file=path.name))
    log.info("prediction run %s: %s %s rows=%s by %s", rid, task, mode, res["summary"]["n"], user["username"])
    return rid


def history(user: dict, limit: int = 200) -> list[dict]:
    q = select(db.prediction_runs).order_by(desc(db.prediction_runs.c.id)).limit(limit)
    if user["role"] != "ADMIN":
        q = q.where(db.prediction_runs.c.username == user["username"])
    return _clean(db.fetch_all(q))


def run_file(user: dict, rid: int) -> Path:
    r = db.fetch_one(select(db.prediction_runs).where(db.prediction_runs.c.id == rid))
    if not r or (user["role"] != "ADMIN" and r["username"] != user["username"]):
        raise ArtifactError("prediction run not found")
    p = _pred_dir() / (r["result_file"] or "")
    if not r["result_file"] or not p.exists():
        raise ArtifactError("result file no longer available")
    return p


# ------------------------------------------------------------------------------------------------ forecasting & segmentation
def _csv(rel: str) -> pd.DataFrame:
    p = _dw() / rel
    if not p.exists():
        raise ArtifactError(f"output not restored: {rel}")
    return pd.read_csv(p, low_memory=False)


def forecasts() -> dict:
    fr = json.loads((_dw() / "reports/forecasting/forecasting_results.json").read_text(encoding="utf-8"))
    sel = _csv("reports/forecasting/forecasts_selected_method.csv")
    best = _csv("reports/forecasting/best_method_by_series_family.csv")
    cov = _csv("reports/forecasting/backtest_summary_by_series_method.csv")
    cov = cov[["series", "method", "wape", "pi80_coverage"] + [c for c in ("n_failed", "eligible_for_selection") if c in cov.columns]]
    return _clean({"label": SYN_LABEL, "series_families": best, "selected_forecasts": sel, "backtest": cov,
                   "conversion_rates": _csv("reports/forecasting/conversion_rate_forecasts.csv"),
                   "conversion_rate_backtest": _csv("reports/forecasting/conversion_rate_backtest_summary.csv"),
                   "annual": _csv("reports/forecasting/annual_series_forecasts.csv"),
                   "annual_backtest": _csv("reports/forecasting/annual_series_backtest_summary.csv"),
                   "next_terms": fr.get("next_terms"), "validation": fr.get("validation"), "fit_failures": fr.get("fit_failures"),
                   "settings": fr.get("settings"), "limitations": MODULE_LIMITATIONS["forecasting"],
                   "figures": sorted(f"reports/forecasting/{p.name}" for p in (_dw() / "reports/forecasting").glob("*.png"))})


def forecast_history(series: str) -> dict:
    """Actual history for a series family (from the backtest file: actual values by target term)."""
    e = _csv("reports/forecasting/backtest_errors.csv")
    e = e[e["series"] == series]
    if e.empty:
        raise ArtifactError(f"unknown series {series!r}")
    h = e.drop_duplicates(["key", "target_term"])[["key", "target_term", "actual"]].sort_values(["key", "target_term"])
    return _clean({"series": series, "history": h})


def segmentation() -> dict:
    base = "reports/feature_analysis/synthetic/"
    r = json.loads((_dw() / base / "segmentation_results.json").read_text(encoding="utf-8"))
    prof = _csv(base + "segmentation_kmeans_profiles.csv")
    asg = _csv(base + "segmentation_assignments.csv")
    expl = _csv(base + "anomaly_flagged_explanations.csv")
    return _clean({"label": SYN_LABEL, "results": {k: v for k, v in r.items() if k not in ("assignments",)}, "profiles": prof,
                   "segment_sizes": asg.groupby("kmeans_segment").size().to_dict(),
                   "anomalies_by_segment": asg.groupby("kmeans_segment")["is_anomaly"].sum().to_dict(),
                   "n_students": len(asg), "anomalies": expl, "limitations": MODULE_LIMITATIONS["segmentation"],
                   "figures": [base + "segmentation_silhouette.png", base + "anomaly_score_distribution.png"]})


def segmentation_assignments() -> pd.DataFrame:
    return _csv("reports/feature_analysis/synthetic/segmentation_assignments.csv")


def model_status() -> dict:
    reg = registry()
    return _clean({"environment": reg.env, "manifest_created_utc": reg.manifest.get("created_utc"), "tasks": reg.status()})


__all__ = ["ArtifactError", "InputValidationError", "catalogue", "task_detail", "input_schema", "template_csv", "predict_frame",
           "read_csv_upload", "cohort_frame", "record_run", "history", "run_file", "forecasts", "forecast_history", "segmentation",
           "segmentation_assignments", "model_status", "registry"]
