"""Model catalogue, evaluation, figures, predictions (single / CSV batch / current cohort), history, forecasts, segmentation."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from ..core.config import get_settings
from ..core.deps import require
from ..core.security import audit
from ..ml import service as ml

router = APIRouter(prefix="/api", tags=["models"])
MODELS = require("models:read")
RUN = require("predictions:run")


class PredictIn(BaseModel):
    rows: list[dict] = Field(min_length=1, max_length=200)
    explain: bool = True


def _strip_ids(res: dict, user: dict) -> dict:
    """Pseudonymous IDs are only returned to users allowed to see student-level results."""
    if "student_level:read" not in user["permissions"]:
        for r in res["rows"]:
            r.pop("id", None)
    return res


# ------------------------------------------------------------------------------------------------ catalogue & evaluation
@router.get("/models")
def list_models(user=Depends(MODELS)):
    return {"tasks": ml.catalogue(), "decision_support": ml.DECISION_SUPPORT, "limitations": ml.MODULE_LIMITATIONS}


@router.get("/models/status")
def models_status(user=Depends(MODELS)):
    return ml.model_status()


@router.get("/models/{task}")
def model_detail(task: str, user=Depends(MODELS)):
    return ml.task_detail(task)


@router.get("/models/{task}/schema")
def model_schema(task: str, user=Depends(MODELS)):
    return ml.input_schema(task)


@router.get("/models/{task}/template.csv")
def model_template(task: str, user=Depends(MODELS)):
    return Response(ml.template_csv(task), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{task}_template.csv"'})


@router.get("/figures/{path:path}")
def figure(path: str, user=Depends(MODELS)):
    """Evaluation / forecasting / segmentation figures. Only PNG files under data_warehouse/reports are served."""
    root = (get_settings().dw_root / "reports").resolve()
    p = (get_settings().dw_root / path).resolve()
    if p.suffix.lower() != ".png" or root not in p.parents or not p.exists():
        raise HTTPException(404, "figure not found")
    return FileResponse(p, media_type="image/png")


# ------------------------------------------------------------------------------------------------ predictions
@router.post("/predict/{task}")
def predict(task: str, body: PredictIn, user=Depends(RUN)):
    res = ml.predict_frame(task, pd.DataFrame(body.rows), explain=body.explain)
    res["run_id"] = ml.record_run(user, task, res, "single" if len(body.rows) == 1 else "batch", "form input")
    audit("predict", user, target=task, detail={"mode": "form", "rows": len(body.rows), "run_id": res["run_id"]}, ip=user["ip"])
    return _strip_ids(res, user)


@router.post("/predict/{task}/batch")
async def predict_batch(task: str, file: UploadFile = File(...), user=Depends(RUN)):
    content = await file.read()
    df = ml.read_csv_upload(content, file.filename or "")
    res = ml.predict_frame(task, df, explain=False)
    keep = [c for c in ml.ID_COLUMNS if c in df.columns]
    res["run_id"] = ml.record_run(user, task, res, "batch", file.filename, df[keep] if keep else None)
    audit("predict", user, target=task, detail={"mode": "csv", "file": file.filename, "rows": len(df), "run_id": res["run_id"]}, ip=user["ip"])
    res["rows"] = res["rows"][:500]
    res["rows_truncated"] = len(df) > 500
    return _strip_ids(res, user)


@router.post("/predict/{task}/cohort")
def predict_cohort(task: str, user=Depends(require("predictions:run", "student_level:read"))):
    df = ml.cohort_frame(task)
    res = ml.predict_frame(task, df, explain=False)          # row ids = pseudonymous student_id
    cols = df[["student_id", "programme_id", "level", "term_id"]].rename(columns={"term_id": "base_term_id"})
    for r, (_, x) in zip(res["rows"], cols.iterrows()):
        r.update({"id": x["student_id"], "programme_id": x["programme_id"], "level": x["level"], "base_term_id": x["base_term_id"]})
    res["run_id"] = ml.record_run(user, task, res, "cohort", "current cohort", cols)
    res["cohort_rule"] = ml.COHORT_RULES[task]["note"]
    audit("predict", user, target=task, detail={"mode": "cohort", "rows": len(df), "run_id": res["run_id"]}, ip=user["ip"])
    return res


@router.get("/predictions")
def prediction_history(limit: int = Query(200, ge=1, le=1000), user=Depends(require("predictions:history"))):
    return {"runs": ml.history(user, limit)}


@router.get("/predictions/{rid}/download")
def prediction_download(rid: int, user=Depends(require("predictions:history", "reports:export"))):
    p = ml.run_file(user, rid)
    audit("download_predictions", user, target=str(rid), ip=user["ip"])
    return FileResponse(p, media_type="text/csv", filename=f"prediction_run_{rid}.csv")


# ------------------------------------------------------------------------------------------------ forecasting & segmentation
@router.get("/forecasts")
def forecasts(user=Depends(require("analytics:read"))):
    return ml.forecasts()


@router.get("/forecasts/history")
def forecasts_history(series: str, user=Depends(require("analytics:read"))):
    return ml.forecast_history(series)


@router.get("/segmentation")
def segmentation(user=Depends(require("analytics:read"))):
    res = ml.segmentation()
    if "student_level:read" not in user["permissions"]:
        res["anomalies"] = []
        res["anomalies_hidden"] = "student-level anomaly list requires the student_level:read permission"
    return res


@router.get("/segmentation/assignments.csv")
def segmentation_assignments(user=Depends(require("student_level:read", "reports:export"))):
    df = ml.segmentation_assignments()
    audit("export", user, target="segmentation_assignments", detail={"rows": len(df)}, ip=user["ip"])
    return StreamingResponse(iter([df.to_csv(index=False)]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="segmentation_assignments.csv"'})
