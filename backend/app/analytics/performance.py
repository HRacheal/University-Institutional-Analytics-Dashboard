"""Academic performance: GPA and academic standing (historical). Predicted future risk is served by app/ml and kept separate."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import T, Filters, apply_filters, cached, enrolments, envelope, label, pct, term_label

DEFINITIONS = {
    "credit_weighted_term_gpa": "Sum(term GPA x GPA credits) / sum(GPA credits) over graded term enrolments (grades final). Same as metrics.performance_by_term.",
    "mean_cumulative_gpa": "Mean cumulative GPA after the term, graded enrolments only.",
    "academic_standing": "Standing assigned after the term under the configured synthetic rule (GOOD, WARNING, PROBATION, DISMISSED, NOT_EVALUATED). "
                         "Thresholds: UG good standing >= 2.0, Master's/Doctorate >= 3.0 (DEMO-RULES-1, not verified policy).",
    "poor_standing": "WARNING + PROBATION + DISMISSED.",
    "gpa_distribution": "Students by cumulative GPA band after the selected term.",
    "standing_transition": "Standing in a term versus the same student's standing in their next graded term.",
    "worsening_flag": "Group whose credit-weighted GPA fell by >= 0.10 or whose poor-standing share rose by >= 3 percentage points between "
                      "the two most recent complete academic years (groups with >= 30 graded enrolments in both years).",
}
LIMITATIONS = ["Historical results only. Predicted next-term risk (AI) is shown separately and is not an observed outcome.",
               "Standing rules are demonstration rules, not verified university policy.", "Synthetic sample data."]
BANDS = [(0, 1.0, "< 1.00"), (1.0, 2.0, "1.00–1.99"), (2.0, 2.5, "2.00–2.49"), (2.5, 3.0, "2.50–2.99"), (3.0, 3.5, "3.00–3.49"), (3.5, 4.01, "3.50–4.00")]
STANDINGS = ("GOOD", "WARNING", "PROBATION", "DISMISSED", "NOT_EVALUATED")


@cached
def graded() -> pd.DataFrame:
    e = enrolments()
    e = e[e["grades_final"] & e["grades_final_available"]]
    st = T("registrar/academic_standing")[["term_enrolment_id", "standing"]]
    return e.merge(st, on="term_enrolment_id", how="left")


def _agg(g: pd.DataFrame) -> dict:
    gr = g[g["gpa_credits"] > 0]
    c = g["standing"].value_counts()
    n = len(g)
    poor = int(c.get("WARNING", 0) + c.get("PROBATION", 0) + c.get("DISMISSED", 0))
    return {"enrolments": n, "graded": len(gr),
            "credit_weighted_term_gpa": round(float((gr["term_gpa"] * gr["gpa_credits"]).sum() / gr["gpa_credits"].sum()), 4) if len(gr) else None,
            "mean_cumulative_gpa": round(float(gr["cumulative_gpa"].mean()), 4) if len(gr) else None,
            **{f"standing_{s.lower()}": int(c.get(s, 0)) for s in STANDINGS}, "poor_standing": poor, "poor_standing_pct": pct(poor, n),
            "good_standing_pct": pct(c.get("GOOD", 0), n)}


@cached
def summary(f: Filters, term_id: str | None = None) -> dict:
    df = apply_filters(graded(), f)
    if df.empty:
        return envelope("performance", "REGISTRAR", {"message": "no graded enrolments match the filters", "trend": []}, DEFINITIONS, f, LIMITATIONS)
    trend = [{"term_id": t, "term_label": term_label(t), "academic_year": g["academic_year"].iloc[0], "season": g["season"].iloc[0], **_agg(g)}
             for t, g in sorted(df.groupby("term_id"), key=lambda x: x[1]["term_sequence"].iloc[0])]
    sel = term_id or trend[-1]["term_id"]
    cur = df[df["term_id"] == sel]
    cg = cur["cumulative_gpa"].dropna()
    dist = [{"band": lab, "students": int(((cg >= lo) & (cg < hi)).sum()), "share_pct": pct(((cg >= lo) & (cg < hi)).sum(), len(cg))} for lo, hi, lab in BANDS]
    by_school = [{"key": k, "label": label("school_id", k), **_agg(g)} for k, g in cur.groupby("school_id")]
    by_prog = [{"key": k, "label": label("programme_id", k), "level": g["level"].iloc[0], **_agg(g)} for k, g in cur.groupby("programme_id")]
    # GPA trend by school (per academic year, complete years)
    yr = df.groupby(["academic_year", "school_id"]).apply(lambda g: pd.Series(_agg(g)), include_groups=False).reset_index()
    yr["school"] = yr["school_id"].map(lambda v: label("school_id", v))
    # standing transitions: term t -> student's next graded term
    s = df.sort_values(["student_id", "term_sequence"])[["student_id", "term_sequence", "term_id", "standing"]]
    s["next_standing"] = s.groupby("student_id")["standing"].shift(-1)
    tr = s[s["term_id"] == sel].dropna(subset=["next_standing"]) if sel != trend[-1]["term_id"] else s.dropna(subset=["next_standing"])
    trans_term = sel if sel != trend[-1]["term_id"] else "all terms"
    mat = pd.crosstab(tr["standing"], tr["next_standing"])
    transitions = [{"from": a, "to": b, "students": int(mat.loc[a, b])} for a in mat.index for b in mat.columns if mat.loc[a, b] > 0]
    worsening = attention(f)
    return envelope("performance", "REGISTRAR", {"selected_term": sel, "kpis": {"term_id": sel, "term_label": term_label(sel), **_agg(cur)},
                                                 "trend": trend, "gpa_distribution": dist, "by_school": by_school,
                                                 "by_programme": sorted(by_prog, key=lambda r: r["credit_weighted_term_gpa"] or 0),
                                                 "school_year_trend": yr, "standing_transitions": {"scope": trans_term, "rows": transitions},
                                                 "attention": worsening}, DEFINITIONS, f, LIMITATIONS)


@cached
def attention(f: Filters) -> dict:
    df = apply_filters(graded(), f)
    from .common import terms
    tm = terms()
    full = tm[tm["grades_final_available"]].groupby("academic_year")["term_id"].count()
    yrs = [y for y in sorted(full[full == 3].index)][-2:]
    if len(yrs) < 2:
        return {"years": yrs, "groups": []}
    out = []
    for col in ("programme_id", "school_id", "level"):
        for k, g in df[df["academic_year"].isin(yrs)].groupby(col):
            a, b = g[g["academic_year"] == yrs[0]], g[g["academic_year"] == yrs[1]]
            if len(a) < 30 or len(b) < 30:
                continue
            ma, mb = _agg(a), _agg(b)
            dg = (mb["credit_weighted_term_gpa"] or 0) - (ma["credit_weighted_term_gpa"] or 0)
            dp = (mb["poor_standing_pct"] or 0) - (ma["poor_standing_pct"] or 0)
            if dg <= -0.10 or dp >= 3.0:
                out.append({"group_by": col, "key": k, "label": label(col, k), "gpa_before": ma["credit_weighted_term_gpa"], "gpa_after": mb["credit_weighted_term_gpa"],
                            "gpa_change": round(dg, 3), "poor_standing_pct_before": ma["poor_standing_pct"], "poor_standing_pct_after": mb["poor_standing_pct"],
                            "poor_standing_change_pp": round(dp, 2), "enrolments_after": mb["enrolments"]})
    return {"years": yrs, "groups": sorted(out, key=lambda r: r["gpa_change"])}


def export_rows(f: Filters) -> pd.DataFrame:
    df = apply_filters(graded(), f)
    rows = [{"term_id": t, "school_id": s, "programme_id": p, **_agg(g)} for (t, s, p), g in df.groupby(["term_id", "school_id", "programme_id"])]
    return pd.DataFrame(rows)
