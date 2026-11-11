"""Enrolment analytics (Registrar census enrolments)."""
from __future__ import annotations

import pandas as pd

from .common import Filters, apply_filters, cached, enrolments, envelope, label, pct, term_label, terms

DEFINITIONS = {
    "headcount": "Distinct students with a term enrolment at the term's census date (any programme). Source: registrar/term_enrolments.",
    "new_student": "A student whose first-ever census enrolment at the institution is this term (first admissions; readmissions and "
                   "programme changes of existing students count as continuing).",
    "continuing_student": "Enrolled this term and enrolled in at least one earlier term.",
    "unduplicated_academic_year_headcount": "Distinct students enrolled in any term of the academic year (Fall + Spring + Summer).",
    "study_mode": "delivery_mode of the term enrolment: FACE_TO_FACE or ONLINE.",
    "census_snapshot": "Fall 2026 is in progress: its census has passed (headcount is final) but grades are not.",
    "year_on_year_change": "Change versus the same season one year earlier (Fall vs Fall etc.), because Summer is much smaller.",
}
LIMITATIONS = ["Synthetic sample data: patterns are illustrative, not real institutional results.",
               "Home-country nationality is a placeholder code (ZZZ) until the institution configures it."]


def _base(f: Filters) -> pd.DataFrame:
    e = enrolments()
    e = e[e["census_passed"]]
    return apply_filters(e, f)


def _breakdown(df: pd.DataFrame, col: str, top: int | None = None) -> list[dict]:
    g = df.groupby(col)["student_id"].nunique().sort_values(ascending=False)
    tot = g.sum()
    rows = [{"key": k, "label": label(col, k), "headcount": int(v), "share_pct": pct(v, tot)} for k, v in g.items()]
    if top and len(rows) > top:
        rest = rows[top:]
        rows = rows[:top] + [{"key": "OTHER", "label": f"Other ({len(rest)})", "headcount": sum(r["headcount"] for r in rest),
                              "share_pct": round(sum(r["share_pct"] or 0 for r in rest), 2)}]
    return rows


