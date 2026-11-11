"""Shared training utilities: preprocessing pipelines, model factory, splits, metrics, plots, artifact saving, tracking."""
from __future__ import annotations

import json
import platform
import time
import warnings
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import sklearn  # noqa: E402
from sklearn.calibration import calibration_curve  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.dummy import DummyClassifier, DummyRegressor  # noqa: E402
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor  # noqa: E402
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.linear_model import LogisticRegression, Ridge  # noqa: E402
from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss, classification_report,  # noqa: E402
                             confusion_matrix, f1_score, mean_absolute_error, mean_squared_error, precision_recall_curve,
                             precision_recall_fscore_support, precision_score, r2_score, recall_score, roc_auc_score)
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # noqa: E402

from ..feature_engineering.common import EXPERIMENTS_DIR, MODELS_DIR, REPORTS_DIR, SYN_BANNER, UCI_BANNER  # noqa: E402

SEED = 20261110
# Random-forest worker threads. RF results do not depend on n_jobs (fixed random_state), so this only trades speed for
# memory on low-RAM machines. Override with UIAD_RF_JOBS (e.g. -1 for all cores).
RF_JOBS = int(__import__("os").environ.get("UIAD_RF_JOBS", "2"))
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def banner(zone: str) -> str:
    return SYN_BANNER if zone == "SYNTHETIC" else UCI_BANNER


# ---------------------------------------------------------------------------------------------------------- preprocessing
def make_preprocessor(numeric: list[str], categorical: list[str], scale: bool) -> ColumnTransformer:
    """Fitted inside the model pipeline, i.e. on training data only."""
    num_steps = [("impute", SimpleImputer(strategy="median", add_indicator=True))]
    if scale:
        num_steps.append(("scale", StandardScaler()))
    cat = Pipeline([("impute", SimpleImputer(strategy="constant", fill_value="MISSING")),
                    ("onehot", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=20, sparse_output=False))])
    return ColumnTransformer([("num", Pipeline(num_steps), numeric), ("cat", cat, categorical)], verbose_feature_names_out=False)


def classifier_factory(name: str, y: pd.Series, n_classes: int = 2):
    pos_weight = float((y == 0).sum() / max((y == 1).sum(), 1)) if n_classes == 2 else 1.0
    if name == "baseline_majority":
        return DummyClassifier(strategy="prior"), False
    if name == "logistic_regression":
        return LogisticRegression(max_iter=3000, class_weight="balanced", C=0.5, random_state=SEED), True
    if name == "random_forest":
        return RandomForestClassifier(n_estimators=300, min_samples_leaf=5, max_features="sqrt", class_weight="balanced_subsample",
                                      n_jobs=RF_JOBS, random_state=SEED), False
    if name == "xgboost":
        from xgboost import XGBClassifier
        kw = dict(scale_pos_weight=pos_weight) if n_classes == 2 else {}
        return XGBClassifier(n_estimators=400, learning_rate=0.05, max_depth=4, subsample=0.8, colsample_bytree=0.8,
                             min_child_weight=3, reg_lambda=1.0, tree_method="hist", n_jobs=4, random_state=SEED,
                             eval_metric="logloss" if n_classes == 2 else "mlogloss", **kw), False
    if name == "lightgbm":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=20, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8, class_weight="balanced", n_jobs=4, random_state=SEED,
                              verbose=-1), False
    if name == "catboost":
        from catboost import CatBoostClassifier
        return CatBoostClassifier(iterations=500, learning_rate=0.05, depth=5, auto_class_weights="Balanced", random_seed=SEED,
                                  verbose=0, thread_count=4, allow_writing_files=False), False
    raise ValueError(name)


def regressor_factory(name: str):
    if name == "baseline_mean":
        return DummyRegressor(strategy="mean"), False
    if name == "linear_regression":
        # L2-regularised (ridge) linear model, like the C=0.5 logistic baseline. Plain OLS is unusable here: the panel
        # features are exactly collinear (e.g. completed_terms vs study_term_number, duplicate missing indicators; design
        # rank 123 of 163), which gave coefficients ~1e12 and a CV RMSE of 5e9 on syn_next_term_gpa.
        return Ridge(alpha=1.0, random_state=SEED), True
    if name == "random_forest":
        return RandomForestRegressor(n_estimators=300, min_samples_leaf=5, max_features=0.5, n_jobs=RF_JOBS, random_state=SEED), False
    if name == "xgboost":
        from xgboost import XGBRegressor
        return XGBRegressor(n_estimators=400, learning_rate=0.05, max_depth=4, subsample=0.8, colsample_bytree=0.8,
                            min_child_weight=3, tree_method="hist", n_jobs=4, random_state=SEED), False
    if name == "lightgbm":
        from lightgbm import LGBMRegressor
        return LGBMRegressor(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=20, subsample=0.8,
                             subsample_freq=1, colsample_bytree=0.8, n_jobs=4, random_state=SEED, verbose=-1), False
    raise ValueError(name)


