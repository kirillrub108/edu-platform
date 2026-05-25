"""Integration tests for the teacher quiz-authoring endpoints."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson, QuizQuestion
from app.models.user import User
from app.schemas.quiz import GeneratedQuestion, QuestionFlag
from tests.factories import (
    make_course,
    make_lesson,
    make_module,
    make_quiz_question,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture()
async def lesson_with_material(
    db_session: AsyncSession, teacher_user: User
) -> Lesson:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(
        db_session, module, text_content="Lecture text long enough."
    )
    return lesson


@pytest_asyncio.fixture()
async def foreign_teacher(db_session: AsyncSession) -> User:
    from app.models.user import User as UserModel
    from app.models.user import UserRole
    from app.services.auth_service import hash_password

    user = UserModel(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        full_name="Other Teacher",
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _bearer(user: User) -> dict[str, str]:
    from app.services.auth_service import create_access_token

    token, _jti, _exp = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


# ── generate ────────────────────────────────────────────────────────────────


async def test_generate_enqueues_and_persists_task_id(
    client: AsyncClient,
    db_session: AsyncSession,
    lesson_with_material: Lesson,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import quiz_teacher as qt_mod

    class _Fake:
        id = "quiz-task-1"

    monkeypatch.setattr(
        qt_mod.generate_quiz_task, "apply_async", lambda *a, **k: _Fake()
    )

    resp = await client.post(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz/generate",
        headers=teacher_token,
        json={},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["task_id"] == "quiz-task-1"

    lesson_id = lesson_with_material.id
    db_session.expire_all()
    refreshed = await db_session.get(Lesson, lesson_id)
    assert refreshed is not None
    assert refreshed.quiz_task_id == "quiz-task-1"


async def test_generate_returns_409_when_no_material(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(
        db_session, module, script=None, text_content=None
    )
    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/quiz/generate",
        headers=teacher_token,
        json={},
    )
    assert resp.status_code == 409


async def test_generate_blocks_student(
    client: AsyncClient,
    lesson_with_material: Lesson,
    student_token: dict[str, str],
) -> None:
    resp = await client.post(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz/generate",
        headers=student_token,
        json={},
    )
    assert resp.status_code == 403


async def test_generate_blocks_non_owner_teacher(
    client: AsyncClient,
    lesson_with_material: Lesson,
    foreign_teacher: User,
) -> None:
    resp = await client.post(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz/generate",
        headers=_bearer(foreign_teacher),
        json={},
    )
    assert resp.status_code == 404


async def test_generate_missing_lesson_returns_404(
    client: AsyncClient, teacher_token: dict[str, str]
) -> None:
    resp = await client.post(
        f"/api/v1/lessons/{uuid.uuid4()}/quiz/generate",
        headers=teacher_token,
        json={},
    )
    assert resp.status_code == 404


# ── generation-status ───────────────────────────────────────────────────────


async def test_generation_status_returns_state(
    client: AsyncClient,
    lesson_with_material: Lesson,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import quiz_teacher as qt_mod

    class _Result:
        status = "PROGRESS"
        state = "PROGRESS"
        info = {"step": "llm", "done": 1, "total": 3}

        def ready(self) -> bool:
            return False

    monkeypatch.setattr(qt_mod, "AsyncResult", lambda *a, **k: _Result())

    resp = await client.get(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz/generation-status/tid",
        headers=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["step"] == "llm"
    assert body["done"] == 1
    assert body["total"] == 3


# ── list / patch / delete ───────────────────────────────────────────────────


async def test_list_quiz_questions(
    client: AsyncClient,
    db_session: AsyncSession,
    lesson_with_material: Lesson,
    teacher_token: dict[str, str],
) -> None:
    await make_quiz_question(db_session, lesson_with_material, order=1, correct_index=1)
    await make_quiz_question(db_session, lesson_with_material, order=0, correct_index=0)

    resp = await client.get(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz",
        headers=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert [q["order"] for q in body] == [0, 1]
    assert "correct_index" in body[0]


async def test_patch_question(
    client: AsyncClient,
    db_session: AsyncSession,
    lesson_with_material: Lesson,
    teacher_token: dict[str, str],
) -> None:
    q = await make_quiz_question(db_session, lesson_with_material, correct_index=0)
    resp = await client.patch(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz/{q.id}",
        headers=teacher_token,
        json={"question": "New question?", "correct_index": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["question"] == "New question?"
    assert body["correct_index"] == 2


async def test_patch_question_oor_returns_422(
    client: AsyncClient,
    db_session: AsyncSession,
    lesson_with_material: Lesson,
    teacher_token: dict[str, str],
) -> None:
    q = await make_quiz_question(db_session, lesson_with_material, correct_index=0)
    resp = await client.patch(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz/{q.id}",
        headers=teacher_token,
        json={"correct_index": 99},
    )
    assert resp.status_code == 422


async def test_delete_question(
    client: AsyncClient,
    db_session: AsyncSession,
    lesson_with_material: Lesson,
    teacher_token: dict[str, str],
) -> None:
    q = await make_quiz_question(db_session, lesson_with_material)
    qid = q.id
    resp = await client.delete(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz/{qid}",
        headers=teacher_token,
    )
    assert resp.status_code == 204

    db_session.expire_all()
    assert await db_session.get(QuizQuestion, qid) is None


# ── regenerate single question ──────────────────────────────────────────────


async def test_regenerate_question_returns_mutated(
    client: AsyncClient,
    db_session: AsyncSession,
    lesson_with_material: Lesson,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    q = await make_quiz_question(
        db_session, lesson_with_material, correct_index=0
    )
    other = await make_quiz_question(
        db_session,
        lesson_with_material,
        question="UNTOUCHED?",
        correct_index=1,
        order=1,
    )
    other_id = other.id

    from app.services import llm_service as llm_mod

    async def _fake_regen(
        material: str, question, mode: str, num_options: int
    ) -> GeneratedQuestion:
        return GeneratedQuestion(
            question="Reworded?", options=["A1", "B1", "C1", "D1"], correct_index=2
        )

    monkeypatch.setattr(llm_mod.llm_service, "regenerate_quiz_question", _fake_regen)

    resp = await client.post(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz/{q.id}/regenerate",
        headers=teacher_token,
        json={"mode": "rephrase"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["question"] == "Reworded?"
    assert body["correct_index"] == 2

    db_session.expire_all()
    untouched = await db_session.get(QuizQuestion, other_id)
    assert untouched is not None
    assert untouched.question == "UNTOUCHED?"


# ── qa-review ───────────────────────────────────────────────────────────────


async def test_qa_review_returns_flags_without_mutation(
    client: AsyncClient,
    db_session: AsyncSession,
    lesson_with_material: Lesson,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    q1 = await make_quiz_question(db_session, lesson_with_material, correct_index=0)
    q2 = await make_quiz_question(db_session, lesson_with_material, correct_index=1, order=1)
    q1_id, q2_id = q1.id, q2.id
    q1_text, q2_text = q1.question, q2.question

    from app.services import llm_service as llm_mod

    async def _fake_qa(material: str, questions: list[dict[str, Any]]) -> list[QuestionFlag]:
        return [
            QuestionFlag(question_id=questions[0]["id"], kind="ok", note=""),
            QuestionFlag(
                question_id=questions[1]["id"], kind="ambiguous", note="check"
            ),
        ]

    monkeypatch.setattr(llm_mod.llm_service, "qa_review_quiz", _fake_qa)

    resp = await client.post(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz/qa-review",
        headers=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["kind"] == "ok"
    assert body[1]["kind"] == "ambiguous"

    db_session.expire_all()
    refreshed_1 = await db_session.get(QuizQuestion, q1_id)
    refreshed_2 = await db_session.get(QuizQuestion, q2_id)
    assert refreshed_1 is not None and refreshed_1.question == q1_text
    assert refreshed_2 is not None and refreshed_2.question == q2_text


async def test_qa_review_empty_quiz_returns_empty(
    client: AsyncClient,
    lesson_with_material: Lesson,
    teacher_token: dict[str, str],
) -> None:
    resp = await client.post(
        f"/api/v1/lessons/{lesson_with_material.id}/quiz/qa-review",
        headers=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ── authz blanket coverage ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("get", "/quiz"),
        ("post", "/quiz/qa-review"),
    ],
)
async def test_student_blocked_on_read_endpoints(
    client: AsyncClient,
    lesson_with_material: Lesson,
    student_token: dict[str, str],
    method: str,
    suffix: str,
) -> None:
    url = f"/api/v1/lessons/{lesson_with_material.id}{suffix}"
    resp = await getattr(client, method)(url, headers=student_token)
    assert resp.status_code == 403
