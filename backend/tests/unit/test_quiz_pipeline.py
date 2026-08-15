"""Unit tests for app.tasks.quiz_pipeline — the Celery side of the quiz domain.

Tasks are prefork/sync by contract, so the DB is a mocked sync Session here (an
AsyncSession inside app/tasks/* deadlocks the worker). The behaviour under test
is the money-and-state bookkeeping around the LLM call: credits are charged only
on success, released on every failure path, the polling handle is always
cleared, and a passed attempt never regresses a better earlier result.

The `graded_by_ai` flag written by grade_attempt_task is covered separately in
test_quiz_graded_by_ai_unit.py.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.constants import CREDIT_WEIGHTS
from app.models.quiz import Quiz
from app.services.llm_service import LLMOutputError
from app.services.quiz_service import EmptyMaterialError
from app.tasks import quiz_pipeline as qp

pytestmark = pytest.mark.unit

_ESTIMATE = CREDIT_WEIGHTS["quiz_generate"]


class _Recorder:
    """Collects the positional args of every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any, **_kwargs: Any) -> None:
        self.calls.append(args)


@pytest.fixture()
def gen_env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Wire generate_quiz_task to a mocked session and stubbed collaborators."""
    quiz = MagicMock()
    quiz.id = uuid.uuid4()
    quiz.generation_task_id = "task-123"

    session = MagicMock()
    session.get.side_effect = lambda model, pk: quiz if pk == quiz.id else None
    session.query.return_value.filter.return_value.first.return_value = quiz

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session)
    session_ctx.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(qp, "SyncSession", MagicMock(return_value=session_ctx))

    generated = [{"type": "single_choice", "payload": {}, "weight": "1.0", "order": 0}]

    async def _generate(*_args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        env.generate_kwargs = kwargs
        return generated

    replaced = _Recorder()
    finalize = _Recorder()
    release_slot = _Recorder()
    published: list[dict[str, Any]] = []

    monkeypatch.setattr(qp, "assemble_material_sync", lambda _s, _lid: "Материал лекции")
    monkeypatch.setattr(qp, "get_or_create_quiz_sync", lambda _s, _lid: quiz)
    monkeypatch.setattr(qp, "replace_questions_sync", replaced)
    monkeypatch.setattr(qp, "sync_finalize_generation", finalize)
    monkeypatch.setattr(qp, "sync_release_slot", release_slot)
    monkeypatch.setattr(qp, "_publish", lambda _lid, payload: published.append(payload))
    monkeypatch.setattr(qp.llm_service, "generate_quiz_v2", _generate)

    env = SimpleNamespace(
        session=session,
        quiz=quiz,
        generated=generated,
        replaced=replaced,
        finalize=finalize,
        release_slot=release_slot,
        published=published,
        generate_kwargs={},
    )
    return env


def _run_generate(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "lesson_id": str(uuid.uuid4()),
        "num_questions": 5,
        "num_options": 4,
        "types": ["single_choice"],
        "billing_ref": "hold-1",
        "billed_via": "credits",
        "owner_id": str(uuid.uuid4()),
    }
    args.update(overrides)
    # apply() gives the bound task a proper EAGER request context.
    return qp.generate_quiz_task.apply(kwargs=args).get()


# ── generate_quiz_task ────────────────────────────────────────────────────────


def test_generate_quiz_charges_full_price_and_clears_handle(gen_env: SimpleNamespace) -> None:
    result = _run_generate()

    assert result == {"status": "ok", "total": 1, "quiz_id": str(gen_env.quiz.id)}
    assert gen_env.replaced.calls[0][1:] == (gen_env.quiz.id, gen_env.generated)
    # The polling handle must be dropped, otherwise the UI spins forever.
    assert gen_env.quiz.generation_task_id is None
    (_session, _owner, ref, estimate, charged, reason) = gen_env.finalize.calls[0]
    assert (ref, estimate, charged, reason) == ("hold-1", _ESTIMATE, _ESTIMATE, "QUIZ_GENERATE")
    assert gen_env.release_slot.calls == []


def test_generate_quiz_forwards_requested_shape_to_the_llm(gen_env: SimpleNamespace) -> None:
    _run_generate(num_questions=8, num_options=3, types=["true_false"])

    assert gen_env.generate_kwargs == {
        "num_questions": 8,
        "num_options": 3,
        "types": ["true_false"],
    }


def test_generate_quiz_defaults_types_when_none(gen_env: SimpleNamespace) -> None:
    _run_generate(types=None)

    assert gen_env.generate_kwargs["types"] == list(qp.QUIZ_TYPE_DISTRIBUTION.keys())


def test_generate_quiz_publishes_progress_steps(gen_env: SimpleNamespace) -> None:
    _run_generate()

    assert [p["step"] for p in gen_env.published] == ["material", "llm", "persist", "persist"]
    assert gen_env.published[-1] == {"step": "persist", "done": 3, "total": 3}


@pytest.mark.parametrize(
    ("exc", "match"),
    [
        (EmptyMaterialError("нет материала"), "нет материала"),
        (LLMOutputError("invalid output"), "invalid output"),
        (RuntimeError("provider down"), "provider down"),
    ],
)
def test_generate_quiz_releases_credits_on_every_failure(
    gen_env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, exc: Exception, match: str
) -> None:
    async def _boom(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise exc

    if isinstance(exc, EmptyMaterialError):
        monkeypatch.setattr(qp, "assemble_material_sync", MagicMock(side_effect=exc))
    else:
        monkeypatch.setattr(qp.llm_service, "generate_quiz_v2", _boom)

    result = _run_generate()

    assert result["status"] == "error"
    assert match in result["error"]
    # Reservation released: charged=0 against the same hold.
    (_session, _owner, ref, estimate, charged, _reason) = gen_env.finalize.calls[0]
    assert (ref, estimate, charged) == ("hold-1", _ESTIMATE, 0)
    assert gen_env.quiz.generation_task_id is None
    assert gen_env.session.rollback.called


def test_generate_quiz_returns_trial_slot_only_on_failure(
    gen_env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        qp, "assemble_material_sync", MagicMock(side_effect=EmptyMaterialError("x"))
    )

    _run_generate(billed_via="trial", billing_ref=None)

    assert gen_env.release_slot.calls[0][2] == qp.TRIAL_QUIZ
    assert gen_env.finalize.calls == []


def test_generate_quiz_keeps_trial_slot_spent_on_success(gen_env: SimpleNamespace) -> None:
    _run_generate(billed_via="trial", billing_ref=None)

    assert gen_env.release_slot.calls == []
    assert gen_env.finalize.calls == []


def test_generate_quiz_without_owner_settles_nothing(gen_env: SimpleNamespace) -> None:
    result = _run_generate(owner_id=None)

    assert result["status"] == "ok"
    assert gen_env.finalize.calls == []
    assert gen_env.release_slot.calls == []


def test_generate_quiz_survives_a_billing_failure(
    gen_env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken ledger write must not turn a finished quiz into an error."""
    monkeypatch.setattr(
        qp, "sync_finalize_generation", MagicMock(side_effect=RuntimeError("ledger down"))
    )

    result = _run_generate()

    assert result["status"] == "ok"
    assert gen_env.quiz.generation_task_id is None


