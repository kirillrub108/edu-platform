import asyncio
import os
import shutil
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.models.course import Course
from app.models.lesson import Lesson, LessonStatus, Module
from app.models.slide_text import SlideText
from app.services import usage_service
from app.services.billing_service import (
    partial_vision_cost,
    sync_claim_billing,
    sync_finalize_generation,
)
from app.services.storage_service import storage_service
from app.services.tts_service import strip_tts_artifacts
from app.services.video_service import video_service
from app.services.vision_analysis import AnalysisCancelled, vision_analysis_service
from app.tasks.video_pipeline import SyncSession, _cancel_requested, _publish

logger = structlog.get_logger()


def _set_status(session: Session, lesson_id: UUID, status: LessonStatus) -> None:
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        return
    lesson.status = status
    # Clear analyze_task_id once the analysis pipeline is no longer active
    # so the frontend stops resuming polling on this finished task.
    if status in (
        LessonStatus.ready_for_edit,
        LessonStatus.error,
        LessonStatus.draft,
        LessonStatus.cancelled,
    ):
        lesson.analyze_task_id = None
        lesson.cancel_requested = False
    session.commit()


def _store_slide_image(lesson_id: str, slide_idx: int, src_png: str) -> str:
    """Copy a rendered PNG into storage and return its relative path."""
    rel_dir = os.path.join("lessons", lesson_id, "slides").replace("\\", "/")
    full_dir = storage_service.get_full_path(rel_dir)
    os.makedirs(full_dir, exist_ok=True)
    rel_path = f"{rel_dir}/slide_{slide_idx + 1:04d}.png"
    full_path = storage_service.get_full_path(rel_path)
    shutil.copy2(src_png, full_path)
    return rel_path


