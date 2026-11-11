"""Run every experiment.  From data_warehouse:  python -m pipelines.model_training.run_all [--only TASK ...] [--skip-forecasting]

--only accepts supervised/Cox task ids plus "syn_segmentation" and "forecasting", so a run can be resumed in small batches.
The run summary is merged into reports/model_evaluation/run_summary.json after EVERY task, so an interrupted run keeps
the results of the tasks it finished.

SAFETY: tasks already recorded as completed (status TRAINED / TRAINED_WITH_PH_CAVEATS) in run_summary.json are SKIPPED by
default, so re-running this script never retrains or overwrites a finished model. To deliberately retrain a task, name it
with --retrain TASK (this overwrites that task's saved models and reports; back them up first).

Zone A (UCI) and Zone B (synthetic) are trained separately; no model ever sees both.
"""
from __future__ import annotations

import argparse
import gc
import json
import time
import traceback

from . import core
from .supervised import CLASSIFIERS, REGRESSORS, LeakageError, TaskSpec, run

SMALL = ["baseline_majority", "logistic_regression", "random_forest", "xgboost"]
OOT_DROP, OOT_PERF = "2022-07-01", "2023-07-01"

SPECS: list[TaskSpec] = [
    # ---------------------------------------------------------------- Zone A: UCI research models (original targets unchanged)
    TaskSpec("uci_dropout_enrolment_time", "uci_enrolment_time", "UCI", "target_dropout", "binary", CLASSIFIERS, None, split="stratified",
             title="UCI dropout vs not (enrolment-time features)"),
    TaskSpec("uci_outcome3_enrolment_time", "uci_enrolment_time", "UCI", "target_3class", "multiclass", CLASSIFIERS, None, split="stratified",
             title="UCI Graduate / Dropout / Enrolled (enrolment-time features)"),
    TaskSpec("uci_dropout_end_of_year1", "uci_end_of_year1", "UCI", "target_dropout", "binary", CLASSIFIERS, None, split="stratified",
             title="UCI dropout vs not (end of first year)"),
    TaskSpec("uci_outcome3_end_of_year1", "uci_end_of_year1", "UCI", "target_3class", "multiclass", CLASSIFIERS, None, split="stratified",
             title="UCI Graduate / Dropout / Enrolled (end of first year)"),
    # ---------------------------------------------------------------- Zone B: synthetic demonstration models
    TaskSpec("syn_dropout_2y", "syn_dropout_2y", "SYNTHETIC", "target_dropout_2y", "binary", CLASSIFIERS, oot_cutoff=OOT_DROP,
             subgroup_cols=["level", "term_season", "is_first_term"], title="Synthetic dropout within 2 years"),
    TaskSpec("syn_next_term_gpa", "syn_next_term_performance", "SYNTHETIC", "target_next_term_gpa", "regression", REGRESSORS,
             oot_cutoff=OOT_PERF, persistence_baseline="term_gpa", title="Synthetic next-term GPA"),
    TaskSpec("syn_next_term_academic_risk", "syn_next_term_performance", "SYNTHETIC", "target_next_term_at_risk", "binary", CLASSIFIERS,
             oot_cutoff=OOT_PERF, subgroup_cols=["level"], title="Synthetic next-term academic risk (WARNING/PROBATION/DISMISSED)"),
]
for ct in ("FALL_TO_FALL", "SPRING_TO_SPRING", "SUMMER_TO_SUMMER"):
    for tgt in ("institutional", "programme"):
        SPECS.append(TaskSpec(f"syn_retention_{ct.lower()}_{tgt}", "syn_retention", "SYNTHETIC", f"target_{tgt}", "binary", SMALL,
                              row_filter={"comparison_type": ct}, oot_cutoff=OOT_PERF, subgroup_cols=["level", "is_first_term"],
                              title=f"Synthetic {ct.replace('_', ' ').title()} {tgt} retention"))
SPECS += [
    TaskSpec("syn_graduation_within_window", "syn_graduation_within_window", "SYNTHETIC", "target_grad_within_window", "binary", SMALL,
             subgroup_cols=["level"], title="Synthetic graduation within window (mature cohorts)"),
    TaskSpec("syn_admissions_offer", "syn_admissions_offer", "SYNTHETIC", "target_offer", "binary", SMALL, group_col="applicant_id",
             split="chronological", chrono_col="entry_academic_year_start", chrono_test_from=2025, subgroup_cols=["level"],
             title="Synthetic application -> offer"),
    TaskSpec("syn_admissions_accept", "syn_admissions_accept", "SYNTHETIC", "target_accept", "binary", SMALL, group_col="applicant_id",
             split="chronological", chrono_col="entry_academic_year_start", chrono_test_from=2025, subgroup_cols=["level"],
             title="Synthetic offer -> acceptance"),
]
COX = [("syn_graduation_cox", "syn_graduation_survival", "event_graduated", "Synthetic time to graduation"),
       ("syn_dropout_cox", "syn_dropout_survival", "event_dropout", "Synthetic time to dropout")]


COMPLETED_STATUSES = ("TRAINED", "TRAINED_WITH_PH_CAVEATS")


