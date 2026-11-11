"""Supervised classification / regression experiments with leakage gates, grouped CV, untouched test set, SHAP and tracking."""
from __future__ import annotations

import gc
import json
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.base import clone

from ..feature_engineering.common import load_dataset
from . import core, leakage

CLASSIFIERS = ["baseline_majority", "logistic_regression", "random_forest", "xgboost", "lightgbm", "catboost"]
REGRESSORS = ["baseline_mean", "linear_regression", "random_forest", "xgboost", "lightgbm"]


@dataclass
class TaskSpec:
    task_id: str
    dataset: str
    zone: str
    target: str
    kind: str = "binary"                     # binary | multiclass | regression
    models: list[str] = field(default_factory=list)
    group_col: str | None = "student_id"
    row_filter: dict | None = None           # column -> value
    split: str = "grouped"                   # grouped | stratified | chronological
    chrono_col: str | None = None
    chrono_test_from: str | None = None
    oot_cutoff: str | None = None
    subgroup_cols: list[str] = field(default_factory=list)
    persistence_baseline: str | None = None  # regression: column used as a naive forecast
    positive_label: str = "1"
    title: str = ""


class LeakageError(RuntimeError):
    pass


def _split(df, y, spec: TaskSpec):
    if spec.split == "stratified":
        from sklearn.model_selection import train_test_split
        tr, te = train_test_split(df.index, test_size=0.25, stratify=y, random_state=core.SEED)
        return tr, te
    if spec.split == "chronological":
        test = df[spec.chrono_col] >= spec.chrono_test_from
        test_groups = set(df.loc[test, spec.group_col]) if spec.group_col else set()
        train = ~test & ~(df[spec.group_col].isin(test_groups) if spec.group_col else False)
        return df.index[train], df.index[test]
    strat = y if spec.kind != "regression" else pd.qcut(y.rank(method="first"), 5, labels=False)
    return core.grouped_holdout(df, strat, df[spec.group_col])


def _cv(X, y, groups, spec):
    if spec.kind == "regression":
        return core.regression_cv_splits(X, y, groups)
    return core.cv_splits(X, y, groups)


def _proba(pipe, X, kind):
    p = pipe.predict_proba(X)
    return p[:, 1] if kind == "binary" else p


# ---------------------------------------------------------------------------------------------------------- checkpoints
# Each model's CV row, test predictions and final fitted pipeline are written to disk as soon as that model finishes, so an
# interruption in post-fit processing (plots, SHAP, out-of-time refit) never loses the expensive CV fits, and fitted models
# are not all held in memory at once. A checkpoint is reused only if its fingerprint (data version, split, estimator
# parameters, seed) matches the current run exactly; checkpoints are deleted once the task has finished.
def _ckpt_dir(spec: TaskSpec):
    from ..feature_engineering.common import EXPERIMENTS_DIR
    return EXPERIMENTS_DIR / "checkpoints" / spec.task_id


def _fingerprint(spec: TaskSpec, name: str, pipe, tr, te, n_folds: int, dv) -> dict:
    import hashlib
    h = lambda idx: hashlib.sha256(np.asarray(idx, dtype=np.int64).tobytes()).hexdigest()[:16]  # noqa: E731
    return {"task_id": spec.task_id, "model": name, "target": spec.target, "kind": spec.kind, "seed": core.SEED,
            "data_version": json.dumps(dv, sort_keys=True, default=str), "train_index": h(tr), "test_index": h(te),
            "cv_folds": n_folds, "estimator": repr(pipe.named_steps["model"].get_params()), "ckpt_format": 2}


def _load_ckpt(path, fp):
    import joblib
    if not path.exists():
        return None
    try:
        ck = joblib.load(path)
    except Exception:
        return None
    return ck if ck.get("fingerprint") == fp else None


def _load_fitted(ckpts: dict, name: str):
    import joblib
    return joblib.load(ckpts[name])["pipe"]


