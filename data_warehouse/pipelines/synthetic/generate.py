"""Generate the synthetic institutional dataset and export it to data/synthetic/<department>/.

Usage (from the data_warehouse folder):
    python -m pipelines.synthetic.generate                 # uses config/synthetic_config.toml
    python -m pipelines.synthetic.generate --out <folder>  # write somewhere else (e.g. for a reproducibility test)
"""
from __future__ import annotations

import argparse
import shutil
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .. import metrics as M
from .. import schema as S
from ..common import CONFIG_FILE, SYNTHETIC_DIR, sha256_of, write_csv, write_json
from . import reference as ref
from .derive import build_status_history
from .it_systems import build_accounts, build_dw_sync_runs, build_logins, build_server_status, daily_change_counts
from .rules import past_due
from .simulate import Simulator

DEPARTMENT_FOLDERS = ("reference", "admissions", "registrar", "finance", "it", "data_warehouse")
SOURCE_SYSTEM = {"reference": "REFERENCE_PLACEHOLDER", "admissions": "ADMISSIONS", "registrar": "REGISTRAR",
                 "finance": "FINANCE", "it": "IT", "data_warehouse": "DATA_WAREHOUSE"}


def run_id(cfg: dict) -> str:
    return f"SYN-RUN-{cfg['meta']['generator_version']}-S{cfg['meta']['random_seed']}"


def stamp(df: pd.DataFrame, folder: str, rid: str) -> pd.DataFrame:
    """Departmental source label + generation-run id on every synthetic row."""
    df = df.copy()
    df["source_system"] = SOURCE_SYSTEM[folder]
    df["generation_run_id"] = rid
    return df

README = """# SYNTHETIC DEMONSTRATION DATA: NOT REAL UNIVERSITY RECORDS

Every file in this folder was produced by `data_warehouse/pipelines/synthetic/generate.py`
(seed and settings in `manifest.json`). Every row has `data_source = SYNTHETIC`.
Reference rows (schools, programmes, calendar, rules, fees) are also `verification_status = PLACEHOLDER`.

* No synthetic person, programme, policy or calendar corresponds to a real university record.
* UCI students are NOT in this folder; they live separately in `data/processed/uci/`.
* Folders follow the institutional architecture: reference, admissions, registrar, finance, it, data_warehouse.
* Every row also carries `source_system` (the departmental system it represents) and `generation_run_id`
  (see `data_warehouse/generation_runs.csv`).
* `schema/data_dictionary.csv` documents every column (type, required, allowed values, description).
* `reports/` holds the data-quality report and validated metric outputs.
* Fall 2026 is IN PROGRESS (census snapshot only: no grades, standing or graduations). Spring/Summer 2027 are FUTURE.

Regenerate:  cd data_warehouse ; python -m pipelines.synthetic.generate
Validate:    cd data_warehouse ; python -m pipelines.validation
"""


def _df(rows: list[dict], cols: list[str] | None = None) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if cols:
        df = df[cols]
    return df


