import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.deps import require_user
from app.api.routes import analytics, assistant, auth, data_quality, forecast, forecast_workspace, ingestion, predictions, punch_analytics, recommendations, training
from app.core.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Sodexo Healthcare Forecasting POC - Application API",
    description="Ingestion trigger, multi-model forecasting engine, labor analytics, time punch anomaly detection, predictive risk models, AI recommendations, AI assistant, and data quality for the Sodexo Healthcare labor-forecasting POC.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        # Lightweight self-migration: create_all only creates missing tables,
        # it never adds columns to a table that already exists. Add any new
        # model_run columns here so an existing sodexo.db picks them up.
        existing_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(model_run)"))}
        if "train_rows" not in existing_columns:
            conn.execute(text("ALTER TABLE model_run ADD COLUMN train_rows INTEGER"))
        if "test_rows" not in existing_columns:
            conn.execute(text("ALTER TABLE model_run ADD COLUMN test_rows INTEGER"))

        # A training_job can only be genuinely "RUNNING" while the process
        # that started its background thread is still alive - if we're
        # starting up and one is marked RUNNING, that process is gone (a
        # restart or crash killed the thread mid-run). Self-heal so the UI
        # doesn't show a stale "training in progress" forever.
        conn.execute(text(
            "UPDATE training_job SET status='FAILED', "
            "error_message='Interrupted by a server restart mid-training.', "
            "completed_at=CURRENT_TIMESTAMP WHERE status='RUNNING'"
        ))

    from app.core.users import ensure_demo_users

    db = SessionLocal()
    try:
        created = ensure_demo_users(db)
        if created:
            logger.info("Created application logins: %s", ", ".join(created))
    finally:
        db.close()


# Open: the login itself, plus the unauthenticated health/root probes below.
app.include_router(auth.router)

# Everything else requires a valid token. Applied here as a router dependency
# rather than inside each route, so a new endpoint added to any of these
# routers is protected by default instead of by remembering to protect it.
_authenticated = [Depends(require_user)]
app.include_router(ingestion.router, dependencies=_authenticated)
app.include_router(training.router, dependencies=_authenticated)
app.include_router(forecast.router, dependencies=_authenticated)
app.include_router(forecast_workspace.router, dependencies=_authenticated)
app.include_router(analytics.router, dependencies=_authenticated)
app.include_router(punch_analytics.router, dependencies=_authenticated)
app.include_router(predictions.router, dependencies=_authenticated)
app.include_router(recommendations.router, dependencies=_authenticated)
app.include_router(assistant.router, dependencies=_authenticated)
app.include_router(data_quality.router, dependencies=_authenticated)


@app.get("/health")
def health():
    return {"status": "UP", "service": "backend-sodexo-application-api"}


@app.get("/")
def root():
    return {"service": "Sodexo Healthcare Forecasting POC - Application API", "docs": "/docs", "health": "/health"}
