"""Graduation rates and time to completion from registrar/graduation_records (definitions: metrics.graduation_rates)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import T, Filters, apply_filters, cached, envelope, label, pct, students, term_label

DEFINITIONS = {
    "cohort": "LEVEL_ENTRY cohort: students entering a level (Undergraduate, Master's, Doctorate) in a term; first admission at that level.",
    "completion_period": "Undergraduate 6 years, Doctorate 6 years, Master's 4 years from the entry term start (project-configured reporting "
                         "assumptions; level_rules DEMO-RULES-1, not verified policy).",
    "graduated_within_period": "Graduation date on or before entry-term start + completion period.",
    "graduation_rate": "graduated within period / cohort size. Published only for MATURE cohorts (period ended on/before the as-of date "
                       "and every term up to the window end is complete). Immature cohorts show progress so far, no rate.",
    "not_yet_graduated": "Cohort members without a graduation (still enrolled, stopped out, or left).",
    "time_to_completion": "Years from admission at the level to graduation, graduates only (within or after the period).",
}
LIMITATIONS = ["Actual graduation statistics only; model predictions (graduation likelihood, survival) are shown separately.",
               "Completion periods are project assumptions until confirmed by the institution.", "Synthetic sample data."]
MAP = {"school_id": "school_at_entry", "programme_id": "programme_at_entry"}


@cached
def records() -> pd.DataFrame:
    g = T("registrar/graduation_records").merge(students(), on="student_id", how="left")
    g["cohort_mature"] = g["cohort_mature"].astype(str) == "True"
    g["entry_year"] = g["entry_term_id"].str[:4].astype(int)
    return g


def _rate(g: pd.DataFrame) -> dict:
    n = len(g)
    mature = bool(g["cohort_mature"].all())
    st = g["graduation_status"].value_counts()
    grads = int(g["graduation_status"].str.startswith("GRADUATED").sum())
    within = int(st.get("GRADUATED_WITHIN_WINDOW", 0))
    r = {"cohort_size": n, "is_final": mature, "graduated_so_far": grads, "graduated_within_period": within,
         "graduated_after_period": int(st.get("GRADUATED_AFTER_WINDOW", 0)), "not_yet_graduated": n - grads,
         "still_enrolled": int(st.get("ENROLLED_NOT_GRADUATED", 0)), "left": int(st.get("LEFT_NOT_GRADUATED", 0)),
         "stopped_out": int(st.get("STOPPED_OUT_NOT_GRADUATED", 0)),
         "reporting_label": "FINAL" if mature else "INCOMPLETE: completion period still open"}
    if mature:
        r["graduation_rate_pct"] = pct(within, n)
    else:
        r["graduated_within_period_so_far_pct"] = pct(within, n)
    return r


@cached
def summary(f: Filters) -> dict:
    g = apply_filters(records(), Filters(**{**f.active(), "academic_year": None, "season": None, "delivery_mode": None, "study_load": None}), MAP)
    if g.empty:
        return envelope("graduation", "REGISTRAR", {"message": "no cohort records match the filters"}, DEFINITIONS, f, LIMITATIONS)
    cohorts = []
    for (lv, et), x in sorted(g.groupby(["level", "entry_term_id"]), key=lambda k: (k[0][0], k[0][1])):
        cohorts.append({"level": lv, "entry_term_id": et, "entry_label": term_label(et), "window_years": int(x["window_years"].iloc[0]),
                        "window_end_date": x["window_end_date"].iloc[0], **_rate(x)})
    mature = g[g["cohort_mature"]]
    by_level = [{"key": lv, "label": lv.title(), "window_years": int(x["window_years"].iloc[0]), **_rate(x)} for lv, x in mature.groupby("level")]
    by_prog = [{"key": k, "label": label("programme_id", k), "level": x["level"].iloc[0], **_rate(x)} for k, x in mature.groupby("programme_at_entry")]
    by_school = [{"key": k, "label": label("school_id", k), **_rate(x)} for k, x in mature.groupby("school_at_entry")]
    by_year = [{"level": lv, "entry_year": int(y), **_rate(x)} for (lv, y), x in g.groupby(["level", "entry_year"])]
    gr = g[g["graduation_status"].str.startswith("GRADUATED")]
    ttd = []
    for lv, x in gr.groupby("level"):
        t = x["time_to_degree_years"].astype(float)
        ttd.append({"level": lv, "graduates": int(len(x)), "median_years": round(float(t.median()), 2), "mean_years": round(float(t.mean()), 2),
                    "p25_years": round(float(t.quantile(.25)), 2), "p75_years": round(float(t.quantile(.75)), 2),
                    "within_period_share_pct": pct((x["graduation_status"] == "GRADUATED_WITHIN_WINDOW").sum(), len(x))})
    hist = []
    for lv, x in gr.groupby("level"):
        t = x["time_to_degree_years"].astype(float)
        bins = np.arange(0, max(10, np.ceil(t.max()) + 1), 0.5)
        h, e = np.histogram(t, bins=bins)
        hist += [{"level": lv, "years_from": float(e[i]), "years_to": float(e[i + 1]), "graduates": int(h[i])} for i in range(len(h)) if h[i]]
    kpi = {lv["key"]: {"graduation_rate_pct": lv.get("graduation_rate_pct"), "cohort_size": lv["cohort_size"], "window_years": lv["window_years"]} for lv in by_level}
    return envelope("graduation", "REGISTRAR", {"kpis": {"overall_mature": _rate(mature) if len(mature) else None, "by_level": kpi,
                                                         "immature_cohort_students": int((~g["cohort_mature"]).sum())},
                                                "cohorts": cohorts, "by_level": by_level, "by_programme": sorted(by_prog, key=lambda r: r.get("graduation_rate_pct") or 0),
                                                "by_school": by_school, "by_entry_year": by_year, "time_to_completion": ttd, "time_to_completion_histogram": hist},
                    DEFINITIONS, f, LIMITATIONS)


def export_rows(f: Filters) -> pd.DataFrame:
    g = apply_filters(records(), Filters(**{**f.active(), "academic_year": None, "season": None}), MAP)
    return pd.DataFrame([{"level": lv, "entry_term_id": et, "programme_at_entry": p, **_rate(x)}
                         for (lv, et, p), x in g.groupby(["level", "entry_term_id", "programme_at_entry"])])
