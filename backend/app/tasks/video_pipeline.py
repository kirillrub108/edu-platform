import asyncio
import logging
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.celery_app import celery_app
from app.config import settings
from app.models.lesson import CreationMode, Lesson, LessonStatus
from app.models.slide_text import SlideText
from app.services.llm_service import llm_service
from app.services.storage_service import storage_service
from app.services.tts_service import tts_service
from app.services.video_service import video_service

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")

_sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
sync_engine = create_engine(_sync_url, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)

# Matches NUMBER_OF_THREADS in the silero-tts docker-compose service.
_TTS_WORKERS = 4
# Matches VideoService._ENCODE_WORKERS — kept in sync to avoid over-subscribing CPU.
_ENCODE_WORKERS = 3


def _set_status(
    session: Session,
    lesson_id: UUID,
    status: LessonStatus,
    video_url: str | None = None,
) -> None:
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        return
    lesson.status = status
    if video_url is not None:
        lesson.video_url = video_url
    session.commit()


def _split_and_annotate(
    script: str, slides_count: int, slide_texts: list[str] | None = None
) -> list[str]:
    """Call async LLM service from sync Celery context to get SSML-annotated chunks."""
    try:
        chunks = asyncio.run(
            llm_service.split_and_annotate_ssml(script, slides_count, slide_texts)
        )
        if len(chunks) == slides_count and all(chunks):
            return chunks
        logger.warning(
            "LLM returned %d SSML chunks for %d slides, using fallback",
            len(chunks), slides_count,
        )
    except Exception:
        logger.exception("LLM SSML split failed, using fallback")
    return llm_service._fallback_ssml(script, slides_count)


