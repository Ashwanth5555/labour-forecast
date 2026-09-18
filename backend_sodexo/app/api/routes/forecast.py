from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ModelPrediction, ModelRun, TrainingJob
from app.services.forecasting.contract import SERIES

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


@router.get("/series")
def list_series():
    return {"series": [{"series_key": s.key, "series_label": s.label} for s in SERIES]}


@router.get("")
def get_forecast(
    series_key: str = Query(...),
    model_id: str | None = Query(None, description="Omit to use the series champion"),
    db: Session = Depends(get_db),
):
    job = db.execute(select(TrainingJob).order_by(TrainingJob.started_at.desc())).scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="No training run has completed yet - click Train All Models first.")

    query = select(ModelRun).where(ModelRun.job_id == job.job_id, ModelRun.series_key == series_key)
    if model_id:
        query = query.where(ModelRun.model_id == model_id)
    else:
        query = query.where(ModelRun.is_champion.is_(True))
    run = db.execute(query).scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail=f"No completed model found for series '{series_key}'" + (f" and model '{model_id}'" if model_id else " (no champion - all models may be not_applicable or failed)"))

    predictions = db.execute(
        select(ModelPrediction).where(ModelPrediction.model_run_id == run.id).order_by(ModelPrediction.business_date, ModelPrediction.hour_of_day)
    ).scalars().all()

    return {
        "series_key": run.series_key, "model_id": run.model_id, "model_label": run.model_label, "is_champion": run.is_champion,
        "evaluation_mode": run.evaluation_mode, "folds": run.folds, "train_rows": run.train_rows, "test_rows": run.test_rows,
        "metrics": {"mape": run.mape, "rmse": run.rmse, "mae": run.mae, "wape": run.wape, "bias": run.bias, "accuracy": run.accuracy},
        "points": [
            {
                "date": f"{p.business_date.isoformat()}T{p.hour_of_day:02d}:00:00",
                "actual": p.actual, "predicted": p.predicted, "lower": p.lower, "upper": p.upper,
                "is_future": p.is_future, "fold": p.fold,
            }
            for p in predictions
        ],
    }
