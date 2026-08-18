"""End-to-end lesson knowledge base: materials (files) + markdown notes.

Pins the access matrix (owner writes / enrolled student reads / draft → 404),
the upload whitelist and quota errors, and the fact that deleting a material
really removes the object from storage — not just the DB row.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.storage_service as storage_mod
from app.models.lesson_material import LessonMaterial
from app.models.user import User
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
    make_published_course_with_lesson,
)

pytestmark = pytest.mark.integration

_PDF = b"%PDF-1.4\n%fake pdf body for tests\n"


def _pdf_upload(name: str = "handout.pdf") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, _PDF, "application/pdf")}


async def _enrolled_lesson(db: AsyncSession, teacher: User, student: User):
    course, module, lesson = await make_published_course_with_lesson(db, teacher)
    await make_enrollment(db, student, course)
    return course, module, lesson


async def _upload(client: AsyncClient, lesson_id, token: dict[str, str], **form: str):
    return await client.post(
        f"/api/v1/lessons/{lesson_id}/materials",
        files=_pdf_upload(),
        data=form or {"title": "Конспект лекции"},
        cookies=token,
    )


# ── Teacher CRUD ─────────────────────────────────────────────────────────────


async def test_teacher_uploads_material_and_sees_it_in_knowledge_base(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)

    created = await _upload(
        client, lesson.id, teacher_token, title="Методичка", description="Глава 1"
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Методичка"
    assert body["description"] == "Глава 1"
    assert body["original_filename"] == "handout.pdf"
    assert body["size_bytes"] == len(_PDF)
    assert body["uploaded_by"] == str(teacher_user.id)
    assert body["download_url"]

    listing = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=teacher_token)
    assert listing.status_code == 200
    data = listing.json()
    assert data["can_edit"] is True
    assert len(data["materials"]) == 1
    assert data["materials"][0]["id"] == body["id"]
    assert data["limits"]["max_files"] > 0
    assert "pdf" in data["limits"]["allowed_ext"]


async def test_material_title_defaults_to_filename(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    created = await _upload(client, lesson.id, teacher_token, title="   ")
    assert created.status_code == 201
    assert created.json()["title"] == "handout.pdf"


async def test_patch_material_updates_metadata_only(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    material_id = (await _upload(client, lesson.id, teacher_token)).json()["id"]

    patched = await client.patch(
        f"/api/v1/lessons/{lesson.id}/materials/{material_id}",
        json={"title": "Новое имя", "description": None},
        cookies=teacher_token,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "Новое имя"
    assert patched.json()["description"] is None
    assert patched.json()["original_filename"] == "handout.pdf"


async def test_delete_material_removes_the_stored_object(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    material_id = (await _upload(client, lesson.id, teacher_token)).json()["id"]

    stored_path = await db_session.scalar(
        select(LessonMaterial.file_path).where(LessonMaterial.id == material_id)
    )
    assert storage_mod.storage_service.exists(stored_path)

    deleted = await client.delete(
        f"/api/v1/lessons/{lesson.id}/materials/{material_id}", cookies=teacher_token
    )
    assert deleted.status_code == 204
    # The DB row going away is not enough — the bytes must be gone too.
    assert not storage_mod.storage_service.exists(stored_path)

    listing = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=teacher_token)
    assert listing.json()["materials"] == []


async def test_material_of_another_lesson_is_404_not_cross_editable(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, module, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    other_lesson = await make_lesson(db_session, module, order=1)
    material_id = (await _upload(client, lesson.id, teacher_token)).json()["id"]

    resp = await client.delete(
        f"/api/v1/lessons/{other_lesson.id}/materials/{material_id}", cookies=teacher_token
    )
    assert resp.status_code == 404


# ── Upload validation ────────────────────────────────────────────────────────


async def test_upload_rejects_extension_off_whitelist(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/materials",
        files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")},
        cookies=teacher_token,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "extension_not_allowed"


async def test_upload_rejects_content_that_does_not_match_extension(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    # Magic-byte check: an executable renamed to .pdf must not slip through.
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/materials",
        files={"file": ("fake.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")},
        cookies=teacher_token,
    )
    assert resp.status_code == 400


async def test_upload_rejects_when_file_count_limit_reached(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import lesson_material_service as svc

    monkeypatch.setattr(svc, "LESSON_MATERIAL_MAX_FILES", 1)
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)

    assert (await _upload(client, lesson.id, teacher_token)).status_code == 201
    second = await _upload(client, lesson.id, teacher_token)
    assert second.status_code == 400
    assert second.json()["detail"]["code"] == "too_many_files"


# ── Notes ────────────────────────────────────────────────────────────────────


async def test_note_crud_and_reorder(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)

    first = await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"title": "Первый", "content": "# Заголовок\n\nтекст"},
        cookies=teacher_token,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"title": "Второй", "content": "- пункт"},
        cookies=teacher_token,
    )
    assert second.status_code == 201
    assert second.json()["order"] > first.json()["order"]

    edited = await client.patch(
        f"/api/v1/lessons/{lesson.id}/notes/{first.json()['id']}",
        json={"content": "правленый текст"},
        cookies=teacher_token,
    )
    assert edited.status_code == 200
    assert edited.json()["content"] == "правленый текст"
    assert edited.json()["title"] == "Первый"

    reordered = await client.put(
        f"/api/v1/lessons/{lesson.id}/notes/order",
        json={"note_ids": [second.json()["id"], first.json()["id"]]},
        cookies=teacher_token,
    )
    assert reordered.status_code == 200
    assert [n["id"] for n in reordered.json()] == [second.json()["id"], first.json()["id"]]

    removed = await client.delete(
        f"/api/v1/lessons/{lesson.id}/notes/{first.json()['id']}", cookies=teacher_token
    )
    assert removed.status_code == 204
    listing = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=teacher_token)
    assert [n["id"] for n in listing.json()["notes"]] == [second.json()["id"]]


async def test_reorder_rejects_incomplete_list(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    first = await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"title": "A", "content": "a"},
        cookies=teacher_token,
    )
    await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"title": "B", "content": "b"},
        cookies=teacher_token,
    )
    resp = await client.put(
        f"/api/v1/lessons/{lesson.id}/notes/order",
        json={"note_ids": [first.json()["id"]]},
        cookies=teacher_token,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_note_order"


async def test_note_content_over_cap_is_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    from app.constants import LESSON_NOTE_MAX_CONTENT_CHARS

    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"title": "big", "content": "x" * (LESSON_NOTE_MAX_CONTENT_CHARS + 1)},
        cookies=teacher_token,
    )
    assert resp.status_code == 422


# ── Student access ───────────────────────────────────────────────────────────


async def test_enrolled_student_reads_knowledge_base_but_cannot_write(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _enrolled_lesson(db_session, teacher_user, student_user)
    await _upload(client, lesson.id, teacher_token)
    await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"title": "Конспект", "content": "**жирный** текст"},
        cookies=teacher_token,
    )

    listing = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=student_token)
    assert listing.status_code == 200
    data = listing.json()
    assert data["can_edit"] is False
    assert len(data["materials"]) == 1
    assert data["materials"][0]["download_url"]
    assert len(data["notes"]) == 1

    upload = await _upload(client, lesson.id, student_token)
    assert upload.status_code == 403
    note = await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"title": "x", "content": "y"},
        cookies=student_token,
    )
    assert note.status_code == 403


async def test_draft_lesson_knowledge_is_404_for_student(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, is_published=False)
    await make_enrollment(db_session, student_user, course)

    # Draft is hidden as 404 (never 403) — the API must not reveal it exists…
    student_resp = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=student_token)
    assert student_resp.status_code == 404

    # …while the owner still sees the same lesson's knowledge base.
    owner_resp = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=teacher_token)
    assert owner_resp.status_code == 200
    assert owner_resp.json()["can_edit"] is True


async def test_unenrolled_student_gets_403(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    resp = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=student_token)
    assert resp.status_code == 403
