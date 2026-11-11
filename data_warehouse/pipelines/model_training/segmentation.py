"""Optional: student segmentation (K-Means, Ward hierarchical) and anomaly detection (Isolation Forest) on the
Fall 2026 student snapshot (latest COMPLETED term per currently enrolled student). Descriptive only, synthetic only."""
from __future__ import annotations

import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..feature_engineering.common import MODELING_DIR, SYN_BANNER, data_version
from . import core

ID_COLUMNS = {"student_id", "student_programme_id", "term_id", "programme_id", "level", "school_id"}
SILHOUETTE_GUIDE = "rule of thumb (Kaufman & Rousseeuw): > 0.70 strong, 0.51-0.70 reasonable, 0.26-0.50 weak, <= 0.25 no substantial structure"


def leakage_checks(df: pd.DataFrame, feats: list[str]) -> list[dict]:
    """Unsupervised task: no identifiers or outcome fields as features, completed terms only, one row per student."""
    from .leakage import ALLOWED_DESPITE_PATTERN, FORBIDDEN, UCI_ONLY, UNREPORTABLE_TERMS
    res = []

    def add(cid, ok, detail):
        res.append({"check": cid, "passed": bool(ok), "detail": detail})
    add("S1 no_identifiers_in_features", not set(feats) & ID_COLUMNS, f"overlap {sorted(set(feats) & ID_COLUMNS)}")
    hit = sorted(f for f in feats if FORBIDDEN.search(f) and f not in ALLOWED_DESPITE_PATTERN)
    add("S2 no_outcome_named_features", not hit, f"suspicious feature names {hit}")
    add("S3 zone_purity", not set(df.columns) & UCI_ONLY, f"foreign (UCI) columns {sorted(set(df.columns) & UCI_ONLY)}")
    bad = int(df["term_id"].isin(UNREPORTABLE_TERMS).sum()) if "term_id" in df else 0
    add("S4 completed_terms_only", bad == 0, f"{bad} rows from in-progress/future terms {sorted(UNREPORTABLE_TERMS)}")
    dup = int(df["student_id"].duplicated().sum()) if "student_id" in df else 0
    add("S5 one_row_per_student", dup == 0, f"{dup} duplicated student_id values")
    non_num = [f for f in feats if not pd.api.types.is_numeric_dtype(df[f])]
    add("S6 numeric_features_only", not non_num, f"non-numeric features {non_num}")
    return res


