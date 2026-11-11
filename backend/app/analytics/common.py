"""Shared helpers for the institutional analytics: data access via the active departmental sources, filters, labels,
caching. Metric definitions follow data_warehouse/pipelines/metrics.py (the single source of truth)."""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, fields
from functools import wraps

import numpy as np
import pandas as pd

from ..integrations import registry

FILTER_FIELDS = ("academic_year", "season", "school_id", "programme_id", "level", "nationality_iso3", "gender", "delivery_mode", "study_load")


@dataclass(frozen=True)
class Filters:
    academic_year: str | None = None
    season: str | None = None              # FALL | SPRING | SUMMER (semester)
    school_id: str | None = None
    programme_id: str | None = None
    level: str | None = None
    nationality_iso3: str | None = None
    gender: str | None = None
    delivery_mode: str | None = None       # FACE_TO_FACE | ONLINE (study mode)
    study_load: str | None = None

    def active(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, "", "ALL")}

    def key(self) -> tuple:
        return tuple(sorted(self.active().items()))


def filters_from(**kw) -> Filters:
    return Filters(**{f.name: (kw.get(f.name) or None) for f in fields(Filters)})


# ------------------------------------------------------------------------------------------------ cache (cleared on source change)
_cache: dict = {}
_lock = threading.Lock()


@registry.on_source_change
def clear_cache():
    with _lock:
        _cache.clear()


def cached(fn):
    @wraps(fn)
    def w(*a, **k):
        key = (fn.__module__, fn.__name__, a, tuple(sorted(k.items())))
        with _lock:
            if key in _cache:
                return _cache[key]
        v = fn(*a, **k)
        with _lock:
            _cache[key] = v
        return v
    return w


# ------------------------------------------------------------------------------------------------ tables & labels
T = registry.table


@cached
def terms() -> pd.DataFrame:
    t = T("reference/academic_terms").copy()
    for c in ("start_date", "census_date", "end_date"):
        t[c] = pd.to_datetime(t[c])
    for c in ("census_passed", "grades_final_available", "in_completed_reporting", "is_regular_term"):
        t[c] = t[c].astype(str) == "True"
    return t.sort_values("term_sequence").reset_index(drop=True)


@cached
def labels() -> dict:
    prog = T("reference/programmes")
    sch = T("reference/schools")
    nat = T("reference/nationalities")
    return {"programme_id": dict(zip(prog["programme_id"], prog["display_name"].str.replace(" [synthetic placeholder]", "", regex=False))),
            "school_id": dict(zip(sch["school_id"], sch["display_name"].str.replace(" [synthetic placeholder]", "", regex=False))),
            "nationality_iso3": dict(zip(nat["nationality_iso3"], nat["label"])),
            "programme_school": dict(zip(prog["programme_id"], prog["school_id"])),
            "programme_level": dict(zip(prog["programme_id"], prog["level"])),
            "placeholder_note": "School and programme names are synthetic placeholders until verified institutional reference data is supplied."}


def label(field: str, value) -> str:
    return labels().get(field, {}).get(value, value)


def term_label(term_id: str) -> str:
    s = {"FA": "Fall", "SP": "Spring", "SU": "Summer"}.get(str(term_id)[-2:], "")
    return f"{s} {str(term_id)[:4]}" if s else str(term_id)


@cached
def students() -> pd.DataFrame:
    return T("registrar/students")[["student_id", "gender", "nationality_iso3", "residency_status"]]


@cached
def enrolments() -> pd.DataFrame:
    """Census term enrolments with student demographics, season and first-term flag."""
    te = T("registrar/term_enrolments")
    tm = terms()[["term_id", "season", "reporting_status", "term_sequence", "census_passed", "grades_final_available"]]
    df = te.drop(columns=["term_sequence"], errors="ignore").merge(tm, on="term_id").merge(students(), on="student_id", how="left")
    first = df.groupby("student_id")["term_sequence"].transform("min")
    df["is_new_student"] = df["term_sequence"] == first           # first-ever term at the institution
    for c in ("grades_final", "withdrew_during_term", "poor_performance_flag"):
        df[c] = df[c].astype(str) == "True"
    return df


def apply_filters(df: pd.DataFrame, f: Filters, mapping: dict | None = None) -> pd.DataFrame:
    """mapping: filter field -> column name in df (default identical). Unknown columns are skipped."""
    mapping = mapping or {}
    for k, v in f.active().items():
        col = mapping.get(k, k)
        if col in df.columns:
            df = df[df[col].astype(str) == str(v)]
    return df


def options() -> dict:
    e = enrolments()
    lab = labels()
    def opts(col, field=None):
        vals = sorted(e[col].dropna().astype(str).unique())
        return [{"value": v, "label": lab.get(field or col, {}).get(v, v.replace("_", " ").title() if v.isupper() else v)} for v in vals]
    return {"academic_year": opts("academic_year"), "season": opts("season"), "school_id": opts("school_id"), "programme_id": opts("programme_id"),
            "level": opts("level"), "nationality_iso3": opts("nationality_iso3"), "gender": opts("gender"),
            "delivery_mode": opts("delivery_mode"), "study_load": opts("study_load"),
            "terms": [{"value": r.term_id, "label": term_label(r.term_id), "reporting_status": r.reporting_status}
                      for r in terms().itertuples() if r.census_passed]}


def pct(a, b):
    return None if not b else round(100.0 * a / b, 2)


def clean(o):
    """JSON-safe conversion (numpy scalars, NaN -> None)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, pd.DataFrame):
        return clean(o.to_dict("records"))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    return o


def envelope(module: str, department: str, payload: dict, definitions: dict, f: Filters | None = None, limitations: list | None = None) -> dict:
    return clean({"module": module, "data": registry.data_label(department), "filters_applied": f.active() if f else {},
                  "definitions": definitions, "limitations": limitations or [], **payload})
