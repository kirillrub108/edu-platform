import logging
import os
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.celery_app import celery_app
from app.config import settings
from app.models.lesson import Lesson, LessonStatus
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


@celery_app.task(bind=True, name="generate_video_lesson")
def generate_video_lesson(self, lesson_id: str, pptx_relative_path: str) -> dict:
    lesson_uuid = UUID(lesson_id)
    work_dir = os.path.join(settings.STORAGE_PATH, "video_jobs", lesson_id)
    os.makedirs(work_dir, exist_ok=True)

    with SyncSession() as session:
        try:
            _set_status(session, lesson_uuid, LessonStatus.processing)

            pptx_full = storage_service.get_full_path(pptx_relative_path)

            slides_dir = os.path.join(work_dir, "slides")
            image_paths = video_service.convert_pptx_to_images(pptx_full, slides_dir)
            logger.info("Got %d slides", len(image_paths))

            lesson = session.get(Lesson, lesson_uuid)
            base_script = (lesson.script or lesson.text_content or "").strip()
            slide_scripts = [base_script or f"Slide {i + 1}" for i in range(len(image_paths))]

            audio_paths: list[str] = []
            audio_dir = os.path.join(work_dir, "audio")
            os.makedirs(audio_dir, exist_ok=True)
            for idx, slide_text in enumerate(slide_scripts):
                audio_path = os.path.join(audio_dir, f"slide_{idx:04d}.wav")
                tts_service.synthesize(slide_text, audio_path)
                audio_paths.append(audio_path)

            video_relative = f"videos/{lesson_id}.mp4"
            video_full = storage_service.get_full_path(video_relative)
            video_service.build_video(image_paths, audio_paths, video_full)

            video_url = storage_service.get_url(video_relative)
            _set_status(session, lesson_uuid, LessonStatus.published, video_url)

            return {"status": "ok", "video_url": video_url}
        except Exception as exc:
            logger.exception("Video pipeline failed for lesson %s", lesson_id)
            _set_status(session, lesson_uuid, LessonStatus.error)
            return {"status": "error", "error": str(exc)}
