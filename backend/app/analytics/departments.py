"""Admissions funnel, Finance and IT summaries (historical, from the active departmental sources)."""
from __future__ import annotations

import pandas as pd

from ..core.config import get_settings
from .common import T, Filters, apply_filters, cached, envelope, label, pct, term_label, terms

ADM_DEF = {
    "applications": "Applications submitted for an entry term (admissions/applications).",
    "offers": "Decision ADMITTED or ADMITTED_DECLINED (an offer was made).",
    "acceptances": "Decision ADMITTED (offer accepted).",
    "new_enrolments": "Applications flagged enrolled (student enrolled in the entry term).",
    "offer_rate": "offers / decided applications (PENDING excluded).",
    "yield": "acceptances / offers.",
    "pending": "Applications without a decision yet (scored by the offer model on the Admissions predictions page).",
}
FIN_DEF = {"payment_completion_pct": "total paid / total charged per student account (finance/account_balances as of the extract date).",
           "outstanding_balance": "Charged minus paid; past due = outstanding after the due date.",
           "active_hold": "Financial hold with status ACTIVE at the extract date (may block registration)."}
IT_DEF = {"uptime_pct": "Mean daily uptime per server (it/server_status_daily).", "login_success_rate": "Successful / attempted logins.",
          "sync_runs": "Historical extract runs of the source systems into the data warehouse (sample data)."}


@cached
def admissions(f: Filters) -> dict:
    a = T("admissions/applications").merge(T("admissions/applicants")[["applicant_id", "gender", "nationality_iso3", "residency_status"]], on="applicant_id", how="left")
    tm = terms()[["term_id", "season", "academic_year", "term_sequence"]]
    a = a.merge(tm, left_on="entry_term_id", right_on="term_id", how="left")
    a = apply_filters(a, f)
    a["offer"] = a["decision"].isin(["ADMITTED", "ADMITTED_DECLINED"])
    a["accept"] = a["decision"] == "ADMITTED"
    a["pending"] = a["decision"] == "PENDING"
    a["enrolled_b"] = a["enrolled"].astype(str) == "True"

    def agg(g):
        dec = (~g["pending"]).sum()
        return {"applications": int(len(g)), "decided": int(dec), "pending": int(g["pending"].sum()), "offers": int(g["offer"].sum()),
                "acceptances": int(g["accept"].sum()), "new_enrolments": int(g["enrolled_b"].sum()),
                "offer_rate_pct": pct(g["offer"].sum(), dec), "yield_pct": pct(g["accept"].sum(), g["offer"].sum()),
                "rejected": int((g["decision"] == "REJECTED").sum()), "withdrawn": int((g["decision"] == "WITHDRAWN_BY_APPLICANT").sum())}
    trend = [{"entry_term_id": t, "term_label": term_label(t), **agg(g)} for t, g in sorted(a.groupby("entry_term_id"), key=lambda x: x[1]["term_sequence"].iloc[0])]
    by_prog = [{"key": k, "label": label("programme_id", k), **agg(g)} for k, g in a.groupby("programme_id")]
    by_school = [{"key": k, "label": label("school_id", k), **agg(g)} for k, g in a.groupby("school_id")]
    by_year = [{"academic_year": k, **agg(g)} for k, g in a.groupby("academic_year")]
    return envelope("admissions", "ADMISSIONS", {"kpis": agg(a), "trend": trend, "by_programme": by_prog, "by_school": by_school,
                                                 "by_academic_year": by_year, "decisions": a["decision"].value_counts().to_dict()}, ADM_DEF, f,
                    ["Historical funnel from records. Offer/acceptance PREDICTIONS are model estimates shown separately, with fairness warnings.", "Synthetic sample data."])


