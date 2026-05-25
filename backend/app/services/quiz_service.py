from uuid import UUID

from app.models.lesson import QuizQuestion
from app.schemas.quiz import QuizAnswerItem, QuizQuestionResult


def grade_quiz(
    questions: list[QuizQuestion],
    answers: list[QuizAnswerItem],
) -> tuple[float, int, list[QuizQuestionResult]]:
    """
    Grade submitted answers against questions.

    Raises ValueError for invalid inputs:
    - answer.question_id not belonging to this lesson's questions
    - duplicate question_id in answers

    Missing answers (questions with no submitted answer) count as incorrect.
    Returns (score, correct_count, per-question results with correct_index exposed).
    """
    question_map: dict[UUID, QuizQuestion] = {q.id: q for q in questions}
    total = len(questions)

    seen: set[UUID] = set()
    for answer in answers:
        if answer.question_id not in question_map:
            raise ValueError(f"Unknown question_id: {answer.question_id}")
        if answer.question_id in seen:
            raise ValueError(f"Duplicate question_id: {answer.question_id}")
        seen.add(answer.question_id)

    answer_map: dict[UUID, int] = {a.question_id: a.selected_index for a in answers}
    results: list[QuizQuestionResult] = []
    correct_count = 0

    for question in questions:
        selected = answer_map.get(question.id)
        is_correct = selected is not None and selected == question.correct_index
        if is_correct:
            correct_count += 1
        results.append(
            QuizQuestionResult(
                question_id=question.id,
                correct=is_correct,
                correct_index=question.correct_index,
            )
        )

    score = correct_count / total if total > 0 else 0.0
    return score, correct_count, results
