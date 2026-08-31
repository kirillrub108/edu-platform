"""Text lessons (content_type == "text") and the knowledge-base wiring around them.

Pins: creating a text lesson, the 400 refusals on every generation entry point,
the draft-is-404 visibility rule, the inline-material orphan sweep on body save,
auto-registration of /uploads/* files into the lesson's knowledge base, and the
course-level knowledge tree with its owner/student gating.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.storage_service as storage_mod
from app.models.lesson import ContentType
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

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


async def _text_lesson(db: AsyncSession, teacher: User):
    course = await make_course(db, teacher, is_published=True)
    module = await make_module(db, course)
    lesson = await make_lesson(db, module, content_type=ContentType.text)
    return course, module, lesson


async def _upload_inline(client: AsyncClient, lesson_id, token: dict[str, str]) -> str:
    res = await client.post(
        f"/api/v1/lessons/{lesson_id}/materials",
        files={"file": ("diagram.png", _PNG, "image/png")},
        data={"is_inline": "true"},
        cookies=token,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["is_inline"] is True
    return body["id"]


# ── Creation & type-specific refusals ────────────────────────────────────────


async def test_create_text_lesson(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)

    res = await client.post(
        "/api/v1/lessons/",
        json={"title": "Конспект по теме", "module_id": str(module.id), "content_type": "text"},
        cookies=teacher_token,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["content_type"] == "text"
    assert body["text_content"] is None


async def test_video_lesson_stays_the_default(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    """Backward compatibility: omitting content_type still yields a video lesson."""
    course = await make_course(db_session, teacher_user)
    module = await make_module(db_session, course)

    res = await client.post(
        "/api/v1/lessons/",
        json={"title": "Лекция", "module_id": str(module.id)},
        cookies=teacher_token,
    )
    assert res.status_code == 201, res.text
    assert res.json()["content_type"] == "video"


async def test_generation_endpoints_reject_a_text_lesson(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await _text_lesson(db_session, teacher_user)

    generate = await client.post(
        f"/api/v1/lessons/{lesson.id}/generate-video",
        json={"pptx_path": "pptx/whatever.pptx", "voice": "nova"},
        cookies=teacher_token,
    )
    assert generate.status_code == 400, generate.text
    assert generate.json()["detail"]["code"] == "text_lesson_no_video"

    analyze = await client.post(
        f"/api/v1/lessons/{lesson.id}/analyze",
        cookies=teacher_token,
    )
    assert analyze.status_code == 400, analyze.text
    assert analyze.json()["detail"]["code"] == "text_lesson_no_video"


async def test_text_body_endpoint_rejects_a_video_lesson(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)

    res = await client.put(
        f"/api/v1/lessons/{lesson.id}/text",
        json={"text_content": "# Заголовок"},
        cookies=teacher_token,
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "not_a_text_lesson"


async def test_generic_lesson_put_cannot_write_the_body(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    """The orphan sweep only runs on PUT /text, so no second path may set it."""
    _, _, lesson = await _text_lesson(db_session, teacher_user)

    res = await client.put(
        f"/api/v1/lessons/{lesson.id}",
        json={"title": "Новое название", "text_content": "смуглённый обход"},
        cookies=teacher_token,
    )
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "Новое название"
    assert res.json()["text_content"] is None


# ── Body save & inline orphan sweep ──────────────────────────────────────────


async def test_save_body_and_empty_body_round_trip(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await _text_lesson(db_session, teacher_user)

    saved = await client.put(
        f"/api/v1/lessons/{lesson.id}/text",
        json={"text_content": "# Тема\n\nПервый абзац."},
        cookies=teacher_token,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["text_content"] == "# Тема\n\nПервый абзац."

    emptied = await client.put(
        f"/api/v1/lessons/{lesson.id}/text",
        json={"text_content": ""},
        cookies=teacher_token,
    )
    assert emptied.status_code == 200
    assert emptied.json()["text_content"] == ""


async def test_orphaned_inline_material_is_swept_on_save(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, lesson = await _text_lesson(db_session, teacher_user)
    kept = await _upload_inline(client, lesson.id, teacher_token)
    dropped = await _upload_inline(client, lesson.id, teacher_token)

    row = await db_session.scalar(
        select(LessonMaterial).where(LessonMaterial.id == dropped)  # type: ignore[arg-type]
    )
    assert row is not None
    assert storage_mod.storage_service.exists(row.file_path)

    res = await client.put(
        f"/api/v1/lessons/{lesson.id}/text",
        json={"text_content": f"Схема: ![схема](material:{kept}) — и всё."},
        cookies=teacher_token,
    )
    assert res.status_code == 200, res.text

    remaining = (
        await db_session.scalars(
            select(LessonMaterial).where(LessonMaterial.lesson_id == lesson.id)
        )
    ).all()
    assert [str(m.id) for m in remaining] == [kept]
    # Storage object went first, then the row (delete_material's order).
    assert not storage_mod.storage_service.exists(row.file_path)


async def test_non_inline_material_survives_a_body_save(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    """The sweep is scoped to inline rows — ordinary «Файлы» are never touched."""
    _, _, lesson = await _text_lesson(db_session, teacher_user)
    plain = await client.post(
        f"/api/v1/lessons/{lesson.id}/materials",
        files={"file": ("handout.pdf", b"%PDF-1.4\nbody\n", "application/pdf")},
        data={"title": "Методичка"},
        cookies=teacher_token,
    )
    assert plain.status_code == 201, plain.text

    await client.put(
        f"/api/v1/lessons/{lesson.id}/text",
        json={"text_content": "Текст без единой ссылки."},
        cookies=teacher_token,
    )

    listing = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=teacher_token)
    assert [m["id"] for m in listing.json()["materials"]] == [plain.json()["id"]]


# ── Student visibility ───────────────────────────────────────────────────────


async def test_student_reads_a_published_text_lesson(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course, _, lesson = await _text_lesson(db_session, teacher_user)
    await make_enrollment(db_session, student_user, course)
    await client.put(
        f"/api/v1/lessons/{lesson.id}/text",
        json={"text_content": "# Материал урока"},
        cookies=teacher_token,
    )

    res = await client.get(f"/api/v1/students/lessons/{lesson.id}", cookies=student_token)
    assert res.status_code == 200, res.text
    assert res.json()["content_type"] == "text"
    assert res.json()["text_content"] == "# Материал урока"


async def test_draft_text_lesson_is_404_for_a_student(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    """Unpublished module → 404, never 403: the API must not leak that it exists."""
    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=False)
    lesson = await make_lesson(db_session, module, content_type=ContentType.text)
    await make_enrollment(db_session, student_user, course)

    res = await client.get(f"/api/v1/students/lessons/{lesson.id}", cookies=student_token)
    assert res.status_code == 404

    knowledge = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=student_token)
    assert knowledge.status_code == 404


# ── Auto-registration from /uploads/* ────────────────────────────────────────


async def test_pptx_upload_registers_a_material(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    sample_pptx_bytes: bytes,
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)

    res = await client.post(
        f"/api/v1/uploads/pptx?lesson_id={lesson.id}",
        files={"file": ("deck.pptx", sample_pptx_bytes, _PPTX_MIME)},
        cookies=teacher_token,
    )
    assert res.status_code == 200, res.text
    assert res.json()["file_path"]

    listing = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=teacher_token)
    materials = listing.json()["materials"]
    assert [m["original_filename"] for m in materials] == ["deck.pptx"]
    # Its own copy under materials/<lesson_id>/, not the pipeline's object.
    row = await db_session.scalar(
        select(LessonMaterial).where(LessonMaterial.lesson_id == lesson.id)
    )
    assert row is not None
    assert row.file_path.startswith(f"materials/{lesson.id}/")
    assert row.is_inline is False


async def test_repeated_pptx_upload_does_not_duplicate_the_material(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    sample_pptx_bytes: bytes,
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)

    for _ in range(2):
        res = await client.post(
            f"/api/v1/uploads/pptx?lesson_id={lesson.id}",
            files={"file": ("deck.pptx", sample_pptx_bytes, _PPTX_MIME)},
            cookies=teacher_token,
        )
        assert res.status_code == 200, res.text

    listing = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=teacher_token)
    assert len(listing.json()["materials"]) == 1


async def test_script_upload_keeps_the_source_and_the_contract(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)

    res = await client.post(
        f"/api/v1/uploads/script?lesson_id={lesson.id}",
        files={"file": ("script.txt", "Текст лекции про алгоритмы.".encode(), "text/plain")},
        cookies=teacher_token,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["script"] == "Текст лекции про алгоритмы."
    assert body["chars"] == len(body["script"])

    listing = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=teacher_token)
    assert [m["original_filename"] for m in listing.json()["materials"]] == ["script.txt"]


async def test_upload_succeeds_when_registration_is_impossible(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    """.html is a valid script source but not a whitelisted material — the
    extraction must still succeed, just without a material row."""
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)

    res = await client.post(
        f"/api/v1/uploads/script?lesson_id={lesson.id}",
        files={"file": ("page.html", b"<p>Lecture body</p>", "text/html")},
        cookies=teacher_token,
    )
    assert res.status_code == 200, res.text
    assert res.json()["script"] == "Lecture body"

    listing = await client.get(f"/api/v1/lessons/{lesson.id}/knowledge", cookies=teacher_token)
    assert listing.json()["materials"] == []


# ── Course-level knowledge tree ──────────────────────────────────────────────


async def test_course_knowledge_tree_groups_by_module_and_lesson(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course, title="Модуль 1")
    lesson = await make_lesson(db_session, module, title="Урок 1")
    await client.post(
        f"/api/v1/lessons/{lesson.id}/materials",
        files={"file": ("handout.pdf", b"%PDF-1.4\nbody\n", "application/pdf")},
        data={"title": "Методичка"},
        cookies=teacher_token,
    )
    await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"title": "Конспект", "content": "Тело конспекта"},
        cookies=teacher_token,
    )

    res = await client.get(f"/api/v1/courses/{course.id}/knowledge", cookies=teacher_token)
    assert res.status_code == 200, res.text
    tree = res.json()
    assert tree["can_edit"] is True
    assert tree["course_title"] == course.title
    node = tree["modules"][0]["lessons"][0]
    assert node["title"] == "Урок 1"
    assert [m["title"] for m in node["materials"]] == ["Методичка"]
    assert [n["title"] for n in node["notes"]] == ["Конспект"]
    # Note bodies are deliberately absent from the course-level payload.
    assert "content" not in node["notes"][0]


async def test_course_knowledge_tree_is_pruned_for_a_student(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, teacher_user, is_published=True)
    visible_module = await make_module(db_session, course, title="Открытый")
    hidden_module = await make_module(db_session, course, title="Скрытый", is_published=False)
    shown = await make_lesson(db_session, visible_module, title="Виден")
    draft = await make_lesson(db_session, visible_module, title="Черновик", is_published=False)
    await make_lesson(db_session, hidden_module, title="В скрытом модуле")
    await make_enrollment(db_session, student_user, course)

    for lesson in (shown, draft):
        await client.post(
            f"/api/v1/lessons/{lesson.id}/materials",
            files={"file": ("handout.pdf", b"%PDF-1.4\nbody\n", "application/pdf")},
            cookies=teacher_token,
        )

    res = await client.get(f"/api/v1/courses/{course.id}/knowledge", cookies=student_token)
    assert res.status_code == 200, res.text
    tree = res.json()
    assert tree["can_edit"] is False
    assert [m["title"] for m in tree["modules"]] == ["Открытый"]
    assert [lesson["title"] for lesson in tree["modules"][0]["lessons"]] == ["Виден"]


async def test_course_knowledge_tree_access_matrix(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, teacher_user, is_published=True)

    not_enrolled = await client.get(f"/api/v1/courses/{course.id}/knowledge", cookies=student_token)
    assert not_enrolled.status_code == 403

    missing = await client.get(
        "/api/v1/courses/00000000-0000-0000-0000-000000000000/knowledge",
        cookies=student_token,
    )
    assert missing.status_code == 404
