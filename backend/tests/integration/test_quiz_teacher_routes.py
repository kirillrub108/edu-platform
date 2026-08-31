"""Integration tests for the teacher-side quiz API."""

from __future__ import annotations

from uuid import UUID

import pytest

from tests.factories import (
    make_course,
    make_lesson,
    make_module,
    make_quiz,
    make_quiz_question,
)


@pytest.mark.asyncio
async def test_get_quiz_creates_lazily_for_teacher(client, db_session, teacher_user, teacher_token):
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    r = await client.get(f"/api/v1/lessons/{lesson.id}/quiz", cookies=teacher_token)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft"
    assert UUID(body["id"])


@pytest.mark.asyncio
async def test_update_quiz_settings(client, db_session, teacher_user, teacher_token):
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    await make_quiz(db_session, lesson)

    r = await client.put(
        f"/api/v1/lessons/{lesson.id}/quiz",
        cookies=teacher_token,
        json={"pass_threshold": "0.75", "attempts_allowed": 3, "shuffle": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pass_threshold"].startswith("0.7")
    assert body["attempts_allowed"] == 3
    assert body["shuffle"] is True


@pytest.mark.asyncio
async def test_publish_requires_questions(client, db_session, teacher_user, teacher_token):
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    await make_quiz(db_session, lesson)

    r = await client.post(f"/api/v1/lessons/{lesson.id}/quiz/publish", cookies=teacher_token)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_publish_unpublish_cycle(client, db_session, teacher_user, teacher_token):
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson)
    await make_quiz_question(db_session, quiz)

    r = await client.post(f"/api/v1/lessons/{lesson.id}/quiz/publish", cookies=teacher_token)
    assert r.status_code == 200
    assert r.json()["status"] == "published"

    r = await client.post(f"/api/v1/lessons/{lesson.id}/quiz/unpublish", cookies=teacher_token)
    assert r.status_code == 200
    assert r.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_create_question_typed_payload(client, db_session, teacher_user, teacher_token):
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    await make_quiz(db_session, lesson)

    r = await client.post(
        f"/api/v1/lessons/{lesson.id}/quiz/questions",
        cookies=teacher_token,
        json={
            "type": "multiple_choice",
            "payload": {
                "type": "multiple_choice",
                "prompt": "Что верно?",
                "options": ["A", "B", "C", "D"],
                "correct_indices": [0, 2],
            },
            "weight": "1.5",
            "order": 0,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "multiple_choice"
    assert body["payload"]["correct_indices"] == [0, 2]
    # Weight serializes as a Decimal string
    assert body["weight"].startswith("1.5")


@pytest.mark.asyncio
async def test_reorder_questions(client, db_session, teacher_user, teacher_token):
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson)
    q1 = await make_quiz_question(db_session, quiz, order=1)
    q2 = await make_quiz_question(db_session, quiz, order=2)

    r = await client.post(
        f"/api/v1/lessons/{lesson.id}/quiz/questions/reorder",
        cookies=teacher_token,
        json={"order": [str(q2.id), str(q1.id)]},
    )
    assert r.status_code == 200, r.text
    ordered = r.json()
    assert [row["id"] for row in ordered] == [str(q2.id), str(q1.id)]


@pytest.mark.asyncio
async def test_other_teachers_cannot_touch(client, db_session, teacher_user, teacher_token):
    """Owner check via get_owned_lesson — another teacher's lesson is 404."""
    from app.models.user import User, UserRole
    from app.services.auth_service import hash_password

    other = User(
        email="other@e.com",
        hashed_password=hash_password("x"),
        full_name="Other",
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    course = await make_course(db_session, other)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    r = await client.get(f"/api/v1/lessons/{lesson.id}/quiz", cookies=teacher_token)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_manual_override_recomputes_score(
    client,
    db_session,
    teacher_user,
    teacher_token,
    student_user,
):
    """End-to-end: build attempt with a wrong open answer scored 0.0, then
    teacher overrides to 1.0 → attempt score and passed flip in one PATCH."""
    from decimal import Decimal

    from app.models.quiz import AttemptStatus, QuestionType, QuizAnswer
    from tests.factories import make_quiz_attempt

    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson, published=True)
    q = await make_quiz_question(
        db_session,
        quiz,
        type=QuestionType.essay,
        payload={"type": "essay", "prompt": "Опишите тему", "rubric": "глубина"},
        weight=1.0,
    )
    snapshot = {
        "version": 1,
        "pointers": [{"question_id": str(q.id), "version": int(q.version), "order": 0}],
    }
    attempt = await make_quiz_attempt(
        db_session,
        quiz,
        student_user,
        questions_snapshot=snapshot,
        status=AttemptStatus.submitted,
    )
    answer = QuizAnswer(
        attempt_id=attempt.id,
        question_id=q.id,
        response={"text": "плохой ответ"},
        awarded_score=Decimal("0"),
        max_score=Decimal("1"),
        is_correct=False,
        needs_review=True,
    )
    db_session.add(answer)
    attempt.score = Decimal("0")
    attempt.passed = False
    await db_session.commit()

    r = await client.patch(
        f"/api/v1/lessons/{lesson.id}/quiz/attempts/{attempt.id}/answers/{answer.id}",
        cookies=teacher_token,
        json={"awarded_score": "1.0", "feedback": "ok"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["score"].startswith("1")
    assert body["passed"] is True
    ans = next(a for a in body["answers"] if a["id"] == str(answer.id))
    assert ans["manually_overridden"] is True
    assert ans["needs_review"] is False


# ── Versioned-question invariants ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_payload_bumps_version_and_supersedes_old(
    client,
    db_session,
    teacher_user,
    teacher_token,
):
    """PATCH on a question payload must insert a new (id, version+1) row and
    stamp `superseded_at` on the previous row, instead of mutating in place.
    """
    from sqlalchemy import select

    from app.models.quiz import QuizQuestion

    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson)
    q = await make_quiz_question(db_session, quiz, order=1)

    r = await client.patch(
        f"/api/v1/lessons/{lesson.id}/quiz/questions/{q.id}",
        cookies=teacher_token,
        json={
            "payload": {
                "type": "single_choice",
                "prompt": "edited",
                "options": ["A", "B"],
                "correct_index": 1,
            }
        },
    )
    assert r.status_code == 200, r.text
    rows = (
        (
            await db_session.execute(
                select(QuizQuestion).where(QuizQuestion.id == q.id).order_by(QuizQuestion.version)
            )
        )
        .scalars()
        .all()
    )
    assert [row.version for row in rows] == [1, 2]
    assert rows[0].superseded_at is not None
    assert rows[1].superseded_at is None
    assert rows[1].payload["prompt"] == "edited"


@pytest.mark.asyncio
async def test_delete_question_is_soft_delete(
    client,
    db_session,
    teacher_user,
    teacher_token,
):
    """DELETE marks `superseded_at`; the row stays so older attempts can still
    resolve their snapshot pointer to it."""
    from app.models.quiz import QuizQuestion

    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson)
    q = await make_quiz_question(db_session, quiz)

    r = await client.delete(
        f"/api/v1/lessons/{lesson.id}/quiz/questions/{q.id}",
        cookies=teacher_token,
    )
    assert r.status_code == 204
    row = await db_session.get(QuizQuestion, (q.id, q.version))
    assert row is not None
    assert row.superseded_at is not None


@pytest.mark.asyncio
async def test_first_load_does_not_trigger_lazy_relationship(
    client,
    db_session,
    teacher_user,
    teacher_token,
):
    """Regression: the previous `get_or_create_quiz` did
    `if lesson.quiz is not None:` on a lazy relationship, which in async
    raised MissingGreenlet. Calling /quiz/generate on a brand-new lesson
    must not 500 from that path (the route then 409s on empty material,
    which is fine — we only care that the lazy load is gone).
    """
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    r = await client.post(
        f"/api/v1/lessons/{lesson.id}/quiz/generate",
        cookies=teacher_token,
        json={"type_counts": [{"type": "single_choice", "count": 1}], "num_options": 2},
    )
    # Lesson has no material → 409, but the important assertion is "not 500".
    assert r.status_code != 500, r.text


@pytest.mark.asyncio
async def test_quiz_creation_is_idempotent(db_session, teacher_user):
    """Regression: a brand-new lesson's page fires several creating endpoints
    at once (/quiz, /quiz/questions, /quiz/generation-options, plus the
    preview's QuizTaker), and the loser used to 500 with a
    uq_quizzes_lesson_id UniqueViolationError. The INSERT is now a no-op on
    conflict, so a second one changes nothing and raises nothing.
    """
    from sqlalchemy import select

    from app.models.quiz import Quiz, QuizStatus
    from app.services.quiz_service import _insert_quiz_if_absent, get_or_create_quiz

    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    first = await get_or_create_quiz(db_session, lesson)
    await db_session.execute(_insert_quiz_if_absent(lesson.id))  # the racing INSERT
    assert (await get_or_create_quiz(db_session, lesson)).id == first.id

    rows = (await db_session.scalars(select(Quiz).where(Quiz.lesson_id == lesson.id))).all()
    assert len(rows) == 1
    assert rows[0].status == QuizStatus.draft  # core INSERT still applies the ORM defaults


@pytest.mark.asyncio
async def test_list_questions_only_returns_current(
    client,
    db_session,
    teacher_user,
    teacher_token,
):
    """After an edit, the listing shows only the current version, not history."""
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson)
    q = await make_quiz_question(db_session, quiz, order=1)
    await client.patch(
        f"/api/v1/lessons/{lesson.id}/quiz/questions/{q.id}",
        cookies=teacher_token,
        json={
            "payload": {
                "type": "single_choice",
                "prompt": "v2",
                "options": ["A", "B"],
                "correct_index": 0,
            }
        },
    )

    r = await client.get(f"/api/v1/lessons/{lesson.id}/quiz/questions", cookies=teacher_token)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["payload"]["prompt"] == "v2"


