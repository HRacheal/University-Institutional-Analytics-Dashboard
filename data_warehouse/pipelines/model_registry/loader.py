"""Load saved model artifacts (once, cached) and score new rows with the exact saved preprocessing and thresholds.

Used by the dashboard backend and by the restoration audit. No model is (re)trained here.
"""
from __future__ import annotations

import json
import threading
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import DW_ROOT, MANIFEST_PATH


PORTABLE_NOTE = ("loaded from the portable XGBoost export (<stem>.portable.joblib + <stem>.booster.json, created with "
                 "Booster.save_model from the original artifact, predictions verified identical); the original pickle's "
                 "internal XGBoost serialisation could not be read by this platform's XGBoost build")


def load_artifact(path: Path):
    """joblib.load with a fallback for XGBoost pickles that do not deserialise across platforms.

    Returns (object, loaded_via). The fallback never alters the original artifact: it reads the sidecar files exported
    from that same artifact (sklearn pipeline without booster + XGBoost JSON model)."""
    path = Path(path)
    try:
        return joblib.load(path), "original_pickle"
    except Exception as ex:
        shell_p = path.with_name(path.stem + ".portable.joblib")
        booster_p = path.with_name(path.stem + ".booster.json")
        if "XGBoost" not in type(ex).__name__ + str(ex) or not (shell_p.exists() and booster_p.exists()):
            raise
        import xgboost as xgb
        obj = joblib.load(shell_p)
        est = obj.steps[-1][1] if hasattr(obj, "steps") else obj
        b = xgb.Booster()
        b.load_model(str(booster_p))
        est._Booster = b
        return obj, "portable_xgboost_json"


class ArtifactError(RuntimeError):
    """A required artifact is missing, corrupt or incompatible with the current environment."""