def build_pipeline(model, scale: bool, numeric, categorical) -> Pipeline:
    return Pipeline([("prep", make_preprocessor(numeric, categorical, scale)), ("model", model)])


# ---------------------------------------------------------------------------------------------------------- splits
def grouped_holdout(df: pd.DataFrame, y: pd.Series, groups: pd.Series, test_share: float = 0.25):
    """Untouched test set made of whole groups (students), stratified on the label."""
    k = int(round(1 / test_share))
    sgkf = StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=SEED)
    tr, te = next(sgkf.split(df, y, groups))
    return df.index[tr], df.index[te]


def cv_splits(X, y, groups=None, k: int = 5):
    if groups is not None:
        return list(StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=SEED).split(X, y, groups))
    return list(StratifiedKFold(n_splits=k, shuffle=True, random_state=SEED).split(X, y))


def regression_cv_splits(X, y, groups, k: int = 5):
    bins = pd.qcut(y.rank(method="first"), 5, labels=False)
    return list(StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=SEED).split(X, bins, groups))


# ---------------------------------------------------------------------------------------------------------- metrics
def best_f1_threshold(y, p) -> float:
    pr, rc, th = precision_recall_curve(y, p)
    f1 = 2 * pr * rc / np.clip(pr + rc, 1e-9, None)
    return float(th[np.nanargmax(f1[:-1])]) if len(th) else 0.5


# Supplementary class-0 view (added 2026-11-11). It never changes model selection or the original class-1 threshold above; it
# reports how well each model finds class 0 (e.g. students who are NOT retained) at a threshold tuned for class 0 on CV.
CLASS0_RULE = ("supplementary threshold: maximise F1 of class 0 on CV out-of-fold predictions; predict class 0 when "
               "P(class 0) = 1 - P(class 1) >= threshold_class0")


def best_f1_threshold_class0(y, p1) -> float:
    """Threshold on P(class 0) maximising F1 of class 0 (same search as best_f1_threshold, with the classes swapped)."""
    return best_f1_threshold(1 - np.asarray(y, dtype=int), 1 - np.asarray(p1, dtype=float))


def predict_class0_threshold(p1, threshold_class0: float) -> np.ndarray:
    """0 where P(class 0) >= threshold_class0, else 1."""
    return np.where(1 - np.asarray(p1, dtype=float) >= threshold_class0, 0, 1)


def both_class_metrics(y, p1, yhat, brief: bool = False) -> dict:
    """Precision / recall / F1 / support for BOTH classes, confusion matrix and accuracy for given hard predictions."""
    y, p1, yhat = np.asarray(y, dtype=int), np.asarray(p1, dtype=float), np.asarray(yhat, dtype=int)
    pr, rc, f1, sup = precision_recall_fscore_support(y, yhat, labels=[0, 1], zero_division=0)
    out = {"n": int(len(y)), "predicted_class0": int((yhat == 0).sum()), "accuracy": float(accuracy_score(y, yhat)),
           "confusion_matrix": confusion_matrix(y, yhat, labels=[0, 1]).tolist(),
           "class0": {"precision": float(pr[0]), "recall": float(rc[0]), "f1": float(f1[0]), "support": int(sup[0])},
           "class1": {"precision": float(pr[1]), "recall": float(rc[1]), "f1": float(f1[1]), "support": int(sup[1])},
           "macro_f1": float(np.mean(f1))}
    if not brief:
        two = len(np.unique(y)) == 2
        out.update({"roc_auc": float(roc_auc_score(y, p1)) if two else None,
                    "pr_auc_class1": float(average_precision_score(y, p1)) if two else None,
                    "pr_auc_class0": float(average_precision_score(1 - y, 1 - p1)) if two else None})
    return out


def binary_metrics(y, p, threshold: float) -> dict:
    yhat = (p >= threshold).astype(int)
    return {"n": int(len(y)), "positives": int(y.sum()), "prevalence": float(y.mean()), "threshold": float(threshold),
            "accuracy": accuracy_score(y, yhat), "precision": precision_score(y, yhat, zero_division=0),
            "recall": recall_score(y, yhat, zero_division=0), "f1": f1_score(y, yhat, zero_division=0),
            "roc_auc": roc_auc_score(y, p) if y.nunique() == 2 else np.nan,
            "pr_auc": average_precision_score(y, p) if y.nunique() == 2 else np.nan,
            "brier": brier_score_loss(y, p), "confusion_matrix": confusion_matrix(y, yhat, labels=[0, 1]).tolist(),
            "classification_report": classification_report(y, yhat, zero_division=0, output_dict=True)}