@celery_app.task(bind=True, name="generate_video_lesson")
def generate_video_lesson(
    self, lesson_id: str, pptx_relative_path: str, voice: str | None = None
) -> dict:
    lesson_uuid = UUID(lesson_id)
    effective_voice = voice or settings.SILERO_TTS_VOICE
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
            _set_status(session, lesson_uuid, LessonStatus.processing)
            _progress("slides", 0, 1)

            pptx_full = storage_service.get_full_path(pptx_relative_path)

            # ── 1. PPTX → PNG slides + extract slide texts ───────────────────
            slides_dir = os.path.join(work_dir, "slides")
            image_paths = video_service.convert_pptx_to_images(
                pptx_full, slides_dir, cache_dir=slides_cache_dir
            )
            total_slides = len(image_paths)
            slide_texts = video_service.extract_slide_texts(pptx_full)
            logger.info(
                "Got %d slides (%d with extracted text)",
                total_slides, sum(1 for t in slide_texts if t),
            )
            _progress("slides", total_slides, total_slides)

            # ── 2. Split + SSML-annotate via LLM ─────────────────────────────
            lesson = session.get(Lesson, lesson_uuid)
            mode = getattr(lesson, "creation_mode", CreationMode.presentation_and_text)

            # When per-slide texts already exist (vision-generated and/or
            # edited by the teacher), use them directly — wrap each in a <p>
            # tag and skip the script-splitting LLM call entirely.
            slide_rows = (
                session.query(SlideText)
                .filter(SlideText.lesson_id == lesson_uuid)
                .order_by(SlideText.slide_number)
                .all()
            )
            per_slide_texts = [
                ((row.edited_text or row.generated_text or "").strip())
                for row in slide_rows
            ]

            _progress("llm", 0, 1)

            if (
                mode == CreationMode.presentation_auto
                and len(per_slide_texts) == total_slides
                and any(per_slide_texts)
            ):
                slide_scripts = [
                    f"<p>{t}</p>" if t else f"<p>Слайд {i + 1}</p>"
                    for i, t in enumerate(per_slide_texts)
                ]
            else:
                base_script = (lesson.script or lesson.text_content or "").strip()
                if base_script and len(base_script.split()) > 5:
                    slide_scripts = _split_and_annotate(base_script, total_slides, slide_texts)
                else:
                    slide_scripts = [f"<p>Слайд {i + 1}</p>" for i in range(total_slides)]

            for i, chunk in enumerate(slide_scripts):
                plain = _TAG_RE.sub("", chunk).strip()
                if not plain:
                    fallback_text = (
                        slide_texts[i].strip()
                        if slide_texts and i < len(slide_texts)
                        else ""
                    ).strip()
                    if not fallback_text:
                        fallback_text = f"Слайд {i + 1}"
                    slide_scripts[i] = f"<p>{fallback_text}</p>"
                    logger.warning(
                        "Slide %d had empty SSML chunk; replaced with: %r",
                        i + 1, slide_scripts[i],
                    )
            _progress("llm", 1, 1)

            # ── 3. TTS + encode pipeline ──────────────────────────────────────
            # Two separate thread pools run concurrently:
            #   tts_pool  (4 workers) — one HTTP request to Silero per thread
            #   enc_pool  (3 workers) — one FFmpeg process per thread
            #
            # As soon as each TTS future resolves, its encoding task is
            # submitted immediately. This means encoding of slide N overlaps
            # with TTS synthesis of slides N+1 … N+4 instead of waiting for
            # all TTS to complete first.
            audio_dir = os.path.join(work_dir, "audio")
            os.makedirs(audio_dir, exist_ok=True)
            seg_work_dir = os.path.join(work_dir, "segments")
            os.makedirs(seg_work_dir, exist_ok=True)

            tts_done = 0
            enc_done = 0
            segment_paths: list[str | None] = [None] * total_slides

            def _do_tts(idx: int) -> tuple[int, str]:
                audio_path = os.path.join(audio_dir, f"slide_{idx:04d}.wav")
                tts_service.synthesize(
                    slide_scripts[idx], audio_path, voice=effective_voice
                )
                return idx, audio_path

            with (
                ThreadPoolExecutor(
                    max_workers=_TTS_WORKERS, thread_name_prefix="tts"
                ) as tts_pool,
                ThreadPoolExecutor(
                    max_workers=_ENCODE_WORKERS, thread_name_prefix="enc"
                ) as enc_pool,
            ):
                # Submit all TTS tasks upfront so Silero processes them in parallel.
                tts_futures = {
                    tts_pool.submit(_do_tts, i): i for i in range(total_slides)
                }
                enc_futures: dict = {}

                # Chain: each completed TTS immediately spawns an encode task.
                for tts_future in as_completed(tts_futures):
                    idx, audio_path = tts_future.result()
                    tts_done += 1
                    _progress("tts", tts_done, total_slides)
                    logger.info(
                        "TTS %d/%d done (slide %d)", tts_done, total_slides, idx
                    )
                    enc_future = enc_pool.submit(
                        video_service.encode_segment,
                        idx, image_paths[idx], audio_path, seg_work_dir,
                    )
                    enc_futures[enc_future] = idx

                # Collect encoding results (enc_pool still running inside `with`).
                for enc_future in as_completed(enc_futures):
                    idx = enc_futures[enc_future]
                    segment_paths[idx] = enc_future.result()
                    enc_done += 1
                    _progress("encoding", enc_done, total_slides)

            # ── 4. Concatenate segments → final MP4 ───────────────────────────
            video_relative = f"videos/{lesson_id}.mp4"
            video_full = storage_service.get_full_path(video_relative)
            os.makedirs(os.path.dirname(video_full), exist_ok=True)

            video_service.concatenate_segments(
                segment_paths, video_full  # type: ignore[arg-type]
            )

            video_url = storage_service.get_url(video_relative)
            _set_status(session, lesson_uuid, LessonStatus.published, video_url)

            return {"status": "ok", "video_url": video_url}

        except Exception as exc:
            logger.exception("Video pipeline failed for lesson %s", lesson_id)
            _set_status(session, lesson_uuid, LessonStatus.error)
            return {"status": "error", "error": str(exc)}

        finally:
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
