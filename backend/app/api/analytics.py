"""Institutional analytics endpoints (historical / official figures). Model estimates live under /api/models and /api/predict."""
from __future__ import annotations

import io
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..analytics import departments, enrollment, graduation, performance, retention
from ..analytics.common import Filters, clean, filters_from, options
from ..core.deps import require
from ..core.security import audit
from ..integrations import registry

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
READ = require("analytics:read")


def filt(academic_year: Optional[str] = None, season: Optional[str] = None, school_id: Optional[str] = None,
         programme_id: Optional[str] = None, level: Optional[str] = None, nationality_iso3: Optional[str] = None,
         gender: Optional[str] = None, delivery_mode: Optional[str] = None, study_load: Optional[str] = None) -> Filters:
    return filters_from(**locals())


@router.get("/options")
def get_options(user=Depends(READ)):
    return clean({**options(), "data": registry.data_label()})


@router.get("/overview")
def overview(user=Depends(READ)):
    f = Filters()
    e, p, g, a = enrollment.summary(f), performance.summary(f), graduation.summary(f), departments.admissions(f)
    return clean({"data": registry.data_label(), "enrollment": e["kpis"], "enrollment_trend": e.get("trend"),
                  "performance": p["kpis"], "retention": retention.headline(), "graduation": g["kpis"], "admissions": a["kpis"],
                  "finance": departments.finance()["kpis"], "it": departments.it()["kpis"]})


@router.get("/enrollment")
def get_enrollment(term_id: Optional[str] = None, f: Filters = Depends(filt), user=Depends(READ)):
    return enrollment.summary(f, term_id)


@router.get("/enrollment/compare")
def get_enrollment_compare(term_a: str, term_b: str, by: str = "school_id", f: Filters = Depends(filt), user=Depends(READ)):
    if by not in ("school_id", "programme_id", "level", "nationality_iso3", "gender", "delivery_mode", "study_load"):
        raise HTTPException(422, "invalid breakdown")
    return enrollment.compare(f, term_a, term_b, by)


@router.get("/performance")
def get_performance(term_id: Optional[str] = None, f: Filters = Depends(filt), user=Depends(READ)):
    return performance.summary(f, term_id)


@router.get("/performance/attention")
def get_attention(f: Filters = Depends(filt), user=Depends(READ)):
    return clean(performance.attention(f))


@router.get("/retention")
def get_retention(comparison: str = "FALL_TO_FALL", base_term: Optional[str] = None, f: Filters = Depends(filt), user=Depends(READ)):
    if comparison not in retention.COMPARISONS:
        raise HTTPException(422, f"comparison must be one of {list(retention.COMPARISONS)}")
    return retention.summary(f, comparison, base_term)


@router.get("/graduation")
def get_graduation(f: Filters = Depends(filt), user=Depends(READ)):
    return graduation.summary(f)


@router.get("/admissions")
def get_admissions(f: Filters = Depends(filt), user=Depends(READ)):
    return departments.admissions(f)


@router.get("/finance")
def get_finance(user=Depends(READ)):
    return departments.finance()


@router.get("/it")
def get_it(user=Depends(READ)):
    return departments.it()


EXPORTS = {"enrollment": enrollment.export_rows, "performance": performance.export_rows, "retention": retention.export_rows,
           "graduation": graduation.export_rows}


@router.get("/export/{module}.csv")
def export(module: str, f: Filters = Depends(filt), user=Depends(require("analytics:read", "reports:export"))):
    if module not in EXPORTS:
        raise HTTPException(404, "unknown export")
    df: pd.DataFrame = EXPORTS[module](f)
    lab = registry.data_label("REGISTRAR")
    buf = io.StringIO()
    buf.write(f"# {module} export; filters={f.active()}; data source: {lab}\n")
    df.to_csv(buf, index=False)
    audit("export", user, target=module, detail={"filters": f.active(), "rows": len(df)}, ip=user["ip"])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{module}_export.csv"'})
