"""IT and Data Warehouse operational records, derived from the simulated student timeline."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from .reference import DEPARTMENT_ROLE, SERVERS


def _d(x) -> date | None:
    if x is None or x == "" or (isinstance(x, float) and np.isnan(x)):
        return None
    return x if isinstance(x, date) else date.fromisoformat(str(x))


def build_accounts(cfg, rng, students, sps, applications, as_of: date):
    grace = cfg["it"]["student_account_grace_days"]
    app_by_id = {a["application_id"]: a for a in applications}
    by_student = defaultdict(list)
    for sp in sps:
        by_student[sp["student_id"]].append(sp)
    accounts, events = [], []
    n = 0
    for s in students:
        intervals = []
        for sp in sorted(by_student[s["student_id"]], key=lambda r: r["admission_date"]):
            app = app_by_id.get(sp["application_id"])
            start = (_d(app["decision_date"]) + timedelta(days=1)) if app else sp["admission_date"]
            if sp["outcome"] == "ACTIVE":
                end = None
            elif sp["outcome"] == "GRADUATED":
                end = _d(sp["outcome_date"]) + timedelta(days=grace["GRADUATED"])
            else:
                end = _d(sp["outcome_recorded_date"]) + timedelta(days=grace["OTHER"])
            intervals.append([start, end])
        merged = []
        for st, en in intervals:
            if merged and (merged[-1][1] is None or st <= merged[-1][1]):
                if merged[-1][1] is not None:
                    merged[-1][1] = None if en is None else max(merged[-1][1], en)
            else:
                merged.append([st, en])
        n += 1
        acc_id = f"SYN-ACC-{n:06d}"
        for i, (st, en) in enumerate(merged):
            events.append({"account_id": acc_id, "event": "ACTIVATED" if i == 0 else "REACTIVATED",
                           "event_date": st, "data_source": "SYNTHETIC"})
            if en is not None and en <= as_of:
                events.append({"account_id": acc_id, "event": "DISABLED", "event_date": en, "data_source": "SYNTHETIC"})
        last_end = merged[-1][1]
        accounts.append({"account_id": acc_id, "username": s["student_id"].lower().replace("-", ""),
                         "account_type": "STUDENT", "person_id": s["student_id"], "role_code": "STUDENT",
                         "department": "", "created_date": merged[0][0],
                         "status_as_of": "ACTIVE" if (last_end is None or last_end > as_of) else "DISABLED",
                         "mfa_enabled": bool(rng.random() < 0.55), "data_source": "SYNTHETIC",
                         "_intervals": merged})
    staff = []
    k = 0
    for dept, count in cfg["it"]["staff_by_department"].items():
        for _ in range(count):
            k += 1
            sid = f"SYN-STF-{k:04d}"
            hire = date(2012, 1, 1) + timedelta(days=int(rng.integers(0, (date(2026, 9, 1) - date(2012, 1, 1)).days)))
            end = None
            if rng.random() < 0.12:
                span = (as_of - hire).days - 180
                if span > 0:
                    end = hire + timedelta(days=180 + int(rng.integers(0, span)))
            staff.append({"staff_id": sid, "department": dept, "role_code": DEPARTMENT_ROLE[dept],
                          "hire_date": hire, "end_date": end or "", "data_source": "SYNTHETIC"})
            n += 1
            acc_id = f"SYN-ACC-{n:06d}"
            events.append({"account_id": acc_id, "event": "ACTIVATED", "event_date": hire, "data_source": "SYNTHETIC"})
            if end:
                events.append({"account_id": acc_id, "event": "DISABLED", "event_date": end, "data_source": "SYNTHETIC"})
            accounts.append({"account_id": acc_id, "username": sid.lower().replace("-", ""), "account_type": "STAFF",
                             "person_id": sid, "role_code": DEPARTMENT_ROLE[dept], "department": dept,
                             "created_date": hire, "status_as_of": "DISABLED" if end else "ACTIVE",
                             "mfa_enabled": True, "data_source": "SYNTHETIC", "_intervals": [[hire, end]]})
    return accounts, events, staff


def build_server_status(cfg, rng, days: list[date]):
    p = cfg["it"]["server_daily_probabilities"]
    status_rows, incidents = [], []
    inc = 0
    for server_id, _desc, _sys in SERVERS:
        for d in days:
            r = rng.random()
            if r < p["OUTAGE"]:
                status, uptime = "OUTAGE", rng.uniform(60, 95)
            elif r < p["OUTAGE"] + p["DEGRADED"]:
                status, uptime = "DEGRADED", rng.uniform(95, 99.5)
            else:
                status, uptime = "OPERATIONAL", rng.uniform(99.5, 100)
            uptime = round(float(uptime), 3)
            downtime = round((100 - uptime) / 100 * 1440, 1)
            status_rows.append({"server_id": server_id, "status_date": d, "status": status, "uptime_pct": uptime,
                                "downtime_minutes": downtime,
                                "cpu_avg_pct": round(float(np.clip(rng.normal(38, 10), 2, 99)), 1),
                                "memory_avg_pct": round(float(np.clip(rng.normal(57, 9), 5, 99)), 1),
                                "data_source": "SYNTHETIC"})
            if status != "OPERATIONAL":
                inc += 1
                start = datetime(d.year, d.month, d.day) + timedelta(minutes=int(rng.integers(0, max(1, 1440 - downtime))))
                incidents.append({"incident_id": f"SYN-INC-{inc:05d}", "server_id": server_id,
                                  "severity": "MAJOR" if status == "OUTAGE" else "MINOR",
                                  "started_at": start, "resolved_at": start + timedelta(minutes=downtime),
                                  "downtime_minutes": downtime, "description": f"Simulated {status.lower()} event",
                                  "data_source": "SYNTHETIC"})
    return status_rows, incidents


def build_logins(cfg, rng, accounts, term_enrolments, terms, days: list[date], server_status):
    rates = cfg["it"]["daily_login_rate"]
    fail_share = cfg["it"]["failed_login_share"]
    term_dates = {t.term_id: (t.start, t.end) for t in terms}
    sessions = defaultdict(list)
    for te in term_enrolments:
        s, e = term_dates[te["term_id"]]
        sessions[te["student_id"]].append((s, e, te["delivery_mode"]))
    outage = {(r["server_id"], r["status_date"]) for r in server_status if r["status"] == "OUTAGE"}
    day0 = days[0]
    nd = len(days)
    day_idx = np.arange(nd)
    weekday = np.array([d.weekday() < 5 for d in days])
    rows = []
    hours = np.array([0.5, 0.3, 0.2, 0.2, 0.3, 0.6, 1.5, 3, 5, 7, 7.5, 7, 6, 6.5, 6.5, 6, 5.5, 5, 5, 5.5, 6, 5, 3, 1.5])
    hours = hours / hours.sum()
    student_sys = (["LMS", "PORTAL", "SIS"], [0.5, 0.35, 0.15])
    staff_sys = {"ADMISSIONS": "ADMISSIONS", "FINANCE": "FINANCE", "DATA_WAREHOUSE": "DATA_WAREHOUSE"}
    sys_server = {"LMS": ["srv-lms-01"], "PORTAL": ["srv-web-01"], "SIS": ["srv-sis-01", "srv-sis-02"],
                  "ADMISSIONS": ["srv-adm-01"], "FINANCE": ["srv-fin-01"], "DATA_WAREHOUSE": ["srv-dw-01"]}
    for acc in accounts:
        active = np.zeros(nd, dtype=bool)
        for st, en in acc["_intervals"]:
            lo = (st - day0).days
            hi = nd if en is None else (en - day0).days
            active[max(lo, 0):max(min(hi, nd), 0)] = True
        exists = np.array([d >= acc["created_date"] for d in days])
        if acc["account_type"] == "STUDENT":
            r = np.where(active, rates["BETWEEN_TERMS"], np.where(exists, 0.003, 0.0))
            for s, e, mode in sessions.get(acc["person_id"], []):
                lo, hi = (s - day0).days, (e - day0).days + 1
                if hi <= 0 or lo >= nd:
                    continue
                sl = slice(max(lo, 0), min(hi, nd))
                r[sl] = np.where(active[sl], rates["ONLINE_IN_SESSION"] if mode == "ONLINE" else rates["IN_SESSION"], r[sl])
        else:
            r = np.where(active, np.where(weekday, rates["STAFF_WEEKDAY"], 0.1), np.where(exists, 0.002, 0.0))
        counts = rng.poisson(r)
        for i in day_idx[counts > 0]:
            d = days[i]
            for _ in range(int(counts[i])):
                if acc["account_type"] == "STUDENT":
                    system = student_sys[0][int(rng.choice(3, p=student_sys[1]))]
                else:
                    system = staff_sys.get(acc["department"], "SIS") if rng.random() < 0.6 else "PORTAL"
                server = sys_server[system][int(rng.integers(len(sys_server[system])))]
                ts = datetime(d.year, d.month, d.day) + timedelta(hours=int(rng.choice(24, p=hours)),
                                                                  seconds=int(rng.integers(0, 3600)))
                if not active[i]:
                    ok, reason = False, "ACCOUNT_DISABLED"
                elif (server, d) in outage and rng.random() < 0.5:
                    ok, reason = False, "SERVICE_UNAVAILABLE"
                elif rng.random() < fail_share:
                    ok, reason = False, "WRONG_PASSWORD"
                else:
                    ok, reason = True, ""
                rows.append({"account_id": acc["account_id"], "event_time": ts, "system": system,
                             "server_id": server, "auth_server_id": "srv-auth-01", "success": ok,
                             "failure_reason": reason, "channel": "MOBILE" if rng.random() < 0.35 else "WEB",
                             "data_source": "SYNTHETIC"})
    rows.sort(key=lambda x: (x["event_time"], x["account_id"]))
    for i, r in enumerate(rows, 1):
        r["login_id"] = f"SYN-LOG-{i:07d}"
    return rows


def build_dw_sync_runs(days: list[date], server_status, daily_counts: dict[str, dict[date, int]]):
    """Nightly sync at 01:00 for each source system. A run fails if the ETL or database server had an outage
    that day; the next successful run then picks up every day since the last success."""
    down = {r["status_date"] for r in server_status if r["status"] == "OUTAGE" and r["server_id"] in ("srv-dw-01", "srv-db-01")}
    runs, k = [], 0
    for source, counts in daily_counts.items():
        last_success = days[0] - timedelta(days=1)
        for d in days:
            k += 1
            window = [last_success + timedelta(days=i) for i in range(1, (d - last_success).days + 1)]
            # run at 01:00 on day d extracts changes from previous days (window ends the day before d)
            extract_days = [x - timedelta(days=1) for x in window]
            ok = d not in down
            rows = int(sum(counts.get(x, 0) for x in extract_days)) if ok else 0
            runs.append({"run_id": "", "extracted_system": source, "run_date": d,
                         "started_at": datetime(d.year, d.month, d.day, 1, 0) + timedelta(minutes=(k % 7) * 3),
                         "status": "SUCCESS" if ok else "FAILED",
                         "extract_from_date": extract_days[0], "extract_to_date": extract_days[-1],
                         "rows_extracted": rows, "failure_reason": "" if ok else "SOURCE_OR_ETL_SERVER_OUTAGE",
                         "data_source": "SYNTHETIC"})
            if ok:
                last_success = d
    runs.sort(key=lambda r: (r["run_date"], r["extracted_system"]))
    for i, r in enumerate(runs, 1):
        r["run_id"] = f"SYN-DWR-{i:05d}"
    return runs


def daily_change_counts(tables: dict[str, pd.DataFrame], days: list[date]) -> dict[str, dict[date, int]]:
    lo, hi = days[0] - timedelta(days=1), days[-1]

    def count(*series):
        c = defaultdict(int)
        for s in series:
            for v in s.dropna():
                v = _d(v)
                if v and lo <= v <= hi:
                    c[v] += 1
        return c

    t = tables
    return {
        "ADMISSIONS": count(t["applications"]["submitted_date"], t["applications"]["decision_date"].replace("", None)),
        "REGISTRAR": count(t["student_programmes"]["admission_date"], t["student_programmes"]["outcome_recorded_date"].replace("", None),
                           t["term_enrolments"]["_census"], t["course_enrolments_final"]["_posted"]),
        "FINANCE": count(t["charges"]["charge_date"], t["payments"]["payment_date"], t["financial_holds"]["placed_date"],
                         t["financial_holds"]["released_date"].replace("", None)),
        "IT": count(t["account_status_events"]["event_date"], t["login_events"]["_date"]),
    }