def multiclass_metrics(y, proba, classes) -> dict:
    yhat = np.asarray(classes)[proba.argmax(1)]
    return {"n": int(len(y)), "accuracy": accuracy_score(y, yhat),
            "precision_macro": precision_score(y, yhat, average="macro", zero_division=0),
            "recall_macro": recall_score(y, yhat, average="macro", zero_division=0),
            "f1_macro": f1_score(y, yhat, average="macro", zero_division=0),
            "f1_weighted": f1_score(y, yhat, average="weighted", zero_division=0),
            "roc_auc_ovr_macro": roc_auc_score(y, proba, multi_class="ovr", average="macro", labels=classes),
            "pr_auc_macro": float(np.mean([average_precision_score((y == c).astype(int), proba[:, i]) for i, c in enumerate(classes)])),
            "confusion_matrix": confusion_matrix(y, yhat, labels=classes).tolist(), "labels": list(classes),
            "classification_report": classification_report(y, yhat, zero_division=0, output_dict=True)}


def regression_metrics(y, yhat) -> dict:
    return {"n": int(len(y)), "mae": mean_absolute_error(y, yhat), "rmse": float(np.sqrt(mean_squared_error(y, yhat))),
            "r2": r2_score(y, yhat)}


def wape(y, yhat) -> float:
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    return float(np.abs(y - yhat).sum() / max(np.abs(y).sum(), 1e-9))


# ---------------------------------------------------------------------------------------------------------- plots
def _stamp(fig, zone: str):
    fig.text(0.5, 0.005, banner(zone) if zone == "SYNTHETIC" else "UCI research dataset (Realinho et al., 2021) — not this university",
             ha="center", va="bottom", fontsize=7, color="#b00020" if zone == "SYNTHETIC" else "#333333")


def plot_confusion(cm, labels, title, path: Path, zone: str):
    cm = np.asarray(cm)
    fig, ax = plt.subplots(figsize=(4.2, 3.8))
    ax.imshow(cm, cmap="Blues")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, f"{cm[i, j]:,}", ha="center", va="center", color="white" if cm[i, j] > cm.max() / 2 else "black", fontsize=9)
    ax.set_xticks(range(len(labels)), labels, fontsize=8); ax.set_yticks(range(len(labels)), labels, fontsize=8)
    ax.set_xlabel("Predicted"); ax.set_ylabel("Actual"); ax.set_title(title, fontsize=9)
    _stamp(fig, zone); fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(path, dpi=110); plt.close(fig)


def plot_curves(y, probs: dict, title, path: Path, zone: str):
    from sklearn.metrics import roc_curve
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
    for name, p in probs.items():
        fpr, tpr, _ = roc_curve(y, p); axes[0].plot(fpr, tpr, label=f"{name} ({roc_auc_score(y, p):.3f})", lw=1.2)
        pr, rc, _ = precision_recall_curve(y, p); axes[1].plot(rc, pr, label=f"{name} ({average_precision_score(y, p):.3f})", lw=1.2)
        fp, mp = calibration_curve(y, p, n_bins=10, strategy="quantile"); axes[2].plot(mp, fp, marker="o", ms=3, lw=1, label=name)
    axes[0].plot([0, 1], [0, 1], "k--", lw=0.7); axes[0].set(xlabel="False positive rate", ylabel="True positive rate", title="ROC")
    axes[1].axhline(np.mean(y), color="k", ls="--", lw=0.7); axes[1].set(xlabel="Recall", ylabel="Precision", title="Precision-recall")
    axes[2].plot([0, 1], [0, 1], "k--", lw=0.7); axes[2].set(xlabel="Mean predicted probability", ylabel="Observed rate", title="Calibration")
    for a in axes:
        a.legend(fontsize=6.5, loc="best")
    fig.suptitle(title, fontsize=10); _stamp(fig, zone); fig.tight_layout(rect=(0, 0.03, 1, 0.95)); fig.savefig(path, dpi=110); plt.close(fig)


