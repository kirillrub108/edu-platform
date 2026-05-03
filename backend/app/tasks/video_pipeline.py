import asyncio
import logging
import os
import shutil
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.celery_app import celery_app
from app.config import settings
from app.models.lesson import Lesson, LessonStatus
from app.services.llm_service import llm_service
from app.services.storage_service import storage_service
from app.services.tts_service import tts_service
from app.services.video_service import video_service

logger = logging.getLogger(__name__)

_sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
sync_engine = create_engine(_sync_url, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)


def _set_status(session: Session, lesson_id: UUID, status: LessonStatus, video_url: str | None = None) -> None:
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        return
    lesson.status = status
    if video_url is not None:
        lesson.video_url = video_url
    session.commit()


def _distribute_evenly(text: str, n: int) -> list[str]:
    """Fallback: split text into n roughly equal chunks by sentences."""
    import re
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sentences:
        return [text] * n
    chunk_size = max(1, len(sentences) // n)
    chunks: list[str] = []
    for i in range(n):
        start = i * chunk_size
        end = start + chunk_size if i < n - 1 else len(sentences)
        chunk = " ".join(sentences[start:end]).strip()
        chunks.append(chunk or f"Слайд {i + 1}")
    return chunks


def _split_script_by_slides(script: str, slides_count: int) -> list[str]:
    """Call async LLM service from sync Celery context."""
    try:
        chunks = asyncio.run(llm_service.split_text_by_slides(script, slides_count))
        if len(chunks) == slides_count and all(chunks):
            return chunks
        logger.warning(
            "LLM returned %d chunks for %d slides, using fallback", len(chunks), slides_count
        )
    except Exception:
        logger.exception("LLM split failed, using fallback")
    return _distribute_evenly(script, slides_count)


@celery_app.task(bind=True, name="generate_video_lesson")
def generate_video_lesson(self, lesson_id: str, pptx_relative_path: str) -> dict:
    lesson_uuid = UUID(lesson_id)
    work_dir = os.path.join(settings.STORAGE_PATH, "video_jobs", lesson_id)
    os.makedirs(work_dir, exist_ok=True)

    def _progress(step: str, done: int, total: int) -> None:
        self.update_state(
            state="PROGRESS",
            meta={"step": step, "done": done, "total": total},
        )

    with SyncSession() as session:
        try:
            _set_status(session, lesson_uuid, LessonStatus.processing)
            _progress("slides", 0, 1)

            pptx_full = storage_service.get_full_path(pptx_relative_path)

            # ── 1. PPTX → PNG slides ──────────────────────────────────────
            slides_dir = os.path.join(work_dir, "slides")
            image_paths = video_service.convert_pptx_to_images(pptx_full, slides_dir)
            total_slides = len(image_paths)
            logger.info("Got %d slides", total_slides)
            _progress("slides", total_slides, total_slides)

            # ── 2. Split script via LLM ───────────────────────────────────
            lesson = session.get(Lesson, lesson_uuid)
            base_script = (lesson.script or lesson.text_content or "").strip()

            _progress("llm", 0, 1)
            if base_script and len(base_script.split()) > 5:
                slide_scripts = _split_script_by_slides(base_script, total_slides)
            else:
                slide_scripts = [base_script or f"Слайд {i + 1}" for i in range(total_slides)]
            _progress("llm", 1, 1)

            # ── 3. TTS per slide ──────────────────────────────────────────
            audio_dir = os.path.join(work_dir, "audio")
            os.makedirs(audio_dir, exist_ok=True)
            audio_paths: list[str] = []

            for idx, slide_text in enumerate(slide_scripts):
                _progress("tts", idx, total_slides)
                audio_path = os.path.join(audio_dir, f"slide_{idx:04d}.wav")
                tts_service.synthesize(slide_text, audio_path)
                audio_paths.append(audio_path)

            _progress("tts", total_slides, total_slides)

            # ── 4. PNG + WAV → MP4 ────────────────────────────────────────
            video_relative = f"videos/{lesson_id}.mp4"
            video_full = storage_service.get_full_path(video_relative)
            os.makedirs(os.path.dirname(video_full), exist_ok=True)

            def _encoding_progress(done: int, total: int) -> None:
                _progress("encoding", done, total)

            video_service.build_video(image_paths, audio_paths, video_full, _encoding_progress)

            video_url = storage_service.get_url(video_relative)
            _set_status(session, lesson_uuid, LessonStatus.published, video_url)

            return {"status": "ok", "video_url": video_url}

        except Exception as exc:
            logger.exception("Video pipeline failed for lesson %s", lesson_id)
            _set_status(session, lesson_uuid, LessonStatus.error)
            return {"status": "error", "error": str(exc)}

        finally:
            # Clean up intermediate files regardless of outcome
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