def completed_tasks(summary_path) -> dict:
    """task_id -> status for tasks already finished according to run_summary.json."""
    try:
        tasks = json.loads(summary_path.read_text()).get("tasks", {})
    except (FileNotFoundError, ValueError):
        return {}
    return {k: v.get("status") for k, v in tasks.items() if v.get("status") in COMPLETED_STATUSES}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--skip-forecasting", action="store_true")
    ap.add_argument("--skip-supervised", action="store_true")
    ap.add_argument("--retrain", nargs="*", default=[], help="explicitly retrain these COMPLETED tasks (overwrites their artifacts)")
    a = ap.parse_args(argv)
    t0 = time.time()
    summary = {"label_synthetic": core.SYN_BANNER, "label_uci": core.UCI_BANNER, "environment": core.env_info(), "tasks": {}}
    out = core.report_dir("model_evaluation")
    prev = out / "run_summary.json"
    done = completed_tasks(prev)
    skipped = []

    def should_run(task_id):
        if a.only and task_id not in a.only:
            return False
        if task_id in done and task_id not in a.retrain:
            skipped.append(task_id)
            print(f"SKIP {task_id}: already completed ({done[task_id]}); use --retrain {task_id} to overwrite", flush=True)
            return False
        return True

    def save():
        """Merge this run's task results into the saved summary (earlier tasks are kept)."""
        cur = {**summary, "seconds": round(time.time() - t0, 1)}
        if prev.exists():
            old = json.loads(prev.read_text())
            tasks = {**old.get("tasks", {}), **cur["tasks"]}
            cur = {**old, "tasks": tasks, "last_partial_run": {k: v for k, v in cur.items() if k != "tasks"} | {"tasks": list(summary["tasks"])}}
        core.write_json(cur, prev)
        gc.collect()
        return cur

    def started(task_id):
        """Recorded before a task runs and replaced when it finishes, so a killed process leaves an honest status."""
        summary["tasks"][task_id] = {"status": "INTERRUPTED", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                     "note": "task started but did not finish (process stopped); see its log"}
        save()

    def mem():
        try:
            import psutil
            mi = psutil.Process().memory_info()
            return {"peak_working_set_mb": round(getattr(mi, "peak_wset", mi.rss) / 2**20),
                    "system_available_mb": round(psutil.virtual_memory().available / 2**20)}
        except Exception:
            return {}
    if not a.skip_supervised:
        for s in SPECS:
            if not should_run(s.task_id):
                continue
            print(f"[{time.time() - t0:7.0f}s] {s.task_id}", flush=True)
            started(s.task_id)
            try:
                r = run(s)
                summary["tasks"][s.task_id] = {"status": r["status"], "best_model": r["best_model"], "n_rows": r["n_rows"],
                                               "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **mem()}
                if r.get("shap_error"):
                    summary["tasks"][s.task_id]["shap_error"] = r["shap_error"]
                if r.get("checkpoints_reused"):
                    summary["tasks"][s.task_id]["checkpoints_reused"] = r["checkpoints_reused"]
            except LeakageError as e:
                summary["tasks"][s.task_id] = {"status": "BLOCKED_BY_LEAKAGE_CHECK", "error": str(e)}
            except Exception as e:  # reported, not hidden
                summary["tasks"][s.task_id] = {"status": "FAILED", "error": repr(e), "trace": traceback.format_exc()}
                print(traceback.format_exc(), flush=True)
            save()
        from .survival import run_cox
        for c in COX:
            if not should_run(c[0]):
                continue
            print(f"[{time.time() - t0:7.0f}s] {c[0]}", flush=True)
            started(c[0])
            try:
                r = run_cox(*c)
                summary["tasks"][c[0]] = {"status": r["status"], "best_model": "cox_ph", "n_rows": r["n_rows"],
                                          "concordance_test": r["concordance_test"], **mem()}
            except Exception as e:
                summary["tasks"][c[0]] = {"status": "FAILED", "error": repr(e), "trace": traceback.format_exc()}
                print(traceback.format_exc(), flush=True)
            save()
        if should_run("syn_segmentation"):
            from .segmentation import run as seg
            print(f"[{time.time() - t0:7.0f}s] segmentation", flush=True)
            started("syn_segmentation")
            try:
                r = seg()
                summary["tasks"]["syn_segmentation"] = {"status": "TRAINED", "chosen_k": r["chosen_k"], **mem()}
            except Exception as e:
                summary["tasks"]["syn_segmentation"] = {"status": "FAILED", "error": repr(e), "trace": traceback.format_exc()}
                print(traceback.format_exc(), flush=True)
            save()
    if not a.skip_forecasting and should_run("forecasting"):
        from .forecasting import run_all as fc
        print(f"[{time.time() - t0:7.0f}s] forecasting", flush=True)
        started("forecasting")
        try:
            r = fc()
            summary["tasks"]["forecasting"] = {"status": "TRAINED", "seconds": r["seconds"],
                                               "fit_failures": r.get("fit_failures", {}).get("count"), **mem()}
        except Exception as e:
            summary["tasks"]["forecasting"] = {"status": "FAILED", "error": repr(e), "trace": traceback.format_exc()}
            print(traceback.format_exc(), flush=True)
    if not summary["tasks"]:
        print(f"nothing to train: {len(skipped)} completed task(s) skipped; run_summary.json left unchanged", flush=True)
        return json.loads(prev.read_text()) if prev.exists() else summary
    summary = save()
    print(json.dumps({k: v.get("status") for k, v in summary["tasks"].items()}, indent=1))
    return summary


if __name__ == "__main__":
    main()
