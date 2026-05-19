import asyncio
import logging
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.celery_app import celery_app
from app.config import settings
from app.models.course import Course
from app.models.lesson import CreationMode, Lesson, LessonStatus, Module
from app.models.lesson_video import LessonVideo
from app.models.slide_text import SlideText
from app.services.llm_service import llm_service
from app.services.storage_service import storage_service
from app.services.tts_service import tts_service
from app.services.video_service import video_service
from app.services.vision_analysis import vision_analysis_service

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
    # Clear video_task_id once the video pipeline is no longer active.
    if status in (LessonStatus.published, LessonStatus.error):
        lesson.video_task_id = None
    session.commit()


def _split_and_annotate(
    script: str, slides_count: int, slide_texts: list[str] | None = None
) -> tuple[list[str], str | None]:
    """Call async LLM service from sync Celery context to get SSML-annotated chunks.

    Returns (chunks, warning) — warning is non-None when fallback was used due to a
    chunk-count mismatch. On LLM exception, falls back silently (no warning).
    """
    try:
        chunks, warning = asyncio.run(
            llm_service.split_and_annotate_ssml(script, slides_count, slide_texts)
        )
        if len(chunks) == slides_count and all(chunks):
            return chunks, warning
        logger.warning(
            "LLM returned %d SSML chunks for %d slides, using fallback",
            len(chunks),
            slides_count,
        )
    except Exception:
        logger.exception("LLM SSML split failed, using fallback")
    return llm_service._fallback_ssml(script, slides_count), None


