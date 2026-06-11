"""Celery pipelines in EAGER mode.

The pipelines use a SEPARATE sync engine (psycopg2 against the same
testcontainer), so the SAVEPOINT-rolled async session used by HTTP
tests cannot see writes the pipeline makes — and vice versa. We seed
input data via the sync session, run the task, then assert on a fresh
sync session. The PG database is wiped between tests by truncating
every table after the task completes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.course import Course
from app.models.lesson import (
    CreationMode,
    Lesson,
    LessonStatus,
    Module,
)
from app.models.lesson_video import LessonVideo
from app.models.slide_text import SlideText
from app.models.user import User, UserRole
from app.services.auth_service import hash_password

pytestmark = pytest.mark.integration


# ── Sync session helper (separate from db_session async fixture) ────────────

@pytest.fixture()
def sync_session(_alembic_upgraded: None) -> Iterator[Session]:
    """psycopg2 session that mirrors what the Celery worker uses.

    Truncates every table after the test so the next pipeline test sees
    a clean DB. This is the price for the worker holding its own
    connection — SAVEPOINT-on-async-session doesn't help here.
    """
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()
        # Wipe every table — fast on the tiny test DB.
        with engine.connect() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE "
                    "lesson_progress, enrollments, slide_texts, quiz_questions, "
                    "lesson_videos, lessons, modules, courses, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
            conn.commit()
        engine.dispose()


def _seed_lesson(
    sync_session: Session,
    creation_mode: CreationMode = CreationMode.presentation_and_text,
    pptx_path: str = "pptx/x.pptx",
    script: str = "Sentence one. Sentence two.",
) -> Lesson:
    user = User(
        email=f"t-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("password123"),
        role=UserRole.teacher,
        is_active=True,
    )
    sync_session.add(user)
    sync_session.commit()
    course = Course(title="C", owner_id=user.id, is_published=False)
    sync_session.add(course)
    sync_session.commit()
    module = Module(title="M", course_id=course.id)
    sync_session.add(module)
    sync_session.commit()
    lesson = Lesson(
        title="L",
        module_id=module.id,
        creation_mode=creation_mode,
        pptx_path=pptx_path,
        script=script,
        status=LessonStatus.draft,
    )
    sync_session.add(lesson)
    sync_session.commit()
    sync_session.refresh(lesson)
    return lesson


# ── Common mock for storage on disk (PPTX file must exist for the worker) ──

@pytest.fixture()
def _seed_pptx_on_disk(tmp_path_factory: pytest.TempPathFactory, sample_pptx_bytes: bytes) -> str:
    """Put a real pptx at STORAGE_PATH/pptx/x.pptx so storage_service.get_full_path resolves."""
    storage = Path(os.environ["STORAGE_PATH"])
    dest = storage / "pptx"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "x.pptx").write_bytes(sample_pptx_bytes)
    return "pptx/x.pptx"


# ── Vision pipeline ─────────────────────────────────────────────────────────

def test_analyze_presentation_task_happy_path(
    sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    _seed_pptx_on_disk: str,
    mock_subprocess: dict[str, list[list[str]]],
    mock_vision: dict[str, Any],
) -> None:
    """Vision pipeline writes SlideText rows and sets status=ready_for_edit."""
    from app.tasks.vision_pipeline import analyze_presentation_task

    lesson = _seed_lesson(sync_session, pptx_path=_seed_pptx_on_disk)
    mock_vision["analyze_return"] = "vision narration"

    # Task runs synchronously thanks to task_always_eager=True
    result = analyze_presentation_task.apply(args=[str(lesson.id), lesson.pptx_path]).get()
    assert result["status"] == "ok"

    sync_session.expire_all()
    refreshed = sync_session.get(Lesson, lesson.id)
    assert refreshed is not None
    assert refreshed.status == LessonStatus.ready_for_edit

    rows = sync_session.query(SlideText).filter(SlideText.lesson_id == lesson.id).all()
    assert len(rows) >= 1
    assert all(r.generated_text for r in rows)


def test_analyze_presentation_task_handles_vision_error(
    sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    _seed_pptx_on_disk: str,
    mock_subprocess: dict[str, list[list[str]]],
    mock_vision: dict[str, Any],
) -> None:
    """When vision throws, status flips to `error`."""
    from app.tasks.vision_pipeline import analyze_presentation_task

    lesson = _seed_lesson(sync_session, pptx_path=_seed_pptx_on_disk)
    mock_vision["analyze_raise"] = RuntimeError("vision down")

    result = analyze_presentation_task.apply(args=[str(lesson.id), lesson.pptx_path]).get()
    assert result["status"] == "error"

    sync_session.expire_all()
    refreshed = sync_session.get(Lesson, lesson.id)
    assert refreshed is not None
    assert refreshed.status == LessonStatus.error


# ── Video pipeline ──────────────────────────────────────────────────────────

def test_generate_video_lesson_happy_path(
    sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    _seed_pptx_on_disk: str,
    mock_subprocess: dict[str, list[list[str]]],
    mock_vision: dict[str, Any],
    mock_tts: dict[str, int],
    mock_llm_split: dict[str, Any],
) -> None:
    from app.tasks.video_pipeline import generate_video_lesson

    lesson = _seed_lesson(sync_session, pptx_path=_seed_pptx_on_disk)

    result = generate_video_lesson.apply(
        args=[str(lesson.id), lesson.pptx_path, "nova"]
    ).get()
    assert result["status"] == "ok"
    assert result["video_url"]
    assert result["video_id"]

    sync_session.expire_all()
    refreshed = sync_session.get(Lesson, lesson.id)
    assert refreshed is not None
    assert refreshed.status == LessonStatus.published
    # video_url on the lesson is only set via /publish — pipeline writes to lesson_videos.
    lv = sync_session.query(LessonVideo).filter(LessonVideo.lesson_id == lesson.id).one()
    assert lv.video_url == result["video_url"]
    assert str(lv.id) == result["video_id"]
    assert lv.is_published is False
    assert lv.voice == "nova"


def test_generate_video_lesson_marks_error_on_tts_failure(
    sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    _seed_pptx_on_disk: str,
    mock_subprocess: dict[str, list[list[str]]],
    mock_vision: dict[str, Any],
    mock_llm_split: dict[str, Any],
) -> None:
    from app.services import tts_service as tts_mod
    from app.tasks.video_pipeline import generate_video_lesson

    def _broken_synthesize(text: str, output_path: str, voice: str | None = None) -> str:
        raise RuntimeError("TTS down")

    monkeypatch.setattr(tts_mod.tts_service, "synthesize", _broken_synthesize)

    lesson = _seed_lesson(sync_session, pptx_path=_seed_pptx_on_disk)

    # Unique voice → unique TTS cache key (cache file is "{sha256}.{voice}.wav").
    # This guarantees a cache MISS so the mocked-to-fail synthesize() is actually
    # invoked; otherwise a WAV cached by another test (the TTS disk cache lives
    # under the session-scoped STORAGE_PATH) would be reused and the pipeline
    # would succeed. synthesize is mocked to raise, so the voice value is inert.
    result = generate_video_lesson.apply(
        args=[str(lesson.id), lesson.pptx_path, "tts-fail-test-voice"]
    ).get()
    assert result["status"] == "error"

    sync_session.expire_all()
    refreshed = sync_session.get(Lesson, lesson.id)
    assert refreshed is not None
    assert refreshed.status == LessonStatus.error


def test_generate_video_lesson_uses_llm_fallback_on_llm_error(
    sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    _seed_pptx_on_disk: str,
    mock_subprocess: dict[str, list[list[str]]],
    mock_vision: dict[str, Any],
    mock_tts: dict[str, int],
    mock_llm_split: dict[str, Any],
) -> None:
    """If the LLM split raises, the pipeline must use the deterministic
    fallback splitter and still finish published."""
    from app.tasks.video_pipeline import generate_video_lesson

    mock_llm_split["raise"] = RuntimeError("LLM down")
    lesson = _seed_lesson(sync_session, pptx_path=_seed_pptx_on_disk)

    result = generate_video_lesson.apply(
        args=[str(lesson.id), lesson.pptx_path, "nova"]
    ).get()
    assert result["status"] == "ok"

    sync_session.expire_all()
    refreshed = sync_session.get(Lesson, lesson.id)
    assert refreshed is not None
    assert refreshed.status == LessonStatus.published
