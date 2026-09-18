from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.ingestion.pipeline import run_full_pipeline

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


@router.post("/run")
def run_ingestion(db: Session = Depends(get_db)):
    """Extracts every source from the Sodexo mock API and upserts it into the
    canonical DB - the same pipeline scripts/run_sodexo_ingestion.py drives
    from the CLI, triggered here from the UI's "Run Ingestion" button."""
    started = datetime.utcnow()
    batches = run_full_pipeline(db)
    return {
        "started_at": started.isoformat(),
        "finished_at": datetime.utcnow().isoformat(),
        "batches": [
            {
                "source_system": batch.source_system,
                "source_endpoint": batch.source_endpoint,
                "status": batch.status,
                "records_received": batch.records_received,
                "records_loaded": batch.records_loaded,
                "records_rejected": batch.records_rejected,
                "error_message": batch.error_message,
            }
            for batch in batches
        ],
    }


@router.get("/status")
def ingestion_status(db: Session = Depends(get_db)):
    """The most recent batch per source endpoint - source health at a glance."""
    rows = db.execute(text(
        """
        SELECT b.source_system, b.source_endpoint, b.status, b.started_at, b.completed_at,
               b.records_received, b.records_loaded, b.records_rejected, b.error_message
        FROM ingestion_batch b
        WHERE b.started_at = (
            SELECT MAX(b2.started_at) FROM ingestion_batch b2 WHERE b2.source_endpoint = b.source_endpoint
        )
        ORDER BY b.source_system, b.source_endpoint
        """
    )).mappings().all()
    return {"sources": [dict(row) for row in rows]}