@cached
def finance() -> dict:
    b = T("finance/account_balances").copy()
    for c in ("total_charged", "total_paid", "outstanding_balance", "past_due_balance"):
        b[c] = pd.to_numeric(b[c], errors="coerce")
    b["has_active_hold"] = b["has_active_hold"].astype(str) == "True"
    b["completion"] = (b["total_paid"] / b["total_charged"]).where(b["total_charged"] > 0)
    h = T("finance/financial_holds")
    p = T("finance/payments").copy()
    p["amount"] = pd.to_numeric(p["amount"], errors="coerce")
    ch = T("finance/charges").copy()
    ch["amount"] = pd.to_numeric(ch["amount"], errors="coerce")
    by_term = (ch.groupby("term_id")["amount"].sum().rename("charged").to_frame().join(p.groupby("term_id")["amount"].sum().rename("paid"), how="outer")
               .reset_index().merge(terms()[["term_id", "term_sequence"]], on="term_id").sort_values("term_sequence"))
    by_term["term_label"] = by_term["term_id"].map(term_label)
    by_term["collection_pct"] = (100 * by_term["paid"] / by_term["charged"]).round(2)
    bands = [(0, .5, "< 50 %"), (.5, .8, "50–79 %"), (.8, .95, "80–94 %"), (.95, .9999, "95–99 %"), (.9999, 10, "100 %")]
    comp = b["completion"].dropna()
    kpis = {"accounts": int(len(b)), "total_charged": float(b["total_charged"].sum()), "total_paid": float(b["total_paid"].sum()),
            "outstanding_balance": float(b["outstanding_balance"].sum()), "past_due_balance": float(b["past_due_balance"].sum()),
            "accounts_with_outstanding": int((b["outstanding_balance"] > 0.005).sum()), "accounts_past_due": int((b["past_due_balance"] > 0.005).sum()),
            "active_holds": int((h["status_as_of"] == "ACTIVE").sum()), "holds_blocking_registration": int(((h["status_as_of"] == "ACTIVE") & (h["blocks_registration"].astype(str) == "True")).sum()),
            "payment_completion_pct": pct(b["total_paid"].sum(), b["total_charged"].sum()), "currency": b["currency_code"].iloc[0], "as_of": b["as_of_date"].iloc[0]}
    return envelope("finance", "FINANCE", {"kpis": kpis, "by_term": by_term.drop(columns="term_sequence"),
                                           "completion_distribution": [{"band": lab, "accounts": int(((comp >= lo) & (comp < hi)).sum())} for lo, hi, lab in bands],
                                           "payment_methods": p["method"].value_counts().to_dict()}, FIN_DEF, None, ["Synthetic sample data; amounts are illustrative (USD placeholder)."])


@cached
def it() -> dict:
    s = T("it/server_status_daily").copy()
    s["uptime_pct"] = pd.to_numeric(s["uptime_pct"], errors="coerce")
    srv = s.groupby("server_id").agg(uptime_pct=("uptime_pct", "mean"), outage_days=("status", lambda x: int((x == "OUTAGE").sum())),
                                     degraded_days=("status", lambda x: int((x == "DEGRADED").sum()))).reset_index().round(3)
    lg = T("it/login_events")
    acc = T("it/user_accounts")
    inc = T("it/incidents")
    sync = pd.read_csv(get_settings().data_root / "synthetic" / "data_warehouse" / "sync_runs.csv")
    kpis = {"servers": int(srv.shape[0]), "mean_uptime_pct": round(float(s["uptime_pct"].mean()), 3), "incidents": int(len(inc)),
            "login_attempts": int(len(lg)), "login_success_rate_pct": pct((lg["success"].astype(str) == "True").sum(), len(lg)),
            "accounts": int(len(acc)), "mfa_enabled_pct": pct((acc["mfa_enabled"].astype(str) == "True").sum(), len(acc)),
            "sample_sync_runs": int(len(sync)), "sample_sync_failures": int((sync["status"] == "FAILED").sum())}
    return envelope("it", "IT", {"kpis": kpis, "servers": srv, "incidents_by_severity": inc["severity"].value_counts().to_dict(),
                                 "sync_runs_by_system": sync.groupby(["extracted_system", "status"]).size().reset_index(name="runs"),
                                 "recent_sync_failures": sync[sync["status"] == "FAILED"].tail(10)[["run_id", "extracted_system", "run_date", "failure_reason"]]},
                    IT_DEF, None, ["Synthetic sample IT operations data (servers, logins, sync history); not live monitoring."])
