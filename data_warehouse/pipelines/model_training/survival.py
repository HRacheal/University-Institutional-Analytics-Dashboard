"""Cox proportional-hazards models (statsmodels PHReg; lifelines is not installed and not needed) with censoring,
Harrell's concordance on a chronological test set, Kaplan-Meier curves and a proportional-hazards check."""
from __future__ import annotations

import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.duration.hazard_regression import PHReg
from statsmodels.duration.survfunc import SurvfuncRight

from ..feature_engineering.common import data_version, load_dataset
from . import core, leakage

# Compact, interpretable covariate set (Cox with ~90 one-hot columns would be unstable and hard to read).
COX_NUMERIC = ["cumulative_gpa", "term_gpa", "cum_course_completion_rate", "credits_attempted", "progression_rate",
               "warning_terms_so_far", "probation_terms_so_far", "prior_gap_terms", "credits_transferred_in", "scholarship_pct",
               "age_at_admission_approx", "fin_payment_completion_pct", "fin_late_payment_terms", "fin_holds_so_far",
               "part_time_share_so_far", "online_share_so_far"]
COX_CATEGORICAL = ["level"]
Z_CLIP = 5.0


def concordance(time_, event, risk, strata=None) -> float:
    """Harrell's C: among comparable pairs (earlier time had the event), share where the earlier one has higher risk.
    With strata, pairs are only compared within the same stratum (the baseline hazard differs between strata)."""
    if strata is not None:
        strata = np.asarray(strata)
        num = den = 0.0
        for s in np.unique(strata):
            k = strata == s
            n_, d_ = _conc_counts(np.asarray(time_)[k], np.asarray(event)[k], np.asarray(risk)[k])
            num, den = num + n_, den + d_
        return float(num / den) if den else np.nan
    n_, d_ = _conc_counts(*map(np.asarray, (time_, event, risk)))
    return float(n_ / d_) if d_ else np.nan


def _conc_counts(t, e, r):
    order = np.argsort(t)
    t, e, r = t[order], e[order], r[order]
    num = den = 0.0
    for i in np.where(e == 1)[0]:
        later = t > t[i]
        den += later.sum()
        num += (r[i] > r[later]).sum() + 0.5 * (r[i] == r[later]).sum()
    return num, den


def _design(df, means=None, sds=None, levels=None):
    X = df[COX_NUMERIC].astype(float).copy()
    if means is None:
        means, sds = X.mean(), X.std().replace(0, 1)
    X = ((X - means) / sds).fillna(0.0).clip(-Z_CLIP, Z_CLIP)   # skewed counts (e.g. transfer credits up to ~30 SD) overflow exp(Xb)
    levels = levels or sorted(df["level"].unique())
    return X, means, sds, levels      # level enters as a STRATUM (separate baseline hazard), not as a covariate


