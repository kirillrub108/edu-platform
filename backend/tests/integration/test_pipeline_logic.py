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


# ── Billing settlement inside the pipelines ─────────────────────────────────


def _seed_reservation(
    sync_session: Session, user_id: Any, balance: int, estimate: int, billing_ref: str
) -> None:
    """Mirror the router-side reservation: account with a hold + RESERVE row."""
    from app.models.credit import CreditAccount, CreditOperation, CreditTransaction

    account = CreditAccount(owner_id=user_id, balance=balance, reserved=estimate)
    sync_session.add(account)
    sync_session.commit()
    sync_session.refresh(account)
    sync_session.add(
        CreditTransaction(
            account_id=account.id,
            delta=-estimate,
            operation=CreditOperation.RESERVE,
            ref_id=billing_ref,
            description="Reserve for LESSON_GENERATE",
        )
    )
    sync_session.commit()


def _billing_state(sync_session: Session, user_id: Any) -> dict[str, Any]:
    from app.models.credit import CreditAccount, CreditOperation, CreditTransaction

    sync_session.expire_all()
    account = (
        sync_session.query(CreditAccount).filter(CreditAccount.owner_id == user_id).one()
    )
    txs = (
        sync_session.query(CreditTransaction)
        .filter(CreditTransaction.account_id == account.id)
        .all()
    )
    return {
        "balance": account.balance,
        "reserved": account.reserved,
        "releases": [t for t in txs if t.operation == CreditOperation.RELEASE],
        "charges": [
            t
            for t in txs
            if t.operation
            in (CreditOperation.LESSON_GENERATE, CreditOperation.LESSON_REGEN)
        ],
    }