def run(spec: TaskSpec) -> dict:
    t0 = time.time()
    df, card = load_dataset(spec.dataset, spec.zone)
    if spec.row_filter:
        for c, v in spec.row_filter.items():
            df = df[df[c] == v]
    df = df[df[spec.target].notna()].reset_index(drop=True)
    num, cat = card["features_numeric"], card["features_categorical"]
    res = {"task_id": spec.task_id, "title": spec.title, "zone": spec.zone, "label": core.banner(spec.zone), "dataset": spec.dataset,
           "target": spec.target, "kind": spec.kind, "prediction_point": card["prediction_point"],
           "target_definition": card["target_definition"], "population": card["population"], "row_filter": spec.row_filter,
           "n_rows": int(len(df)), "n_features": len(num) + len(cat), "features_numeric": num, "features_categorical": cat,
           "excluded_leakage_columns": card["excluded_leakage_columns"]}

    checks = leakage.static_checks(df, {**card, "targets": card["targets"]})
    y = df[spec.target]
    if spec.kind == "binary":
        y = y.astype(int)
    elif spec.kind == "regression":
        y = y.astype(float)
    X = df[num + cat].copy()
    for c in cat:
        X[c] = X[c].astype("string").fillna("MISSING").astype(object)
    tr, te = _split(df, y, spec)
    checks += leakage.split_checks(df.loc[tr], df.loc[te], spec.group_col)
    screen = leakage.single_feature_screen(X.loc[tr], y.loc[tr], num, "regression" if spec.kind == "regression" else "classification")
    checks.append({k: v for k, v in screen.items() if k != "strongest"})
    res["leakage_checks"] = checks
    res["strongest_single_features"] = screen["strongest"]
    failed = [c for c in checks if not c["passed"]]
    if failed:
        res["status"] = "BLOCKED_BY_LEAKAGE_CHECK"
        res["failed_checks"] = failed
        raise LeakageError(f"{spec.task_id}: {failed}")

    Xtr, Xte, ytr, yte = X.loc[tr], X.loc[te], y.loc[tr], y.loc[te]
    gtr = df.loc[tr, spec.group_col] if spec.group_col else None
    res["split"] = {"method": card["split"] if spec.split != "stratified" else card["split"], "train_rows": int(len(tr)),
                    "test_rows": int(len(te)),
                    "train_groups": int(gtr.nunique()) if gtr is not None else int(len(tr)),
                    "test_groups": int(df.loc[te, spec.group_col].nunique()) if spec.group_col else int(len(te))}
    if spec.kind != "regression":
        res["class_distribution"] = {"train": ytr.value_counts().sort_index().to_dict(), "test": yte.value_counts().sort_index().to_dict()}
    else:
        res["target_summary"] = {"train_mean": float(ytr.mean()), "train_sd": float(ytr.std()), "test_mean": float(yte.mean())}
    folds = _cv(Xtr, ytr, gtr if gtr is not None else None, spec)
    classes = sorted(y.unique()) if spec.kind == "multiclass" else None

    import joblib
    from ..feature_engineering.common import data_version
    dv = data_version()
    ckdir = _ckpt_dir(spec)
    ckdir.mkdir(parents=True, exist_ok=True)
    models, rows, test_scores, ckpts, oofs = spec.models, [], {}, {}, {}
    res["checkpoints_reused"] = []
    for name in models:
        m0 = time.time()
        if spec.kind == "regression":
            est, scale = core.regressor_factory(name)
        else:
            est, scale = core.classifier_factory(name, ytr, 2 if spec.kind == "binary" else len(classes))
        pipe = core.build_pipeline(est, scale, num, cat)
        fp = _fingerprint(spec, name, pipe, tr, te, len(folds), dv)
        ck_path = ckdir / f"{name}.joblib"
        ck = _load_ckpt(ck_path, fp)
        if ck is not None:
            rows.append(ck["row"]); test_scores[name] = ck["test_pred"]; ckpts[name] = ck_path; oofs[name] = ck.get("oof")
            res["checkpoints_reused"].append(name)
            del ck; gc.collect()
            print(f"    {spec.task_id:42s} {name:20s} reused checkpoint (CV fit not repeated)", flush=True)
            continue
        oof = np.zeros(len(ytr)) if spec.kind != "multiclass" else np.zeros((len(ytr), len(classes)))
        fold_scores = []
        for ftr, fva in folds:
            p = clone(pipe)
            fit_kw = {}
            if spec.kind == "multiclass" and name in ("xgboost",):
                yy = ytr.iloc[ftr].map({c: i for i, c in enumerate(classes)})
                from sklearn.utils.class_weight import compute_sample_weight
                fit_kw = {"model__sample_weight": compute_sample_weight("balanced", yy)}
                p.fit(Xtr.iloc[ftr], yy, **fit_kw)
            else:
                if spec.kind == "multiclass" and name == "random_forest":
                    pass
                p.fit(Xtr.iloc[ftr], ytr.iloc[ftr], **fit_kw)
            if spec.kind == "regression":
                oof[fva] = p.predict(Xtr.iloc[fva])
                fold_scores.append(core.regression_metrics(ytr.iloc[fva], oof[fva])["rmse"])
            elif spec.kind == "binary":
                oof[fva] = _proba(p, Xtr.iloc[fva], "binary")
                fold_scores.append(core.average_precision_score(ytr.iloc[fva], oof[fva]))
            else:
                oof[fva] = p.predict_proba(Xtr.iloc[fva])
                fold_scores.append(core.multiclass_metrics(ytr.iloc[fva], oof[fva], classes)["pr_auc_macro"])
        # final fit on all training rows
        if spec.kind == "multiclass" and name == "xgboost":
            from sklearn.utils.class_weight import compute_sample_weight
            yy = ytr.map({c: i for i, c in enumerate(classes)})
            pipe.fit(Xtr, yy, model__sample_weight=compute_sample_weight("balanced", yy))
        else:
            pipe.fit(Xtr, ytr)
        row = {"model": name, "cv_folds": len(folds), "fit_seconds": round(time.time() - m0, 1)}
        if spec.kind == "regression":
            cvm = core.regression_metrics(ytr, oof)
            pred = pipe.predict(Xte)
            tm = core.regression_metrics(yte, pred)
            test_scores[name] = pred
            row.update({"cv_rmse": cvm["rmse"], "cv_rmse_sd": float(np.std(fold_scores)), "cv_mae": cvm["mae"], "cv_r2": cvm["r2"],
                        "test_mae": tm["mae"], "test_rmse": tm["rmse"], "test_r2": tm["r2"]})
        elif spec.kind == "binary":
            thr = core.best_f1_threshold(ytr, oof) if name != "baseline_majority" else 0.5
            p = _proba(pipe, Xte, "binary")
            test_scores[name] = p
            m05, mt = core.binary_metrics(yte, p, 0.5), core.binary_metrics(yte, p, thr)
            row.update({"cv_pr_auc": core.average_precision_score(ytr, oof), "cv_pr_auc_sd": float(np.std(fold_scores)),
                        "cv_roc_auc": core.roc_auc_score(ytr, oof), "threshold_from_cv": thr,
                        **{f"test_{k}": m05[k] for k in ("accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc", "brier")},
                        **{f"test_tuned_{k}": mt[k] for k in ("accuracy", "precision", "recall", "f1")},
                        "test_confusion_matrix_0.5": m05["confusion_matrix"], "test_confusion_matrix_tuned": mt["confusion_matrix"],
                        "test_classification_report_tuned": mt["classification_report"]})
            # supplementary only (selection and threshold_from_cv above are unchanged): class-0 F1 threshold from CV OOF
            thr0 = core.best_f1_threshold_class0(ytr, oof) if name != "baseline_majority" else 0.5
            row["supplementary_class0"] = {
                "threshold_rule": core.CLASS0_RULE, "threshold_class0": thr0, "equivalent_p_class1_cutoff": 1 - thr0,
                "cv_pr_auc_class0": float(core.average_precision_score(1 - ytr, 1 - oof)),
                "cv_at_class0_threshold": core.both_class_metrics(ytr, oof, core.predict_class0_threshold(oof, thr0), brief=True),
                "test_at_class0_threshold": core.both_class_metrics(yte, p, core.predict_class0_threshold(p, thr0)),
                "test_at_original_threshold": core.both_class_metrics(yte, p, (p >= thr).astype(int)),
                "test_at_0.5": core.both_class_metrics(yte, p, (p >= 0.5).astype(int))}
        else:
            p = pipe.predict_proba(Xte)
            test_scores[name] = p
            cvm = core.multiclass_metrics(ytr, oof, classes)
            tm = core.multiclass_metrics(yte, p, classes)
            row.update({"cv_pr_auc_macro": cvm["pr_auc_macro"], "cv_pr_auc_macro_sd": float(np.std(fold_scores)),
                        "cv_f1_macro": cvm["f1_macro"],
                        **{f"test_{k}": tm[k] for k in ("accuracy", "precision_macro", "recall_macro", "f1_macro", "f1_weighted",
                                                       "roc_auc_ovr_macro", "pr_auc_macro")},
                        "test_confusion_matrix": tm["confusion_matrix"], "labels": classes,
                        "test_classification_report": tm["classification_report"]})
        rows.append(row)
        joblib.dump({"fingerprint": fp, "row": row, "test_pred": test_scores[name], "oof": oof, "pipe": pipe}, ck_path, compress=3)
        ckpts[name] = ck_path
        oofs[name] = oof
        del pipe, oof; gc.collect()
        print(f"    {spec.task_id:42s} {name:20s} {row.get('cv_pr_auc', row.get('cv_rmse', row.get('cv_pr_auc_macro'))):.4f}  "
              f"({row['fit_seconds']} s)", flush=True)

    # ---------------------------------------------------------------- selection on CV only (never on the test set)
    key, asc = {"binary": ("cv_pr_auc", False), "multiclass": ("cv_pr_auc_macro", False), "regression": ("cv_rmse", True)}[spec.kind]
    table = pd.DataFrame(rows).sort_values(key, ascending=asc)
    cand = table[~table["model"].str.startswith("baseline")]
    best = cand.iloc[0]["model"]
    res["models"] = rows
    res["selection_rule"] = f"highest CV {key}" if not asc else f"lowest CV {key}"
    res["best_model"] = best
    if spec.kind == "binary":
        res["threshold_methodology"] = {"selection": "unchanged: highest CV PR-AUC of class 1",
                                        "original_threshold": "unchanged: threshold_from_cv maximises F1 of class 1 on CV out-of-fold predictions",
                                        "supplementary_threshold": core.CLASS0_RULE}
    base = "logistic_regression" if spec.kind != "regression" else "linear_regression"
    b, l = table.set_index("model").loc[best], table.set_index("model").loc[base]
    res["best_vs_linear_baseline"] = {"metric": key, "best": float(b[key]), "linear_baseline": float(l[key]),
                                      "difference": float(b[key] - l[key]),
                                      "cv_sd_best": float(b.get(key + "_sd", np.nan))}
    if spec.kind == "regression" and spec.persistence_baseline:
        naive = df.loc[te, spec.persistence_baseline].astype(float)
        mask = naive.notna()
        res["persistence_baseline"] = {"column": spec.persistence_baseline, "rows_with_value": int(mask.sum()),
                                       **core.regression_metrics(yte[mask], naive[mask]),
                                       "best_model_on_same_rows": core.regression_metrics(yte[mask], pd.Series(test_scores[best], index=yte.index)[mask])}

    # ---------------------------------------------------------------- plots (test-set predictions only; no models in memory)
    out = core.report_dir("model_evaluation") / spec.zone.lower() / spec.task_id
    out.mkdir(parents=True, exist_ok=True)
    fa = core.report_dir("feature_analysis") / spec.zone.lower()
    fa.mkdir(parents=True, exist_ok=True)
    zone = spec.zone
    ttl = f"{spec.title} — test set"
    if spec.kind == "binary":
        core.plot_curves(yte, {k: v for k, v in test_scores.items() if not k.startswith("baseline")}, ttl, out / "roc_pr_calibration.png", zone)
        r = table.set_index("model").loc[best]
        core.plot_confusion(r["test_confusion_matrix_tuned"], ["0", "1"], f"{best} (threshold {r['threshold_from_cv']:.2f} from CV)",
                            out / f"confusion_{best}.png", zone)
        core.plot_confusion(table.set_index("model").loc[base, "test_confusion_matrix_tuned"], ["0", "1"], f"{base} (CV threshold)",
                            out / f"confusion_{base}.png", zone)
        # supplementary: saved OOF / test predictions and the class-0 threshold view of the selected model
        gcol = spec.group_col if spec.group_col and spec.group_col in df else None
        pd.DataFrame({"row": np.asarray(tr), **({gcol: df.loc[tr, gcol].values} if gcol else {}), "y": np.asarray(ytr),
                      **{f"oof_p1_{k}": v for k, v in oofs.items() if v is not None}}).to_csv(out / "oof_predictions.csv", index=False, float_format="%.9f")
        pd.DataFrame({"row": np.asarray(te), **({gcol: df.loc[te, gcol].values} if gcol else {}), "y": np.asarray(yte),
                      **{f"test_p1_{k}": v for k, v in test_scores.items()}}).to_csv(out / "test_predictions.csv", index=False, float_format="%.9f")
        s0 = r["supplementary_class0"]
        core.plot_confusion(s0["test_at_class0_threshold"]["confusion_matrix"], ["0", "1"],
                            f"{best} (supplementary class-0 threshold: P(0) >= {s0['threshold_class0']:.2f})",
                            out / f"confusion_{best}_class0_threshold.png", zone)
        res["supplementary_class0"] = {"note": "Supplementary evaluation only; model selection (CV PR-AUC of class 1) and the original "
                                               "threshold (F1 of class 1) are unchanged.", "rule": core.CLASS0_RULE, "model": best,
                                       "original_threshold_p_class1": float(r["threshold_from_cv"]),
                                       "class0_threshold_p_class0": s0["threshold_class0"],
                                       "equivalent_p_class1_cutoff": s0["equivalent_p_class1_cutoff"],
                                       "missing_oof_models": [k for k, v in oofs.items() if v is None],
                                       **{k: s0[k] for k in ("cv_pr_auc_class0", "cv_at_class0_threshold", "test_at_original_threshold",
                                                             "test_at_class0_threshold", "test_at_0.5")}}
    elif spec.kind == "multiclass":
        core.plot_confusion(table.set_index("model").loc[best, "test_confusion_matrix"], classes, f"{best}", out / f"confusion_{best}.png", zone)
    else:
        core.plot_regression(yte, test_scores[best], f"{spec.title} — {best}", out / f"actual_vs_predicted_{best}.png", zone)

    # ---------------------------------------------------------------- linear-model coefficients
    lin_pipe = _load_fitted(ckpts, base)
    lin = lin_pipe.named_steps["model"]
    names = lin_pipe.named_steps["prep"].get_feature_names_out()
    coef = lin.coef_ if lin.coef_.ndim == 1 else (lin.coef_[0] if lin.coef_.shape[0] == 1 else np.abs(lin.coef_).mean(0))
    cs = pd.Series(coef, index=names)
    cs.reindex(cs.abs().sort_values(ascending=False).index).rename("coefficient_standardised").to_csv(
        fa / f"{spec.task_id}_coefficients_{base}.csv", header=True)
    res["linear_top10"] = [(k, round(float(v), 4)) for k, v in cs.reindex(cs.abs().sort_values(ascending=False).index).head(10).items()]
    del lin_pipe, lin
    gc.collect()

    # ---------------------------------------------------------------- subgroup results on the test set (best model)
    if spec.kind == "binary" and spec.subgroup_cols:
        thr = float(table.set_index("model").loc[best, "threshold_from_cv"])
        thr0_best = float(table.set_index("model").loc[best, "supplementary_class0"]["threshold_class0"])
        sg = []
        for c in spec.subgroup_cols:
            for v, idx in df.loc[te].groupby(c).groups.items():
                yy = yte.loc[idx]
                if len(yy) < 30 or yy.nunique() < 2:
                    sg.append({"column": c, "value": v, "n": int(len(yy)), "note": "too few rows or one class: not evaluated"})
                    continue
                m = core.binary_metrics(yy, pd.Series(test_scores[best], index=yte.index).loc[idx], thr)
                sg.append({"column": c, "value": v, "n": m["n"], "positives": m["positives"], "recall": m["recall"],
                           "precision": m["precision"], "pr_auc": m["pr_auc"], "roc_auc": m["roc_auc"]})
                pp_sg = pd.Series(test_scores[best], index=yte.index).loc[idx].values
                sg[-1]["supplementary_class0"] = {
                    "at_original_threshold": core.both_class_metrics(yy, pp_sg, (pp_sg >= thr).astype(int), brief=True),
                    "at_class0_threshold": core.both_class_metrics(yy, pp_sg, core.predict_class0_threshold(pp_sg, thr0_best), brief=True)}
        res["subgroups"] = sg

    # ---------------------------------------------------------------- out-of-time robustness (best model refit)
    if spec.oot_cutoff and spec.kind != "multiclass":
        test_groups = set(df.loc[te, spec.group_col])
        trm = (~df[spec.group_col].isin(test_groups)) & (pd.to_datetime(df["label_known_date"]) < spec.oot_cutoff)
        tem = df[spec.group_col].isin(test_groups) & (pd.to_datetime(df["prediction_date"]) >= spec.oot_cutoff)
        oc = leakage.split_checks(df[trm], df[tem], spec.group_col, out_of_time=True)
        if spec.kind == "regression":
            est, scale = core.regressor_factory(best)
        else:
            est, scale = core.classifier_factory(best, y[trm])
        p = core.build_pipeline(est, scale, num, cat).fit(X[trm], y[trm])
        if spec.kind == "regression":
            om = core.regression_metrics(y[tem], p.predict(X[tem]))
        else:
            pp = p.predict_proba(X[tem])[:, 1]
            om = core.binary_metrics(y[tem], pp, float(table.set_index("model").loc[best, "threshold_from_cv"]))
            om = {k: om[k] for k in ("n", "positives", "prevalence", "precision", "recall", "f1", "roc_auc", "pr_auc")}
            oot_thr1 = float(table.set_index("model").loc[best, "threshold_from_cv"])
            oot_thr0 = float(table.set_index("model").loc[best, "supplementary_class0"]["threshold_class0"])
            oot_sup = {"rule": core.CLASS0_RULE, "at_original_threshold": core.both_class_metrics(y[tem], pp, (pp >= oot_thr1).astype(int)),
                       "at_class0_threshold": core.both_class_metrics(y[tem], pp, core.predict_class0_threshold(pp, oot_thr0))}
        res["out_of_time"] = {"cutoff": spec.oot_cutoff, "model": best, "train_rows": int(trm.sum()), "test_rows": int(tem.sum()),
                              "checks": oc, "metrics": om, **({"supplementary_class0": oot_sup} if spec.kind == "binary" else {})}
        res["leakage_checks"] += oc
        del p
        gc.collect()

    # ---------------------------------------------------------------- save essential artifacts BEFORE explainability
    meta = {k: res[k] for k in ("task_id", "dataset", "target", "prediction_point", "target_definition", "population",
                                "features_numeric", "features_categorical", "excluded_leakage_columns", "split", "selection_rule")}
    meta["data_version"] = dv
    meta["test_metrics"] = {k: v for k, v in table.set_index("model").loc[best].items() if k.startswith("test_") and not isinstance(v, (list, dict))}
    if any(not c["passed"] for c in res["leakage_checks"]):
        res["status"] = "BLOCKED_BY_LEAKAGE_CHECK"
        core.write_json(res, out / "results.json")
        raise LeakageError(f"{spec.task_id}: out-of-time check failed {[c for c in res['leakage_checks'] if not c['passed']]}")
    res["saved_models"] = {}
    for nm in dict.fromkeys([best, base]):
        mp = _load_fitted(ckpts, nm)
        res["saved_models"][nm] = core.save_model(mp, zone, spec.task_id, nm, meta)
        del mp
        gc.collect()
    res["status"] = "PARTIAL"
    res["status_note"] = "evaluation, out-of-time test and models saved; explainability (SHAP) not yet finished"
    res["seconds"] = round(time.time() - t0, 1)
    core.write_json(res, out / "results.json")
    core.log_experiment({"task_id": spec.task_id, "zone": zone, "dataset": spec.dataset, "target": spec.target,
                         "best_model": best, "selection_rule": res["selection_rule"], "seed": core.SEED,
                         "metrics": [{k: v for k, v in r.items() if not isinstance(v, (list, dict))} for r in rows],
                         "data_version": meta["data_version"], "artifact_dir": str(out)})

    # ---------------------------------------------------------------- explanations (a failure is recorded, never hidden)
    tree_for_shap = best if best not in ("logistic_regression", "linear_regression") else \
        cand[cand["model"].isin(["xgboost", "lightgbm", "random_forest", "catboost"])].iloc[0]["model"]
    tree_pipe = _load_fitted(ckpts, tree_for_shap)
    try:
        imp = core.shap_importance(tree_pipe, Xte)
        if imp is not None:
            imp.rename("mean_abs_shap").to_csv(fa / f"{spec.task_id}_shap_{tree_for_shap}.csv", header=True)
            core.plot_importance(imp, f"{spec.title}: SHAP importance ({tree_for_shap})", fa / f"{spec.task_id}_shap_{tree_for_shap}.png", zone)
            res["shap_model"] = tree_for_shap
            res["shap_rows"] = getattr(core.shap_importance, "last_rows", None)
            res["shap_top15"] = [(k, round(float(v), 5)) for k, v in imp.head(15).items()]
    except Exception as e:  # recorded, never hidden
        res["shap_error"] = repr(e)
    gc.collect()
    try:
        tm = tree_pipe.named_steps["model"]
        if hasattr(tm, "feature_importances_"):
            gi = core.aggregate_to_source(pd.Series(tm.feature_importances_, index=tree_pipe.named_steps["prep"].get_feature_names_out()), num + cat)
            gi.rename("model_importance").to_csv(fa / f"{spec.task_id}_builtin_importance_{tree_for_shap}.csv", header=True)
    except Exception as e:
        res["importance_error"] = repr(e)
    del tree_pipe
    gc.collect()

    res["seconds"] = round(time.time() - t0, 1)
    res["status"] = "TRAINED"
    res.pop("status_note", None)
    core.write_json(res, out / "results.json")
    import shutil
    shutil.rmtree(ckdir, ignore_errors=True)
    return res