def drop_degenerate(X: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Constant columns and columns that are exact linear combinations of earlier ones (e.g. at a first term
    cumulative GPA == term GPA). Returns (constant, collinear)."""
    const = [c for c in X.columns if X[c].std() == 0]
    keep, coll = [], []
    for c in [c for c in X.columns if c not in const]:
        M = X[keep + [c]].values - X[keep + [c]].values.mean(0)
        (keep if np.linalg.matrix_rank(M) == len(keep) + 1 else coll).append(c)
    return const, coll


def run_cox(task_id: str, dataset: str, event_col: str, title: str) -> dict:
    t0 = time.time()
    df, card = load_dataset(dataset, "SYNTHETIC")
    df = df[df["duration_years"] > 0].reset_index(drop=True)
    checks = leakage.static_checks(df, card)
    tri, tei = core.grouped_holdout(df, df[event_col], df["student_id"])
    tr, te = df.index.isin(tri), df.index.isin(tei)
    checks += leakage.split_checks(df[tr], df[te], "student_id")
    failed = [c for c in checks if not c["passed"]]
    if failed:
        raise RuntimeError(f"{task_id}: leakage check failed {failed}")
    Xtr, mu, sd, lv = _design(df[tr])
    Xte, *_ = _design(df[te], mu, sd, lv)
    const, coll = drop_degenerate(Xtr)                        # e.g. prior_gap_terms is always 0 at a first term
    Xtr, Xte = Xtr.drop(columns=const + coll), Xte.drop(columns=const + coll)
    s_tr, s_te = df.loc[tr, "level"].values, df.loc[te, "level"].values
    mod = PHReg(df.loc[tr, "duration_years"].values, Xtr.values, status=df.loc[tr, event_col].values, strata=s_tr, ties="efron")
    # plain Newton from 0 overshoots when level effects are large (|log HR| ~ 2); BFGS gives a stable start, Newton refines
    start = mod.fit(method="bfgs", maxiter=1000, disp=False).params
    m = mod.fit(start_params=start, method="newton", disp=False)
    if not np.all(np.isfinite(m.params)):
        raise RuntimeError("Cox fit did not converge")
    hr = pd.DataFrame({"coef": m.params, "hazard_ratio_per_sd": np.exp(m.params), "ci_low": np.exp(m.conf_int()[:, 0]),
                       "ci_high": np.exp(m.conf_int()[:, 1]), "p_value": m.pvalues}, index=Xtr.columns)
    c_tr = concordance(df.loc[tr, "duration_years"], df.loc[tr, event_col], Xtr.values @ m.params, s_tr)
    c_te = concordance(df.loc[te, "duration_years"], df.loc[te, event_col], Xte.values @ m.params, s_te)
    # proportional-hazards check (Grambsch-Therneau style): Spearman correlation of SCALED Schoenfeld residuals
    # r* = beta + d * V(beta) r  with event time; a clear trend means the covariate's effect changes over time.
    ph = []
    try:
        ev = df.loc[tr, event_col].values == 1
        sr = m.schoenfeld_residuals[ev]
        tt = df.loc[tr, "duration_years"].values[ev]
        ok_rows = ~np.isnan(sr).any(1)
        scaled = m.params + ev.sum() * (sr[ok_rows] @ m.cov_params())
        tt = tt[ok_rows]
        for j, c in enumerate(Xtr.columns):
            r = scaled[:, j]
            ok = ~np.isnan(r)
            rho, p = stats.spearmanr(tt[ok], r[ok])
            ph.append({"covariate": c, "spearman_rho_with_time": float(rho), "p_value": float(p)})
    except Exception as e:
        ph.append({"error": repr(e)})
    viol = [x["covariate"] for x in ph if "p_value" in x and x["p_value"] < 0.01 and abs(x["spearman_rho_with_time"]) > 0.1]
    out = core.report_dir("model_evaluation") / "synthetic" / task_id
    out.mkdir(parents=True, exist_ok=True)
    hr.to_csv(out / "hazard_ratios.csv")
    # Kaplan-Meier by level (whole dataset, descriptive)
    fig, ax = plt.subplots(figsize=(6, 4))
    km = {}
    for lvl, g in df.groupby("level"):
        sf = SurvfuncRight(g["duration_years"].values, g[event_col].values)
        ax.step(sf.surv_times, 1 - sf.surv_prob if event_col == "event_graduated" else sf.surv_prob, where="post", label=f"{lvl} (n={len(g)})")
        km[lvl] = {"n": int(len(g)), "events": int(g[event_col].sum())}
    ax.set_xlabel("Years since admission"); ax.set_ylabel("Cumulative graduation" if event_col == "event_graduated" else "Share without dropout")
    ax.set_title(f"{title}: Kaplan-Meier by level", fontsize=9); ax.legend(fontsize=7)
    core._stamp(fig, "SYNTHETIC"); fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(out / "kaplan_meier_by_level.png", dpi=110); plt.close(fig)
    res = {"task_id": task_id, "title": title, "zone": "SYNTHETIC", "label": core.SYN_BANNER, "dataset": dataset, "model": "cox_ph_statsmodels",
           "target_definition": card["target_definition"], "prediction_point": card["prediction_point"], "population": card["population"],
           "n_rows": int(len(df)), "events": int(df[event_col].sum()), "censored": int((df[event_col] == 0).sum()),
           "split": {"method": card["split"], "train_rows": int(tr.sum()), "test_rows": int(te.sum()), "dropped_constant_covariates": const, "dropped_collinear_covariates": coll,
                     "strata": "level (separate baseline hazard per level)",
                     "train_events": int(df.loc[tr, event_col].sum()), "test_events": int(df.loc[te, event_col].sum())},
           "covariates": list(Xtr.columns), "covariate_note": "numeric covariates standardised on training data and clipped to +/-5 SD; HR is per 1 SD",
           "concordance_train": c_tr, "concordance_test": c_te, "hazard_ratios": hr.reset_index(names="covariate").to_dict("records"),
           "ph_check": ph, "ph_possible_violations": viol, "kaplan_meier": km, "leakage_checks": checks,
           "excluded_leakage_columns": card["excluded_leakage_columns"],
           "status": "TRAINED" if not viol else "TRAINED_WITH_PH_CAVEATS", "seconds": round(time.time() - t0, 1)}
    meta = {k: res[k] for k in ("task_id", "dataset", "target_definition", "prediction_point", "population", "covariates", "split")}
    meta.update({"standardisation_means": mu.to_dict(), "standardisation_sds": sd.to_dict(), "levels": lv,
                 "concordance_test": c_te, "data_version": data_version()})
    res["saved_models"] = {"cox_ph": core.save_model({"params": pd.Series(m.params, index=Xtr.columns), "means": mu, "sds": sd, "levels": lv},
                                                     "SYNTHETIC", task_id, "cox_ph", meta)}
    core.write_json(res, out / "results.json")
    core.log_experiment({"task_id": task_id, "zone": "SYNTHETIC", "dataset": dataset, "best_model": "cox_ph",
                         "metrics": {"c_train": c_tr, "c_test": c_te}, "seed": core.SEED, "data_version": meta["data_version"]})
    return res