@celery_app.task(bind=True, name="analyze_presentation", queue="vision", acks_late=True, reject_on_worker_lost=True)
def analyze_presentation_task(self, lesson_id: str, pptx_relative_path: str) -> dict:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=self.request.id, task_name=self.name)
    lesson_uuid = UUID(lesson_id)
    work_dir = os.path.join(settings.STORAGE_PATH, "video_jobs", lesson_id)
    slides_cache_dir = os.path.join(settings.STORAGE_PATH, "slides_cache")
    os.makedirs(work_dir, exist_ok=True)
    _success = False
    _owner_id: UUID | None = None
    # Billing state written by the router before apply_async (see lessons/
    # slides routers); the task only settles it. Trial-covered analysis
    # consumes nothing — the trial lecture slot is taken by generate-video.
    _billed_via: str | None = None
    _billing_ref: str | None = None
    _estimate = 0
    _settled = False
    _spent_now = 0

    def _progress(step: str, done: int, total: int) -> None:
        meta = {
            "step": step,
            "done": done,
            "total": total,
            "credits_spent": _spent_now,
            "credits_reserved": _estimate,
            "billed_via": _billed_via,
        }
        self.update_state(state="PROGRESS", meta=meta)
        _publish(lesson_id, meta)

    with SyncSession() as session:

        def _settle(spent: int) -> None:
            nonlocal _settled
            if _settled or _owner_id is None or _billed_via is None:
                _settled = True
                return
            claimed = sync_claim_billing(session, lesson_uuid)
            if claimed == "credits" and _billing_ref:
                sync_finalize_generation(
                    session, _owner_id, _billing_ref, _estimate, spent, "VISION_ANALYZE"
                )
            settled_lesson = session.get(Lesson, lesson_uuid)
            if settled_lesson:
                settled_lesson.credits_spent = spent if _billed_via == "credits" else 0
                session.commit()
            _settled = True

        try:
            _set_status(session, lesson_uuid, LessonStatus.analyzing)

            lesson = session.get(Lesson, lesson_uuid)
            if not lesson:
                raise RuntimeError(f"Lesson {lesson_id} not found")
            course_title = lesson.title or ""

            module = session.get(Module, lesson.module_id)
            course = session.get(Course, module.course_id) if module else None
            if course is None:
                raise RuntimeError(f"Lesson {lesson_id} has no owning course")
            _owner_id = course.owner_id

            _billed_via = lesson.billed_via
            _billing_ref = lesson.billing_ref
            _estimate = lesson.credit_estimate or 0
            if _billed_via is None:
                logger.warning("vision_pipeline_unbilled_run", lesson_id=lesson_id)

            usage_service.set_usage_context("vision_analyze", lesson_id=lesson_id)
            _progress("slides", 0, 1)

            pptx_full = storage_service.get_full_path(pptx_relative_path)

            # 1. PPTX → PNG slides
            slides_dir = os.path.join(work_dir, "slides")
            image_paths = video_service.convert_pptx_to_images(
                pptx_full, slides_dir, cache_dir=slides_cache_dir
            )
            total = len(image_paths)
            _progress("slides", total, total)

            # 2. Persist images into storage and create SlideText rows.
            session.query(SlideText).filter(SlideText.lesson_id == lesson_uuid).delete(
                synchronize_session=False
            )
            session.commit()

            stored_rel_paths: list[str] = []
            slide_rows: list[SlideText] = []
            for idx, src in enumerate(image_paths):
                rel = _store_slide_image(lesson_id, idx, src)
                stored_rel_paths.append(rel)
                row = SlideText(
                    lesson_id=lesson_uuid,
                    slide_number=idx + 1,
                    generated_text="",
                    image_path=rel,
                )
                session.add(row)
                slide_rows.append(row)
            session.commit()
            for row in slide_rows:
                session.refresh(row)

            # 3. Run vision LLM slide-by-slide.
            _progress("vision", 0, total)

            def _on_progress(done: int, total_: int) -> None:
                # Per-slide checkpoint: pro-rata spend is persisted so the SSE
                # stream (and a cancel settlement) always reflect real progress.
                nonlocal _spent_now
                new_spent = (
                    partial_vision_cost(_estimate, done, total_)
                    if _billed_via == "credits"
                    else 0
                )
                if new_spent != _spent_now:
                    _spent_now = new_spent
                    row = session.get(Lesson, lesson_uuid)
                    if row:
                        row.credits_spent = new_spent
                        session.commit()
                _progress("vision", done, total_)

            texts = asyncio.run(
                vision_analysis_service.analyze_presentation(
                    image_paths,
                    course_title,
                    progress_cb=_on_progress,
                    cancel_check=lambda: _cancel_requested(session, lesson_uuid),
                )
            )

            # 4. Save generated texts.
            empty_count = sum(1 for t in texts if not t)
            for row, text in zip(slide_rows, texts):
                clean = strip_tts_artifacts(text or "")
                if text and clean != text:
                    logger.warning(
                        "vision_llm_tail_stripped",
                        slide=row.slide_number,
                        original_len=len(text),
                        clean_len=len(clean),
                    )
                row.generated_text = clean
            session.commit()

            if empty_count == total:
                raise RuntimeError(
                    f"Vision LLM returned no text for any of the {total} slides. "
                    f"Every request to {settings.VISION_OLLAMA_BASE_URL} failed — check "
                    f"VISION_API_KEY (auth) and that model '{settings.VISION_MODEL}' exists "
                    f"at that endpoint. See the per-slide errors above for the exact cause."
                )

            _set_status(session, lesson_uuid, LessonStatus.ready_for_edit)
            _progress("vision", total, total)
            _publish(lesson_id, {"status": "ready_for_edit"})
            _success = True
            return {"status": "ok", "total_slides": total, "empty_slides": empty_count}

        except AnalysisCancelled as exc:
            spent = (
                partial_vision_cost(_estimate, exc.slides_done, total)
                if _billed_via == "credits"
                else 0
            )
            logger.info(
                "vision_pipeline_cancelled",
                lesson_id=lesson_id,
                processed_slides=exc.slides_done,
                credits_spent=spent,
            )
            try:
                _settle(spent)
            except Exception:
                logger.exception("credit_finalize_failed", lesson_id=lesson_id)
            _spent_now = spent
            _set_status(session, lesson_uuid, LessonStatus.cancelled)
            _publish(lesson_id, {"status": "cancelled", "credits_spent": spent})
            return {"status": "cancelled", "credits_spent": spent}

        except Exception as exc:
            logger.exception("vision_pipeline_failed", lesson_id=lesson_id)
            _set_status(session, lesson_uuid, LessonStatus.error)
            _publish(lesson_id, {"status": "error"})
            return {"status": "error", "error": str(exc)}

        finally:
            # Full charge on success, full release on service failure; the
            # cancel handler settles its partial charge itself (no-op here).
            try:
                _settle(_estimate if _success else 0)
            except Exception:
                logger.exception("credit_finalize_failed", lesson_id=lesson_id)

            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
