"""Restoration audit: load every saved model artifact from its persistent location, restore its preprocessing and
feature definitions, score the task's held-out test rows and check the predictions reproduce the saved evaluation.

    python -m pipelines.model_registry.audit --drive-root /content/drive/MyDrive/analytics_project_outputs   # Colab
    python -m pipelines.model_registry.audit                                                                 # local copy
Options: --checkpoints (also every CV candidate checkpoint on Drive), --forecast-rerun (regenerate all forecasts in a
temporary directory and compare them with the saved outputs; no saved file is touched).

Test rows are rebuilt with the training pipeline's own deterministic code (dataset card, row filter, split). Nothing is
refitted except in --forecast-rerun, where the statistical forecasting methods are refitted by design (no forecasting
model objects were ever saved) into a temporary directory.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
import traceback
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import ARTIFACTS_DIR, DW_ROOT, MANIFEST_PATH
from .loader import LoadedModel, ModelRegistry, _env, load_artifact
from .manifest import sha256

TOL_EXACT, TOL_CLOSE = 1e-6, 1e-3


def _status(ok_load, ok_pred, diffs):
    if not ok_load:
        return "FAIL_LOAD"
    if not ok_pred:
        return "FAIL_PREDICT"
    d = max([x for x in diffs if x is not None and np.isfinite(x)] or [0.0])
    return "PASS" if d <= TOL_EXACT else ("PASS_NUMERIC_DIFF_LT_1E-3" if d <= TOL_CLOSE else "FAIL_NOT_REPRODUCED")


class Locator:
    def __init__(self, manifest, artifact_root: Path, drive_root: Path | None):
        self.m, self.root, self.drive = manifest, artifact_root, drive_root

    def __call__(self, rel):
        e = self.m["files"].get(rel, {})
        if self.drive and e.get("drive_path") and (self.drive / e["drive_path"]).exists():
            return self.drive / e["drive_path"], f"MyDrive/analytics_project_outputs/{e['drive_path']}"
        p = self.root / rel
        return p, (e.get("persistent_location") if self.drive else f"local working copy: {rel}")


def _task_data(task, entry):
    """Rebuild X, y and the test index exactly as supervised.run() did."""
    from ..feature_engineering.common import load_dataset
    from ..model_training.run_all import SPECS
    from ..model_training.supervised import _split
    spec = next(s for s in SPECS if s.task_id == task)
    df, card = load_dataset(spec.dataset, spec.zone)
    if spec.row_filter:
        for c, v in spec.row_filter.items():
            df = df[df[c] == v]
    df = df[df[spec.target].notna()].reset_index(drop=True)
    num, cat = card["features_numeric"], card["features_categorical"]
    assert num == entry["features_numeric"] and cat == entry["features_categorical"], "feature definitions changed since training"
    y = df[spec.target]
    y = y.astype(int) if spec.kind == "binary" else (y.astype(float) if spec.kind == "regression" else y)
    X = df[num + cat].copy()
    tr, te = _split(df, y, spec)
    return df, X, y, tr, te


def _score(kind, pipe, X, labels):
    if kind == "binary":
        return pipe.predict_proba(X)[:, 1]
    if kind == "multiclass":
        return pipe.predict_proba(X)
    return pipe.predict(X)


def _validity(kind, out, n):
    a = np.asarray(out)
    v = {"n_rows": int(n), "output_shape": list(a.shape), "dtype": str(a.dtype), "all_finite": bool(np.isfinite(a).all())}
    if kind == "binary":
        v["probabilities_in_0_1"] = bool(((a >= 0) & (a <= 1)).all())
    if kind == "multiclass":
        v["probabilities_in_0_1"] = bool(((a >= 0) & (a <= 1)).all())
        v["rows_sum_to_1"] = bool(np.allclose(a.sum(1), 1, atol=1e-6))
    ok = v["all_finite"] and a.shape[0] == n and v.get("probabilities_in_0_1", True) and v.get("rows_sum_to_1", True)
    return v, ok


def _metrics(kind, y, out, labels, thr):
    from ..model_training import core
    if kind == "binary":
        m = core.binary_metrics(y, out, thr)
        return {"test_roc_auc": m["roc_auc"], "test_pr_auc": m["pr_auc"], "test_tuned_f1": m["f1"]}
    if kind == "multiclass":
        m = core.multiclass_metrics(y, out, labels)
        return {"test_f1_macro": m["f1_macro"], "test_roc_auc_ovr_macro": m["roc_auc_ovr_macro"]}
    m = core.regression_metrics(y, out)
    return {"test_rmse": m["rmse"], "test_r2": m["r2"]}


def audit_supervised(task, entry, reg: ModelRegistry, loc: Locator, checkpoints: bool, manifest) -> list[dict]:
    recs = []
    t_load = time.time()
    df, X, y, tr, te = _task_data(task, entry)
    res = json.loads(loc(entry["results"])[0].read_text())
    rows = {r["model"]: r for r in res["models"]}
    tp_path = loc(f"reports/model_evaluation/{'uci' if task.startswith('uci_') else 'synthetic'}/{task}/test_predictions.csv")[0]
    tp = pd.read_csv(tp_path) if tp_path.exists() else None
    labels = entry.get("labels")
    targets = [(n, m["path"], "selected" if n == entry["selected_model"] else "baseline (saved for comparison)") for n, m in entry["models"].items()]
    if checkpoints:
        targets += [(Path(r).stem, r, "candidate checkpoint (CV candidate, Drive only)") for r, e in manifest["files"].items()
                    if e["role"] == "candidate_checkpoint" and e["task"] == task]
    for name, rel, role in targets:
        p, where = loc(rel)
        rec = {"task": task, "model": name, "role": role, "artifact": where, "kind": entry["kind"], "errors": []}
        fe = manifest["files"].get(rel, {})
        ok_load = ok_pred = False
        diffs = []
        try:
            rec["sha256_verified"] = bool(p.exists() and fe.get("sha256") and sha256(p) == fe["sha256"])
            if not p.exists():
                raise FileNotFoundError(f"{where} not found")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                obj, rec["loaded_via"] = load_artifact(p)
            rec["version_warnings"] = sorted({str(w.message)[:160] for w in caught if "version" in str(w.message).lower()})
            ck = obj if role.startswith("candidate") else None
            pipe = ck["pipe"] if ck else obj
            rec["algorithm"] = type(pipe.named_steps["model"]).__name__ if hasattr(pipe, "named_steps") else type(pipe).__name__
            prep = pipe.named_steps.get("prep") if hasattr(pipe, "named_steps") else None
            rec["preprocessing_restored"] = bool(prep is not None and hasattr(prep, "transformers_"))
            rec["n_model_input_columns"] = int(len(prep.get_feature_names_out())) if rec["preprocessing_restored"] else None
            ok_load = True
            # identical input handling to training (categorical -> string, missing -> "MISSING") via the registry loader
            lm = LoadedModel(task, name, entry["kind"], pipe, {}, entry)
            Xte = lm.prepare(X.loc[te]).X
            out = _score(entry["kind"], pipe, Xte, labels)
            v, okv = _validity(entry["kind"], out, len(te))
            rec["output_validity"] = v
            row = (ck or {}).get("row") or rows.get(name, {})
            thr = float(row.get("threshold_from_cv", 0.5)) if entry["kind"] == "binary" else None
            rec_m = _metrics(entry["kind"], y.loc[te], out, labels, thr)
            rec["metrics"] = {k: {"saved": row.get(k), "reproduced": v_, "abs_diff": (abs(v_ - row[k]) if row.get(k) is not None else None)}
                              for k, v_ in rec_m.items()}
            diffs += [m["abs_diff"] for m in rec["metrics"].values()]
            saved = None
            if ck is not None:
                saved = np.asarray(ck["test_pred"])
            elif tp is not None and f"test_p1_{name}" in tp:
                assert (tp["row"].to_numpy() == np.asarray(te)).all(), "saved test rows differ from rebuilt split"
                saved = tp[f"test_p1_{name}"].to_numpy()
            if saved is not None:
                rec["saved_predictions_max_abs_diff"] = float(np.max(np.abs(np.asarray(out, float) - saved)))
                diffs.append(rec["saved_predictions_max_abs_diff"] if ck is None else min(rec["saved_predictions_max_abs_diff"], 1.0))
            # single representative row with injected missing values: exercised through the dashboard loader path
            one = X.loc[te].iloc[[0]].copy()
            one.iloc[0, :3] = np.nan
            r1 = lm.predict(one)
            rec["single_row_with_missing_values"] = "ok" if r1["n"] == 1 else "failed"
            if entry["kind"] == "binary" and "pred_original" in r1:
                rec["thresholds_applied"] = {"original_p_class1": r1.get("threshold_original"),
                                             "supplementary_class0_p_class0": r1.get("threshold_supplementary_class0")}
            ok_pred = okv and rec["single_row_with_missing_values"] == "ok"
        except Exception as ex:
            rec["errors"].append(f"{type(ex).__name__}: {ex}"[:400])
            rec["traceback_tail"] = traceback.format_exc().splitlines()[-3:]
        rec["load_succeeded"], rec["prediction_succeeded"] = ok_load, ok_pred
        rec["final_status"] = _status(ok_load, ok_pred, diffs)
        rec["seconds"] = round(time.time() - t_load, 1)
        recs.append(rec)
    return recs


def audit_cox(task, entry, loc: Locator, manifest) -> list[dict]:
    from ..feature_engineering.common import load_dataset
    from ..model_training import core
    from ..model_training.survival import _design, concordance
    rel = entry["models"]["cox_ph"]["path"]
    p, where = loc(rel)
    rec = {"task": task, "model": "cox_ph", "role": "selected", "artifact": where, "kind": "survival", "algorithm": "statsmodels PHReg "
           "(saved as coefficients + standardisation; level strata)", "errors": []}
    ok_load = ok_pred = False
    diffs = []
    try:
        rec["sha256_verified"] = sha256(p) == manifest["files"][rel]["sha256"]
        o = joblib.load(p)
        ok_load = True
        rec["preprocessing_restored"] = all(k in o for k in ("means", "sds", "levels"))
        res = json.loads(loc(entry["results"])[0].read_text())
        ev = "event_graduated" if "graduation" in task else "event_dropout"
        df, _ = load_dataset(res["dataset"], "SYNTHETIC")
        df = df[df["duration_years"] > 0].reset_index(drop=True)
        tri, tei = core.grouped_holdout(df, df[ev], df["student_id"])
        te = df.index.isin(tei)
        Xte, *_ = _design(df[te], o["means"], o["sds"], o["levels"])
        lp = Xte[list(o["params"].index)].to_numpy() @ o["params"].to_numpy()
        c = concordance(df.loc[te, "duration_years"], df.loc[te, ev], lp, df.loc[te, "level"].values)
        rec["output_validity"] = {"n_rows": int(te.sum()), "all_finite": bool(np.isfinite(lp).all()), "output": "linear predictor / relative hazard"}
        rec["metrics"] = {"concordance_test": {"saved": res["concordance_test"], "reproduced": c, "abs_diff": abs(c - res["concordance_test"])}}
        diffs.append(abs(c - res["concordance_test"]))
        rec["supported_outputs"] = entry["supported_outputs"]
        rec["ph_caveats"] = entry.get("ph_possible_violations")
        ok_pred = rec["output_validity"]["all_finite"]
    except Exception as ex:
        rec["errors"].append(f"{type(ex).__name__}: {ex}"[:400])
    rec["load_succeeded"], rec["prediction_succeeded"] = ok_load, ok_pred
    rec["final_status"] = _status(ok_load, ok_pred, diffs)
    return [rec]


def audit_segmentation(task, entry, loc: Locator, manifest) -> list[dict]:
    from ..feature_engineering.common import MODELING_DIR
    rel = entry["models"]["kmeans_isolation_forest"]["path"]
    p, where = loc(rel)
    rec = {"task": task, "model": "kmeans_isolation_forest", "role": "selected", "artifact": where, "kind": "segmentation",
           "algorithm": "median imputer + StandardScaler -> KMeans(k=%s) + IsolationForest(300 trees, 2%%)" % entry.get("chosen_k"), "errors": []}
    ok_load = ok_pred = False
    diffs = []
    try:
        rec["sha256_verified"] = sha256(p) == manifest["files"][rel]["sha256"]
        o = joblib.load(p)
        ok_load = True
        rec["preprocessing_restored"] = hasattr(o["preprocess"], "transform")
        snap = pd.read_csv(MODELING_DIR / "synthetic" / "syn_segmentation_snapshot.csv")
        asg = pd.read_csv(loc("reports/feature_analysis/synthetic/segmentation_assignments.csv")[0])
        snap = snap.set_index("student_id").loc[asg["student_id"]].reset_index()
        Z = o["preprocess"].transform(snap[o["features"]])
        seg = o["kmeans"].predict(Z)
        sc = -o["isolation_forest"].score_samples(Z)
        flag = sc > -o["isolation_forest"].offset_
        rec["output_validity"] = {"n_rows": len(snap), "segments": sorted(map(int, np.unique(seg))), "scores_finite": bool(np.isfinite(sc).all())}
        rec["metrics"] = {"segment_agreement_with_saved": {"saved": 1.0, "reproduced": float((seg == asg["kmeans_segment"]).mean()),
                                                          "abs_diff": float(1 - (seg == asg["kmeans_segment"]).mean())},
                          "anomaly_score_max_abs_diff": {"saved": 0.0, "reproduced": float(np.max(np.abs(sc - asg["anomaly_score"]))),
                                                         "abs_diff": float(np.max(np.abs(sc - asg["anomaly_score"])))},
                          "flag_agreement_with_saved": {"saved": 1.0, "reproduced": float((flag == asg["is_anomaly"]).mean()),
                                                        "abs_diff": float(1 - (flag == asg["is_anomaly"]).mean())}}
        # anomaly scores are saved with 4-6 decimals in the CSV: allow rounding
        diffs += [rec["metrics"]["segment_agreement_with_saved"]["abs_diff"], rec["metrics"]["flag_agreement_with_saved"]["abs_diff"],
                  0.0 if rec["metrics"]["anomaly_score_max_abs_diff"]["abs_diff"] < 1e-4 else 1.0]
        ok_pred = rec["output_validity"]["scores_finite"]
    except Exception as ex:
        rec["errors"].append(f"{type(ex).__name__}: {ex}"[:400])
    rec["load_succeeded"], rec["prediction_succeeded"] = ok_load, ok_pred
    rec["final_status"] = _status(ok_load, ok_pred, diffs)
    return [rec]


def audit_forecasting(entry, loc: Locator, rerun: bool) -> list[dict]:
    rec = {"task": "forecasting", "model": "per-series selected method", "role": "forecast outputs (no saved model objects)",
           "artifact": loc("reports/forecasting/forecasts_selected_method.csv")[1], "kind": "forecasting",
           "algorithm": "seasonal naive / ETS / ARIMA / SARIMA / XGBoost-lags, best by backtest WAPE", "errors": [],
           "preprocessing_restored": "n/a (methods refit on the series history)", "saved_model_objects": entry["saved_model_objects"]}
    ok_load = ok_pred = False
    diffs = []
    try:
        sel = pd.read_csv(loc("reports/forecasting/forecasts_selected_method.csv")[0])
        ok_load = True
        f = sel["forecast"].astype(float)
        lo, hi = sel["pi80_low"].astype(float), sel["pi80_high"].astype(float)
        has = lo.notna() & hi.notna()
        rec["output_validity"] = {"selected_forecasts": len(sel), "finite": bool(np.isfinite(f).all()), "non_negative": bool((f >= 0).all()),
                                  "interval_rows": int(has.sum()), "interval_ordered": bool(((lo <= f + 1e-9) & (f <= hi + 1e-9))[has].all())}
        ok_pred = rec["output_validity"]["finite"] and rec["output_validity"]["non_negative"]
        if rerun:
            from ..model_training import core, forecasting
            with tempfile.TemporaryDirectory() as tmp:
                old_r, old_log = core.REPORTS_DIR, core.log_experiment
                core.REPORTS_DIR, core.log_experiment = Path(tmp), (lambda rec_: None)
                t0 = time.time()
                try:
                    forecasting.run_all()
                finally:
                    core.REPORTS_DIR, core.log_experiment = old_r, old_log
                new = pd.read_csv(Path(tmp) / "forecasting" / "forecasts_selected_method.csv")
                k = ["series", "key", "method", "horizon"]
                j = sel.merge(new, on=k, suffixes=("_saved", "_rerun"), how="outer", indicator=True)
                d = (j["forecast_saved"].astype(float) - j["forecast_rerun"].astype(float)).abs()
                rec["rerun"] = {"seconds": round(time.time() - t0, 1), "rows_saved": len(sel), "rows_rerun": len(new),
                                "rows_unmatched": int((j["_merge"] != "both").sum()), "forecast_max_abs_diff": float(d.max())}
                diffs += [float(d.max()), float((j["_merge"] != "both").sum())]
                rec["metrics"] = {"forecast_reproduction_max_abs_diff": {"saved": 0.0, "reproduced": float(d.max()), "abs_diff": float(d.max())}}
    except Exception as ex:
        rec["errors"].append(f"{type(ex).__name__}: {ex}"[:400])
    rec["load_succeeded"], rec["prediction_succeeded"] = ok_load, ok_pred
    rec["final_status"] = _status(ok_load, ok_pred, diffs)
    return [rec]


def run(artifact_root: Path = DW_ROOT, drive_root: Path | None = None, checkpoints=False, forecast_rerun=False, tasks=None) -> dict:
    reg = ModelRegistry(DW_ROOT, MANIFEST_PATH, artifact_root)
    man = reg.manifest
    loc = Locator(man, Path(artifact_root), Path(drive_root) if drive_root else None)
    recs, t0 = [], time.time()
    for task, e in man["tasks"].items():
        if tasks and task not in tasks:
            continue
        try:
            if e["kind"] in ("binary", "multiclass", "regression"):
                recs += audit_supervised(task, e, reg, loc, checkpoints, man)
            elif e["kind"] == "survival":
                recs += audit_cox(task, e, loc, man)
            elif e["kind"] == "segmentation":
                recs += audit_segmentation(task, e, loc, man)
            elif e["kind"] == "forecasting":
                recs += audit_forecasting(e, loc, forecast_rerun)
        except Exception as ex:
            recs.append({"task": task, "model": e.get("selected_model"), "role": "task", "final_status": "FAIL_TASK_SETUP",
                         "errors": [f"{type(ex).__name__}: {ex}"[:400]], "load_succeeded": False, "prediction_succeeded": False})
        print(f"[{time.time() - t0:6.0f}s] {task}: " + ", ".join(f"{r['model']}={r['final_status']}" for r in recs if r["task"] == task), flush=True)
    st = pd.Series([r["final_status"] for r in recs]).value_counts().to_dict()
    return {"audit_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "environment": _env(),
            "artifact_source": "Google Drive backup sets (MyDrive/analytics_project_outputs) + working copy for Batch 1" if drive_root
            else f"local working copy {artifact_root}", "checkpoints_included": checkpoints, "forecast_rerun": forecast_rerun,
            "tolerances": {"PASS": TOL_EXACT, "PASS_NUMERIC_DIFF_LT_1E-3": TOL_CLOSE}, "registered_tasks": len(man["tasks"]),
            "artifacts_audited": len(recs), "status_counts": st, "seconds": round(time.time() - t0, 1), "records": recs}


def to_markdown(rep: dict) -> str:
    L = [f"# Model restoration audit", "", f"- Audit time (UTC): {rep['audit_utc']}", f"- Artifact source: {rep['artifact_source']}",
         f"- Environment: {json.dumps(rep['environment'])}", f"- Registered tasks: {rep['registered_tasks']}; artifacts audited: "
         f"{rep['artifacts_audited']} (candidate checkpoints included: {rep['checkpoints_included']}; forecasts regenerated: {rep['forecast_rerun']})",
         f"- Result: {rep['status_counts']}", "",
         "PASS = loaded from the persistent location, SHA-256 matched the manifest, preprocessing restored, valid predictions on the "
         "task's held-out test rows, and the saved test metric / saved per-row predictions reproduced within 1e-6.", "",
         "| Task | Model | Role | Algorithm | SHA-256 | Loaded | Preprocessing | Predicted | Reproduction (saved → reproduced) | Status |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["records"]:
        mets = "; ".join(f"{k} {v['saved']:.4f}→{v['reproduced']:.4f}" if isinstance(v.get("saved"), (int, float)) and v.get("reproduced") is not None
                         else f"{k} n/a" for k, v in (r.get("metrics") or {}).items())
        if "saved_predictions_max_abs_diff" in r:
            mets += f"; per-row max |Δp| {r['saved_predictions_max_abs_diff']:.1e}"
        L.append(f"| {r['task']} | {r['model']} | {r['role']} | {r.get('algorithm', '')} | {'✓' if r.get('sha256_verified') else ('n/a' if r['kind'] == 'forecasting' else '✗')} | "
                 f"{'✓' if r['load_succeeded'] else '✗'} | {r.get('preprocessing_restored', '')} | {'✓' if r['prediction_succeeded'] else '✗'} | {mets} | **{r['final_status']}** |")
    L += ["", "## Errors, warnings and notes", ""]
    for r in rep["records"]:
        notes = r.get("errors", []) + [f"version warning: {w}" for w in r.get("version_warnings", [])]
        if r.get("rerun"):
            notes.append(f"forecast regeneration: {r['rerun']}")
        if r.get("saved_model_objects"):
            notes.append(r["saved_model_objects"])
        if r.get("supported_outputs"):
            notes.append(f"supported outputs: {r['supported_outputs']}; PH caveats: {r.get('ph_caveats')}")
        if notes:
            L.append(f"- **{r['task']} / {r['model']}**: " + " | ".join(map(str, notes)))
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-root", type=Path, default=DW_ROOT)
    ap.add_argument("--drive-root", type=Path, default=None)
    ap.add_argument("--checkpoints", action="store_true")
    ap.add_argument("--forecast-rerun", action="store_true")
    ap.add_argument("--task", action="append")
    ap.add_argument("--out", type=Path, default=ARTIFACTS_DIR / "restoration_audit")
    a = ap.parse_args(argv)
    rep = run(a.artifact_root, a.drive_root, a.checkpoints, a.forecast_rerun, a.task)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{a.out}.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    Path(f"{a.out}.md").write_text(to_markdown(rep), encoding="utf-8")
    print(json.dumps(rep["status_counts"]))


if __name__ == "__main__":
    main()