@cached
def summary(f: Filters, term_id: str | None = None) -> dict:
    df = _base(f)
    tm = terms()
    if df.empty:
        return envelope("enrollment", "REGISTRAR", {"kpis": {}, "trend": [], "breakdowns": {}, "message": "no enrolments match the filters"}, DEFINITIONS, f, LIMITATIONS)
    trend = (df.groupby(["term_id", "term_sequence", "season", "academic_year", "reporting_status"])
             .agg(headcount=("student_id", "nunique"), new_students=("is_new_student", "sum"),
                  online=("delivery_mode", lambda s: int((s == "ONLINE").sum())), part_time=("study_load", lambda s: int((s == "PART_TIME").sum())),
                  credits_attempted=("credits_attempted", "sum"))
             .reset_index().sort_values("term_sequence"))
    trend["continuing_students"] = trend["headcount"] - trend["new_students"]
    trend["face_to_face"] = trend["headcount"] - trend["online"]
    trend["term_label"] = trend["term_id"].map(term_label)
    prev_same = {r.term_id: trend[(trend["season"] == r.season) & (trend["term_sequence"] == r.term_sequence - 3)]["headcount"].sum() or None
                 for r in trend.itertuples()}
    trend["yoy_change_pct"] = [pct(r.headcount - prev_same[r.term_id], prev_same[r.term_id]) if prev_same[r.term_id] else None for r in trend.itertuples()]
    sel = term_id or trend["term_id"].iloc[-1]
    cur = df[df["term_id"] == sel]
    row = trend.set_index("term_id").loc[sel] if sel in set(trend["term_id"]) else None
    last_completed = trend[trend["reporting_status"] == "COMPLETED_TERM"]["term_id"].iloc[-1] if (trend["reporting_status"] == "COMPLETED_TERM").any() else None
    kpis = {}
    if row is not None:
        prev = prev_same.get(sel)
        kpis = {"term_id": sel, "term_label": term_label(sel), "reporting_status": row["reporting_status"], "headcount": int(row["headcount"]),
                "same_term_last_year": int(prev) if prev else None, "yoy_change": int(row["headcount"] - prev) if prev else None,
                "yoy_change_pct": row["yoy_change_pct"], "new_students": int(row["new_students"]), "continuing_students": int(row["continuing_students"]),
                "online_share_pct": pct(row["online"], row["headcount"]), "part_time_share_pct": pct(row["part_time"], row["headcount"]),
                "international_share_pct": pct((cur["residency_status"] == "INTERNATIONAL").sum(), len(cur)),
                "programmes": int(cur["programme_id"].nunique()), "last_completed_term": last_completed}
    years = (df.groupby("academic_year").agg(unduplicated_headcount=("student_id", "nunique"), term_enrolments=("term_enrolment_id", "count"))
             .reset_index().sort_values("academic_year"))
    complete_years = set(tm.groupby("academic_year")["census_passed"].all().loc[lambda s: s].index)
    years["complete_year"] = years["academic_year"].isin(complete_years)
    by_season = trend.pivot_table(index="academic_year", columns="season", values="headcount", aggfunc="sum").reset_index()
    breakdowns = {"programme": _breakdown(cur, "programme_id"), "school": _breakdown(cur, "school_id"), "nationality": _breakdown(cur, "nationality_iso3", 12),
                  "gender": _breakdown(cur, "gender"), "study_mode": _breakdown(cur, "delivery_mode"), "level": _breakdown(cur, "level"),
                  "study_load": _breakdown(cur, "study_load"),
                  "new_vs_continuing": [{"key": "NEW", "label": "New students", "headcount": int(cur["is_new_student"].sum())},
                                        {"key": "CONTINUING", "label": "Continuing students", "headcount": int((~cur["is_new_student"]).sum())}]}
    school_trend = (df.groupby(["term_id", "term_sequence", "school_id"])["student_id"].nunique().reset_index(name="headcount")
                    .sort_values("term_sequence"))
    school_trend["school"] = school_trend["school_id"].map(lambda v: label("school_id", v))
    mode_trend = trend[["term_id", "term_label", "online", "face_to_face"]]
    return envelope("enrollment", "REGISTRAR", {"selected_term": sel, "kpis": kpis, "trend": trend.drop(columns=["term_sequence"]),
                                                "academic_years": years, "by_academic_year_and_season": by_season,
                                                "breakdowns": breakdowns, "school_trend": school_trend.drop(columns=["term_sequence"]),
                                                "mode_trend": mode_trend}, DEFINITIONS, f, LIMITATIONS)


def compare(f: Filters, term_a: str, term_b: str, by: str = "school_id") -> dict:
    df = _base(f)
    a = df[df["term_id"] == term_a].groupby(by)["student_id"].nunique()
    b = df[df["term_id"] == term_b].groupby(by)["student_id"].nunique()
    keys = sorted(set(a.index) | set(b.index))
    rows = [{"key": k, "label": label(by, k), "term_a": int(a.get(k, 0)), "term_b": int(b.get(k, 0)),
             "change": int(b.get(k, 0) - a.get(k, 0)), "change_pct": pct(b.get(k, 0) - a.get(k, 0), a.get(k, 0))} for k in keys]
    tot_a, tot_b = int(df[df["term_id"] == term_a]["student_id"].nunique()), int(df[df["term_id"] == term_b]["student_id"].nunique())
    return envelope("enrollment_compare", "REGISTRAR", {"term_a": term_a, "term_b": term_b, "by": by, "rows": rows,
                                                        "total": {"term_a": tot_a, "term_b": tot_b, "change": tot_b - tot_a, "change_pct": pct(tot_b - tot_a, tot_a)}},
                    DEFINITIONS, f, LIMITATIONS)


def export_rows(f: Filters) -> pd.DataFrame:
    df = _base(f)
    g = (df.groupby(["term_id", "academic_year", "season", "reporting_status", "level", "school_id", "programme_id", "delivery_mode", "study_load",
                     "gender", "nationality_iso3"]).agg(headcount=("student_id", "nunique"), new_students=("is_new_student", "sum")).reset_index())
    return g