def test_video_failure_refunds_fully_and_retry_does_not_double_release(
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
    billing_ref = f"{lesson.id}:test1"
    user_id = sync_session.query(User).order_by(User.created_at.desc()).first().id
    _seed_reservation(sync_session, user_id, balance=30, estimate=9, billing_ref=billing_ref)
    lesson.billed_via = "credits"
    lesson.billing_ref = billing_ref
    lesson.credit_estimate = 9
    sync_session.commit()

    result = generate_video_lesson.apply(
        args=[str(lesson.id), lesson.pptx_path, "billing-fail-voice"]
    ).get()
    assert result["status"] == "error"

    state = _billing_state(sync_session, user_id)
    assert state["reserved"] == 0
    assert state["balance"] == 30  # full refund — service failure
    assert len(state["releases"]) == 1
    assert state["releases"][0].delta == 9
    assert state["charges"] == []

    # Celery redelivery: the same task runs again — billing already claimed,
    # the failing rerun must not produce a second release.
    result2 = generate_video_lesson.apply(
        args=[str(lesson.id), lesson.pptx_path, "billing-fail-voice"]
    ).get()
    assert result2["status"] == "error"
    state2 = _billing_state(sync_session, user_id)
    assert state2["balance"] == 30
    assert len(state2["releases"]) == 1


def test_video_success_charges_exactly_estimate(
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
    user_id = sync_session.query(User).order_by(User.created_at.desc()).first().id
    billing_ref = f"{lesson.id}:test2"
    _seed_reservation(sync_session, user_id, balance=30, estimate=9, billing_ref=billing_ref)
    lesson.billed_via = "credits"
    lesson.billing_ref = billing_ref
    lesson.credit_estimate = 9
    sync_session.commit()

    result = generate_video_lesson.apply(
        args=[str(lesson.id), lesson.pptx_path, "nova"]
    ).get()
    assert result["status"] == "ok"

    state = _billing_state(sync_session, user_id)
    assert state["reserved"] == 0
    assert state["balance"] == 30 - 9  # exactly the estimate, no more, no less
    assert len(state["charges"]) == 1
    assert state["charges"][0].delta == -9
    assert state["releases"] == []

    refreshed = sync_session.get(Lesson, lesson.id)
    assert refreshed.credits_spent == 9
    assert refreshed.billed_via is None  # settled (claimed)


def test_video_cooperative_cancel_charges_partially(
    sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    _seed_pptx_on_disk: str,
    mock_subprocess: dict[str, list[list[str]]],
    mock_vision: dict[str, Any],
    mock_tts: dict[str, int],
    mock_llm_split: dict[str, Any],
) -> None:
    """cancel_requested set before the run → the pipeline stops at its first
    checkpoint, charges the base price and releases the remainder."""
    from app.constants import VIDEO_TEXT_BASE_CREDITS
    from app.tasks.video_pipeline import generate_video_lesson

    lesson = _seed_lesson(sync_session, pptx_path=_seed_pptx_on_disk)
    user_id = sync_session.query(User).order_by(User.created_at.desc()).first().id
    billing_ref = f"{lesson.id}:test3"
    _seed_reservation(sync_session, user_id, balance=30, estimate=9, billing_ref=billing_ref)
    lesson.billed_via = "credits"
    lesson.billing_ref = billing_ref
    lesson.credit_estimate = 9
    lesson.cancel_requested = True
    sync_session.commit()

    result = generate_video_lesson.apply(
        args=[str(lesson.id), lesson.pptx_path, "nova"]
    ).get()
    assert result["status"] == "cancelled"
    assert result["credits_spent"] == VIDEO_TEXT_BASE_CREDITS  # no slides voiced yet

    state = _billing_state(sync_session, user_id)
    assert state["reserved"] == 0
    assert state["balance"] == 30 - VIDEO_TEXT_BASE_CREDITS
    assert len(state["charges"]) == 1
    assert state["charges"][0].delta == -VIDEO_TEXT_BASE_CREDITS
    assert len(state["releases"]) == 1
    assert state["releases"][0].delta == 9 - VIDEO_TEXT_BASE_CREDITS

    refreshed = sync_session.get(Lesson, lesson.id)
    assert refreshed.status == LessonStatus.cancelled
    assert refreshed.credits_spent == VIDEO_TEXT_BASE_CREDITS
    assert refreshed.cancel_requested is False


def test_video_trial_failure_refunds_slot(
    sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    _seed_pptx_on_disk: str,
    mock_subprocess: dict[str, list[list[str]]],
    mock_vision: dict[str, Any],
    mock_llm_split: dict[str, Any],
) -> None:
    """A service failure must give the trial-lecture slot back."""
    from app.models.usage_counter import UsageCounter
    from app.services import tts_service as tts_mod
    from app.tasks.video_pipeline import generate_video_lesson

    def _broken_synthesize(text: str, output_path: str, voice: str | None = None) -> str:
        raise RuntimeError("TTS down")

    monkeypatch.setattr(tts_mod.tts_service, "synthesize", _broken_synthesize)

    lesson = _seed_lesson(sync_session, pptx_path=_seed_pptx_on_disk)
    user_id = sync_session.query(User).order_by(User.created_at.desc()).first().id
    counter = UsageCounter(
        user_id=user_id, period_key="lifetime", resource="trial_lecture", count=1
    )
    sync_session.add(counter)
    lesson.billed_via = "trial"
    lesson.credit_estimate = 0
    sync_session.commit()

    result = generate_video_lesson.apply(
        args=[str(lesson.id), lesson.pptx_path, "trial-fail-voice"]
    ).get()
    assert result["status"] == "error"

    sync_session.expire_all()
    refreshed_counter = sync_session.get(UsageCounter, counter.id)
    assert refreshed_counter.count == 0  # slot refunded — service fault


def test_vision_cooperative_cancel_releases_hold(
    sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    _seed_pptx_on_disk: str,
    mock_subprocess: dict[str, list[list[str]]],
    mock_vision: dict[str, Any],
) -> None:
    from app.tasks.vision_pipeline import analyze_presentation_task

    lesson = _seed_lesson(sync_session, pptx_path=_seed_pptx_on_disk)
    user_id = sync_session.query(User).order_by(User.created_at.desc()).first().id
    billing_ref = f"{lesson.id}:test4"
    _seed_reservation(sync_session, user_id, balance=10, estimate=5, billing_ref=billing_ref)
    lesson.billed_via = "credits"
    lesson.billing_ref = billing_ref
    lesson.credit_estimate = 5
    lesson.cancel_requested = True
    sync_session.commit()

    result = analyze_presentation_task.apply(args=[str(lesson.id), lesson.pptx_path]).get()
    assert result["status"] == "cancelled"
    assert result["credits_spent"] == 0  # cancelled before the first slide

    state = _billing_state(sync_session, user_id)
    assert state["reserved"] == 0
    assert state["balance"] == 10
    assert len(state["releases"]) == 1

    refreshed = sync_session.get(Lesson, lesson.id)
    assert refreshed.status == LessonStatus.cancelled
