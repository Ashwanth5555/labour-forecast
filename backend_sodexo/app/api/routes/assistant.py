from typing import Literal

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.assistant import llm, service

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.get("/status")
def status():
    return {"llm_configured": llm.is_configured()}


class AssistantTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AssistantQuestion(BaseModel):
    question: str
    # Prior turns, oldest first, excluding the question being asked. Optional,
    # so an existing caller that only sends `question` keeps working; sending
    # it is what makes follow-ups like "why?" or "what about the cafe?" resolve.
    history: list[AssistantTurn] = Field(default_factory=list)


@router.post("/ask")
def ask(payload: AssistantQuestion, db: Session = Depends(get_db)):
    return service.ask(db, payload.question, [t.model_dump() for t in payload.history])
