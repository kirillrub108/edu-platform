import uuid

from sqlalchemy import Column, DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class GenerationUsage(Base):
    """Append-only journal of actual provider spend per AI call (margin control).

    One row per real LLM/vision/TTS provider request — cache hits never get
    here. lesson_id/quiz_id are plain UUIDs (no FK) so the journal survives
    lesson/quiz purges. The user-facing price is the deterministic credit
    formula; this table records the underlying ruble cost for calibration.
    """

    __tablename__ = "generation_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation = Column(String(32), nullable=False)
    model = Column(String(128), nullable=False)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    chars = Column(Integer, nullable=True)
    cost_rub = Column(Numeric(12, 4), nullable=False, default=0, server_default="0")
    lesson_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    quiz_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
