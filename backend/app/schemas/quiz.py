from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QuizQuestionStudentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    question: str
    options: list[str]
    order: int


class QuizAnswerItem(BaseModel):
    question_id: UUID
    selected_index: int = Field(ge=0)


class QuizAnswerSubmit(BaseModel):
    answers: list[QuizAnswerItem]


class QuizQuestionResult(BaseModel):
    question_id: UUID
    correct: bool
    correct_index: int


class QuizResultRead(BaseModel):
    score: float
    correct_count: int
    total: int
    passed: bool
    questions: list[QuizQuestionResult]


class QuizTeacherResultRow(BaseModel):
    student_id: UUID
    full_name: str | None
    email: str
    quiz_score: float | None
    attempted: bool
    completed: bool
