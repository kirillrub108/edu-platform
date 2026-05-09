import asyncio
import logging
import os
import shutil
from uuid import UUID

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.models.lesson import Lesson, LessonStatus
from app.models.slide_text import SlideText
from app.services.storage_service import storage_service
from app.services.video_service import video_service
from app.services.vision_analysis import vision_analysis_service
from app.tasks.video_pipeline import SyncSession

logger = logging.getLogger(__name__)


def _set_status(session: Session, lesson_id: UUID, status: LessonStatus) -> None:
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        return
    lesson.status = status
    # Clear analyze_task_id once the analysis pipeline is no longer active
    # so the frontend stops resuming polling on this finished task.
    if status in (LessonStatus.ready_for_edit, LessonStatus.error, LessonStatus.draft):
        lesson.analyze_task_id = None
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


@celery_app.task(bind=True, name="analyze_presentation")
def analyze_presentation_task(self, lesson_id: str, pptx_relative_path: str) -> dict:
    lesson_uuid = UUID(lesson_id)
    work_dir = os.path.join(settings.STORAGE_PATH, "video_jobs", lesson_id)
    slides_cache_dir = os.path.join(settings.STORAGE_PATH, "slides_cache")
    os.makedirs(work_dir, exist_ok=True)

    def _progress(step: str, done: int, total: int) -> None:
        self.update_state(
            state="PROGRESS",
            meta={"step": step, "done": done, "total": total},
        )

    with SyncSession() as session:
        try:
            _set_status(session, lesson_uuid, LessonStatus.analyzing)
            _progress("slides", 0, 1)

            lesson = session.get(Lesson, lesson_uuid)
            if not lesson:
                raise RuntimeError(f"Lesson {lesson_id} not found")
            course_title = lesson.title or ""

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
                _progress("vision", done, total_)

            texts = asyncio.run(
                vision_analysis_service.analyze_presentation(
                    image_paths,
                    course_title,
                    progress_cb=_on_progress,
                )
            )

            # 4. Save generated texts.
            empty_count = sum(1 for t in texts if not t)
            for row, text in zip(slide_rows, texts):
                row.generated_text = text or ""
            session.commit()

            if empty_count == total:
                raise RuntimeError(
                    f"Vision LLM returned no text for any of the {total} slides. "
                    f"Check that model '{settings.VISION_MODEL}' is available in Ollama "
                    f"(run: ollama pull {settings.VISION_MODEL})."
                )

            _set_status(session, lesson_uuid, LessonStatus.ready_for_edit)
            _progress("vision", total, total)
            return {"status": "ok", "total_slides": total, "empty_slides": empty_count}

        except Exception as exc:
            logger.exception("Vision pipeline failed for lesson %s", lesson_id)
            _set_status(session, lesson_uuid, LessonStatus.error)
            return {"status": "error", "error": str(exc)}

        finally:
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