@celery_app.task(bind=True, name="generate_video_lesson", queue="video")
def generate_video_lesson(
    self, lesson_id: str, pptx_relative_path: str, voice: str | None = None
) -> dict:
    lesson_uuid = UUID(lesson_id)
    effective_voice = voice or settings.SILERO_TTS_VOICE
    work_dir = os.path.join(settings.STORAGE_PATH, "video_jobs", lesson_id)
    slides_cache_dir = os.path.join(settings.STORAGE_PATH, "slides_cache")
    os.makedirs(work_dir, exist_ok=True)
    _success = False

    def _progress(step: str, done: int, total: int) -> None:
        self.update_state(
            state="PROGRESS",
            meta={"step": step, "done": done, "total": total},
        )

    with SyncSession() as session:
        try:
            # Reset any previous warning from a prior run before starting fresh.
            lesson_reset = session.get(Lesson, lesson_uuid)
            if lesson_reset:
                lesson_reset.last_warning = None
                session.commit()

            _set_status(session, lesson_uuid, LessonStatus.processing)
            _progress("slides", 0, 1)

            pptx_full = storage_service.get_full_path(pptx_relative_path)

            # ── 1. PPTX → PNG slides ─────────────────────────────────────────
            slides_dir = os.path.join(work_dir, "slides")
            image_paths = video_service.convert_pptx_to_images(
                pptx_full, slides_dir, cache_dir=slides_cache_dir
            )
            total_slides = len(image_paths)
            _progress("slides", total_slides, total_slides)

            # ── 2. Decide processing path ────────────────────────────────────
            lesson = session.get(Lesson, lesson_uuid)
            mode = getattr(lesson, "creation_mode", CreationMode.presentation_and_text)

            # When per-slide texts already exist (vision-generated and/or
            # edited by the teacher), use them directly — wrap each in a <p>
            # tag and skip both the summary and script-splitting LLM calls.
            slide_rows = (
                session.query(SlideText)
                .filter(SlideText.lesson_id == lesson_uuid)
                .order_by(SlideText.slide_number)
                .all()
            )
            per_slide_texts = [
                ((row.edited_text or row.generated_text or "").strip()) for row in slide_rows
            ]

            use_per_slide = (
                mode == CreationMode.presentation_auto
                and len(per_slide_texts) == total_slides
                and any(per_slide_texts)
            )

            # ── 3. VLM summaries — alignment hints for the script splitter ───
            # Skipped in auto mode (per_slide_texts already describe each slide
            # in detail). In manual mode, VLM summaries replace the legacy
            # python-pptx text extraction so PDFs and image-based slides also
            # get usable alignment hints.
            slide_summaries: list[str] = []
            if not use_per_slide:
                _progress("summary", 0, total_slides)

                def _summary_progress(done: int, total: int) -> None:
                    _progress("summary", done, total)

                try:
                    slide_summaries = asyncio.run(
                        vision_analysis_service.summarize_presentation(
                            image_paths, progress_cb=_summary_progress
                        )
                    )
                except Exception:
                    logger.exception("VLM summarisation failed; falling back to no slide hints")
                    slide_summaries = []
                logger.info(
                    "Got %d slide summaries (%d non-empty)",
                    len(slide_summaries),
                    sum(1 for s in slide_summaries if s),
                )
                _progress("summary", total_slides, total_slides)

            # ── 4. Split + SSML-annotate via LLM ─────────────────────────────
            _progress("llm", 0, 1)

            if use_per_slide:
                slide_scripts = [
                    f"<p>{t}</p>" if t else f"<p>Слайд {i + 1}</p>"
                    for i, t in enumerate(per_slide_texts)
                ]
            else:
                base_script = (lesson.script or lesson.text_content or "").strip()
                if base_script and len(base_script.split()) > 5:
                    slide_scripts, llm_warning = _split_and_annotate(
                        base_script, total_slides, slide_summaries or None
                    )
                    if llm_warning:
                        llm_lesson = session.get(Lesson, lesson_uuid)
                        if llm_lesson:
                            llm_lesson.last_warning = llm_warning
                            session.commit()
                else:
                    slide_scripts = [f"<p>Слайд {i + 1}</p>" for i in range(total_slides)]

            for i, chunk in enumerate(slide_scripts):
                plain = _TAG_RE.sub("", chunk).strip()
                if not plain:
                    # slide_summaries are alignment anchors for the LLM, not spoken
                    # narration — never feed them to TTS. Use a silent placeholder.
                    slide_scripts[i] = f"<p>Слайд {i + 1}</p>"
                    logger.warning(
                        "Slide %d had empty SSML chunk; replaced with placeholder",
                        i + 1,
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
                tts_service.synthesize(slide_scripts[idx], audio_path, voice=effective_voice)
                return idx, audio_path

            with (
                ThreadPoolExecutor(max_workers=_TTS_WORKERS, thread_name_prefix="tts") as tts_pool,
                ThreadPoolExecutor(
                    max_workers=_ENCODE_WORKERS, thread_name_prefix="enc"
                ) as enc_pool,
            ):
                # Submit all TTS tasks upfront so Silero processes them in parallel.
                tts_futures = {tts_pool.submit(_do_tts, i): i for i in range(total_slides)}
                enc_futures: dict = {}

                # Chain: each completed TTS immediately spawns an encode task.
                for tts_future in as_completed(tts_futures):
                    idx, audio_path = tts_future.result()
                    tts_done += 1
                    _progress("tts", tts_done, total_slides)
                    logger.info("TTS %d/%d done (slide %d)", tts_done, total_slides, idx)
                    enc_future = enc_pool.submit(
                        video_service.encode_segment,
                        idx,
                        image_paths[idx],
                        audio_path,
                        seg_work_dir,
                    )
                    enc_futures[enc_future] = idx

                # Collect encoding results (enc_pool still running inside `with`).
                for enc_future in as_completed(enc_futures):
                    idx = enc_futures[enc_future]
                    segment_paths[idx] = enc_future.result()
                    enc_done += 1
                    _progress("encoding", enc_done, total_slides)

            # ── 4. Concatenate segments → final MP4 ───────────────────────────
            # Each generation gets its own file so history entries stay independent.
            video_uuid = uuid4()
            video_relative = f"videos/{lesson_id}/{video_uuid}.mp4"
            video_full = storage_service.get_full_path(video_relative)
            os.makedirs(os.path.dirname(video_full), exist_ok=True)

            video_service.concatenate_segments(
                segment_paths,
                video_full,  # type: ignore[arg-type]
            )

            # Sign with the course owner (teacher); read endpoints re-sign for
            # the current viewer so non-owner readers and post-expiry owner
            # reads also get a valid signature.
            owner_lesson = session.get(Lesson, lesson_uuid)
            owner_module = session.get(Module, owner_lesson.module_id)
            owner_course = session.get(Course, owner_module.course_id)
            video_url = storage_service.get_url(video_relative, str(owner_course.owner_id))

            new_video = LessonVideo(
                id=video_uuid,
                lesson_id=lesson_uuid,
                video_url=video_url,
                voice=effective_voice,
                creation_mode=mode.value,
                is_published=False,
            )
            session.add(new_video)
            video_id = str(video_uuid)
            # _set_status commits the session, which also persists new_video.
            _set_status(session, lesson_uuid, LessonStatus.published)

            _success = True
            return {"status": "ok", "video_id": video_id, "video_url": video_url}

        except Exception as exc:
            logger.exception("Video pipeline failed for lesson %s", lesson_id)
            _set_status(session, lesson_uuid, LessonStatus.error)
            return {"status": "error", "error": str(exc)}

        finally:
            if work_dir and os.path.exists(work_dir):
                if _success:
                    shutil.rmtree(work_dir, ignore_errors=True)
                else:
                    logger.warning("work_dir retained for post-mortem: %s", work_dir)
