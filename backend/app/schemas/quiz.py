"""Quiz schemas — polymorphic by `type` discriminator.

Two parallel question-read families exist to prevent reference-answer leakage:

  * `*Teacher*`  — full payload, including correct indices / reference answers.
  * `*Student*`  — payload stripped of any answer data; what the test-taker sees.

The discriminator is `type`. New types must register a Payload variant in both
families so static validation catches missing branches.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.quiz import AttemptStatus, QuestionType, QuizStatus


# ── Teacher-facing payloads (with reference answers) ────────────────────────


class SingleChoicePayloadT(BaseModel):
    type: Literal["single_choice"] = "single_choice"
    prompt: str = Field(min_length=1)
    options: list[str] = Field(min_length=2)
    correct_index: int = Field(ge=0)
    explanation: str = ""

    @model_validator(mode="after")
    def _check_index(self) -> "SingleChoicePayloadT":
        if not 0 <= self.correct_index < len(self.options):
            raise ValueError("correct_index out of range")
        return self


class MultipleChoicePayloadT(BaseModel):
    type: Literal["multiple_choice"] = "multiple_choice"
    prompt: str = Field(min_length=1)
    options: list[str] = Field(min_length=2)
    correct_indices: list[int] = Field(min_length=1)
    explanation: str = ""

    @model_validator(mode="after")
    def _check_indices(self) -> "MultipleChoicePayloadT":
        if len(set(self.correct_indices)) != len(self.correct_indices):
            raise ValueError("correct_indices must be unique")
        if any(not 0 <= i < len(self.options) for i in self.correct_indices):
            raise ValueError("correct_indices out of range")
        return self


class TrueFalsePayloadT(BaseModel):
    type: Literal["true_false"] = "true_false"
    prompt: str = Field(min_length=1)
    correct: bool
    explanation: str = ""


class ShortAnswerPayloadT(BaseModel):
    type: Literal["short_answer"] = "short_answer"
    prompt: str = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    rubric: str = ""


class EssayPayloadT(BaseModel):
    type: Literal["essay"] = "essay"
    prompt: str = Field(min_length=1)
    rubric: str = Field(min_length=1)


class MatchingPayloadT(BaseModel):
    type: Literal["matching"] = "matching"
    prompt: str = Field(min_length=1)
    left: list[str] = Field(min_length=2)
    right: list[str] = Field(min_length=2)
    correct_pairs: list[tuple[int, int]] = Field(min_length=1)
    explanation: str = ""

    @model_validator(mode="after")
    def _check_pairs(self) -> "MatchingPayloadT":
        for li, ri in self.correct_pairs:
            if not 0 <= li < len(self.left):
                raise ValueError("matching: left index out of range")
            if not 0 <= ri < len(self.right):
                raise ValueError("matching: right index out of range")
        if len({li for li, _ in self.correct_pairs}) != len(self.correct_pairs):
            raise ValueError("matching: duplicate left indices")
        return self


class OrderingPayloadT(BaseModel):
    type: Literal["ordering"] = "ordering"
    prompt: str = Field(min_length=1)
    items: list[str] = Field(min_length=2)
    correct_order: list[int] = Field(min_length=2)
    explanation: str = ""

    @model_validator(mode="after")
    def _check_order(self) -> "OrderingPayloadT":
        if sorted(self.correct_order) != list(range(len(self.items))):
            raise ValueError("correct_order must be a permutation of 0..N-1")
        return self


class FillBlankPayloadT(BaseModel):
    type: Literal["fill_blank"] = "fill_blank"
    prompt: str = Field(min_length=1)  # contains "___" markers, one per blank
    blanks: list[list[str]] = Field(min_length=1)
    case_insensitive: bool = True
    explanation: str = ""

    @model_validator(mode="after")
    def _check_blanks(self) -> "FillBlankPayloadT":
        if any(not alts or any(not a.strip() for a in alts) for alts in self.blanks):
            raise ValueError("each blank must have at least one non-empty alternative")
        if self.prompt.count("___") != len(self.blanks):
            raise ValueError("prompt '___' marker count must equal len(blanks)")
        return self


QuestionPayloadTeacher = Annotated[
    SingleChoicePayloadT
    | MultipleChoicePayloadT
    | TrueFalsePayloadT
    | ShortAnswerPayloadT
    | EssayPayloadT
    | MatchingPayloadT
    | OrderingPayloadT
    | FillBlankPayloadT,
    Field(discriminator="type"),
]


# ── Student-facing payloads (no reference answers) ──────────────────────────


class SingleChoicePayloadS(BaseModel):
    type: Literal["single_choice"] = "single_choice"
    prompt: str
    options: list[str]


class MultipleChoicePayloadS(BaseModel):
    type: Literal["multiple_choice"] = "multiple_choice"
    prompt: str
    options: list[str]


class TrueFalsePayloadS(BaseModel):
    type: Literal["true_false"] = "true_false"
    prompt: str


class ShortAnswerPayloadS(BaseModel):
    type: Literal["short_answer"] = "short_answer"
    prompt: str


class EssayPayloadS(BaseModel):
    type: Literal["essay"] = "essay"
    prompt: str


class MatchingPayloadS(BaseModel):
    type: Literal["matching"] = "matching"
    prompt: str
    left: list[str]
    right: list[str]


class OrderingPayloadS(BaseModel):
    type: Literal["ordering"] = "ordering"
    prompt: str
    items: list[str]


class FillBlankPayloadS(BaseModel):
    type: Literal["fill_blank"] = "fill_blank"
    prompt: str
    blanks_count: int


QuestionPayloadStudent = Annotated[
    SingleChoicePayloadS
    | MultipleChoicePayloadS
    | TrueFalsePayloadS
    | ShortAnswerPayloadS
    | EssayPayloadS
    | MatchingPayloadS
    | OrderingPayloadS
    | FillBlankPayloadS,
    Field(discriminator="type"),
]


def to_student_payload(teacher_payload: dict[str, Any]) -> dict[str, Any]:
    """Strip reference-answer fields from a stored payload (JSONB dict)."""
    t = teacher_payload.get("type")
    if t == "single_choice":
        return {"type": t, "prompt": teacher_payload["prompt"], "options": teacher_payload["options"]}
    if t == "multiple_choice":
        return {"type": t, "prompt": teacher_payload["prompt"], "options": teacher_payload["options"]}
    if t == "true_false":
        return {"type": t, "prompt": teacher_payload["prompt"]}
    if t == "short_answer":
        return {"type": t, "prompt": teacher_payload["prompt"]}
    if t == "essay":
        return {"type": t, "prompt": teacher_payload["prompt"]}
    if t == "matching":
        return {
            "type": t,
            "prompt": teacher_payload["prompt"],
            "left": teacher_payload["left"],
            "right": teacher_payload["right"],
        }
    if t == "ordering":
        return {
            "type": t,
            "prompt": teacher_payload["prompt"],
            "items": teacher_payload["items"],
        }
    if t == "fill_blank":
        return {
            "type": t,
            "prompt": teacher_payload["prompt"],
            "blanks_count": len(teacher_payload["blanks"]),
        }
    raise ValueError(f"unknown question type: {t!r}")


# ── Question CRUD schemas (teacher) ─────────────────────────────────────────


class QuizQuestionCreate(BaseModel):
    type: QuestionType
    payload: QuestionPayloadTeacher
    weight: Decimal = Decimal("1.0")
    order: int = 0


class QuizQuestionUpdate(BaseModel):
    payload: QuestionPayloadTeacher | None = None
    weight: Decimal | None = None
    order: int | None = None


class QuizQuestionTeacherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    quiz_id: UUID
    type: QuestionType
    payload: dict[str, Any]
    weight: Decimal
    order: int


class QuizQuestionStudentRead(BaseModel):
    id: UUID
    type: QuestionType
    payload: dict[str, Any]
    order: int


class QuizQuestionReorder(BaseModel):
    order: list[UUID]


# ── Quiz settings (teacher) ─────────────────────────────────────────────────


class QuizRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    lesson_id: UUID
    status: QuizStatus
    attempts_allowed: int | None
    pass_threshold: Decimal
    show_answers: bool
    shuffle: bool
    generation_task_id: str | None
    created_at: datetime
    updated_at: datetime


class QuizSettingsUpdate(BaseModel):
    attempts_allowed: int | None | Literal["__unset__"] = "__unset__"
    pass_threshold: Decimal | None = Field(default=None, ge=0, le=1)
    show_answers: bool | None = None
    shuffle: bool | None = None

    @model_validator(mode="after")
    def _validate_attempts(self) -> "QuizSettingsUpdate":
        if self.attempts_allowed != "__unset__":
            a = self.attempts_allowed
            if a is not None and a < 1:
                raise ValueError("attempts_allowed must be >= 1 or null")
        return self


# ── Generation (LLM) ────────────────────────────────────────────────────────

# Subset of types the LLM is allowed to generate. Matching/ordering/fill_blank
# come out poorly from current open-weight models; teachers add those manually.
GeneratableType = Literal[
    "single_choice", "multiple_choice", "true_false", "short_answer"
]


class QuizGenerateRequest(BaseModel):
    num_questions: int | None = Field(default=None, ge=1, le=20)
    num_options: int | None = Field(default=None, ge=2, le=8)
    types: list[GeneratableType] | None = None  # None = use QUIZ_TYPE_DISTRIBUTION default mix


class QuizGenerateResponse(BaseModel):
    task_id: str
    quiz_id: UUID
    lesson_id: UUID


class QuizGenerationStatus(BaseModel):
    task_id: str
    status: str
    step: str | None = None
    done: int | None = None
    total: int | None = None
    error: str | None = None


# ── Per-question AI ops (teacher) ───────────────────────────────────────────

RegenerateMode = Literal["rephrase", "harder", "easier", "improve_distractors"]


class QuizRegenerateRequest(BaseModel):
    mode: RegenerateMode


FlagKind = Literal["ok", "wrong_answer", "ambiguous", "duplicate"]


class QuestionFlag(BaseModel):
    question_id: UUID
    kind: FlagKind
    note: str = ""


# ── Attempt (student) ───────────────────────────────────────────────────────


class QuizAttemptStartResponse(BaseModel):
    attempt_id: UUID
    quiz_id: UUID
    attempt_number: int
    started_at: datetime
    questions: list[QuizQuestionStudentRead]


class AnswerInput(BaseModel):
    question_id: UUID
    response: dict[str, Any]


class QuizAttemptSave(BaseModel):
    answers: list[AnswerInput]


class QuizAnswerStudentResult(BaseModel):
    question_id: UUID
    awarded_score: Decimal | None
    max_score: Decimal
    is_correct: bool | None
    needs_review: bool
    llm_feedback: str | None = None
    # Filled only when show_answers && attempts_allowed == 1 — never otherwise.
    correct_payload: dict[str, Any] | None = None


class QuizAttemptResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    attempt_id: UUID
    quiz_id: UUID
    attempt_number: int
    status: AttemptStatus
    score: Decimal | None
    passed: bool | None
    started_at: datetime
    submitted_at: datetime | None
    graded_at: datetime | None
    grading_task_id: str | None
    # Question definitions as the student saw them — never with reference answers.
    questions: list[QuizQuestionStudentRead]
    # User's submitted responses + per-question grading outcome.
    answers: list[QuizAnswerStudentResult]


class QuizSubmitResponse(BaseModel):
    attempt_id: UUID
    status: AttemptStatus
    score: Decimal | None
    passed: bool | None
    grading_task_id: str | None  # Set when any LLM grading was queued.


# ── Teacher attempts view + manual override ─────────────────────────────────


class QuizAttemptTeacherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    quiz_id: UUID
    student_id: UUID
    student_email: str
    student_full_name: str | None
    attempt_number: int
    status: AttemptStatus
    score: Decimal | None
    passed: bool | None
    submitted_at: datetime | None
    graded_at: datetime | None
    has_pending_review: bool


class QuizAnswerTeacherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    question_id: UUID
    question_payload: dict[str, Any]
    response: dict[str, Any]
    awarded_score: Decimal | None
    max_score: Decimal
    is_correct: bool | None
    needs_review: bool
    llm_feedback: str | None
    manually_overridden: bool


class QuizAttemptTeacherDetail(QuizAttemptTeacherRead):
    answers: list[QuizAnswerTeacherRead]


class AnswerOverride(BaseModel):
    awarded_score: Decimal = Field(ge=0)
    feedback: str | None = None


# ── Student attempts history ─────────────────────────────────────────────────


class QuizAttemptSummary(BaseModel):
    id: UUID
    attempt_number: int
    score: float | None
    passed: bool | None
    attempted_at: datetime
    status: AttemptStatus


class MyQuizAttemptsResponse(BaseModel):
    attempts: list[QuizAttemptSummary]
    best_score: float | None
    final_score: float | None
    is_manual: bool
    is_passed: bool


# ── Teacher grade override ────────────────────────────────────────────────────


class GradeOverride(BaseModel):
    score: float = Field(ge=0.0, le=1.0)


class GradeOverrideResponse(BaseModel):
    lesson_id: UUID
    student_id: UUID
    manual_override_score: float
    is_completed: bool


# ── Legacy aggregate (teacher /quiz-results) ────────────────────────────────


class QuizTeacherResultRow(BaseModel):
    student_id: UUID
    full_name: str | None
    email: str
    best_score: Decimal | None
    attempts_count: int
    passed: bool
    last_submitted_at: datetime | None
