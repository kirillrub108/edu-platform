import asyncio
import hashlib
import json
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import UUID, uuid4

import redis as _sync_redis
import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.celery_app import celery_app
from app.config import settings
from app.constants import CREDIT_WEIGHTS, ENCODE_WORKERS, TTS_CACHE_TTL_DAYS, TTS_WORKERS
from app.models.course import Course
from app.models.lesson import CreationMode, Lesson, LessonStatus, Module
from app.models.lesson_video import LessonVideo
from app.models.slide_text import SlideText
from app.services.billing_service import (
    sync_charge_credits,
    sync_release_credits,
    sync_reserve_credits,
)
from app.services.llm_service import llm_service
from app.services.storage_service import storage_service
from app.services.tts_service import tts_service
from app.services.video_service import video_service
from app.services.vision_analysis import vision_analysis_service

logger = structlog.get_logger()

_TAG_RE = re.compile(r"<[^>]+>")

_sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
sync_engine = create_engine(_sync_url, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)

# Sync Redis client for progress pub/sub from prefork workers.
# Lazy-initialized so the URL is not validated at import time (test envs set
# REDIS_URL=memory:// which redis-py rejects). The connection is only attempted
# when _publish() is first called, and any error is silently swallowed.
_redis: "_sync_redis.Redis | None" = None


def _get_sync_redis() -> "_sync_redis.Redis":
    global _redis
    if _redis is None:
        _redis = _sync_redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2
        )
    return _redis


def _publish(lesson_id: str, payload: dict) -> None:
    """Publish a progress/status event to lesson:{lesson_id} pub/sub channel.
    Swallowed on error so a Redis outage never breaks the pipeline."""
    try:
        _get_sync_redis().publish(f"lesson:{lesson_id}", json.dumps(payload))
    except Exception:
        pass


_TTS_WORKERS = TTS_WORKERS
_ENCODE_WORKERS = ENCODE_WORKERS


# ── Checkpoint helpers ────────────────────────────────────────────────────────
# Checkpoint key: job:{lesson_id}:checkpoint
# Structure: {"voice": str, "ssml_chunks": [...], "tts_done": [...], "segments_done": [...]}
# Written atomically via redis.set. Not a hard dependency — any error is logged and swallowed.

def _cp_key(lesson_id: str) -> str:
    return f"job:{lesson_id}:checkpoint"


def _cp_read(r: "_sync_redis.Redis", lesson_id: str) -> dict:
    try:
        raw = r.get(_cp_key(lesson_id))
        if raw:
            return json.loads(raw)
    except Exception:
        logger.error("checkpoint_read_failed", lesson_id=lesson_id)
    return {}


def _cp_write(r: "_sync_redis.Redis", lesson_id: str, cp: dict) -> None:
    try:
        r.set(_cp_key(lesson_id), json.dumps(cp), ex=86400 * TTS_CACHE_TTL_DAYS)
    except Exception:
        logger.error("checkpoint_write_failed", lesson_id=lesson_id)


def _cp_delete(r: "_sync_redis.Redis", lesson_id: str) -> None:
    try:
        r.delete(_cp_key(lesson_id))
    except Exception:
        logger.error("checkpoint_delete_failed", lesson_id=lesson_id)


# ── TTS disk-cache helpers ────────────────────────────────────────────────────
# Cache path: storage/tts_cache/{sha256[:2]}/{sha256}.{voice}.wav
# Two-level directory keeps individual dirs from accumulating thousands of files.

def _tts_cache_path(ssml: str, voice: str) -> str | None:
    try:
        h = hashlib.sha256(ssml.encode()).hexdigest()
        cache_dir = os.path.join(settings.STORAGE_PATH, "tts_cache", h[:2])
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"{h}.{voice}.wav")
    except Exception:
        return None


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
            "llm_ssml_chunk_mismatch",
            got=len(chunks),
            expected=slides_count,
        )
    except Exception:
        logger.exception("llm_ssml_split_failed")
    return llm_service._fallback_ssml(script, slides_count), None


