"""Institutional metric definitions: the single source of truth (to be mirrored as SQL views for the backend).

STATUS of a student at a term's census date (priority order):
  ENROLLED   has a term enrolment in that term (any programme)
  COMPLETED  not enrolled, has graduated (graduation date <= census date)
  ON_GAP     not enrolled, has a programme admission still open at the census date (stopped out)
  LEFT       otherwise (withdrawn / dismissed and not readmitted)

RETENTION (decision D12 + v1.1 requirements)
  * Institutional retention: ENROLLED in the comparison term in ANY programme (programme transfers count).
  * Programme retention: ENROLLED in the comparison term in the SAME programme as in the base term / at entry.
  * Students who COMPLETED (graduated and not enrolled) are excluded from the retained population and reported
    separately: eligible_to_return = denominator - completed;  retention_rate = retained / eligible_to_return.
    The unadjusted rate (retained / denominator) is also published.
  * Optional Summer: a student not enrolled at a SUMMER comparison census who IS enrolled at the next regular
    (Fall) term's census is CONTINUING_SKIPPED_OPTIONAL_SUMMER - never stopped out, withdrawn or left (this also covers
    internal programme transfers that take effect in the Fall). Summer comparisons publish the strict summer
    re-enrolment rate and a summer continuation rate = (retained + continuing) / (cohort - completed).
  * A comparison is FINAL only if the comparison term's census date has passed (FINAL_CENSUS_SNAPSHOT when the
    comparison term is still in progress, e.g. Fall 2026). Otherwise INCOMPLETE and no rate is published.
GRADUATION
  * LEVEL_ENTRY cohort; graduated within window = graduation date <= entry-term start + window (UG 6, MA 4, DR 6).
  * A cohort is MATURE (final) only if the window end is on/before the as-of date and every term ending on/before the
    window end is a COMPLETED term. Immature cohorts publish no rate.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

PERSISTENCE = {"FALL": "FALL_TO_FALL", "SPRING": "SPRING_TO_SPRING", "SUMMER": "SUMMER_TO_SUMMER"}
RETENTION_GROUPS = ("level", "school_id", "programme_id", "delivery_mode", "study_load")


def load(out_dir: Path) -> dict[str, pd.DataFrame]:
    def r(rel):
        return pd.read_csv(Path(out_dir) / rel, keep_default_na=False, na_values=[""], low_memory=False)
    t = {"terms": r("reference/academic_terms.csv"), "level_rules": r("reference/level_rules.csv"),
         "programmes": r("reference/programmes.csv"), "sp": r("registrar/student_programmes.csv"),
         "te": r("registrar/term_enrolments.csv"), "cohorts": r("registrar/cohorts.csv"),
         "members": r("registrar/cohort_members.csv"), "students": r("registrar/students.csv"),
         "standing": r("registrar/academic_standing.csv")}
    for c in ("start_date", "census_date", "end_date"):
        t["terms"][c] = pd.to_datetime(t["terms"][c])
    for c in ("admission_date", "outcome_date"):
        t["sp"][c] = pd.to_datetime(t["sp"][c])
    t["as_of"] = pd.Timestamp(json.loads((Path(out_dir) / "manifest.json").read_text())["as_of_date"])
    return t


class Timeline:
    """Fast status lookup: student status at the census date of any term."""

    def __init__(self, t: dict):
        self.terms = t["terms"].set_index("term_id")
        self.enrolled = defaultdict(dict)                      # term -> student -> (programme, level)
        for r in t["te"].itertuples():
            self.enrolled[r.term_id][r.student_id] = (r.programme_id, r.level)
        self.sps = defaultdict(list)
        for r in t["sp"].itertuples():
            self.sps[r.student_id].append(r)

    def status(self, sid: str, term_id: str) -> tuple[str, str | None, str | None]:
        if sid in self.enrolled[term_id]:
            p, lv = self.enrolled[term_id][sid]
            return "ENROLLED", p, lv
        census = self.terms.loc[term_id, "census_date"]
        progs = [p for p in self.sps[sid] if p.admission_date <= census]
        if any(p.outcome == "GRADUATED" and p.outcome_date <= census for p in progs):
            return "COMPLETED", None, None
        if any(p.outcome == "ACTIVE" or p.outcome_date > census for p in progs):
            return "ON_GAP", None, None
        return "LEFT", None, None


def _comparison_state(terms: pd.DataFrame, compare: str | None, as_of) -> tuple[bool, str]:
    if compare is None:
        return False, "INCOMPLETE: comparison term outside the calendar"
    row = terms.loc[compare]
    if row["census_date"] <= as_of and row["has_enrolment_data"]:
        return True, "FINAL_CENSUS_SNAPSHOT" if row["reporting_status"] == "CENSUS_SNAPSHOT_ONLY" else "FINAL"
    return False, "INCOMPLETE: comparison census not reached"


def _same_season_next_year(terms_df: pd.DataFrame, term_id: str) -> str | None:
    tt = terms_df.set_index("term_id")
    e = tt.loc[term_id]
    m = terms_df[(terms_df["season"] == e["season"]) & (terms_df["calendar_year"] == e["calendar_year"] + 1)]
    return None if m.empty else m.iloc[0]["term_id"]


def build_retention_members(t: dict) -> pd.DataFrame:
    terms_df, as_of = t["terms"], t["as_of"]
    terms = terms_df.set_index("term_id")
    tl = Timeline(t)
    school = t["programmes"].set_index("programme_id")["school_id"].to_dict()
    rows = []
    ordered = terms_df.sort_values("term_sequence")

    def next_regular(term_id):
        seq = terms.loc[term_id, "term_sequence"]
        nxt = ordered[(ordered["term_sequence"] > seq) & ordered["is_regular_term"]]
        if nxt.empty:
            return None
        n = nxt.iloc[0]
        return n["term_id"] if (n["census_date"] <= as_of and n["has_enrolment_data"]) else None

    def add(ctype, base, compare, sid, prog, level, mode, load):
        final, label = _comparison_state(terms, compare, as_of)
        row = {"comparison_id": f"{ctype}:{base}->{compare or 'NONE'}", "comparison_type": ctype,
               "base_term_id": base, "base_census_date": terms.loc[base, "census_date"].date(),
               "compare_term_id": compare or "", "compare_census_date": terms.loc[compare, "census_date"].date() if compare else "",
               "student_id": sid, "base_programme_id": prog, "base_school_id": school[prog], "base_level": level,
               "base_delivery_mode": mode, "base_study_load": load, "is_final": final, "reporting_label": label,
               "status_at_compare": "", "compare_programme_id": "", "compare_level": "", "outcome_category": "",
               "institutionally_retained": "", "programme_retained": "", "completed_before_compare": "",
               "next_regular_term_id": "", "continued_next_regular_term": ""}
        if final:
            st, p2, lv2 = tl.status(sid, compare)
            cat = {"COMPLETED": "COMPLETED_NOT_ENROLLED", "ON_GAP": "STOPPED_OUT", "LEFT": "LEFT"}.get(st)
            if st == "ENROLLED":
                cat = "RETAINED_SAME_PROGRAMME" if p2 == prog else (
                    "RETAINED_PROGRAMME_TRANSFER" if lv2 == level else "RETAINED_NEXT_LEVEL")
            if terms.loc[compare, "season"] == "SUMMER":
                nr = next_regular(compare)
                cont = bool(nr) and tl.status(sid, nr)[0] == "ENROLLED"
                row.update(next_regular_term_id=nr or "", continued_next_regular_term=cont)
                if st in ("ON_GAP", "LEFT") and cont:
                    cat = "CONTINUING_SKIPPED_OPTIONAL_SUMMER"
            row.update(status_at_compare=st, compare_programme_id=p2 or "", compare_level=lv2 or "",
                       outcome_category=cat, institutionally_retained=st == "ENROLLED",
                       programme_retained=(st == "ENROLLED" and p2 == prog), completed_before_compare=st == "COMPLETED")
        rows.append(row)

    # 1) first-year institutional cohorts (first admission term -> same season one year later)
    m = t["members"].merge(t["cohorts"][["cohort_id", "cohort_type", "entry_term_id"]], on="cohort_id")
    for r in m[m["cohort_type"] == "INSTITUTIONAL"].sort_values(["entry_term_id", "student_id"]).itertuples():
        add("FIRST_YEAR_COHORT", r.entry_term_id, _same_season_next_year(terms_df, r.entry_term_id), r.student_id,
            r.programme_at_entry, r.level_at_entry, r.delivery_mode_at_entry, r.study_load_at_entry)
    # 2) Fall->Fall, Spring->Spring, Summer->Summer persistence of everyone enrolled in the base term
    for r in t["te"].sort_values(["term_sequence", "student_id"]).itertuples():
        add(PERSISTENCE[terms.loc[r.term_id, "season"]], r.term_id, _same_season_next_year(terms_df, r.term_id),
            r.student_id, r.programme_id, r.level, r.delivery_mode, r.study_load)
    df = pd.DataFrame(rows)
    df.insert(0, "retention_record_id", [f"SYN-RET-{i:07d}" for i in range(1, len(df) + 1)])
    df["data_source"] = "SYNTHETIC"
    return df


def retention_rates(members: pd.DataFrame) -> pd.DataFrame:
    rows = []
    keys = ["comparison_id", "comparison_type", "base_term_id", "compare_term_id", "base_census_date",
            "compare_census_date", "reporting_label", "is_final"]
    for gcol in (None,) + RETENTION_GROUPS:
        col = None if gcol is None else f"base_{gcol}"
        grouped = members.groupby(keys + ([col] if col else []), sort=True, dropna=False)
        for k, g in grouped:
            base = dict(zip(keys, k[:len(keys)]))
            base.update(group_by=gcol or "ALL", group_value=k[-1] if col else "ALL")
            n = len(g)
            if not base["is_final"]:
                rows.append({**base, "denominator": n})
                continue
            c = g["outcome_category"].value_counts()
            completed = int(c.get("COMPLETED_NOT_ENROLLED", 0))
            retained = int((g["institutionally_retained"] == True).sum())  # noqa: E712
            prog = int((g["programme_retained"] == True).sum())  # noqa: E712
            elig = n - completed
            rows.append({**base, "denominator": n, "completed": completed, "eligible_to_return": elig,
                         "institutionally_retained": retained, "programme_retained": prog,
                         "retained_programme_transfer": int(c.get("RETAINED_PROGRAMME_TRANSFER", 0)),
                         "retained_next_level": int(c.get("RETAINED_NEXT_LEVEL", 0)),
                         "continuing_skipped_optional_summer": int(c.get("CONTINUING_SKIPPED_OPTIONAL_SUMMER", 0)),
                         "stopped_out": int(c.get("STOPPED_OUT", 0)), "left": int(c.get("LEFT", 0)),
                         "institutional_retention_rate": round(retained / elig, 4) if elig else "",
                         "programme_retention_rate": round(prog / elig, 4) if elig else "",
                         "summer_continuation_rate": (round((retained + int(c.get("CONTINUING_SKIPPED_OPTIONAL_SUMMER", 0))) / elig, 4)
                                                      if elig and str(base["compare_term_id"]).endswith("SU") else ""),
                         "unadjusted_retention_rate": round(retained / n, 4),
                         "completion_rate": round(completed / n, 4)})
    return pd.DataFrame(rows)


def cohort_retention_multi_year(t: dict, max_years: int = 3) -> pd.DataFrame:
    """Institutional cohort retention k = 1..max_years after entry (same season)."""
    terms_df, as_of = t["terms"], t["as_of"]
    terms = terms_df.set_index("term_id")
    tl = Timeline(t)
    rows = []
    inst = t["cohorts"][t["cohorts"]["cohort_type"] == "INSTITUTIONAL"]
    for c in inst.sort_values("entry_term_id").itertuples():
        sids = t["members"].loc[t["members"]["cohort_id"] == c.cohort_id, "student_id"]
        e = terms.loc[c.entry_term_id]
        for k in range(1, max_years + 1):
            m = terms_df[(terms_df["season"] == e["season"]) & (terms_df["calendar_year"] == e["calendar_year"] + k)]
            fu = None if m.empty else m.iloc[0]["term_id"]
            final, label = _comparison_state(terms, fu, as_of)
            row = {"cohort_id": c.cohort_id, "entry_term_id": c.entry_term_id, "years_after_entry": k,
                   "measured_at_term_id": fu or "", "denominator": len(sids), "is_final": final, "reporting_label": label}
            if final:
                cnt = pd.Series([tl.status(s, fu)[0] for s in sids]).value_counts()
                completed = int(cnt.get("COMPLETED", 0))
                elig = len(sids) - completed
                row.update(enrolled=int(cnt.get("ENROLLED", 0)), completed=completed, on_gap=int(cnt.get("ON_GAP", 0)),
                           left=int(cnt.get("LEFT", 0)),
                           retention_rate=round(int(cnt.get("ENROLLED", 0)) / elig, 4) if elig else "")
            rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------ graduation
def cohort_maturity(terms_df: pd.DataFrame, window_end, as_of) -> bool:
    ending = terms_df[terms_df["end_date"] <= window_end]
    return bool(window_end <= as_of and (ending["reporting_status"] == "COMPLETED_TERM").all())


def build_graduation_records(t: dict) -> pd.DataFrame:
    terms_df, as_of = t["terms"], t["as_of"]
    terms = terms_df.set_index("term_id")
    lr = t["level_rules"].set_index("level")
    school = t["programmes"].set_index("programme_id")["school_id"].to_dict()
    credits_req = t["programmes"].set_index("programme_id")["credits_required"].to_dict()
    sp, te = t["sp"], t["te"]
    current_term = terms_df[terms_df["reporting_status"] == "CENSUS_SNAPSHOT_ONLY"]["term_id"].tolist()
    enrolled_now = set(te.loc[te["term_id"].isin(current_term), "student_programme_id"])
    te_by_sp = {k: g.sort_values("term_sequence") for k, g in te.groupby("student_programme_id")}
    m = t["members"].merge(t["cohorts"][["cohort_id", "cohort_type", "entry_term_id"]], on="cohort_id")
    rows = []
    for r in m[m["cohort_type"] == "LEVEL_ENTRY"].sort_values(["cohort_id", "student_id"]).itertuples():
        level = r.level_at_entry
        w = int(lr.loc[level, "graduation_window_years"])
        start = terms.loc[r.entry_term_id, "start_date"]
        window_end = start + pd.DateOffset(years=w)
        mature = cohort_maturity(terms_df, window_end, as_of)
        path = sp[(sp["student_id"] == r.student_id) & (sp["level"] == level)].sort_values("admission_date")
        grad = path[path["outcome"] == "GRADUATED"]
        g = grad.iloc[0] if len(grad) else None
        last = path.iloc[-1]
        if g is not None:
            status = "GRADUATED_WITHIN_WINDOW" if g.outcome_date <= window_end else "GRADUATED_AFTER_WINDOW"
        elif last.student_programme_id in enrolled_now:
            status = "ENROLLED_NOT_GRADUATED"
        elif last.outcome == "ACTIVE":
            status = "STOPPED_OUT_NOT_GRADUATED"
        else:
            status = "LEFT_NOT_GRADUATED"
        # graduation eligibility from the latest completed term on the path (credits, minimum years, GPA)
        tes = pd.concat([te_by_sp[x] for x in path["student_programme_id"]])
        done = tes[tes["grades_final"] == True]  # noqa: E712
        lastdone = done[done["student_programme_id"] == last.student_programme_id].tail(1)
        eligible = False
        if len(lastdone):
            ld = lastdone.iloc[0]
            years = (terms.loc[ld.term_id, "end_date"] - start).days / 365.25
            eligible = bool(ld.cumulative_credits_earned >= credits_req[last.programme_id]
                            and years >= lr.loc[level, "min_years_to_graduate"]
                            and ld.cumulative_gpa >= lr.loc[level, "graduation_min_gpa"])
        upto = tes if g is None else tes[tes["term_sequence"] <= terms.loc[g.outcome_term_id, "term_sequence"]]
        rows.append({
            "graduation_record_id": "", "cohort_id": r.cohort_id, "student_id": r.student_id, "level": level,
            "entry_term_id": r.entry_term_id, "admission_date": start.date(), "programme_at_entry": r.programme_at_entry,
            "school_at_entry": school[r.programme_at_entry], "window_years": w, "window_end_date": window_end.date(),
            "window_basis": lr.loc[level, "window_basis"], "cohort_mature": mature,
            "graduation_status": status, "graduated_programme_id": g.programme_id if g is not None else "",
            "graduation_term_id": g.outcome_term_id if g is not None else "",
            "graduation_date": g.outcome_date.date() if g is not None else "",
            "time_to_degree_years": round((g.outcome_date - start).days / 365.25, 3) if g is not None else "",
            "enrolled_terms_to_degree": int(len(upto)) if g is not None else "",
            "gap_terms_to_degree": int(upto["prior_gap_terms"].sum()) if g is not None else "",
            "graduated_within_window": (status == "GRADUATED_WITHIN_WINDOW") if (mature or g is not None) else "",
            "graduation_eligible_by_rules": eligible,
            "counts_in_final_rate": mature, "data_source": "SYNTHETIC"})
    df = pd.DataFrame(rows)
    df["graduation_record_id"] = [f"SYN-GRD-{i:06d}" for i in range(1, len(df) + 1)]
    return df


def graduation_rates(records: pd.DataFrame) -> pd.DataFrame:
    rows = []
    specs = [("cohort_id", ["cohort_id", "level", "entry_term_id", "window_years", "window_end_date", "cohort_mature"]),
             ("level", ["level", "window_years"]), ("programme_at_entry", ["level", "programme_at_entry", "window_years"]),
             ("school_at_entry", ["level", "school_at_entry", "window_years"])]
    for name, keys in specs:
        data = records if name == "cohort_id" else records[records["cohort_mature"] == True]  # noqa: E712
        for k, g in data.groupby(keys, sort=True):
            k = k if isinstance(k, tuple) else (k,)
            base = {"aggregation": "COHORT" if name == "cohort_id" else f"MATURE_COHORTS_BY_{name.upper()}",
                    **dict(zip(keys, k))}
            mature = bool(g["cohort_mature"].all())
            n = len(g)
            within = int((g["graduation_status"] == "GRADUATED_WITHIN_WINDOW").sum())
            row = {**base, "denominator": n, "is_final": mature,
                   "graduated_so_far": int(g["graduation_status"].str.startswith("GRADUATED").sum()),
                   "currently_enrolled_not_graduated": int((g["graduation_status"] == "ENROLLED_NOT_GRADUATED").sum()),
                   "reporting_label": "FINAL" if mature else "INCOMPLETE: graduation window still open"}
            if mature:
                row.update(graduated_within_window=within, graduation_rate=round(within / n, 4))
            rows.append(row)
    return pd.DataFrame(rows)


def time_to_degree(records: pd.DataFrame) -> pd.DataFrame:
    g = records[records["graduation_status"].str.startswith("GRADUATED")]
    out = g.groupby("level").agg(graduates=("student_id", "count"),
                                 median_years=("time_to_degree_years", "median"),
                                 mean_years=("time_to_degree_years", "mean"),
                                 median_enrolled_terms=("enrolled_terms_to_degree", "median"),
                                 mean_gap_terms=("gap_terms_to_degree", "mean")).round(3).reset_index()
    return out


# ------------------------------------------------------------------------------------------------ enrolment & performance
def enrolment_by_term(t: dict) -> pd.DataFrame:
    te = t["te"].merge(t["students"][["student_id", "gender", "nationality_iso3", "residency_status"]], on="student_id")
    te = te.merge(t["terms"][["term_id", "reporting_status"]], on="term_id")
    keys = ["term_id", "academic_year", "reporting_status", "level", "school_id", "programme_id", "delivery_mode",
            "study_load", "gender", "residency_status", "nationality_iso3"]
    return te.groupby(keys).agg(headcount=("student_id", "nunique"), credits_attempted=("credits_attempted", "sum")).reset_index()


def enrolment_by_academic_year(t: dict) -> pd.DataFrame:
    te = t["te"]
    out = te.groupby(["academic_year", "level", "school_id"]).agg(unduplicated_headcount=("student_id", "nunique"),
                                                                 term_enrolments=("term_enrolment_id", "count")).reset_index()
    tot = te.groupby("academic_year").agg(unduplicated_headcount=("student_id", "nunique"),
                                          term_enrolments=("term_enrolment_id", "count")).reset_index()
    tot["level"], tot["school_id"] = "ALL", "ALL"
    return pd.concat([tot, out], ignore_index=True)


def performance_by_term(t: dict) -> pd.DataFrame:
    te = t["te"][t["te"]["grades_final"] == True].merge(  # noqa: E712
        t["standing"][["term_enrolment_id", "standing"]], on="term_enrolment_id", how="left")
    rows = []
    for gcols in (["term_id", "level"], ["term_id", "level", "school_id"], ["term_id", "level", "school_id", "programme_id"]):
        for k, g in te.groupby(gcols, sort=True):
            graded = g[g["gpa_credits"] > 0]
            c = g["standing"].value_counts()
            pts = (graded["term_gpa"] * graded["gpa_credits"]).sum()
            rows.append({**dict(zip(gcols, k)), "aggregation": "+".join(gcols[1:]),
                         "completed_enrolments": len(g), "graded_enrolments": len(graded),
                         "credit_weighted_term_gpa": round(pts / graded["gpa_credits"].sum(), 4) if len(graded) else "",
                         "mean_cumulative_gpa": round(graded["cumulative_gpa"].mean(), 4) if len(graded) else "",
                         **{f"standing_{s.lower()}": int(c.get(s, 0)) for s in ("GOOD", "WARNING", "PROBATION", "DISMISSED", "NOT_EVALUATED")},
                         "poor_performance": int((g["poor_performance_flag"] == True).sum())})  # noqa: E712
    return pd.DataFrame(rows)


def compute_aggregates(out_dir: Path) -> dict[str, pd.DataFrame]:
    t = load(out_dir)
    members = pd.read_csv(Path(out_dir) / "registrar/retention_cohort_members.csv", keep_default_na=False, na_values=[""], low_memory=False)
    records = pd.read_csv(Path(out_dir) / "registrar/graduation_records.csv", keep_default_na=False, na_values=[""], low_memory=False)
    return {"retention_rates": retention_rates(members), "cohort_retention_multi_year": cohort_retention_multi_year(t),
            "graduation_rates": graduation_rates(records), "time_to_degree": time_to_degree(records),
            "enrolment_by_term": enrolment_by_term(t), "enrolment_by_academic_year": enrolment_by_academic_year(t),
            "performance_by_term": performance_by_term(t)}
