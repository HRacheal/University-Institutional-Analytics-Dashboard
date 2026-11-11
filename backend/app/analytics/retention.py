"""Institutional retention rates from registrar/retention_cohort_members, using the published definitions of
data_warehouse/pipelines/metrics.py. Model-predicted retention probabilities are served separately (app/ml)."""
from __future__ import annotations

import pandas as pd

from .common import T, Filters, apply_filters, cached, envelope, label, pct, students, term_label

COMPARISONS = {"FALL_TO_FALL": "Fall to Fall", "SPRING_TO_SPRING": "Spring to Spring", "SUMMER_TO_SUMMER": "Summer to Summer"}
DEFINITIONS = {
    "cohort": "All students enrolled at the census of the base term (e.g. Fall 2025), by programme/school/level at the base term.",
    "retained": "Enrolled at the census of the same season one year later (e.g. Fall 2026) in ANY programme (institutional retention). "
                "Programme retention requires the SAME programme.",
    "graduates": "Students who graduated before the comparison census are excluded from the eligible population "
                 "(eligible = cohort - completed) and reported separately.",
    "transfers": "Internal programme transfers count as institutionally retained but not as programme retained. "
                 "External transfers are not identifiable in the records and count as not retained (LEFT).",
    "deferrals_and_breaks": "Students on a gap (open admission, not enrolled) count as not retained (STOPPED_OUT). "
                            "The records do not distinguish approved leave from unapproved stop-out, so approved breaks cannot be excluded yet.",
    "optional_summer": "For Summer-to-Summer, students who skip the optional Summer but are enrolled at the next Fall census are reported as "
                       "continuing; the strict Summer re-enrolment rate and the summer continuation rate are both published.",
    "retention_rate": "retained / eligible (eligible = cohort - graduated before the comparison census). Unadjusted rate = retained / cohort.",
    "non_retention_rate": "1 - retention rate (eligible students not retained: stopped out or left).",
    "status": "FINAL when the comparison census has passed; FINAL_CENSUS_SNAPSHOT for Fall 2026 (census passed, term in progress); "
              "INCOMPLETE comparisons (Spring/Summer 2027 not reached) publish no rate.",
}
LIMITATIONS = ["Official-style retention RATES are computed from observed records; model retention PROBABILITIES are estimates and are never mixed in.",
               "Approved leave of absence is not recorded in the data and cannot be excluded from the cohort.", "Synthetic sample data."]
MAP = {"school_id": "base_school_id", "programme_id": "base_programme_id", "level": "base_level", "delivery_mode": "base_delivery_mode",
       "study_load": "base_study_load"}


@cached
def members() -> pd.DataFrame:
    m = T("registrar/retention_cohort_members").merge(students(), on="student_id", how="left")
    for c in ("is_final", "institutionally_retained", "programme_retained", "completed_before_compare"):
        m[c] = m[c].astype(str) == "True"
    return m[m["comparison_type"].isin(COMPARISONS)]


def _rate(g: pd.DataFrame) -> dict:
    n = len(g)
    final = bool(g["is_final"].all())
    base = {"cohort_size": n, "is_final": final, "reporting_label": g["reporting_label"].iloc[0]}
    if not final:
        return {**base, "message": "comparison census not reached: no rate published"}
    c = g["outcome_category"].value_counts()
    completed = int(c.get("COMPLETED_NOT_ENROLLED", 0))
    elig = n - completed
    ret = int(g["institutionally_retained"].sum())
    prog = int(g["programme_retained"].sum())
    cont = int(c.get("CONTINUING_SKIPPED_OPTIONAL_SUMMER", 0))
    summer = str(g["compare_term_id"].iloc[0]).endswith("SU")
    return {**base, "graduated_before_compare": completed, "eligible": elig, "retained": ret, "not_retained": elig - ret,
            "retention_rate_pct": pct(ret, elig), "non_retention_rate_pct": pct(elig - ret, elig),
            "programme_retained": prog, "programme_retention_rate_pct": pct(prog, elig), "unadjusted_retention_rate_pct": pct(ret, n),
            "retained_programme_transfer": int(c.get("RETAINED_PROGRAMME_TRANSFER", 0)), "retained_next_level": int(c.get("RETAINED_NEXT_LEVEL", 0)),
            "stopped_out": int(c.get("STOPPED_OUT", 0)), "left": int(c.get("LEFT", 0)),
            "continuing_skipped_optional_summer": cont if summer else None,
            "summer_continuation_rate_pct": pct(ret + cont, elig) if summer else None}


@cached
def summary(f: Filters, comparison: str = "FALL_TO_FALL", base_term: str | None = None) -> dict:
    m = apply_filters(members(), Filters(**{**f.active(), "academic_year": None, "season": None}), MAP)
    m = m[m["comparison_type"] == comparison]
    if m.empty:
        return envelope("retention", "REGISTRAR", {"message": "no cohort members match the filters", "trend": []}, DEFINITIONS, f, LIMITATIONS)
    trend = []
    for (b, cterm), g in sorted(m.groupby(["base_term_id", "compare_term_id"])):
        trend.append({"base_term_id": b, "compare_term_id": cterm, "label": f"{term_label(b)} → {term_label(cterm)}", **_rate(g)})
    finals = [t for t in trend if t["is_final"]]
    sel = base_term or (finals[-1]["base_term_id"] if finals else trend[-1]["base_term_id"])
    cur = m[m["base_term_id"] == sel]
    by = {}
    for col, key in (("base_school_id", "school_id"), ("base_programme_id", "programme_id"), ("base_level", "level"), ("base_delivery_mode", "delivery_mode")):
        by[key] = sorted([{"key": k, "label": label(key, k), **_rate(g)} for k, g in cur.groupby(col)], key=lambda r: r.get("retention_rate_pct") or 0)
    outcomes = cur["outcome_category"].value_counts().to_dict()
    return envelope("retention", "REGISTRAR", {"comparison": comparison, "comparison_label": COMPARISONS[comparison], "selected_base_term": sel,
                                               "selected": {"base_term_id": sel, "compare_term_id": cur["compare_term_id"].iloc[0],
                                                            "label": f"{term_label(sel)} → {term_label(cur['compare_term_id'].iloc[0])}", **_rate(cur)},
                                               "outcomes": outcomes, "trend": trend, "by": by}, DEFINITIONS, f, LIMITATIONS)


@cached
def headline() -> dict:
    """Required comparisons: Fall 2025 -> Fall 2026, latest final Spring-to-Spring and Summer-to-Summer."""
    m = members()
    out = {}
    for ct in COMPARISONS:
        g = m[(m["comparison_type"] == ct) & m["is_final"]]
        b = sorted(g["base_term_id"].unique())[-1]
        x = g[g["base_term_id"] == b]
        out[ct] = {"base_term_id": b, "compare_term_id": x["compare_term_id"].iloc[0], "label": f"{term_label(b)} → {term_label(x['compare_term_id'].iloc[0])}", **_rate(x)}
    return out


def export_rows(f: Filters) -> pd.DataFrame:
    m = apply_filters(members(), Filters(**{**f.active(), "academic_year": None, "season": None}), MAP)
    rows = []
    for (ct, b, s, p), g in m.groupby(["comparison_type", "base_term_id", "base_school_id", "base_programme_id"]):
        r = _rate(g)
        r.pop("message", None)
        rows.append({"comparison_type": ct, "base_term_id": b, "school_id": s, "programme_id": p, **r})
    return pd.DataFrame(rows)