@celery_app.task(bind=True, name="generate_video_lesson", queue="video", acks_late=True, reject_on_worker_lost=True)
def generate_video_lesson(
    self,
    lesson_id: str,
    pptx_relative_path: str,
    voice: str | None = None,
    is_regen: bool = False,
) -> dict:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=self.request.id, task_name=self.name)
    lesson_uuid = UUID(lesson_id)
    effective_voice = voice or settings.SILERO_TTS_VOICE
    work_dir = os.path.join(settings.STORAGE_PATH, "video_jobs", lesson_id)
    slides_cache_dir = os.path.join(settings.STORAGE_PATH, "slides_cache")
    os.makedirs(work_dir, exist_ok=True)
    _success = False
    _reserved = False
    _owner_id: UUID | None = None
    _credit_op = "LESSON_REGEN" if is_regen else "LESSON_GENERATE"
    _credit_amount = CREDIT_WEIGHTS["lesson_regen" if is_regen else "lesson_generate"]

    # Per-task Redis client for checkpoints.
    # Prefork workers must not share connections — create one per task invocation.
    cp_redis: "_sync_redis.Redis | None" = None
    cp: dict = {}
    try:
        cp_redis = _sync_redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2
        )
        cp = _cp_read(cp_redis, lesson_id)
        if cp:
            logger.info(
                "checkpoint_restored",
                lesson_id=lesson_id,
                tts_done_count=len(cp.get("tts_done", [])),
                segments_done_count=len(cp.get("segments_done", [])),
            )
    except Exception:
        logger.error("checkpoint_redis_connect_failed", lesson_id=lesson_id)
        cp_redis = None

    def _progress(step: str, done: int, total: int) -> None:
        self.update_state(state="PROGRESS", meta={"step": step, "done": done, "total": total})
        _publish(lesson_id, {"step": step, "done": done, "total": total})

    with SyncSession() as session:
        try:
            # Reset any previous warning from a prior run before starting fresh.
            lesson_reset = session.get(Lesson, lesson_uuid)
            if lesson_reset:
                lesson_reset.last_warning = None
                session.commit()

            _set_status(session, lesson_uuid, LessonStatus.processing)
            _progress("slides", 0, 1)

            # ── 0. Reserve credits before any expensive work ─────────────────
            owner_lesson = session.get(Lesson, lesson_uuid)
            owner_module = session.get(Module, owner_lesson.module_id) if owner_lesson else None
            owner_course = session.get(Course, owner_module.course_id) if owner_module else None
            if owner_course is None:
                raise RuntimeError(f"Lesson {lesson_id} has no owning course")
            _owner_id = owner_course.owner_id

            if not sync_reserve_credits(
                session, _owner_id, _credit_amount, lesson_id, _credit_op
            ):
                shortfall = session.get(Lesson, lesson_uuid)
                if shortfall:
                    shortfall.last_warning = "Недостаточно кредитов для генерации видео"
                _set_status(session, lesson_uuid, LessonStatus.error)
                _publish(lesson_id, {"status": "error"})
                return {"status": "error", "error": "insufficient_credits"}
            _reserved = True

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
                    logger.exception("vlm_summarisation_failed")
                    slide_summaries = []
                logger.info(
                    "slide_summaries",
                    total=len(slide_summaries),
                    non_empty=sum(1 for s in slide_summaries if s),
                )
                _progress("summary", total_slides, total_slides)

            # ── 4. Split + SSML-annotate via LLM ─────────────────────────────
            _progress("llm", 0, 1)

            cp_ssml = cp.get("ssml_chunks", [])
            if use_per_slide:
                slide_scripts = [
                    f"<p>{t}</p>" if t else f"<p>Слайд {i + 1}</p>"
                    for i, t in enumerate(per_slide_texts)
                ]
            elif cp_ssml and len(cp_ssml) == total_slides:
                # Restore from checkpoint to skip the LLM call.
                logger.info("checkpoint_ssml_restored", lesson_id=lesson_id, count=len(cp_ssml))
                slide_scripts = cp_ssml
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
                    logger.warning("empty_ssml_chunk", slide=i + 1)
            _progress("llm", 1, 1)

            # Persist ssml_chunks and voice to checkpoint. If the voice changed
            # compared to what was previously checkpointed, invalidate tts_done
            # and segments_done (audio must be re-synthesised with the new voice)
            # but keep ssml_chunks to avoid re-running the LLM.
            _voice_matches = cp.get("voice", "") == effective_voice
            cp["voice"] = effective_voice
            cp["ssml_chunks"] = slide_scripts
            if not _voice_matches:
                cp["tts_done"] = []
                cp["segments_done"] = []
            cp.setdefault("tts_done", [])
            cp.setdefault("segments_done", [])
            if cp_redis:
                _cp_write(cp_redis, lesson_id, cp)

            cp_tts_done: set[int] = set(cp["tts_done"])
            cp_segments_done: set[int] = set(cp["segments_done"])

            # ── 5. TTS + encode pipeline ──────────────────────────────────────
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

            # Verify segments_done against disk: the worker may have written the
            # checkpoint entry but crashed before the MKV was fsynced.
            cp_segments_done = {
                k for k in cp_segments_done
                if os.path.exists(os.path.join(seg_work_dir, f"segment_{k:03d}.mkv"))
            }

            segment_paths: list[str | None] = [None] * total_slides
            # Pre-fill already-encoded segments so concatenation can use them.
            for k in cp_segments_done:
                segment_paths[k] = os.path.join(seg_work_dir, f"segment_{k:03d}.mkv")

            tts_done_count = len(cp_segments_done)  # start from already-done slides
            enc_done = len(cp_segments_done)

            _cp_lock = threading.Lock()

            def _do_tts(idx: int) -> tuple[int, str]:
                audio_path = os.path.join(audio_dir, f"slide_{idx:04d}.wav")
                ssml = slide_scripts[idx]
                cache_path = _tts_cache_path(ssml, effective_voice)

                if cache_path and os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
                    logger.info("tts_cache_hit", slide=idx)
                    shutil.copy2(cache_path, audio_path)
                else:
                    if cache_path and os.path.exists(cache_path):
                        # Zero-byte or otherwise empty cache file — treat as miss.
                        logger.warning("tts_cache_corrupted", slide=idx, path=cache_path)
                    logger.info("tts_cache_miss", slide=idx)
                    tts_service.synthesize(ssml, audio_path, voice=effective_voice)
                    if cache_path:
                        try:
                            shutil.copy2(audio_path, cache_path)
                        except Exception:
                            logger.warning("tts_cache_write_failed", slide=idx)

                with _cp_lock:
                    cp_tts_done.add(idx)
                    cp["tts_done"] = list(cp_tts_done)
                    if cp_redis:
                        _cp_write(cp_redis, lesson_id, cp)

                return idx, audio_path

            with (
                ThreadPoolExecutor(max_workers=_TTS_WORKERS, thread_name_prefix="tts") as tts_pool,
                ThreadPoolExecutor(
                    max_workers=_ENCODE_WORKERS, thread_name_prefix="enc"
                ) as enc_pool,
            ):
                # Skip TTS entirely for slides whose segments are already encoded.
                slides_needing_tts = [i for i in range(total_slides) if i not in cp_segments_done]
                tts_futures = {tts_pool.submit(_do_tts, i): i for i in slides_needing_tts}
                enc_futures: dict = {}

                # Chain: each completed TTS immediately spawns an encode task.
                for tts_future in as_completed(tts_futures):
                    idx, audio_path = tts_future.result()
                    tts_done_count += 1
                    _progress("tts", tts_done_count, total_slides)
                    logger.info("tts_done", done=tts_done_count, total=total_slides, slide=idx)
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
                    with _cp_lock:
                        cp_segments_done.add(idx)
                        cp["segments_done"] = list(cp_segments_done)
                        if cp_redis:
                            _cp_write(cp_redis, lesson_id, cp)

            # ── 6. Concatenate segments → final MP4 ───────────────────────────
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
            _publish(lesson_id, {"status": "published", "video_url": video_url})

            # Remove checkpoint on clean completion — no longer needed.
            if cp_redis:
                _cp_delete(cp_redis, lesson_id)

            _success = True
            return {"status": "ok", "video_id": video_id, "video_url": video_url}

        except Exception as exc:
            logger.exception("video_pipeline_failed", lesson_id=lesson_id)
            _set_status(session, lesson_uuid, LessonStatus.error)
            _publish(lesson_id, {"status": "error"})
            # Do NOT delete the checkpoint here — it enables the next retry to resume.
            return {"status": "error", "error": str(exc)}

        finally:
            # Finalize billing before cleanup: charge on success, release the
            # reserved hold on failure.
            if _reserved and _owner_id is not None:
                try:
                    if _success:
                        sync_charge_credits(
                            session, _owner_id, _credit_amount, lesson_id, _credit_op
                        )
                    else:
                        sync_release_credits(session, _owner_id, _credit_amount, lesson_id)
                except Exception:
                    logger.exception("credit_finalize_failed", lesson_id=lesson_id)

            if work_dir and os.path.exists(work_dir):
                if _success:
                    shutil.rmtree(work_dir, ignore_errors=True)
                else:
                    logger.warning("work_dir_retained", path=work_dir)
