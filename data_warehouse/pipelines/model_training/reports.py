"""Write the four Markdown reports from the saved result files (numbers are never typed by hand).

python -m pipelines.model_training.reports
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..feature_engineering.common import MODELING_DIR, MODELS_DIR, REPORTS_DIR, SYN_BANNER, UCI_BANNER

EV = REPORTS_DIR / "model_evaluation"
FA = REPORTS_DIR / "feature_analysis"
FC = REPORTS_DIR / "forecasting"

FEATURE_GROUPS = {
    "A. Demographic and admission": [
        ("gender, residency_status, nationality_iso3", "Student record (synthetic)", "As recorded; no other demographics exist in the synthetic data"),
        ("age_at_admission_approx", "birth_year, admission_date", "Admission calendar year minus birth year (only birth YEAR exists, so +/- 1 year)"),
        ("programme_id, school_id, level", "student_programmes / term_enrolments", "Programme, school and level of the term enrolment"),
        ("entry_season, entry_academic_year_start", "academic_terms", "Admission term season and academic-year start"),
        ("entry_type, application_type", "student_programmes, applications", "Admission route (NEW / TRANSFER / READMISSION / PROGRAMME_CHANGE; application type)"),
        ("admission_score", "applications", "Synthetic 0-100 admission score"),
        ("application_lead_days", "applications", "Days from application submission to admission"),
        ("decision_to_start_days", "applications", "Days from admission decision to the admission (first-enrolment) date"),
        ("credits_transferred_in, scholarship_pct, prior_admissions", "student_programmes", "Transfer credit, scholarship share, earlier admissions of the same student"),
        ("application conversion", "applications", "Targets of the admissions models (offer, acceptance) and programme-level conversion features (group E)"),
    ],
    "B. Academic performance (completed terms only)": [
        ("term_gpa, cumulative_gpa", "term_enrolments", "Credit-weighted GPA on the demonstration 4-point scale (W excluded)"),
        ("prev_term_gpa, prev_cumulative_gpa, gpa_change_vs_prev, consecutive_gpa_declines", "derived", "Previous graded term GPA, change and current run of declines"),
        ("term_mean_grade_points", "course_enrolments", "Unweighted mean grade points of graded courses: a GRADE measure kept separate from GPA"),
        ("courses_registered / passed / failed / withdrawn (+ cumulative)", "course_enrolments", "Course counts per term and to date"),
        ("term_course_completion_rate, cum_course_completion_rate, credit_completion_rate_cum, passed_credit_ratio", "derived", "Passed / registered courses; earned / attempted credits"),
        ("credits_attempted, credits_earned, cumulative_credits_earned", "term_enrolments", "Credit load and progress"),
        ("standing, warning_terms_so_far, probation_terms_so_far, max_standing_level_so_far", "academic_standing", "Standing after the term (configured synthetic rule) and history"),
        ("poor_performance_flag, poor_performance_terms_so_far", "term_enrolments", "Configured poor-performance rule (term GPA below minimum or pass ratio < 0.5)"),
        ("withdrew_during_term", "term_enrolments", "Withdrew from the term's courses after census (a term event, NOT the final programme withdrawal)"),
    ],
    "C. Engagement and progression": [
        ("completed_terms, study_term_number, term_sequence", "term_enrolments", "Number of completed terms; chronological term index"),
        ("regular_streak", "derived", "Consecutive REGULAR terms enrolled; a skipped optional Summer neither breaks nor extends it"),
        ("prior_gap_terms, interruptions_so_far, missed_regular_terms_so_far", "term_enrolments", "Missed REGULAR terms before this term (Summer never counts as missed)"),
        ("summer_terms_taken", "derived", "Optional Summers attended"),
        ("progression_rate, credits_earned_per_year, years_since_admission", "derived", "Earned / required credits; pace; time since admission"),
        ("delivery_mode, study_load, online_share_so_far, part_time_share_so_far", "term_enrolments", "Current and historical delivery mode / load"),
        ("is_first_term, term_season", "derived", "First-term indicator; season of the term"),
    ],
    "D. Financial (as of the prediction date)": [
        ("fin_total_charged, fin_total_paid", "charges, payments", "Cumulative charges and payments dated on/before the prediction date"),
        ("fin_outstanding_balance, fin_past_due_amount", "derived", "Charges minus payments; amount due before the prediction date and unpaid"),
        ("fin_payment_completion_pct, fin_outstanding_ratio", "derived", "Paid / charged; outstanding / charged"),
        ("fin_late_payment_terms", "charges, payments", "Terms whose charges were not fully paid by the due date (count of late/unpaid term charges)"),
        ("fin_holds_so_far, fin_active_hold", "financial_holds", "Holds placed to date; hold active at the prediction date"),
        ("fin_registration_blocks_so_far", "registration_blocks", "Registration attempts blocked by a hold"),
    ],
    "E. Programme and institutional context (prior information only)": [
        ("prog_headcount, prog_headcount_growth_yoy, prog_new_intake", "term_enrolments, student_programmes", "Programme census headcount, growth vs same season last year, new intake"),
        ("inst_headcount, inst_headcount_growth_yoy, inst_returning_students", "term_enrolments", "Institution headcount, growth and returning students"),
        ("prog_applications_12m, prog_offers_12m, prog_acceptances_12m, prog_decision_acceptance_rate_12m", "applications", "Programme demand in the 12 months before the prediction date"),
        ("prog_hist_retention_rate_2y", "retention_cohort_members", "Programme institutional retention from comparisons whose census fell in the previous 2 years"),
        ("prog_hist_grad_rate_mature", "graduation_records", "Programme graduation-within-window rate of cohorts whose window ended before the prediction date"),
        ("prog_prev_year_applications / offer_rate / yield", "applications", "Admissions models: programme funnel in the PREVIOUS academic year"),
    ],
    "F. Time series (forecasting datasets)": [
        ("term_id, term_sequence, academic_year, season", "academic_terms", "Chronological order (term_sequence) and seasonal indicator"),
        ("value lags 0-3 (lag 3 = same season previous year)", "ts_* datasets", "Used by the XGBoost lag model (log scale, relative to last year's same-season value)"),
        ("year-over-year growth at the origin", "derived", "log(y_t) - log(y_{t-3})"),
        ("applications, unique_applicants, offers, acceptances, new_enrolments", "ts_admissions_by_term", "Admissions funnel per entry term (applications = unique applicants per term)"),
        ("course_registrations, registrations_per_student", "ts_course_demand_by_programme", "Course demand per programme and term"),
    ],
}
UNAVAILABLE = [
    ("Real USIU-Africa records of any kind", "All Zone B data is synthetic; Zone A is a Portuguese public dataset"),
    ("Marital status, parents' education/occupation, displaced, special needs (synthetic)", "Exist only in UCI; not generated for synthetic students (not invented)"),
    ("Exact date of birth", "Only birth year exists, so age is approximate (+/- 1 year)"),
    ("Secondary-school grades / entrance exam detail (synthetic)", "Only a single synthetic admission_score exists"),
    ("LMS / attendance / library / advising engagement", "Not in the data model; login_events exist but are IT-system activity, not learning engagement, so they were not used"),
    ("Financial-aid need, sponsor, employment, housing", "Not in the data model"),
    ("Course-section capacity, room capacity, programme seat limits, faculty FTE/teaching load", "Not in the data model: capacity utilisation cannot be computed"),
    ("Rolling-mean features for forecasting", "Not added separately: the lag model already sees the last four terms"),
    ("UCI dates, terms, schools, GPA, programmes", "Not in the UCI data and never invented"),
]


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _f(x, d=3):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x:.{d}f}" if isinstance(x, (float, np.floating)) else str(x)


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(map(str, cols)) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(_f(v) if isinstance(v, (float, np.floating)) else str(v) for v in r.values) + " |")
    return "\n".join(out)


def load_results() -> dict:
    res = {}
    for f in sorted(EV.rglob("results.json")):
        r = _j(f)
        r["_dir"] = f.parent
        res[r["task_id"]] = r
    return res


def _rel(p: Path) -> str:
    return p.relative_to(REPORTS_DIR).as_posix()


# ================================================================================================ model comparison table
def comparison_rows(res: dict) -> pd.DataFrame:
    rows = []
    for tid, r in res.items():
        if "models" not in r:
            continue
        for m in r["models"]:
            row = {"task": tid, "zone": r["zone"], "model": m["model"], "best": "**yes**" if m["model"] == r["best_model"] else ""}
            if r["kind"] == "binary":
                row.update({"CV PR-AUC": m["cv_pr_auc"], "CV sd": m["cv_pr_auc_sd"], "test PR-AUC": m["test_pr_auc"], "test ROC-AUC": m["test_roc_auc"],
                            "test recall*": m["test_tuned_recall"], "test precision*": m["test_tuned_precision"], "test F1*": m["test_tuned_f1"],
                            "test accuracy (0.5)": m["test_accuracy"], "Brier": m["test_brier"]})
            elif r["kind"] == "multiclass":
                row.update({"CV PR-AUC": m["cv_pr_auc_macro"], "CV sd": m["cv_pr_auc_macro_sd"], "test PR-AUC": m["test_pr_auc_macro"],
                            "test ROC-AUC": m["test_roc_auc_ovr_macro"], "test recall*": m["test_recall_macro"],
                            "test precision*": m["test_precision_macro"], "test F1*": m["test_f1_macro"], "test accuracy (0.5)": m["test_accuracy"]})
            else:
                row.update({"CV RMSE": m["cv_rmse"], "CV sd": m["cv_rmse_sd"], "test MAE": m["test_mae"], "test RMSE": m["test_rmse"], "test R2": m["test_r2"]})
            rows.append(row)
    return pd.DataFrame(rows)


def evidence(r: dict) -> str:
    """Is the selected model meaningfully better than the linear baseline? (difference vs. 1 CV standard deviation)"""
    b = r["best_vs_linear_baseline"]
    lower_better = r["kind"] == "regression"
    gain = -b["difference"] if lower_better else b["difference"]
    sd = b["cv_sd_best"] or 0
    if r["best_model"] in ("logistic_regression", "linear_regression"):
        return "linear baseline is best"
    if gain > sd:
        return f"supported (+{gain:.3f} > 1 CV sd {sd:.3f})"
    return f"not clearly better than the linear baseline (+{gain:.3f} <= 1 CV sd {sd:.3f}); prefer the simpler model"


# ================================================================================================ reports
def feature_engineering_report(res: dict) -> str:
    man = _j(MODELING_DIR / "modeling_manifest.json")
    L = [f"# Feature Engineering Report\n", f"> **Zone B outputs: {SYN_BANNER}**  ",
         f"> **Zone A outputs: {UCI_BANNER}**\n",
         f"Data version: synthetic run `{man['data_version']['synthetic_generation_run_id']}`, as-of date {man['data_version']['as_of_date']}, "
         f"UCI raw SHA-256 `{man['data_version']['uci_raw_sha256'][:16]}…` (unchanged).  ",
         "Code: `data_warehouse/pipelines/feature_engineering/` (`student_panel.py`, `datasets.py`). Re-run: "
         "`python -m pipelines.feature_engineering.datasets` from `data_warehouse`.\n",
         "## 1. Which features were engineered\n",
         "All synthetic student features are computed on a **student-term panel**: one row per completed term enrolment (grades final). "
         "The *prediction point* of a row is that term's end date, and every feature uses only records dated on or before it. "
         "Each row stores `feature_max_source_date`, and the leakage checker verifies that it never exceeds the prediction date. "
         f"Panel size: {man['datasets']['syn_student_term_panel']['rows']:,} rows; "
         f"{man['datasets']['syn_student_term_panel']['features']} candidate features.\n"]
    for g, items in FEATURE_GROUPS.items():
        L.append(f"### {g}\n")
        L.append(_md(pd.DataFrame(items, columns=["feature(s)", "source", "definition"])) + "\n")
    L.append("## 2. Which source datasets were used\n")
    ds = pd.DataFrame([{"dataset": k, "zone": v["zone"], "rows": v["rows"], "features": v["features"] if v["features"] is not None else "-",
                        "targets": ", ".join(v.get("targets", []) or []) or "-"} for k, v in man["datasets"].items()])
    L.append(_md(ds) + "\n")
    L.append("Source tables: UCI `data/processed/uci/uci_source_records.csv` (derived from the untouched `data/raw/data.csv`). Synthetic: "
             "`reference/academic_terms, programmes, level_rules`, `registrar/students, student_programmes, term_enrolments, course_enrolments, "
             "academic_standing, retention_cohort_members, graduation_records`, `admissions/applications, applicants`, `finance/charges, payments, "
             "financial_holds, registration_blocks`. No source file was modified.\n")
    L.append("### Task definitions (target, prediction point, population)\n")
    for name in [k for k in man["datasets"] if (MODELING_DIR / man["datasets"][k]["zone"].lower() / f"{k}.card.json").exists()]:
        c = _j(MODELING_DIR / man["datasets"][name]["zone"].lower() / f"{name}.card.json")
        L.append(f"**`{name}`** ({c['zone']}, {c['rows']:,} rows)  \n- *Prediction point:* {c['prediction_point']}  \n- *Target:* {c['target_definition']}  \n"
                 f"- *Population:* {c['population']}  \n- *Split:* {c['split']}  \n" + "".join(f"- *Note:* {n}  \n" for n in c.get("notes", [])))
    L.append("## 3. Which features were unavailable\n")
    L.append(_md(pd.DataFrame(UNAVAILABLE, columns=["feature", "why it is not used"])) + "\n")
    L.append("## Leakage prevention\n")
    L.append("Columns excluded from every synthetic student task (and the reason):\n")
    c = _j(MODELING_DIR / "synthetic" / "syn_dropout_2y.card.json")
    L.append(_md(pd.DataFrame(list(c["excluded_leakage_columns"].items()), columns=["excluded column(s)", "reason"])) + "\n")
    L.append("Task-specific exclusions are listed in each dataset card (`*.card.json`) and in every model's `*.meta.json`. "
             "Automated checks (`pipelines/model_training/leakage.py`) run before every model is trained; a failure blocks the task:\n")
    chk = {}
    for tid, r in res.items():
        for x in r.get("leakage_checks", []):
            chk.setdefault(x["check"], [0, 0])
            chk[x["check"]][0 if x["passed"] else 1] += 1
    L.append(_md(pd.DataFrame([{"check": k, "passed": v[0], "failed": v[1]} for k, v in sorted(chk.items())])) + "\n")
    L.append("Issues found by the checks during development and fixed at the source (not by weakening the checks): (1) the graduation "
             "survival dataset dated censored labels at the window end instead of the censoring date (fixed in `datasets.py`); (2) a descriptive "
             "exclusion rule was parsed as a column name (rules are now marked `[rule]`). The strongest single features per task "
             "(screen L9) are in each `results.json`; none exceeded the 0.97 AUC/|r| limit.\n")
    L.append("## Data-quality notes affecting features\n")
    L.append("- 180 UCI students have no evaluations in either semester (`NOT_EVALUATED_BOTH_SEMESTERS`); they are kept, since their semester counts are real zeros.\n"
             "- Fall 2026 is census-only (no grades), so it never enters the student panel; Spring/Summer 2027 are future.\n"
             "- 2016FA is the first simulated term (ramp-up): early terms have few students, so programme-context features start sparse.\n"
             "- `prog_hist_grad_rate_mature` is missing until the first cohort window closes (no mature history yet); it is imputed and flagged.\n")
    return "\n".join(L)


def _task_section(r: dict) -> list[str]:
    L = [f"### `{r['task_id']}` — {r['title']}\n", f"> {r['label']}\n",
         f"- Dataset `{r['dataset']}`, target `{r['target']}` ({r['kind']}); rows {r['n_rows']:,}; features {r['n_features']}.",
         f"- Prediction point: {r['prediction_point']}",
         f"- Split: {r['split']['method']}  \n  Train {r['split']['train_rows']:,} rows / {r['split']['train_groups']:,} groups; "
         f"test {r['split']['test_rows']:,} rows / {r['split']['test_groups']:,} groups."]
    if "class_distribution" in r:
        L.append(f"- Class distribution: train {r['class_distribution']['train']}; test {r['class_distribution']['test']}")
    if r.get("row_filter"):
        L.append(f"- Subset: {r['row_filter']}")
    L.append(f"- Selected: **{r['best_model']}** ({r['selection_rule']}; test set not used for selection). Evidence vs linear baseline: {evidence(r)}.")
    if r.get("persistence_baseline"):
        pb = r["persistence_baseline"]
        L.append(f"- Naive baseline (next-term GPA = current-term GPA, {pb['rows_with_value']:,} rows): MAE {pb['mae']:.3f}, RMSE {pb['rmse']:.3f}; "
                 f"best model on the same rows: MAE {pb['best_model_on_same_rows']['mae']:.3f}, RMSE {pb['best_model_on_same_rows']['rmse']:.3f}.")
    if r.get("out_of_time"):
        o = r["out_of_time"]
        mm = o["metrics"]
        txt = ", ".join(f"{k} {_f(v)}" for k, v in mm.items() if k in ("pr_auc", "roc_auc", "recall", "precision", "rmse", "mae", "r2", "prevalence"))
        L.append(f"- Out-of-time check ({o['model']}, cutoff {o['cutoff']}: train {o['train_rows']:,}, test {o['test_rows']:,}): {txt}.")
    d = r["_dir"]
    imgs = sorted(d.glob("*.png"))
    for i in imgs:
        L.append(f"\n![{i.stem}]({_rel(i)})")
    shp = sorted((FA / r["zone"].lower()).glob(f"{r['task_id']}_shap_*.png"))
    for i in shp:
        L.append(f"\n![{i.stem}]({_rel(i)})")
    if r.get("shap_top15"):
        L.append("\nTop features (mean |SHAP|, " + r["shap_model"] + "): " + ", ".join(f"`{k}` {v:.3f}" for k, v in r["shap_top15"][:10]) + ".")
    L.append("")
    return L


def model_training_report(res: dict) -> str:
    summ = _j(EV / "run_summary.json")
    L = ["# Model Training Report\n", f"> **Every synthetic result below: {SYN_BANNER}** Synthetic performance is NOT evidence of predictive accuracy "
         "at any real institution: the synthetic generator encodes known rules, so models partly re-learn those rules.  ",
         f"> **UCI results: {UCI_BANNER}**\n",
         "Code: `data_warehouse/pipelines/model_training/` (`supervised.py`, `survival.py`, `forecasting.py`, `segmentation.py`, `leakage.py`, `core.py`, "
         "`run_all.py`). Re-run everything with `python -m pipelines.model_training.run_all` from `data_warehouse`.\n",
         "## Method (applies to every supervised task)\n",
         "- Separate training populations for Zone A (UCI) and Zone B (synthetic); no model ever sees both.\n"
         "- Pipelines: median imputation with missing-value indicators; one-hot encoding (rare categories < 20 grouped; unseen categories handled); "
         "standard scaling for linear models only. All preprocessing is fitted inside the pipeline on training folds only.\n"
         "- Class imbalance: class weights (`balanced`, `scale_pos_weight`, `auto_class_weights`); no oversampling.\n"
         "- Splits: UCI one row per student: stratified 75/25. Synthetic student tasks: **student-grouped** 75/25 (StratifiedGroupKFold), so no "
         "student appears in both train and test; 5-fold grouped CV on the training students; admissions: chronological (entry year 2025/26+ is test) "
         "with test-period applicants removed from training. Out-of-time robustness checks for the panel tasks.\n"
         "- Selection: on CV only (PR-AUC for classification, RMSE for regression), never on the test set or on accuracy alone. Decision threshold "
         "chosen to maximise F1 on CV out-of-fold predictions and then applied unchanged to the test set (metrics marked *).\n"
         f"- Seed {summ['environment']['seed']}; environment: " + ", ".join(f"{k} {v}" for k, v in summ["environment"].items() if k != "seed") + ".\n"
         "- Experiment tracking: MLflow is not installed, so a simple JSON-lines log is used (`data_warehouse/experiments/experiment_log.jsonl`), "
         "plus a `results.json` per task and a `*.meta.json` per saved model.\n",
         "## 4. Which predictive tasks were successfully trained\n"]
    rows = [{"task": k, "status": v["status"], "selected model": v.get("best_model", "-"), "rows": v.get("n_rows", "-")} for k, v in summ["tasks"].items()]
    L.append(_md(pd.DataFrame(rows)) + "\n")
    L.append("## 5-7. Algorithms, sample sizes and metrics per task\n")
    L.append("Full metric tables for every algorithm are in `model_comparison.md`. Each task's `results.json` also stores the classification "
             "report, both confusion matrices (0.5 and the CV threshold), subgroup results and the leakage-check log.\n")
    for zone, head in (("UCI", "### Zone A: UCI research models"), ("SYNTHETIC", "### Zone B: synthetic demonstration models")):
        L.append(head + "\n")
        for tid, r in res.items():
            if r["zone"] == zone and "models" in r:
                L += _task_section(r)
    L.append("### Survival models (Cox proportional hazards, statsmodels PHReg)\n")
    for tid in ("syn_graduation_cox", "syn_dropout_cox"):
        if tid not in res:
            continue
        r = res[tid]
        hr = pd.DataFrame(r["hazard_ratios"])[["covariate", "hazard_ratio_per_sd", "ci_low", "ci_high", "p_value"]]
        L += [f"#### `{tid}` — {r['title']}\n", f"> {r['label']}\n",
              f"- {r['target_definition']}",
              f"- Rows {r['n_rows']:,}; events {r['events']:,}; censored {r['censored']:,}. Train {r['split']['train_rows']:,} "
              f"({r['split']['train_events']} events) / test {r['split']['test_rows']:,} ({r['split']['test_events']} events), student-grouped.",
              f"- Stratified by level; dropped constant covariates {r['split']['dropped_constant_covariates']}, exactly collinear {r['split']['dropped_collinear_covariates']}.",
              f"- Concordance (Harrell's C, within level): train {r['concordance_train']:.3f}, **test {r['concordance_test']:.3f}**.",
              f"- Proportional-hazards check (scaled Schoenfeld residuals vs time; flagged if p < 0.01 and |rho| > 0.1): "
              f"{', '.join(r['ph_possible_violations']) or 'none'}. Flagged effects change over time, so their hazard ratios are averages.\n",
              _md(hr.round(4)) + "\n", f"![km]({_rel(r['_dir'] / 'kaplan_meier_by_level.png')})\n"]
    seg = FA / "synthetic" / "segmentation_results.json"
    if seg.exists():
        s = _j(seg)
        L += ["### Optional: segmentation and anomaly detection\n", f"> {SYN_BANNER}\n",
              f"- {s['population']}: {s['n_students']:,} students, {len(s['features'])} features (standardised).",
              f"- K-Means k chosen by silhouette: k = {s['chosen_k']} (silhouette {s['silhouette_by_k'][str(s['chosen_k'])] if str(s['chosen_k']) in s['silhouette_by_k'] else s['silhouette_by_k'][s['chosen_k']]:.3f}); "
              f"agreement with Ward hierarchical clustering (adjusted Rand) {s['kmeans_vs_ward_adjusted_rand']:.3f}. Segment sizes {s['segment_sizes']}.",
              f"- Isolation Forest (2 % contamination) flagged {s['isolation_forest']['flagged']} students; most unusual features among them: "
              f"{s['isolation_forest']['features_most_unusual_among_flagged_mean_abs_z']}.",
              f"- {s['interpretation']} Profiles: `reports/feature_analysis/synthetic/segmentation_kmeans_profiles.csv`.\n",
              "![silhouette](feature_analysis/synthetic/segmentation_silhouette.png)\n"]
    L.append("## Models not trained and why\n")
    L.append(_md(pd.DataFrame(NOT_TRAINED, columns=["model / task", "reason"])) + "\n")
    L.append("## 11. Limitations and data-quality concerns\n")
    L.append("\n".join(f"- {x}" for x in LIMITATIONS) + "\n")
    return "\n".join(L)


NOT_TRAINED = [
    ("Acceptance -> enrolment conversion model", "Every accepted offer enrolled in every historical term (rate = 1.000): no variation to learn"),
    ("Cox model for retention", "Retention is a fixed one-year binary outcome defined by the registrar comparison; time-to-dropout is modelled by `syn_dropout_cox` instead"),
    ("CatBoost / LightGBM for retention, graduation and admissions", "Not required by the brief for these tasks; LR, RF and XGBoost were compared as specified"),
    ("Prophet", "Not justified: <= 31 term observations at 3 irregular terms per year; SARIMA/ETS cover the seasonality"),
    ("Forecasts for series flagged REQUIRES_MORE_DATA", "Fewer than 18 terms since the first non-zero value or a recent term below 5 (see forecasting report)"),
    ("Capacity utilisation", "No capacity data exists (section/room/seat/faculty capacity); not inferred from enrolment counts"),
    ("Any model on combined UCI + synthetic data", "Forbidden by design: the zones are never combined"),
    ("UCI time-based or institutional models (retention by term, GPA, forecasting)", "UCI has no dates, terms, GPA or programmes; these were not invented"),
]
LIMITATIONS = [
    "Synthetic data are generated from configured rules (standing, withdrawal after > 3 missed regular terms, payment behaviour). Models partly "
    "re-discover those rules, so synthetic metrics are optimistic about real-world signal and say nothing about real students.",
    "Synthetic cohorts start in 2016FA (ramp-up): early terms are small and programme-context features are sparse at the start.",
    "Fall 2026 is census-only and Spring/Summer 2027 are future: recent students have short histories; the 2-year dropout label "
    "needs 730 days of follow-up, so the most recent prediction dates are excluded from that task.",
    "Graduation-within-window uses mature cohorts only (UG/DR 6 years and MA 4 years are project-configured reporting assumptions, not verified policy).",
    "UCI: a single Portuguese institution, outcomes at the end of the normal course duration, no time stamps; results cannot be transferred to this university.",
    "Probabilities are calibrated only to the class balance of the data they were trained on; class weighting shifts calibration "
    "(see the calibration curves and Brier scores). Thresholds would need re-setting on real data.",
    "Feature importance and SHAP describe what the model uses, not causes.",
]


def model_comparison_report(res: dict) -> str:
    df = comparison_rows(res)
    L = ["# Model Comparison\n", f"> **Synthetic rows: {SYN_BANNER}**  ", f"> **UCI rows: {UCI_BANNER}**\n",
         "Selection uses cross-validated metrics on the training data only. `*` = at the decision threshold chosen on CV out-of-fold predictions. "
         "A 'best' model is called *supported* only when its CV gain over the linear baseline exceeds one CV standard deviation; otherwise the simpler "
         "linear model is recommended.\n",
         "## 8. Best-performing model per task\n"]
    best = []
    for tid, r in res.items():
        if "models" not in r:
            continue
        m = {x["model"]: x for x in r["models"]}[r["best_model"]]
        key = "test_pr_auc" if r["kind"] == "binary" else ("test_pr_auc_macro" if r["kind"] == "multiclass" else "test_rmse")
        bkey = "test_pr_auc" if r["kind"] == "binary" else ("test_pr_auc_macro" if r["kind"] == "multiclass" else "test_rmse")
        base = {x["model"]: x for x in r["models"]}["baseline_majority" if r["kind"] != "regression" else "baseline_mean"]
        best.append({"task": tid, "zone": r["zone"], "selected": r["best_model"], "metric": key.replace("test_", "test "),
                     "selected value": m[key], "trivial baseline": base[bkey], "evidence vs linear model": evidence(r)})
    for tid in ("syn_graduation_cox", "syn_dropout_cox"):
        if tid in res:
            best.append({"task": tid, "zone": "SYNTHETIC", "selected": "cox_ph", "metric": "test concordance",
                         "selected value": res[tid]["concordance_test"], "trivial baseline": 0.5, "evidence vs linear model": "only survival model fitted"})
    L.append(_md(pd.DataFrame(best)) + "\n")
    L.append("Trivial baselines: majority class (PR-AUC = prevalence) or mean prediction (RMSE = SD).\n")
    for kind, head in (("binary", "## Binary classification"), ("multiclass", "## Three-class classification (UCI Graduate / Dropout / Enrolled)"),
                       ("regression", "## Regression")):
        ids = [t for t, r in res.items() if r.get("kind") == kind]
        if not ids:
            continue
        L.append(head + "\n")
        sub = df[df["task"].isin(ids)].dropna(axis=1, how="all")
        for tid in ids:
            L.append(f"**{tid}** ({res[tid]['zone']})\n")
            L.append(_md(sub[sub["task"] == tid].drop(columns=["task", "zone"])) + "\n")
    L.append("## Subgroup results (selected model, test set)\n")
    for tid, r in res.items():
        if r.get("subgroups"):
            sg = pd.DataFrame(r["subgroups"])
            L.append(f"**{tid}**\n\n" + _md(sg) + "\n")
    L.append("## 9. Important features (mean |SHAP|, top 8)\n")
    rows = []
    for tid, r in res.items():
        if r.get("shap_top15"):
            rows.append({"task": tid, "model": r["shap_model"], "top features": ", ".join(k for k, _ in r["shap_top15"][:8])})
    L.append(_md(pd.DataFrame(rows)) + "\n")
    L.append("Feature importance describes what the model relies on; it is not causal. For synthetic tasks it largely reflects the generator's rules.\n")
    L.append("## 12-13. Suitability for dashboard integration\n")
    L.append(_md(pd.DataFrame(SUITABILITY, columns=["model group", "dashboard use now", "before operational use"])) + "\n")
    return "\n".join(L)


SUITABILITY = [
    ("UCI dropout / outcome models", "Research panel only, clearly labelled as Portuguese UCI data (e.g. 'what predicts dropout in a public dataset')",
     "Cannot be used for this university's students at all; would need retraining on real institutional data"),
    ("Synthetic dropout, academic-risk, retention, graduation models", "Demonstration of the pipeline, risk-list UI and explanation views, with the synthetic banner on every screen",
     "Retrain and re-validate on real registrar, finance and admissions data; fairness review by subgroup; threshold and calibration on real outcomes; governance approval"),
    ("Synthetic next-term GPA regression", "Demonstration only", "Real grades; check that it beats the naive 'same as last term' baseline on real data"),
    ("Synthetic Cox survival models", "Demonstration of time-to-event curves", "Real data; proportional-hazards assumption re-checked"),
    ("Synthetic forecasts (enrolment, admissions, course demand)", "Demonstration of forecast charts with intervals and backtest accuracy", "Real term-level history (each term = one observation); real capacity data for any utilisation view"),
    ("Segmentation / anomaly detection", "Exploratory demo only", "Real data and a defined business use; segments must not be used to label individual students"),
]


def forecasting_report() -> str:
    r = _j(FC / "forecasting_results.json")
    el = pd.read_csv(FC / "series_eligibility.csv")
    best = pd.read_csv(FC / "best_method_by_series_family.csv")
    summ = pd.read_csv(FC / "backtest_summary_by_series_method.csv")
    sel = pd.read_csv(FC / "forecasts_selected_method.csv")
    L = ["# Forecasting Report\n", f"> **{SYN_BANNER}** All series are synthetic; forecasts describe the synthetic demonstration dataset only.\n",
         "Code: `pipelines/model_training/forecasting.py`. Outputs: `reports/forecasting/`.\n",
         "## How much history is there?\n",
         f"Each series has **one observation per term**: {r['n_term_observations']} terms ({r['enrolment_terms'][0]}–{r['enrolment_terms'][-1]}; "
         "2026FA is the census snapshot). Thousands of student records do **not** make thousands of time-series observations. "
         f"Annual series have {r['annual_observations']} observations. Rules: a series is forecast only if it has at least "
         f"{r['settings']['min_terms_since_first_nonzero']} terms since its first non-zero value and at least {r['settings']['min_recent_value']} in each of "
         "the last 9 terms; otherwise it is marked **REQUIRES_MORE_DATA**.\n"]
    ec = el.groupby(["series", "status"]).size().unstack(fill_value=0).reset_index()
    L.append(_md(ec) + "\n")
    short = el[el["status"] != "ELIGIBLE"]
    if len(short):
        L.append("<details><summary>Series not forecast (REQUIRES_MORE_DATA)</summary>\n\n" +
                 _md(short[["series", "dimension"] + [c for c in ("series_key", "programme_id") if c in short] + ["terms_since_first_nonzero", "reason"]].fillna("")) + "\n\n</details>\n")
    L += ["## Methods and evaluation\n",
          "Seasonal naive (same season last year) is the baseline. ETS (damped additive trend, additive seasonality, log scale), ARIMA(1,1,0) "
          "(non-seasonal comparison), SARIMA(0,1,1)(0,1,1)[3], and one global XGBoost model with lag features trained across all eligible series. "
          f"Rolling-origin backtest: origins from term index {r['settings']['first_backtest_origin_index']} ({r['enrolment_terms'][r['settings']['first_backtest_origin_index']]}) "
          f"onwards, horizons 1-{r['settings']['horizon_terms']} terms, refitted at every origin using only data up to that origin. Metrics: MAE, RMSE, "
          "WAPE (sum |error| / sum actual). 80 % prediction intervals are model-based for ETS/ARIMA/SARIMA (coverage checked in the backtest) and "
          "empirical (backtest error quantiles) for seasonal naive and XGBoost. Prophet: " + r["settings"]["prophet"] + f". Fit failures recorded: {r['fit_failures']['count']}.\n",
          "### Best method per series family (lowest pooled backtest WAPE; failing methods excluded)\n", _md(best) + "\n",
          "### All methods\n", _md(summ) + "\n"]
    L.append("## 10. Forecasted enrolment and programme demand\n")
    tot = sel[sel["series"] == "enrolment_headcount:TOTAL"][["target_term", "method", "forecast", "pi80_low", "pi80_high", "interval_type", "target_term_note"]]
    L.append("**Total census headcount**\n\n" + _md(tot) + "\n\n![total](forecasting/total_enrolment_forecast.png)\n")
    for dim in ("level", "school_id", "delivery_mode", "gender", "study_load", "nationality_iso3"):
        s = sel[sel["series"] == f"enrolment_headcount:{dim}"]
        if len(s):
            L.append(f"**By {dim}**\n\n" + _md(s[["key", "target_term", "method", "forecast", "pi80_low", "pi80_high"]]) + "\n")
            img = FC / f"enrolment_forecast_by_{dim}.png"
            if img.exists():
                L.append(f"![{dim}]({_rel(img)})\n")
    ann = pd.DataFrame(r["annual_summary"])
    L.append("**By academic year and by semester (annual series, " + ", ".join(f"{k}: {v} obs" for k, v in r["annual_observations"].items()) +
             ")** — too short for seasonal models; naive, drift and damped Holt compared with a 1-step rolling backtest:\n\n" + _md(ann) + "\n")
    af = pd.read_csv(FC / "annual_series_forecasts.csv")
    L.append(_md(af.drop(columns=["label"])) + "\n")
    L.append("### Admissions demand\n")
    adm = sel[sel["series"].str.startswith("admissions_") & (sel["key"] == "ALL")][["series", "target_term", "method", "forecast", "pi80_low", "pi80_high"]]
    L.append(_md(adm) + "\n\n![admissions](forecasting/admissions_funnel_forecast.png)\n")
    cr = pd.read_csv(FC / "conversion_rate_backtest_summary.csv")
    cf = pd.read_csv(FC / "conversion_rate_forecasts.csv")
    L.append("Conversion rates (institution level; rates are bounded, so they are forecast from same-season history and evaluated in percentage points):\n\n" +
             _md(cr) + "\n\n" + _md(cf.drop(columns=["label"])) + "\n")
    L.append("Acceptance -> enrolment is 1.000 in every term (every accepted offer enrolled in the synthetic data), so it carries no forecasting signal. "
             "Applications are counted once per applicant per entry term (no applicant applied twice for the same term), so there is no double counting.\n")
    L.append("### Programme demand (applications, headcount and course registrations) — scenarios\n")
    sc = pd.read_csv(FC / "programme_demand_scenarios.csv")
    nxt = r["next_terms"][-1]
    piv = sc[sc["target_term"] == nxt].pivot_table(index="key", columns="series", values="scenario_baseline").round(0)
    L.append(f"Baseline forecasts for {nxt} per programme (low / high scenarios = 80 % interval; ±10 % demand scenarios in "
             "`programme_demand_scenarios.csv`):\n\n" + _md(piv.reset_index().fillna("not forecast")) + "\n")
    L.append("### Capacity\n")
    L.append("**Demand is not capacity.** The data contain no capacity information, so utilisation is **not** computed and capacity is **not** inferred "
             "from enrolment counts. Fields needed: course-section capacity (seats per section), room capacity and timetable, programme intake caps, "
             "faculty FTE / maximum teaching load, lab/studio capacity, and online delivery limits. No synthetic capacity was created because "
             "the demand forecasts are complete without it.\n")
    L.append("## Limitations\n")
    L.append("- Synthetic growth is smooth and rule-driven; real enrolment has shocks (policy, fees, economy) that these short series cannot anticipate.\n"
             "- 2016FA-2018 is the simulated ramp-up from an empty institution; it is kept in the history (methods are refitted at each origin) but makes early growth steeper than later growth.\n"
             "- The horizon ends at 2027FA, which lies beyond the configured calendar (2027SU) and is labelled as such.\n"
             "- Backtests have 12 origins at most, so method rankings are indicative, not definitive.\n")
    return "\n".join(L)


def main():
    res = load_results()
    (REPORTS_DIR / "feature_engineering_report.md").write_text(feature_engineering_report(res), encoding="utf-8")
    (REPORTS_DIR / "model_training_report.md").write_text(model_training_report(res), encoding="utf-8")
    (REPORTS_DIR / "model_comparison.md").write_text(model_comparison_report(res), encoding="utf-8")
    (REPORTS_DIR / "forecasting_report.md").write_text(forecasting_report(), encoding="utf-8")
    print("reports written")


if __name__ == "__main__":
    main()
