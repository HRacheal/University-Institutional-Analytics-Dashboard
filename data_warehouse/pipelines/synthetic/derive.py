"""Student status history: an append-only event log derived from admissions and term enrolments.

Events never modify the admission record: a withdrawal, dismissal, programme change or graduation is a NEW event
that follows the ADMITTED event of the same student programme.
"""
from __future__ import annotations

from datetime import date

import pandas as pd


def build_status_history(sp: pd.DataFrame, te: pd.DataFrame, terms: list, as_of: date) -> pd.DataFrame:
    by_seq = {t.seq: t for t in terms}
    by_id = {t.term_id: t for t in terms}
    regular = [t.seq for t in terms if t.is_regular]
    te_by_sp = {k: sorted(g["term_sequence"]) for k, g in te.groupby("student_programme_id")}
    rows = []

    def ev(r, code, term, d, status_after, note=""):
        rows.append({"student_id": r["student_id"], "student_programme_id": r["student_programme_id"],
                     "status_code": code, "term_id": term.term_id, "event_date": d, "status_after": status_after,
                     "rule_reference": note, "data_source": "SYNTHETIC"})

    for r in sp.sort_values(["student_id", "admission_date", "student_programme_id"]).to_dict("records"):
        seqs = te_by_sp[r["student_programme_id"]]
        ev(r, "ADMITTED", by_id[r["entry_term_id"]], r["admission_date"], "ACTIVE", r["entry_type"])
        for a, b in zip(seqs, seqs[1:]):
            missed = [s for s in regular if a < s < b]
            if missed:
                ev(r, "STOPPED_OUT", by_seq[missed[0]], by_seq[missed[0]].census, "ON_GAP", f"{len(missed)} regular term(s) missed")
                ev(r, "RETURNED", by_seq[b], by_seq[b].census, "ACTIVE")
        after = [s for s in regular if s > seqs[-1] and by_seq[s].census <= as_of]
        outcome = r["outcome"]
        if outcome == "ACTIVE":
            if after:
                ev(r, "STOPPED_OUT", by_seq[after[0]], by_seq[after[0]].census, "ON_GAP", "on gap at as-of date")
        elif outcome == "WITHDRAWN":
            rec = date.fromisoformat(str(r["outcome_recorded_date"])[:10])
            if r["withdrawal_type"] == "UNOFFICIAL":
                ev(r, "STOPPED_OUT", by_seq[after[0]], by_seq[after[0]].census, "ON_GAP")
                term = next(by_seq[s] for s in after if by_seq[s].census == rec)
                ev(r, "WITHDRAWN", term, rec, "WITHDRAWN", "SYN-WD-MISSED-TERMS (synthetic business rule)")
            else:
                term = next(t for t in terms if t.start == rec)
                ev(r, "WITHDRAWN", term, rec, "WITHDRAWN", "formal withdrawal before registering")
        else:
            code = {"GRADUATED": "GRADUATED", "DISMISSED": "DISMISSED", "CHANGED_PROGRAMME": "CHANGED_PROGRAMME"}[outcome]
            ev(r, code, by_id[r["outcome_term_id"]], date.fromisoformat(str(r["outcome_date"])[:10]), outcome)
    df = pd.DataFrame(rows)
    df.insert(0, "status_event_id", [f"SYN-EVT-{i:07d}" for i in range(1, len(df) + 1)])
    return df