def run() -> dict:
    df = pd.read_csv(MODELING_DIR / "synthetic" / "syn_segmentation_snapshot.csv")
    feats = json.loads((MODELING_DIR / "modeling_manifest.json").read_text())["segmentation_features"]
    checks = leakage_checks(df, feats)
    if not all(c["passed"] for c in checks):
        raise RuntimeError(f"segmentation leakage/data checks failed: {[c for c in checks if not c['passed']]}")
    prep = make_pipeline(SimpleImputer(strategy="median"), StandardScaler())
    Z = prep.fit_transform(df[feats])
    sil = {}
    for k in range(2, 9):
        lab = KMeans(n_clusters=k, n_init=10, random_state=core.SEED).fit_predict(Z)
        sil[k] = float(silhouette_score(Z, lab, sample_size=min(2000, len(Z)), random_state=core.SEED))
    k = max(sil, key=sil.get)
    km = KMeans(n_clusters=k, n_init=10, random_state=core.SEED).fit(Z)
    hc = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(Z)
    df["kmeans_segment"] = km.labels_
    df["ward_segment"] = hc
    prof = df.groupby("kmeans_segment")[feats].median().round(3)
    prof.insert(0, "students", df.groupby("kmeans_segment").size())
    iso = IsolationForest(n_estimators=300, contamination=0.02, random_state=core.SEED).fit(Z)
    df["anomaly_score"] = -iso.score_samples(Z)
    df["is_anomaly"] = iso.predict(Z) == -1
    zc = pd.DataFrame(Z, columns=feats)
    top_dev = zc[df["is_anomaly"].values].abs().mean().sort_values(ascending=False).head(6)
    out = core.report_dir("feature_analysis") / "synthetic"
    out.mkdir(parents=True, exist_ok=True)
    prof.to_csv(out / "segmentation_kmeans_profiles.csv")
    df.assign(label=SYN_BANNER)[["label", "student_id", "level", "school_id", "kmeans_segment", "ward_segment", "anomaly_score", "is_anomaly"]] \
        .to_csv(out / "segmentation_assignments.csv", index=False, float_format="%.4f")
    fig, ax = plt.subplots(figsize=(5, 3.4))
    ax.plot(list(sil), list(sil.values()), "o-"); ax.set(xlabel="k", ylabel="Silhouette", title="K-Means: silhouette by k")
    core._stamp(fig, "SYNTHETIC"); fig.tight_layout(rect=(0, 0.04, 1, 1)); fig.savefig(out / "segmentation_silhouette.png", dpi=110); plt.close(fig)
    res = {"label": SYN_BANNER, "population": "Students enrolled at the Fall 2026 census; features from their latest completed term",
           "n_students": int(len(df)), "features": feats, "silhouette_by_k": sil, "chosen_k": k,
           "kmeans_vs_ward_adjusted_rand": float(adjusted_rand_score(km.labels_, hc)),
           "segment_sizes": df["kmeans_segment"].value_counts().sort_index().to_dict(),
           "isolation_forest": {"contamination": 0.02, "flagged": int(df["is_anomaly"].sum()),
                                "features_most_unusual_among_flagged_mean_abs_z": top_dev.round(2).to_dict()},
           "interpretation": "Segments are descriptive groupings of synthetic records; they are not student types at any real university.",
           "data_version": data_version()}
    # ------------------------------------------------------------------ supplementary diagnostics (added 2026-11-11; nothing above changes)
    from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score
    res["leakage_checks"] = checks
    res["cluster_quality"] = {
        "silhouette_kmeans_chosen_k_full_data": float(silhouette_score(Z, km.labels_)),
        "silhouette_ward_chosen_k_full_data": float(silhouette_score(Z, hc)),
        "davies_bouldin_kmeans": float(davies_bouldin_score(Z, km.labels_)), "calinski_harabasz_kmeans": float(calinski_harabasz_score(Z, km.labels_)),
        "kmeans_seed_stability_adjusted_rand": [float(adjusted_rand_score(km.labels_, KMeans(n_clusters=k, n_init=10, random_state=core.SEED + i).fit_predict(Z)))
                                                for i in range(1, 6)],
        "ward_segment_sizes": pd.Series(hc).value_counts().sort_index().to_dict(), "silhouette_guide": SILHOUETTE_GUIDE}
    s, thr = df["anomaly_score"].to_numpy(), float(-iso.offset_)
    flag = df["is_anomaly"].to_numpy()
    jac = []
    for i in range(1, 6):
        f2 = IsolationForest(n_estimators=300, contamination=0.02, random_state=core.SEED + i).fit(Z).predict(Z) == -1
        jac.append(float((flag & f2).sum() / max((flag | f2).sum(), 1)))
    maxz = np.abs(zc.to_numpy()).max(axis=1)
    rank = pd.Series(s).rank(ascending=False)
    res["anomaly_diagnostics"] = {
        "score_definition": "anomaly_score = -IsolationForest.score_samples (higher = more isolated); flagged when score > threshold",
        "threshold_score": thr, "flagged_share": float(flag.mean()),
        "score_quantiles": {str(q): float(np.quantile(s, q)) for q in (0.5, 0.9, 0.95, 0.98, 0.99, 1.0)},
        "flagged_if_contamination": {str(c): int((rank <= round(c * len(s))).sum()) for c in (0.01, 0.02, 0.05)},
        "seed_stability_jaccard_of_flagged_sets": jac,
        "spearman_score_vs_max_abs_z": float(pd.Series(s).corr(pd.Series(maxz), method="spearman")),
        "flagged_by_level": df.groupby("level")["is_anomaly"].agg(["size", "sum"]).rename(columns={"size": "students", "sum": "flagged"}).to_dict("index"),
        "flagged_by_kmeans_segment": df.groupby("kmeans_segment")["is_anomaly"].agg(["size", "sum"]).rename(columns={"size": "students", "sum": "flagged"}).to_dict("index"),
        "validation_evidence": "None available: the synthetic data contain no ground-truth anomaly labels. Flags mark statistically unusual "
                               "feature combinations only; they are not evidence of error, fraud or misconduct and must not be used to act on individuals."}
    ex = []
    for i in np.where(flag)[0]:
        top = zc.iloc[i].abs().sort_values(ascending=False).head(3)
        ex.append({"label": SYN_BANNER, "student_id": df["student_id"].iloc[i], "anomaly_score": float(s[i]), "level": df["level"].iloc[i],
                   **{f"feature_{j + 1}": f for j, f in enumerate(top.index)}, **{f"z_{j + 1}": float(zc.iloc[i][f]) for j, f in enumerate(top.index)},
                   **{f"value_{j + 1}": float(df[f].iloc[i]) if pd.notna(df[f].iloc[i]) else None for j, f in enumerate(top.index)}})
    pd.DataFrame(ex).sort_values("anomaly_score", ascending=False).to_csv(out / "anomaly_flagged_explanations.csv", index=False, float_format="%.4f")
    fig, ax = plt.subplots(figsize=(5, 3.4))
    ax.hist(s, bins=40); ax.axvline(thr, color="r", ls="--", label=f"threshold ({int(flag.sum())} flagged, 2 %)")
    ax.set(xlabel="anomaly score", ylabel="students", title="Isolation Forest anomaly scores"); ax.legend(fontsize=7)
    core._stamp(fig, "SYNTHETIC"); fig.tight_layout(rect=(0, 0.04, 1, 1)); fig.savefig(out / "anomaly_score_distribution.png", dpi=110); plt.close(fig)
    core.write_json(res, out / "segmentation_results.json")
    core.save_model({"preprocess": prep, "kmeans": km, "isolation_forest": iso, "features": feats}, "SYNTHETIC", "segmentation",
                    "kmeans_isolation_forest", {"chosen_k": k, "silhouette": sil[k]})
    return res