class InputValidationError(ValueError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


def _env() -> dict:
    import platform

    import sklearn
    out = {"python": platform.python_version(), "sklearn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__}
    for mod in ("xgboost", "lightgbm", "catboost", "statsmodels"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:          # pragma: no cover - optional dependency missing
            out[mod] = None
    return out


@dataclass
class Prepared:
    X: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    imputed: dict = field(default_factory=dict)        # column -> number of missing values handled by the saved imputer


@dataclass
class LoadedModel:
    task: str
    name: str
    kind: str
    obj: object
    meta: dict
    entry: dict
    version_warnings: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- input validation using the saved feature definitions
    @property
    def numeric(self) -> list[str]:
        return list(self.entry.get("features_numeric") or self.meta.get("features_numeric") or [])

    @property
    def categorical(self) -> list[str]:
        return list(self.entry.get("features_categorical") or self.meta.get("features_categorical") or [])

    def prepare(self, df: pd.DataFrame) -> Prepared:
        if not isinstance(df, pd.DataFrame) or df.empty:
            raise InputValidationError("no input rows")
        need = self.numeric + self.categorical
        missing = [c for c in need if c not in df.columns]
        if missing:
            raise InputValidationError(f"{len(missing)} required feature column(s) missing", {"missing_columns": missing})
        X = df[need].copy()
        bad, imputed = {}, {}
        for c in self.numeric:
            raw = X[c]
            conv = pd.to_numeric(raw.replace({"": np.nan}), errors="coerce")
            nonnum = raw.notna() & (raw.astype(str).str.strip() != "") & conv.isna()
            if nonnum.any():
                bad[c] = raw[nonnum].astype(str).head(3).tolist()
            inf = np.isinf(conv)
            if inf.any():
                bad[c] = ["inf"]
            X[c] = conv.astype(float)
            if X[c].isna().any():
                imputed[c] = int(X[c].isna().sum())
        if bad:
            raise InputValidationError("non-numeric values in numeric feature(s)", {"invalid_values": bad})
        for c in self.categorical:                       # identical to training: string, missing -> "MISSING"
            if X[c].isna().any():
                imputed[c] = int(X[c].isna().sum())
            X[c] = X[c].astype("string").fillna("MISSING").astype(object)
        w = [f"{len(imputed)} feature(s) had missing values; the saved pipeline's imputer handled them"] if imputed else []
        return Prepared(X, w, imputed)

    # ---------------------------------------------------------------- scoring
    def predict(self, df: pd.DataFrame) -> dict:
        p = self.prepare(df)
        th = (self.entry.get("models", {}).get(self.name, {}) or {}).get("thresholds") or {}
        out = {"task": self.task, "model": self.name, "kind": self.kind, "n": len(p.X), "warnings": p.warnings + self.version_warnings,
               "imputed_missing": p.imputed}
        if self.kind == "binary":
            p1 = self.obj.predict_proba(p.X)[:, 1].astype(float)
            out["p_class1"] = p1
            if "original_p_class1" in th:
                out["threshold_original"] = th["original_p_class1"]
                out["pred_original"] = (p1 >= th["original_p_class1"]).astype(int)
            if "supplementary_class0_p_class0" in th:
                out["threshold_supplementary_class0"] = th["supplementary_class0_p_class0"]
                out["pred_supplementary_class0"] = np.where(1 - p1 >= th["supplementary_class0_p_class0"], 0, 1)
        elif self.kind == "multiclass":
            proba = self.obj.predict_proba(p.X).astype(float)
            labels = self.entry.get("labels") or [str(c) for c in getattr(self.obj, "classes_", range(proba.shape[1]))]
            out["labels"], out["proba"] = labels, proba
            out["pred_label"] = [labels[i] for i in proba.argmax(1)]
        elif self.kind == "regression":
            out["prediction"] = self.obj.predict(p.X).astype(float)
        return out

    def explain(self, df: pd.DataFrame, top: int = 8) -> list[list[dict]]:
        """Per-row contributions in model space, summed back to the original features (linear: coef x scaled value;
        trees: TreeSHAP). Returns [] when the model type is not supported."""
        from ..model_training.core import aggregate_to_source
        p = self.prepare(df)
        prep, model = self.obj.named_steps["prep"], self.obj.named_steps["model"]
        Z = prep.transform(p.X)
        names = prep.get_feature_names_out()
        Zd = np.asarray(Z.toarray() if hasattr(Z, "toarray") else Z, dtype=float)
        # Direction of attribution: binary -> towards class 1; multiclass -> towards each row's predicted class.
        # (Averaging over classes would cancel: binary class-0 and class-1 contributions are exact negatives.)
        pred_k = np.asarray(model.predict_proba(Z)).argmax(1) if hasattr(model, "predict_proba") else None
        if hasattr(model, "coef_"):
            coef = np.asarray(model.coef_)
            if coef.ndim == 1 or coef.shape[0] == 1:
                contrib = Zd * coef.reshape(-1)
            else:
                contrib = Zd * coef[pred_k]
        else:
            try:
                import shap
                sv = shap.TreeExplainer(model).shap_values(Z)
            except Exception:
                return []
            if isinstance(sv, list):                         # older shap: one (n, f) array per class
                sv = np.stack(sv, axis=-1)
            sv = np.asarray(sv)
            if sv.ndim == 2:                                 # single output (regression, or binary log-odds for boosters)
                contrib = sv
            elif sv.shape[-1] == 2:
                contrib = sv[..., 1]
            else:
                contrib = sv[np.arange(sv.shape[0]), :, pred_k]
        res = []
        for i in range(len(p.X)):
            s = aggregate_to_source(pd.Series(contrib[i], index=names), list(p.X.columns))
            s = s.reindex(s.abs().sort_values(ascending=False).index).head(top)
            res.append([{"feature": f, "contribution": float(v), "value": None if pd.isna(p.X.iloc[i][f]) else
                         (p.X.iloc[i][f] if isinstance(p.X.iloc[i][f], str) else float(p.X.iloc[i][f]))} for f, v in s.items()])
        return res


@dataclass
class LoadedCox(LoadedModel):
    def predict(self, df: pd.DataFrame) -> dict:
        from ..model_training.survival import COX_NUMERIC, _design
        missing = [c for c in COX_NUMERIC + ["level"] if c not in df.columns]
        if missing:
            raise InputValidationError(f"{len(missing)} required covariate column(s) missing", {"missing_columns": missing})
        d = df.copy()
        for c in COX_NUMERIC:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        o = self.obj
        X, *_ = _design(d, o["means"], o["sds"], o["levels"])
        params = o["params"]
        lp = X[list(params.index)].to_numpy() @ params.to_numpy()
        unknown = sorted(set(d["level"].astype(str)) - set(map(str, o["levels"])))
        return {"task": self.task, "model": self.name, "kind": "survival", "n": len(d), "linear_predictor": lp,
                "relative_hazard": np.exp(lp), "level": d["level"].astype(str).tolist(),
                "warnings": ([f"unknown level(s) {unknown}: no baseline stratum in the model"] if unknown else []) + self.version_warnings,
                "interpretation": "relative hazard vs. a student at the training mean of every covariate within the same level "
                                  "(stratum); > 1 = event expected sooner. Not an absolute probability."}


@dataclass
class LoadedSegmentation(LoadedModel):
    def predict(self, df: pd.DataFrame) -> dict:
        o = self.obj
        feats = list(o["features"])
        missing = [c for c in feats if c not in df.columns]
        if missing:
            raise InputValidationError(f"{len(missing)} required feature column(s) missing", {"missing_columns": missing})
        X = df[feats].apply(pd.to_numeric, errors="coerce")
        Z = o["preprocess"].transform(X)
        score = -o["isolation_forest"].score_samples(Z)
        thr = float(-o["isolation_forest"].offset_)
        return {"task": self.task, "model": self.name, "kind": "segmentation", "n": len(X), "segment": o["kmeans"].predict(Z).astype(int),
                "anomaly_score": score, "anomaly_threshold": thr, "is_anomaly": score > thr, "warnings": self.version_warnings,
                "interpretation": "anomaly = statistically unusual feature combination; not evidence of error, fraud or misconduct"}


class ModelRegistry:
    """Thread-safe, lazily loading cache of the saved models listed in the artifact manifest."""

    def __init__(self, root: Path = DW_ROOT, manifest_path: Path | None = None, artifact_root: Path | None = None):
        self.root = Path(root)
        self.artifact_root = Path(artifact_root) if artifact_root else self.root
        mp = Path(manifest_path) if manifest_path else (self.root / MANIFEST_PATH.relative_to(DW_ROOT))
        if not mp.exists():
            raise ArtifactError(f"artifact manifest not found: {mp}")
        self.manifest = json.loads(mp.read_text(encoding="utf-8"))
        self._cache: dict[tuple, LoadedModel] = {}
        self._errors: dict[tuple, str] = {}
        self._lock = threading.Lock()
        self.env = _env()

    @property
    def tasks(self) -> dict:
        return self.manifest["tasks"]

    def resolve(self, rel: str) -> Path:
        return self.artifact_root / rel

    def available(self, task: str, name: str | None = None) -> bool:
        e = self.tasks.get(task, {})
        name = name or e.get("selected_model")
        m = (e.get("models") or {}).get(name)
        return bool(m) and self.resolve(m["path"]).exists()

    def get(self, task: str, name: str | None = None, verify_sha: bool = True) -> LoadedModel:
        if task not in self.tasks:
            raise ArtifactError(f"unknown task {task!r}")
        e = self.tasks[task]
        name = name or e.get("selected_model")
        if not name or name not in (e.get("models") or {}):
            raise ArtifactError(f"task {task!r} has no saved model {name!r}")
        key = (task, name)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            m = e["models"][name]
            path = self.resolve(m["path"])
            if not path.exists():
                raise ArtifactError(f"model file not restored: {m['path']} (run: python -m pipelines.model_registry.restore --source <Drive outputs>)")
            fe = self.manifest["files"].get(m["path"], {})
            if verify_sha and fe.get("sha256"):
                from .manifest import sha256
                if sha256(path) != fe["sha256"]:
                    raise ArtifactError(f"SHA-256 mismatch for {m['path']}: the local file is not the backed-up artifact")
            meta_p = self.resolve(m["meta"])
            meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    obj, loaded_via = load_artifact(path)
                except Exception as ex:
                    self._errors[key] = repr(ex)
                    raise ArtifactError(f"could not load {m['path']}: {ex!r} (trained with {meta.get('environment')}, running {self.env})") from ex
            vw = sorted({str(w.message)[:200] for w in caught if "version" in str(w.message).lower()})
            cls = {"survival": LoadedCox, "segmentation": LoadedSegmentation}.get(e["kind"], LoadedModel)
            lm = cls(task, name, e["kind"], obj, meta, e, [f"version warning: {v}" for v in vw] + ([PORTABLE_NOTE] if loaded_via != "original_pickle" else []))
            lm.loaded_via = loaded_via
            self._cache[key] = lm
            return lm

    def status(self) -> list[dict]:
        out = []
        for t, e in self.tasks.items():
            sel = e.get("selected_model")
            row = {"task": t, "module": e["module"], "kind": e.get("kind"), "status": e.get("status"), "selected_model": sel,
                   "artifact_present": self.available(t) if sel else None, "loaded": (t, sel) in self._cache,
                   "load_error": self._errors.get((t, sel))}
            if e.get("kind") == "forecasting":
                row["artifact_present"] = self.resolve("reports/forecasting/forecasts_selected_method.csv").exists()
            out.append(row)
        return out
