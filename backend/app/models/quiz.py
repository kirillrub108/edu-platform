import enum
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class QuizStatus(str, enum.Enum):
    draft = "draft"
    published = "published"


class QuestionType(str, enum.Enum):
    single_choice = "single_choice"
    multiple_choice = "multiple_choice"
    true_false = "true_false"
    short_answer = "short_answer"
    essay = "essay"
    matching = "matching"
    ordering = "ordering"
    fill_blank = "fill_blank"


class AttemptStatus(str, enum.Enum):
    in_progress = "in_progress"
    submitted = "submitted"
    graded = "graded"


class Quiz(Base):
    __tablename__ = "quizzes"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("lesson_id", name="uq_quizzes_lesson_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(
        SAEnum(QuizStatus, name="quiz_status"),
        default=QuizStatus.draft,
        nullable=False,
    )
    attempts_allowed = Column(Integer, nullable=True)  # null = unlimited
    pass_threshold = Column(Numeric(5, 4), nullable=False, default=0.6)
    show_answers = Column(Boolean, nullable=False, default=True)
    shuffle = Column(Boolean, nullable=False, default=False)
    generation_task_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    lesson = relationship("Lesson", back_populates="quiz")
    # Only the live ("current") version rows. Historical versions stay in the
    # table to back per-attempt snapshots; teachers never need to see them.
    # viewonly=True because lifecycle (insert new version / supersede / soft-
    # delete) is managed explicitly by services, not by ORM cascades.
    questions = relationship(
        "QuizQuestion",
        primaryjoin=(
            "and_(Quiz.id == QuizQuestion.quiz_id,"
            " QuizQuestion.superseded_at.is_(None))"
        ),
        order_by="QuizQuestion.order",
        viewonly=True,
    )
    attempts = relationship(
        "QuizAttempt",
        back_populates="quiz",
        cascade="all, delete-orphan",
    )


class QuizQuestion(Base):
    """Versioned, immutable question rows.

    Each meaningful edit (payload / weight / regenerate) INSERTs a new row with
    the same `id` and `version + 1`, then sets the old row's `superseded_at`.
    Reorder and soft-delete mutate the current row in place — order is part of
    the snapshot, soft-delete just sets `superseded_at`.

    Attempts reference (id, version) pairs via QuizAttempt.questions_snapshot,
    so historical versions stay queryable forever (no GC in this PR).
    """
    __tablename__ = "quiz_questions"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        # Partial index serving the "current questions for this quiz" hot path.
        Index(
            "ix_quiz_questions_current",
            "quiz_id",
            "order",
            postgresql_where=Column("superseded_at").is_(None),
        ),
        Index("ix_quiz_questions_quiz_id", "quiz_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version = Column(Integer, primary_key=True, default=1, nullable=False)
    quiz_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
    )
    type = Column(
        SAEnum(QuestionType, name="question_type"),
        nullable=False,
    )
    payload = Column(JSONB, nullable=False)
    weight = Column(Numeric(6, 3), nullable=False, default=1.0)
    order = Column(Integer, default=0, nullable=False)
    # NULL = current version. Set to now() when superseded by a new version
    # or when the question is soft-deleted.
    superseded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    quiz = relationship("Quiz", back_populates="questions")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint(
            "quiz_id", "student_id", "attempt_number",
            name="uq_quiz_attempts_quiz_student_number",
        ),
        Index("ix_quiz_attempts_quiz_student", "quiz_id", "student_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number = Column(Integer, nullable=False)
    status = Column(
        SAEnum(AttemptStatus, name="attempt_status"),
        default=AttemptStatus.in_progress,
        nullable=False,
    )
    score = Column(Numeric(5, 4), nullable=True)
    passed = Column(Boolean, nullable=True)
    # Frozen at attempt start; the only source of truth for grading.
    questions_snapshot = Column(JSONB, nullable=False)
    grading_task_id = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    graded_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    quiz = relationship("Quiz", back_populates="attempts")
    answers = relationship(
        "QuizAnswer",
        back_populates="attempt",
        cascade="all, delete-orphan",
    )


class QuizAnswer(Base):
    __tablename__ = "quiz_answers"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "question_id",
            name="uq_quiz_answers_attempt_question",
        ),
        Index("ix_quiz_answers_attempt_id", "attempt_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quiz_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Refers to a question id inside the attempt's questions_snapshot;
    # NOT a FK to quiz_questions (snapshot is the source of truth).
    question_id = Column(UUID(as_uuid=True), nullable=False)
    response = Column(JSONB, nullable=False, server_default="{}")
    awarded_score = Column(Numeric(6, 4), nullable=True)
    max_score = Column(Numeric(6, 4), nullable=False, default=1.0)
    is_correct = Column(Boolean, nullable=True)
    needs_review = Column(Boolean, nullable=False, default=False)
    llm_feedback = Column(Text, nullable=True)
    manually_overridden = Column(Boolean, nullable=False, default=False)
    graded_by_ai = Column(Boolean, nullable=False, server_default="false")
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    attempt = relationship("QuizAttempt", back_populates="answers")