# ── Answer-key exposure guard ────────────────────────────────────────────────


async def _make_outsider(db_session, role):
    """A user with no relationship to the fixture teacher's course."""
    import uuid as _uuid

    from app.models.user import User, UserRole
    from app.services.auth_service import hash_password

    user = User(
        email=f"outsider-{_uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("outsider-pass-123"),
        full_name="Outsider",
        role=UserRole.teacher if role == "teacher" else UserRole.student,
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _cookies(user):
    from app.services.auth_service import create_access_token

    token, _jti, _exp = create_access_token(user)
    return {"access_token": token, "csrf_token": "test-csrf-fixed-value"}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["teacher", "student"])
async def test_question_listing_hides_answer_key_from_non_owners(
    client, db_session, teacher_user, teacher_token, role
):
    """GET /lessons/{id}/quiz/questions returns the teacher payload, which carries
    the answer key (`correct_index`, `reference_answer`, `rubric`, ...). Only the
    course owner may read it — anyone else gets 404, never the key."""
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson)
    await make_quiz_question(db_session, quiz)

    # Owner still sees the key.
    r = await client.get(f"/api/v1/lessons/{lesson.id}/quiz/questions", cookies=teacher_token)
    assert r.status_code == 200
    assert "correct_index" in r.json()[0]["payload"]

    # Any other authenticated user must not. A non-owning teacher gets 404 (the
    # lesson is never revealed); a student is rejected earlier by the role check
    # with 403, which leaks nothing since it precedes any lesson lookup.
    outsider = await _make_outsider(db_session, role)
    r = await client.get(f"/api/v1/lessons/{lesson.id}/quiz/questions", cookies=_cookies(outsider))
    assert r.status_code in (403, 404), (
        f"{role} outside the course read the quiz answer key: {r.text}"
    )
    assert "correct_index" not in r.text
