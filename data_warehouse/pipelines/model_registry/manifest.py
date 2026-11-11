"""Build ``artifacts/artifact_manifest.json``: every registered task, its saved models, thresholds, features, evaluation
files and where each file is persisted (Google Drive backup set + SHA-256).

The manifest is built where the complete set of outputs exists (the Colab working copy with Drive mounted):
    python -m pipelines.model_registry.manifest --drive-root /content/drive/MyDrive/analytics_project_outputs
Values are read from the saved results; nothing is recomputed or retrained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import DW_ROOT, MANIFEST_PATH

ORIGINAL_ZIP_NOTE = ("No dedicated Drive backup set (Batch 1, trained before per-task Drive backups were introduced): persisted in the "
                     "local project and in the original Drive ZIP backups MyDrive/University-Institutional-Analytics-Dashboard*.zip")

# batch, dashboard module, meaning of class 1 (or of the prediction), short algorithm description
TASKS = {
    "uci_dropout_enrolment_time": (1, "academic_risk", "Dropout (UCI outcome) predicted at enrolment", "binary classifier"),
    "uci_outcome3_enrolment_time": (1, "academic_risk", "UCI outcome class (Dropout / Enrolled / Graduate) at enrolment", "multiclass classifier"),
    "uci_dropout_end_of_year1": (1, "academic_risk", "Dropout (UCI outcome) predicted at the end of year 1", "binary classifier"),
    "uci_outcome3_end_of_year1": (1, "academic_risk", "UCI outcome class (Dropout / Enrolled / Graduate) at end of year 1", "multiclass classifier"),
    "syn_dropout_2y": (1, "academic_risk", "Dropout (withdrawn/dismissed) recorded within 2 years after the term", "binary classifier"),
    "syn_next_term_gpa": (1, "academic_risk", "GPA of the next completed term (4-point demonstration scale)", "regressor"),
    "syn_next_term_academic_risk": (1, "academic_risk", "Next-term standing WARNING / PROBATION / DISMISSED", "binary classifier"),
    "syn_graduation_cox": (1, "graduation", "Relative hazard (rate) of graduating", "Cox proportional hazards (statsmodels PHReg, stratified by level)"),
    "syn_dropout_cox": (1, "academic_risk", "Relative hazard (rate) of dropout", "Cox proportional hazards (statsmodels PHReg, stratified by level)"),
    "syn_retention_fall_to_fall_institutional": (2, "retention", "Retained at the institution at the next Fall census", "binary classifier"),
    "syn_retention_fall_to_fall_programme": (2, "retention", "Retained in the same programme at the next Fall census", "binary classifier"),
    "syn_retention_spring_to_spring_institutional": (2, "retention", "Retained at the institution at the next Spring census", "binary classifier"),
    "syn_retention_spring_to_spring_programme": (2, "retention", "Retained in the same programme at the next Spring census", "binary classifier"),
    "syn_retention_summer_to_summer_institutional": (2, "retention", "Retained at the institution at the next Summer census (or next Fall)", "binary classifier"),
    "syn_retention_summer_to_summer_programme": (2, "retention", "Retained in the same programme at the next Summer census (or next Fall)", "binary classifier"),
    "syn_graduation_within_window": (3, "graduation", "Graduates within the window (UG 6, Master's 4, Doctorate 6 years)", "binary classifier"),
    "syn_admissions_offer": (3, "admissions", "Application receives an offer", "binary classifier"),
    "syn_admissions_accept": (3, "admissions", "Offer holder accepts the offer", "binary classifier"),
    "forecasting": (4, "forecasting", "Term headcount, admissions funnel and programme/course demand forecasts", "seasonal naive / ETS / ARIMA / SARIMA / XGBoost-lags"),
    "syn_segmentation": (5, "segmentation", "Student segment and anomaly score", "K-Means (k by silhouette) + Ward + Isolation Forest"),
}
COX = {"syn_graduation_cox", "syn_dropout_cox"}
SHARED = {"experiments/experiment_log.jsonl", "reports/model_evaluation/run_summary.json"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _posix(p: str) -> str:
    """Batch 1 results.json files were written on Windows and store model paths with backslashes."""
    return str(p).replace("\\", "/")


def role_of(rel: str) -> str:
    if rel.startswith("experiments/checkpoints/"):
        return "candidate_checkpoint"
    if rel.startswith("experiments/"):
        return "log"
    if rel.startswith("models/"):
        return "model_metadata" if rel.endswith(".meta.json") else "model"
    if rel.endswith(".png"):
        return "figure"
    if rel.startswith("reports/forecasting/"):
        return "forecast_output"
    if rel.endswith(("results.json", "segmentation_results.json")) or rel.endswith("run_summary.json"):
        return "evaluation"
    if rel.endswith(("test_predictions.csv", "oof_predictions.csv")):
        return "predictions"
    if rel.startswith("reports/feature_analysis/"):
        return "feature_importance" if "segmentation" not in rel and "anomaly" not in rel else "segmentation_output"
    return "evaluation"


REQUIRED_ROLES = {"model", "model_metadata", "evaluation", "feature_importance", "figure", "forecast_output", "segmentation_output"}


def _files_of(task: str, dw: Path) -> list[str]:
    pats = {"forecasting": ["reports/forecasting/*"],
            "syn_segmentation": ["reports/feature_analysis/synthetic/segmentation_*", "reports/feature_analysis/synthetic/anomaly_*",
                                 "models/synthetic/segmentation/*"]}.get(task)
    if pats is None:
        z = "uci" if task.startswith("uci_") else "synthetic"
        pats = [f"models/{z}/{task}/*", f"reports/model_evaluation/{z}/{task}/*", f"reports/feature_analysis/{z}/{task}_*"]
    out = []
    for p in pats:
        out += [str(f.relative_to(dw)).replace("\\", "/") for f in dw.glob(p) if f.is_file() and "_superseded" not in str(f)]
    return sorted(set(out))


def _thresholds(row: dict, kind: str) -> dict:
    if kind != "binary":
        return {}
    t = {"original_p_class1": float(row["threshold_from_cv"]),
         "original_rule": "predict class 1 when P(class 1) >= threshold; threshold maximises F1 of class 1 on CV out-of-fold predictions"}
    s0 = row.get("supplementary_class0")
    if isinstance(s0, dict) and "threshold_class0" in s0:
        t.update({"supplementary_class0_p_class0": float(s0["threshold_class0"]),
                  "supplementary_rule": "SUPPLEMENTARY (added after the original evaluation): predict class 0 when P(class 0) >= threshold; "
                                        "threshold maximises F1 of class 0 on CV out-of-fold predictions"})
    return t


def _metric_subset(row: dict, kind: str) -> dict:
    keys = {"binary": ["cv_pr_auc", "cv_roc_auc", "test_roc_auc", "test_pr_auc", "test_brier", "test_tuned_precision", "test_tuned_recall",
                       "test_tuned_f1", "test_tuned_accuracy"],
            "multiclass": ["cv_pr_auc_macro", "test_accuracy", "test_f1_macro", "test_roc_auc_ovr_macro", "test_pr_auc_macro"],
            "regression": ["cv_rmse", "test_rmse", "test_mae", "test_r2"]}[kind]
    out = {k: row[k] for k in keys if k in row}
    s0 = row.get("supplementary_class0")
    if isinstance(s0, dict) and "test_at_class0_threshold" in s0:
        out["supplementary_test_at_class0_threshold"] = s0["test_at_class0_threshold"]
        out["supplementary_test_at_original_threshold"] = s0.get("test_at_original_threshold")
    return out


def build(dw: Path = DW_ROOT, drive_root: Path | None = None) -> dict:
    drive = {}
    if drive_root and Path(drive_root).exists():
        for d in sorted(Path(drive_root).iterdir()):
            mf = d / "backup_manifest.json"
            if d.is_dir() and mf.exists():
                drive[d.name] = json.loads(mf.read_text())
    summary = json.loads((dw / "reports/model_evaluation/run_summary.json").read_text())

    def locate(rel: str, task: str):
        cands = [s for s, m in drive.items() if rel in m]
        if not cands:
            return None
        if rel in SHARED:                          # the most recent copy is in the last batch's set
            s = "syn_segmentation" if "syn_segmentation" in cands else cands[-1]
        else:
            s = task if task in cands else cands[0]
        return {"backup_set": s, "drive_path": f"{s}/{rel}", "sha256": drive[s][rel]["sha256"], "bytes": drive[s][rel]["bytes"]}

    tasks, files = {}, {}
    for task, (batch, module, meaning, algo) in TASKS.items():
        st = summary["tasks"].get(task, {})
        rels = _files_of(task, dw)
        entry = {"batch": batch, "module": module, "prediction_meaning": meaning, "algorithm_family": algo,
                 "status": st.get("status", "NOT_IN_RUN_SUMMARY"), "files": rels}
        if task == "forecasting":
            r = json.loads((dw / "reports/forecasting/forecasting_results.json").read_text())
            entry.update({"kind": "forecasting", "zone": "SYNTHETIC", "results": "reports/forecasting/forecasting_results.json",
                          "saved_model_objects": "none: statistical methods are refitted on the full history at forecast time; the "
                                                 "forecast CSV outputs are the persisted artifacts",
                          "best_method_by_series": r.get("best_method_by_series")})
        elif task == "syn_segmentation":
            r = json.loads((dw / "reports/feature_analysis/synthetic/segmentation_results.json").read_text())
            entry.update({"kind": "segmentation", "zone": "SYNTHETIC", "results": "reports/feature_analysis/synthetic/segmentation_results.json",
                          "selected_model": "kmeans_isolation_forest", "chosen_k": r["chosen_k"], "features": r["features"],
                          "models": {"kmeans_isolation_forest": {"path": "models/synthetic/segmentation/kmeans_isolation_forest.joblib",
                                                                 "meta": "models/synthetic/segmentation/kmeans_isolation_forest.meta.json"}},
                          "anomaly_threshold_score": r.get("anomaly_diagnostics", {}).get("threshold_score")})
        elif task in COX:
            res_p = f"reports/model_evaluation/synthetic/{task}/results.json"
            r = json.loads((dw / res_p).read_text())
            entry.update({"kind": "survival", "zone": "SYNTHETIC", "dataset": r["dataset"], "results": res_p, "selected_model": "cox_ph",
                          "covariates": r["covariates"], "concordance_test": r["concordance_test"],
                          "ph_possible_violations": r.get("ph_possible_violations", []),
                          "supported_outputs": "linear predictor / relative hazard per student (baseline hazard not saved, so absolute "
                                               "survival curves are not available from the saved artifact)",
                          "models": {"cox_ph": {"path": _posix(r["saved_models"]["cox_ph"]), "meta": _posix(r["saved_models"]["cox_ph"]).replace(".joblib", ".meta.json")}}})
        else:
            z = "uci" if task.startswith("uci_") else "synthetic"
            res_p = f"reports/model_evaluation/{z}/{task}/results.json"
            r = json.loads((dw / res_p).read_text())
            rows = {m["model"]: m for m in r["models"]}
            best = r["best_model"]
            entry.update({"kind": r["kind"], "zone": r["zone"], "dataset": r["dataset"], "target": r["target"], "row_filter": r.get("row_filter"),
                          "results": res_p, "selected_model": best, "selection_rule": r.get("selection_rule"),
                          "features_numeric": r["features_numeric"], "features_categorical": r["features_categorical"],
                          "labels": rows[best].get("labels"), "thresholds": _thresholds(rows[best], r["kind"]),
                          "test_metrics_selected": _metric_subset(rows[best], r["kind"]),
                          "candidates_evaluated": [m["model"] for m in r["models"]],
                          "models": {n: {"path": _posix(p), "meta": _posix(p).replace(".joblib", ".meta.json"),
                                         "thresholds": _thresholds(rows[n], r["kind"]) if n in rows else {}}
                                     for n, p in r["saved_models"].items()}})
        tasks[task] = entry
        for rel in rels + ([*SHARED] if task == "syn_segmentation" else []):
            loc = locate(rel, task)
            p = dw / rel
            local_sha = sha256(p) if p.exists() else None
            files[rel] = {"role": role_of(rel), "task": task if rel not in SHARED else "shared",
                          "required_for_dashboard": role_of(rel) in REQUIRED_ROLES,
                          "sha256": loc["sha256"] if loc else local_sha, "bytes": loc["bytes"] if loc else (p.stat().st_size if p.exists() else None),
                          "drive_backup_set": loc["backup_set"] if loc else None, "drive_path": loc["drive_path"] if loc else None,
                          "persistent_location": f"MyDrive/analytics_project_outputs/{loc['drive_path']}" if loc else ORIGINAL_ZIP_NOTE,
                          "working_copy_matches_backup": (local_sha == loc["sha256"]) if loc and local_sha else None}
    # candidate checkpoints (all CV candidates of Batch 2-3 tasks) exist only on Drive
    for s, m in drive.items():
        for rel, e in m.items():
            if rel.startswith("experiments/checkpoints/") and rel not in files:
                files[rel] = {"role": "candidate_checkpoint", "task": rel.split("/")[2], "required_for_dashboard": False,
                              "sha256": e["sha256"], "bytes": e["bytes"], "drive_backup_set": s, "drive_path": f"{s}/{rel}",
                              "persistent_location": f"MyDrive/analytics_project_outputs/{s}/{rel}", "working_copy_matches_backup": None}
    man = {"manifest_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "drive_root": "MyDrive/analytics_project_outputs", "drive_backup_sets": {s: len(m) for s, m in drive.items()},
            "registered_tasks": len(tasks), "label": "Models trained on SYNTHETIC demonstration data or the public UCI dataset; "
                                                     "not validated for decisions about real students.",
            "tasks": tasks, "files": dict(sorted(files.items()))}
    if drive_root and (Path(drive_root) / PORTABLE_SET / "portable_xgboost").exists():
        found = {}
        for f in sorted((Path(drive_root) / PORTABLE_SET / "portable_xgboost").glob("*/*")):
            found[f"models/synthetic/{f.parent.name}/{f.name}"] = (sha256(f), f.stat().st_size)
        add_portable_exports(man, found)
    return man


PORTABLE_SET = "_final_restoration_and_dashboard"


def add_portable_exports(man: dict, found: dict) -> dict:
    """Register the portable XGBoost exports (Booster.save_model JSON + booster-free sklearn wrapper) made in the final
    stage from the ORIGINAL saved models (no retraining; predictions verified identical). They are new files in a new
    Drive folder; the original artifacts and backup sets are untouched. found: {rel_path: (sha256, bytes)}."""
    for rel, (h, n) in found.items():
        task = rel.split("/")[2]
        man["files"][rel] = {"role": "model_portable_export", "task": task, "required_for_dashboard": True, "sha256": h, "bytes": n,
                             "drive_backup_set": PORTABLE_SET, "drive_path": f"{PORTABLE_SET}/portable_xgboost/{task}/{rel.split('/')[-1]}",
                             "persistent_location": f"MyDrive/analytics_project_outputs/{PORTABLE_SET}/portable_xgboost/{task}/{rel.split('/')[-1]}",
                             "working_copy_matches_backup": None, "derived_from": rel.rsplit("/", 1)[0] + "/xgboost.joblib",
                             "reason": "the original pickle's internal XGBoost serialisation does not load on the Windows XGBoost build"}
        m = man["tasks"].get(task, {}).get("models", {}).get("xgboost")
        if m is not None:
            m.setdefault("portable_export", {})["booster_json" if rel.endswith(".json") else "sklearn_wrapper"] = rel
    man["files"] = dict(sorted(man["files"].items()))
    return man


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive-root", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=MANIFEST_PATH)
    a = ap.parse_args(argv)
    m = build(DW_ROOT, a.drive_root)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(m, indent=1, default=str), encoding="utf-8")
    print(f"manifest: {len(m['tasks'])} tasks, {len(m['files'])} files -> {a.out}")


if __name__ == "__main__":
    main()