def test_generate_quiz_error_without_quiz_row_still_returns_error(
    gen_env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    gen_env.session.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr(
        qp, "assemble_material_sync", MagicMock(side_effect=EmptyMaterialError("x"))
    )

    assert _run_generate()["status"] == "error"


# ── _clear_generation_task ────────────────────────────────────────────────────


def test_clear_generation_task_is_a_noop_for_a_missing_quiz() -> None:
    session = MagicMock()
    session.get.return_value = None

    qp._clear_generation_task(session, uuid.uuid4())

    assert not session.commit.called


def test_clear_generation_task_commits_the_reset() -> None:
    session = MagicMock()
    quiz = MagicMock(generation_task_id="task-1")
    session.get.return_value = quiz

    qp._clear_generation_task(session, uuid.uuid4())

    assert quiz.generation_task_id is None
    assert session.commit.called


# ── _grade_one_open ───────────────────────────────────────────────────────────


def test_grade_one_open_returns_llm_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _grade(payload: dict[str, Any], text: str) -> tuple[float, str]:
        assert payload["prompt"] == "Что такое энтропия?"
        assert text == "мера беспорядка"
        return 0.8, "Почти верно"

    monkeypatch.setattr(qp.llm_service, "grade_open_answer", _grade)
    answer_id = uuid.uuid4()

    result = qp._grade_one_open(answer_id, {"prompt": "Что такое энтропия?"}, "мера беспорядка")

    assert result == (answer_id, 0.8, "Почти верно", True)


def test_grade_one_open_degrades_to_needs_review_on_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider outage must never silently score a student 0/1."""

    async def _boom(*_args: Any, **_kwargs: Any) -> tuple[float, str]:
        raise RuntimeError("provider down")

    monkeypatch.setattr(qp.llm_service, "grade_open_answer", _boom)
    answer_id = uuid.uuid4()

    ans_id, score, feedback, ok = qp._grade_one_open(answer_id, {}, "ответ")

    assert (ans_id, score, ok) == (answer_id, 0.0, False)
    assert "provider down" in feedback


# ── _recompute_attempt ────────────────────────────────────────────────────────


def _snap_question(weight: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), version=1, type="short_answer", payload={}, weight=Decimal(weight)
    )


def _answer(question_id: uuid.UUID, awarded: str | None, max_score: str = "1.0") -> SimpleNamespace:
    return SimpleNamespace(
        question_id=question_id,
        awarded_score=Decimal(awarded) if awarded is not None else None,
        max_score=Decimal(max_score),
    )


def _recompute(
    monkeypatch: pytest.MonkeyPatch,
    questions: list[SimpleNamespace],
    answers: list[SimpleNamespace],
    threshold: str = "0.6",
) -> SimpleNamespace:
    monkeypatch.setattr(qp, "resolve_snapshot_sync", lambda _s, _snap: questions)
    session = MagicMock()
    session.get.side_effect = lambda model, pk: (
        SimpleNamespace(pass_threshold=Decimal(threshold)) if model is Quiz else None
    )
    attempt = SimpleNamespace(
        quiz_id=uuid.uuid4(),
        questions_snapshot={"version": 1, "pointers": []},
        answers=answers,
        score=None,
        passed=None,
    )
    qp._recompute_attempt(session, attempt)
    return attempt


def test_recompute_attempt_uses_snapshot_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    heavy, light = _snap_question("3.0"), _snap_question("1.0")
    attempt = _recompute(
        monkeypatch,
        [heavy, light],
        [_answer(heavy.id, "1.0"), _answer(light.id, "0.0")],
    )

    assert attempt.score == Decimal("0.75")
    assert attempt.passed is True


def test_recompute_attempt_counts_ungraded_answers_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    q1, q2 = _snap_question("1.0"), _snap_question("1.0")
    attempt = _recompute(monkeypatch, [q1, q2], [_answer(q1.id, "1.0"), _answer(q2.id, None)])

    assert attempt.score == Decimal("0.5")
    assert attempt.passed is False  # below the 0.6 threshold


def test_recompute_attempt_ignores_answers_outside_the_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A question deleted after submission must not dilute the score."""
    q1 = _snap_question("1.0")
    attempt = _recompute(monkeypatch, [q1], [_answer(q1.id, "1.0"), _answer(uuid.uuid4(), "0.0")])

    assert attempt.score == Decimal("1")
    assert attempt.passed is True


def test_recompute_attempt_falls_back_to_default_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(qp, "resolve_snapshot_sync", lambda _s, _snap: [])
    session = MagicMock()
    session.get.return_value = None
    attempt = SimpleNamespace(
        quiz_id=uuid.uuid4(),
        questions_snapshot={},
        answers=[],
        score=None,
        passed=None,
    )

    qp._recompute_attempt(session, attempt)

    assert attempt.score == Decimal("0")
    assert attempt.passed is False


# ── _mark_lesson_progress_if_passed ───────────────────────────────────────────


def _progress_env(
    *,
    passed: bool = True,
    score: str | None = "0.9",
    quiz: Any = "auto",
    lesson: Any = "auto",
    module: Any = "auto",
    enrollment: Any = "auto",
    progress: Any = None,
) -> tuple[MagicMock, SimpleNamespace]:
    lesson_id, module_id, course_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    quiz_obj = SimpleNamespace(id=uuid.uuid4(), lesson_id=lesson_id) if quiz == "auto" else quiz
    lesson_obj = SimpleNamespace(id=lesson_id, module_id=module_id) if lesson == "auto" else lesson
    module_obj = SimpleNamespace(id=module_id, course_id=course_id) if module == "auto" else module
    enrollment_obj = SimpleNamespace(id=uuid.uuid4()) if enrollment == "auto" else enrollment

    session = MagicMock()
    by_type = {"Quiz": quiz_obj, "Lesson": lesson_obj, "Module": module_obj}
    session.get.side_effect = lambda model, _pk: by_type.get(model.__name__)
    session.query.return_value.filter.return_value.first.side_effect = [enrollment_obj, progress]

    attempt = SimpleNamespace(
        quiz_id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        passed=passed,
        score=Decimal(score) if score is not None else None,
    )
    return session, attempt


def test_progress_created_for_a_passing_attempt() -> None:
    session, attempt = _progress_env()

    qp._mark_lesson_progress_if_passed(session, attempt)

    created = session.add.call_args[0][0]
    assert created.quiz_score == 0.9
    assert created.is_completed is True
    assert created.completed_at is not None


def test_progress_keeps_the_best_previous_score() -> None:
    """A later, worse attempt must never regress a completed lesson."""
    previous = SimpleNamespace(
        quiz_score=0.95, is_completed=True, completed_at="2026-01-01T00:00:00Z"
    )
    session, attempt = _progress_env(score="0.7", progress=previous)

    qp._mark_lesson_progress_if_passed(session, attempt)

    assert previous.quiz_score == 0.95
    assert previous.completed_at == "2026-01-01T00:00:00Z"
    assert not session.add.called


def test_progress_upgrades_score_on_a_better_attempt() -> None:
    previous = SimpleNamespace(quiz_score=0.5, is_completed=False, completed_at=None)
    session, attempt = _progress_env(score="0.8", progress=previous)

    qp._mark_lesson_progress_if_passed(session, attempt)

    assert previous.quiz_score == 0.8
    assert previous.is_completed is True
    assert previous.completed_at is not None


def test_progress_untouched_for_a_failed_attempt() -> None:
    session, attempt = _progress_env(passed=False)

    qp._mark_lesson_progress_if_passed(session, attempt)

    assert not session.add.called
    assert not session.get.called


@pytest.mark.parametrize("missing", ["quiz", "lesson", "module", "enrollment"])
def test_progress_noop_when_a_link_in_the_chain_is_missing(missing: str) -> None:
    session, attempt = _progress_env(**{missing: None})

    qp._mark_lesson_progress_if_passed(session, attempt)

    assert not session.add.called