def plot_regression(y, yhat, title, path: Path, zone: str):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
    axes[0].scatter(y, yhat, s=4, alpha=0.3); lim = [min(np.min(y), np.min(yhat)), max(np.max(y), np.max(yhat))]
    axes[0].plot(lim, lim, "k--", lw=0.8); axes[0].set(xlabel="Actual", ylabel="Predicted", title="Actual vs predicted")
    r = np.asarray(y) - np.asarray(yhat)
    axes[1].scatter(yhat, r, s=4, alpha=0.3); axes[1].axhline(0, color="k", lw=0.8)
    axes[1].set(xlabel="Predicted", ylabel="Residual (actual - predicted)", title="Residuals")
    fig.suptitle(title, fontsize=10); _stamp(fig, zone); fig.tight_layout(rect=(0, 0.03, 1, 0.95)); fig.savefig(path, dpi=110); plt.close(fig)


def plot_importance(imp: pd.Series, title, path: Path, zone: str, xlabel="Mean |SHAP value|"):
    imp = imp.sort_values().tail(20)
    fig, ax = plt.subplots(figsize=(7, 0.28 * len(imp) + 1.2))
    ax.barh(imp.index, imp.values, color="#3b6ea8"); ax.set_xlabel(xlabel); ax.set_title(title, fontsize=9)
    ax.tick_params(axis="y", labelsize=7)
    _stamp(fig, zone); fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(path, dpi=110); plt.close(fig)


# ---------------------------------------------------------------------------------------------------------- explainability
def shap_importance(pipe: Pipeline, X: pd.DataFrame, max_rows: int = 1500) -> pd.Series | None:
    """Mean |SHAP| per original (pre-encoding) feature for tree models; one-hot columns are summed back to their source."""
    import shap
    model = pipe.named_steps["model"]
    if not hasattr(model, "feature_importances_") and not type(model).__name__.startswith("CatBoost"):
        return None
    if type(model).__name__ == "RandomForestRegressor":
        # Exact TreeSHAP cost grows with leaves x depth^2; 300 deep regression trees on 1,500 rows ran for hours on an
        # 8 GB machine. 300 rows is enough to rank mean |SHAP| per feature.
        max_rows = min(max_rows, 300)
    Xs = X.sample(min(max_rows, len(X)), random_state=SEED)
    shap_importance.last_rows = len(Xs)
    Z = pipe.named_steps["prep"].transform(Xs)
    names = pipe.named_steps["prep"].get_feature_names_out()
    sv = shap.TreeExplainer(model).shap_values(Z)
    if isinstance(sv, list):
        sv = np.abs(np.stack(sv)).mean(0)
    sv = np.abs(np.asarray(sv))
    if sv.ndim == 3:
        sv = sv.mean(2)
    per_col = pd.Series(sv.mean(0), index=names)
    return aggregate_to_source(per_col, list(X.columns))


def aggregate_to_source(per_col: pd.Series, sources: list[str]) -> pd.Series:
    out = {}
    for n, v in per_col.items():
        base = n.replace("missingindicator_", "")
        src = base if base in sources else next((s for s in sorted(sources, key=len, reverse=True) if base.startswith(s + "_")), base)
        out[src] = out.get(src, 0.0) + float(v)
    return pd.Series(out).sort_values(ascending=False)


# ---------------------------------------------------------------------------------------------------------- saving & tracking
def env_info() -> dict:
    import catboost, lightgbm, statsmodels, xgboost  # noqa: E401
    return {"python": platform.python_version(), "sklearn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__,
            "xgboost": xgboost.__version__, "lightgbm": lightgbm.__version__, "catboost": catboost.__version__,
            "statsmodels": statsmodels.__version__, "seed": SEED}


def save_model(obj, zone: str, task: str, model_name: str, meta: dict) -> str:
    d = MODELS_DIR / zone.lower() / task
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(obj, d / f"{model_name}.joblib", compress=3)
    status = ("DEMONSTRATION_ONLY — trained on synthetic data; NOT production-ready and NOT valid for real students"
              if zone == "SYNTHETIC" else "RESEARCH_ONLY — trained on the public UCI dataset; not calibrated to this university")
    meta = {**meta, "zone": zone, "task": task, "model": model_name, "deployment_status": status, "label": banner(zone),
            "environment": env_info()}
    (d / f"{model_name}.meta.json").write_text(json.dumps(meta, indent=2, default=_json_default), encoding="utf-8")
    return (d / f"{model_name}.joblib").relative_to(MODELS_DIR.parent).as_posix()   # portable (Batch 1 stored Windows paths)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def log_experiment(record: dict):
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    record = {"logged_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **record}
    with open(EXPERIMENTS_DIR / "experiment_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=_json_default) + "\n")


def write_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=_json_default), encoding="utf-8")


def report_dir(kind: str) -> Path:
    d = REPORTS_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d