def build_cohorts(sps: pd.DataFrame, tes: pd.DataFrame, terms_by_id: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    first_te = tes.sort_values("term_sequence").groupby("student_programme_id").first()
    members, cohorts = [], {}
    sps = sps.sort_values(["student_id", "admission_date", "student_programme_id"])
    # INSTITUTIONAL: first admission to the university
    for sid, g in sps.groupby("student_id", sort=True):
        first = g.iloc[0]
        assert first["entry_type"] == "FIRST_ADMISSION"
        te = first_te.loc[first["student_programme_id"]]
        cid = f"COH-INST-{first['entry_term_id']}"
        cohorts.setdefault(cid, ("INSTITUTIONAL", first["entry_term_id"], ""))
        members.append({"cohort_id": cid, "student_id": sid, "student_programme_id": first["student_programme_id"],
                        "level_at_entry": first["level"], "programme_at_entry": first["programme_id"],
                        "delivery_mode_at_entry": te["delivery_mode"], "study_load_at_entry": te["study_load"]})
        # LEVEL_ENTRY: first admission at each level
        for level, lg in g.groupby("level", sort=True):
            f = lg.iloc[0]
            te2 = first_te.loc[f["student_programme_id"]]
            cid2 = f"COH-{level[:2]}-{f['entry_term_id']}"
            cohorts.setdefault(cid2, ("LEVEL_ENTRY", f["entry_term_id"], level))
            members.append({"cohort_id": cid2, "student_id": sid, "student_programme_id": f["student_programme_id"],
                            "level_at_entry": level, "programme_at_entry": f["programme_id"],
                            "delivery_mode_at_entry": te2["delivery_mode"], "study_load_at_entry": te2["study_load"]})
    m = pd.DataFrame(members)
    m["data_source"] = "SYNTHETIC"
    sizes = m.groupby("cohort_id").size()
    c = pd.DataFrame([{"cohort_id": k, "cohort_type": v[0], "entry_term_id": v[1], "level": v[2],
                       "size_at_census": int(sizes[k]), "frozen_at": terms_by_id[v[1]].census,
                       "data_source": "SYNTHETIC"} for k, v in sorted(cohorts.items())])
    return c, m.sort_values(["cohort_id", "student_id"]).reset_index(drop=True)


def generate(out_dir: Path = SYNTHETIC_DIR, config_path: Path = CONFIG_FILE, overrides: dict | None = None) -> dict:
    cfg = ref.load_config(config_path, overrides)
    seed = cfg["meta"]["random_seed"]
    as_of = date.fromisoformat(cfg["meta"]["as_of_date"])
    sim_ss, it_ss = np.random.SeedSequence(seed).spawn(2)
    sim_rng, it_rng = np.random.default_rng(sim_ss), np.random.default_rng(it_ss)

    terms = ref.build_terms(cfg)
    terms_by_id = {t.term_id: t for t in terms}
    courses = ref.courses_table(cfg)
    fees = ref.fee_schedule_table(cfg, terms)
    reference = {
        "academic_terms": _df(ref.terms_table(terms, cfg)), "schools": _df(ref.schools_table()),
        "programmes": _df(ref.programmes_table(cfg)), "courses": _df(courses),
        "academic_years": _df(ref.academic_years_table(terms, cfg)), "nationalities": _df(ref.nationalities_table(cfg)),
        **{name: _df(ref.code_table(key, vals)) for name, (key, vals) in ref.CODE_LISTS.items()},
        "grading_schemes": _df(ref.grading_scheme_table(cfg)), "rule_sets": _df(ref.rule_sets_table(cfg)),
        "level_rules": _df(ref.level_rules_table(cfg)), "fee_schedules": _df(fees),
        "roles": _df(ref.roles_table()), "servers": _df(ref.servers_table()),
    }

    sim = Simulator(cfg, sim_rng, terms, courses, fees)
    out = sim.run()

    pays = sorted(out["payments"], key=lambda p: (p["payment_date"], p["student_id"], p["amount"]))
    for i, p in enumerate(pays, 1):
        p["payment_id"] = f"SYN-PAY-{i:07d}"
    out["payments"] = pays

    t = {k: pd.DataFrame(v) for k, v in out.items()}
    t["payments"] = t["payments"][["payment_id", "student_id", "term_id", "payment_date", "amount", "method",
                                   "payment_type", "data_source"]]
    cohorts, members = build_cohorts(t["student_programmes"], t["term_enrolments"], terms_by_id)
    t["cohorts"], t["cohort_members"] = cohorts, members
    t["student_status_history"] = build_status_history(t["student_programmes"], t["term_enrolments"], terms, as_of)

    # Finance snapshot at the as-of date
    bal = []
    ch_by = defaultdict(list)
    for c in out["charges"]:
        ch_by[c["student_id"]].append(c)
    pay_by = defaultdict(list)
    for p in pays:
        pay_by[p["student_id"]].append(p)
    active_holds = set(t["financial_holds"].loc[t["financial_holds"]["status_as_of"] == "ACTIVE", "student_id"]) \
        if len(t["financial_holds"]) else set()
    for sid in t["students"]["student_id"]:
        charged = round(sum(c["amount"] for c in ch_by[sid]), 2)
        paid = round(sum(p["amount"] for p in pay_by[sid]), 2)
        bal.append({"student_id": sid, "as_of_date": as_of, "total_charged": charged, "total_paid": paid,
                    "outstanding_balance": round(charged - paid, 2),
                    "past_due_balance": past_due(ch_by[sid], pay_by[sid], as_of),
                    "has_active_hold": sid in active_holds, "currency_code": cfg["meta"]["currency_code"],
                    "data_source": "SYNTHETIC"})
    t["account_balances"] = pd.DataFrame(bal)

    # IT systems
    window = cfg["it"]["login_window_days"]
    days = [as_of - timedelta(days=window - 1 - i) for i in range(window)]
    accounts, events, staff = build_accounts(cfg, it_rng, out["students"], out["student_programmes"],
                                             out["applications"], as_of)
    status, incidents = build_server_status(cfg, it_rng, days)
    logins = build_logins(cfg, it_rng, accounts, out["term_enrolments"], terms, days, status)
    t["user_accounts"] = pd.DataFrame([{k: v for k, v in a.items() if k != "_intervals"} for a in accounts])
    ev = pd.DataFrame(events).sort_values(["event_date", "account_id", "event"]).reset_index(drop=True)
    ev.insert(0, "event_id", [f"SYN-ACE-{i:06d}" for i in range(1, len(ev) + 1)])
    t["account_status_events"] = ev
    rb = t["registration_blocks"]
    rb.insert(0, "block_id", [f"SYN-BLK-{i:05d}" for i in range(1, len(rb) + 1)])
    t["staff"] = pd.DataFrame(staff)
    t["server_status_daily"] = pd.DataFrame(status)
    t["incidents"] = pd.DataFrame(incidents)
    cols = ["login_id", "account_id", "event_time", "system", "server_id", "auth_server_id", "success",
            "failure_reason", "channel", "data_source"]
    t["login_events"] = pd.DataFrame(logins)[cols]

    # Data warehouse nightly sync log (counts are the records that really changed in each source)
    helper = dict(t)
    helper["term_enrolments"] = t["term_enrolments"].assign(_census=t["term_enrolments"]["term_id"].map(lambda x: terms_by_id[x].census))
    fin = t["course_enrolments"][t["course_enrolments"]["grade_status"] != "IN_PROGRESS"]
    helper["course_enrolments_final"] = fin.assign(_posted=fin["term_id"].map(lambda x: terms_by_id[x].end))
    helper["login_events"] = t["login_events"].assign(_date=t["login_events"]["event_time"].map(lambda x: x.date()))
    t["sync_runs"] = pd.DataFrame(build_dw_sync_runs(days, status, daily_change_counts(helper, days)))

    layout = {
        "reference": reference,
        "admissions": {"applicants": t["applicants"], "applications": t["applications"]},
        "registrar": {k: t[k] for k in ("students", "student_programmes", "term_enrolments", "course_enrolments",
                                         "academic_standing", "cohorts", "cohort_members", "student_status_history")},
        "finance": {k: t[k] for k in ("charges", "payments", "financial_holds", "registration_blocks", "account_balances")},
        "it": {k: t[k] for k in ("user_accounts", "account_status_events", "staff", "login_events",
                                  "server_status_daily", "incidents")},
        "data_warehouse": {"sync_runs": t["sync_runs"]},
    }
    rid = run_id(cfg)
    layout["data_warehouse"]["generation_runs"] = pd.DataFrame([{
        "generation_run_id": rid, "generator_version": cfg["meta"]["generator_version"], "random_seed": seed,
        "config_sha256": sha256_of(Path(config_path)), "as_of_date": as_of, "first_term": cfg["meta"]["first_term"],
        "last_admission_term": cfg["meta"]["last_admission_term"], "target_students": cfg["meta"]["target_students"],
        "label": "SYNTHETIC DEMONSTRATION DATA - NOT REAL UNIVERSITY RECORDS", "data_source": "SYNTHETIC"}])
    out_dir = Path(out_dir)
    for folder in DEPARTMENT_FOLDERS:
        if (out_dir / folder).exists():
            shutil.rmtree(out_dir / folder)          # only generator-owned sub-folders are replaced
    files = {}

    def export(folder, name, df):
        path = out_dir / folder / f"{name}.csv"
        write_csv(stamp(df, folder, rid), path)
        files[f"{folder}/{name}.csv"] = {"rows": int(len(df)), "sha256": sha256_of(path)}

    for folder, tables in layout.items():
        for name, df in tables.items():
            export(folder, name, df)
    write_json({"as_of_date": as_of}, out_dir / "manifest.json")     # provisional (read by metrics.load)
    # Registrar reporting records derived with the single metric definitions (validated independently later)
    mt = M.load(out_dir)
    export("registrar", "retention_cohort_members", M.build_retention_members(mt))
    export("registrar", "graduation_records", M.build_graduation_records(mt))
    if (out_dir / "schema").exists():
        shutil.rmtree(out_dir / "schema")
    dd = out_dir / "schema" / "data_dictionary.csv"
    write_csv(pd.DataFrame(S.data_dictionary_rows()), dd)
    files["schema/data_dictionary.csv"] = {"rows": len(S.data_dictionary_rows()), "sha256": sha256_of(dd)}
    (out_dir / "README.md").write_text(README, encoding="utf-8")
    manifest = {"generation_run_id": rid,
        "label": "SYNTHETIC DEMONSTRATION DATA - NOT REAL UNIVERSITY RECORDS",
        "data_source": "SYNTHETIC", "generator_version": cfg["meta"]["generator_version"],
        "random_seed": seed, "as_of_date": as_of, "config_file": str(Path(config_path).name),
        "config_sha256": sha256_of(Path(config_path)), "overrides": overrides or {},
        "first_term": cfg["meta"]["first_term"], "last_admission_term": cfg["meta"]["last_admission_term"],
        "calendar_end_term": cfg["meta"]["calendar_end_term"], "files": files,
    }
    write_json(manifest, out_dir / "manifest.json")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=SYNTHETIC_DIR)
    ap.add_argument("--students", type=int, default=None, help="override target_students (testing)")
    ap.add_argument("--seed", type=int, default=None, help="override random_seed (testing)")
    a = ap.parse_args()
    ov = {}
    if a.students:
        ov["meta.target_students"] = a.students
    if a.seed is not None:
        ov["meta.random_seed"] = a.seed
    m = generate(a.out, overrides=ov)
    for f, info in m["files"].items():
        print(f"{f:42s} {info['rows']:>8d} rows")


if __name__ == "__main__":
    main()
