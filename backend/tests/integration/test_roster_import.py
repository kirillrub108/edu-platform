"""Bulk roster import endpoint: POST /courses/{id}/access-grants/import."""

from __future__ import annotations

import io
import uuid

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import ROSTER_IMPORT_MAX_FILE_BYTES
from app.models.course import AccessMode, CourseAccessGrant
from app.models.user import User, UserRole
from tests.factories import make_course

pytestmark = pytest.mark.integration


async def _make_student(db: AsyncSession, email: str) -> User:
    from app.services.auth_service import hash_password

    user = User(
        email=email,
        hashed_password=hash_password("student-pass-123"),
        full_name="Imported Student",
        role=UserRole.student,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _upload(content: bytes, name: str = "roster.xlsx") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, content, "application/octet-stream")}


async def test_import_adds_registered_students_and_reports_every_row(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    student = await _make_student(db_session, f"imported-{uuid.uuid4().hex[:8]}@example.com")
    course = await make_course(
        db_session, owner=teacher_user, is_published=True, access_mode=AccessMode.invite
    )
    content = _xlsx(
        [
            ["ФИО", "Группа", "Email"],
            ["Иванов", "БИ-21", student.email.upper()],
            ["Петров", "БИ-21", student.email],  # duplicate of the row above
            ["Сидоров", "БИ-21", "Иванов И.И."],
            ["Ничей", "БИ-21", "nobody@example.com"],
            ["Сам", "БИ-21", teacher_user.email],
        ]
    )

    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-grants/import",
        files=_upload(content),
        cookies=teacher_token,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_column_choice"] is False
    assert body["detected_column"] == {"index": 2, "header": "Email"}
    assert (body["added"], body["skipped"], body["total_rows"]) == (1, 4, 5)
    by_row = {r["row"]: r for r in body["results"]}
    assert by_row[2]["status"] == "added"
    assert by_row[3]["reason"] == "duplicate_in_file"
    assert by_row[4]["reason"] == "invalid_email"
    assert by_row[5]["reason"] == "not_registered"
    assert by_row[6]["reason"] == "is_course_owner"

    grants = (
        await db_session.scalars(
            select(CourseAccessGrant).where(CourseAccessGrant.course_id == course.id)
        )
    ).all()
    assert [g.student_id for g in grants] == [student.id]


async def test_reimporting_the_same_file_changes_nothing(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    student = await _make_student(db_session, f"again-{uuid.uuid4().hex[:8]}@example.com")
    course = await make_course(
        db_session, owner=teacher_user, is_published=True, access_mode=AccessMode.invite
    )
    content = f"email\n{student.email}\n".encode("utf-8")
    url = f"/api/v1/courses/{course.id}/access-grants/import"

    first = await client.post(url, files=_upload(content, "roster.csv"), cookies=teacher_token)
    second = await client.post(url, files=_upload(content, "roster.csv"), cookies=teacher_token)
    assert first.json()["added"] == 1
    assert second.json()["added"] == 0
    assert second.json()["results"][0]["reason"] == "already_in_list"

    grants = (
        await db_session.scalars(
            select(CourseAccessGrant).where(CourseAccessGrant.course_id == course.id)
        )
    ).all()
    assert len(grants) == 1


async def test_two_email_columns_ask_for_a_choice_without_writing(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    student = await _make_student(db_session, f"work-{uuid.uuid4().hex[:8]}@example.com")
    course = await make_course(
        db_session, owner=teacher_user, is_published=True, access_mode=AccessMode.invite
    )
    content = f"Личная;Рабочая\npersonal@example.com;{student.email}\n".encode("utf-8")
    url = f"/api/v1/courses/{course.id}/access-grants/import"

    ask = await client.post(url, files=_upload(content, "roster.csv"), cookies=teacher_token)
    assert ask.status_code == 200, ask.text
    assert ask.json()["needs_column_choice"] is True
    assert [c["header"] for c in ask.json()["columns"]] == ["Личная", "Рабочая"]
    assert ask.json()["results"] == []
    assert not (
        await db_session.scalars(
            select(CourseAccessGrant).where(CourseAccessGrant.course_id == course.id)
        )
    ).all()

    chosen = await client.post(
        url,
        files=_upload(content, "roster.csv"),
        data={"email_column": "1"},
        cookies=teacher_token,
    )
    assert chosen.json()["added"] == 1
    grants = (
        await db_session.scalars(
            select(CourseAccessGrant).where(CourseAccessGrant.course_id == course.id)
        )
    ).all()
    assert [g.student_id for g in grants] == [student.id]


async def test_import_into_someone_elses_course_is_refused(
    client: AsyncClient,
    db_session: AsyncSession,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    from app.services.auth_service import hash_password

    other = User(
        email=f"other-teacher-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("teacher-pass-123"),
        full_name="Other Teacher",
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    course = await make_course(db_session, owner=other, access_mode=AccessMode.invite)

    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-grants/import",
        files=_upload(b"email\na@example.com\n", "roster.csv"),
        cookies=teacher_token,
    )
    # 403, matching the single add-by-email path (`_get_owned_course`).
    assert resp.status_code == 403
    missing = await client.post(
        f"/api/v1/courses/{uuid.uuid4()}/access-grants/import",
        files=_upload(b"email\na@example.com\n", "roster.csv"),
        cookies=teacher_token,
    )
    assert missing.status_code == 404


async def test_oversized_file_is_rejected_with_413(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(
        db_session, owner=teacher_user, is_published=True, access_mode=AccessMode.invite
    )
    oversized = b"email\n" + b"a@example.com\n" * (ROSTER_IMPORT_MAX_FILE_BYTES // 10)
    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-grants/import",
        files=_upload(oversized, "roster.csv"),
        cookies=teacher_token,
    )
    assert resp.status_code == 413


async def test_pdf_disguised_as_csv_is_rejected_with_400(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(
        db_session, owner=teacher_user, is_published=True, access_mode=AccessMode.invite
    )
    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-grants/import",
        files=_upload(b"%PDF-1.7\n1 0 obj\n", "roster.csv"),
        cookies=teacher_token,
    )
    assert resp.status_code == 400
    assert "CSV" in resp.json()["detail"]
