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
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.celery_app import celery_app
from app.config import settings
from app.constants import (
    ENCODE_WORKERS,
    TTS_CACHE_TTL_DAYS,
    TTS_WORKERS,
    VIDEO_AUTO_BASE_CREDITS,
    VIDEO_TEXT_BASE_CREDITS,
)
from app.models.course import Course
from app.models.lesson import CreationMode, Lesson, LessonStatus, Module
from app.models.lesson_video import LessonVideo
from app.models.slide_text import SlideText
from app.models.user import User
from app.services import usage_service
from app.services.billing_service import (
    partial_video_cost,
    sync_claim_billing,
    sync_finalize_generation,
)
from app.services.llm_service import llm_service
from app.services.quota_service import TRIAL_LECTURE, sync_release_slot
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


# TTS_WORKERS=4 is tied to the Silero container's thread count; the polza cloud
# gateway is bounded by its own rate limits instead, so its pool size is
# deployment-tunable via POLZA_TTS_WORKERS.
_TTS_WORKERS = (
    settings.POLZA_TTS_WORKERS if settings.TTS_PROVIDER == "polza" else TTS_WORKERS
)
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
        # Non-default providers get a provider-qualified filename so the same
        # ssml+voice key never returns audio synthesised by another provider.
        # polza additionally keys by model so switching the TTS model never
        # reuses audio from a different one (and switching back revalidates the
        # old cache automatically).
        # Silero keeps the legacy unqualified name — existing caches stay valid.
        if settings.TTS_PROVIDER == "polza":
            suffix = f".polza.{settings.POLZA_TTS_MODEL.replace('/', '-')}"
        elif settings.TTS_PROVIDER != "silero":
            suffix = f".{settings.TTS_PROVIDER}"
        else:
            suffix = ""
        return os.path.join(cache_dir, f"{h}.{voice}{suffix}.wav")
    except Exception:
        return None


class GenerationCancelled(Exception):
    """Cooperative cancellation: cancel_requested was observed at a checkpoint."""


def _cancel_requested(session: Session, lesson_id: UUID) -> bool:
    """Fresh read of the cooperative-cancel flag (bypasses the identity map)."""
    return bool(
        session.execute(
            select(Lesson.cancel_requested).where(Lesson.id == lesson_id)
        ).scalar()
    )


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
    if status in (LessonStatus.published, LessonStatus.error, LessonStatus.cancelled):
        lesson.video_task_id = None
        lesson.cancel_requested = False
    session.commit()


def _enqueue_video_ready_email(session: Session, lesson: Lesson, owner_id: UUID) -> None:
    """Notify the course owner that their video lesson is published. Best-effort:
    any failure (owner gone, no email, broker down) is logged and swallowed so it
    can never roll back the published status."""
    try:
        from app.tasks.email_pipeline import send_email

        owner = session.get(User, owner_id)
        if not owner or not owner.email:
            return
        lesson_url = f"{settings.FRONTEND_URL}/lessons/{lesson.id}"
        send_email.delay(
            to=owner.email,
            subject="Видеолекция готова — Edllm",
            template_name="video_ready.html",
            context={
                "full_name": owner.full_name or "",
                "lesson_title": lesson.title or "",
                "lesson_url": lesson_url,
            },
        )
    except Exception:
        logger.warning("video_ready_email_enqueue_failed", lesson_id=str(lesson.id), exc_info=True)


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
    _owner_id: UUID | None = None
    _credit_op = "LESSON_REGEN" if is_regen else "LESSON_GENERATE"
    # Billing state is written by the router before apply_async (reservation
    # already taken there); the task only settles it. Filled in below.
    _billed_via: str | None = None
    _billing_ref: str | None = None
    _estimate = 0
    _base_credits = VIDEO_TEXT_BASE_CREDITS
    _settled = False
    # Slides whose narration was synthesized (or restored from checkpoint) and
    # their plain char counts — the inputs of the partial-cancellation price.
    _voiced_idx: set[int] = set()
    _plain_lens: list[int] = []
    _spent_now = 0

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

        def _current_spent() -> int:
            if _billed_via != "credits":
                return 0
            voiced_chars = sum(_plain_lens[i] for i in _voiced_idx if i < len(_plain_lens))
            return min(_estimate, partial_video_cost(_base_credits, len(_voiced_idx), voiced_chars))

        def _settle(spent: int, keep_trial_slot: bool) -> None:
            """Settle billing exactly once (idempotent against the cancel
            endpoint and Celery redelivery via claim + ledger guard)."""
            nonlocal _settled
            if _settled or _owner_id is None or _billed_via is None:
                _settled = True
                return
            claimed = sync_claim_billing(session, lesson_uuid)
            if claimed == "credits" and _billing_ref:
                sync_finalize_generation(
                    session, _owner_id, _billing_ref, _estimate, spent, _credit_op
                )
            elif claimed == "trial" and not keep_trial_slot:
                sync_release_slot(session, _owner_id, TRIAL_LECTURE)
            settled_lesson = session.get(Lesson, lesson_uuid)
            if settled_lesson:
                settled_lesson.credits_spent = spent if _billed_via == "credits" else 0
                session.commit()
            _settled = True

        def _checkpoint(step: str, done: int, total: int) -> None:
            """Per-slide checkpoint (main thread): refresh credits_spent in the
            DB, emit progress, and honour cooperative cancellation."""
            nonlocal _spent_now
            new_spent = _current_spent()
            if new_spent != _spent_now:
                _spent_now = new_spent
                cp_lesson = session.get(Lesson, lesson_uuid)
                if cp_lesson:
                    cp_lesson.credits_spent = new_spent
                    session.commit()
            _progress(step, done, total)
            if _cancel_requested(session, lesson_uuid):
                raise GenerationCancelled()

        try:
            # Reset any previous warning from a prior run before starting fresh.
            lesson_reset = session.get(Lesson, lesson_uuid)
            if lesson_reset:
                lesson_reset.last_warning = None
                session.commit()

            _set_status(session, lesson_uuid, LessonStatus.processing)

            owner_lesson = session.get(Lesson, lesson_uuid)
            owner_module = session.get(Module, owner_lesson.module_id) if owner_lesson else None
            owner_course = session.get(Course, owner_module.course_id) if owner_module else None
            if owner_course is None:
                raise RuntimeError(f"Lesson {lesson_id} has no owning course")
            _owner_id = owner_course.owner_id

            # Billing context persisted by the router (None for pre-deploy
            # enqueues — those run unbilled; queues are drained on deploy).
            _billed_via = owner_lesson.billed_via
            _billing_ref = owner_lesson.billing_ref
            _estimate = owner_lesson.credit_estimate or 0
            if _billed_via is None:
                logger.warning("video_pipeline_unbilled_run", lesson_id=lesson_id)

            usage_service.set_usage_context("video", lesson_id=lesson_id)
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
            # Mirror the router's estimate formula for partial-cancel pricing.
            _base_credits = VIDEO_AUTO_BASE_CREDITS if use_per_slide else VIDEO_TEXT_BASE_CREDITS
            if _cancel_requested(session, lesson_uuid):
                raise GenerationCancelled()

            # ── 3. VLM summaries — alignment hints for the script splitter ───
            # Skipped in auto mode (per_slide_texts already describe each slide
            # in detail). In manual mode, VLM summaries replace the legacy
            # python-pptx text extraction so PDFs and image-based slides also
            # get usable alignment hints.
            slide_summaries: list[str] = []
            if not use_per_slide:
                _progress("summary", 0, total_slides)
                usage_service.set_usage_context("video_summary", lesson_id=lesson_id)

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
                if _cancel_requested(session, lesson_uuid):
                    raise GenerationCancelled()

            # ── 4. Split + SSML-annotate via LLM ─────────────────────────────
            _progress("llm", 0, 1)
            usage_service.set_usage_context("video_split", lesson_id=lesson_id)

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
            _plain_lens = [len(_TAG_RE.sub("", s).strip()) for s in slide_scripts]
            _progress("llm", 1, 1)
            if _cancel_requested(session, lesson_uuid):
                raise GenerationCancelled()

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
            # Checkpoint-restored slides count as processed for partial pricing.
            _voiced_idx.update(cp_segments_done)

            _cp_lock = threading.Lock()

            def _do_tts(idx: int) -> tuple[int, str]:
                # Cooperative cancel before starting a new synthesis. Pool
                # threads must not touch the task's session — use a private one.
                with SyncSession() as tts_session:
                    if _cancel_requested(tts_session, lesson_uuid):
                        raise GenerationCancelled()
                # ContextVars don't cross thread boundaries — set per thread.
                usage_service.set_usage_context("tts", lesson_id=lesson_id)
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

                try:
                    # Chain: each completed TTS immediately spawns an encode task.
                    for tts_future in as_completed(tts_futures):
                        idx, audio_path = tts_future.result()
                        tts_done_count += 1
                        _voiced_idx.add(idx)
                        logger.info("tts_done", done=tts_done_count, total=total_slides, slide=idx)
                        enc_future = enc_pool.submit(
                            video_service.encode_segment,
                            idx,
                            image_paths[idx],
                            audio_path,
                            seg_work_dir,
                        )
                        enc_futures[enc_future] = idx
                        _checkpoint("tts", tts_done_count, total_slides)

                    # Collect encoding results (enc_pool still running inside `with`).
                    for enc_future in as_completed(enc_futures):
                        idx = enc_futures[enc_future]
                        segment_paths[idx] = enc_future.result()
                        enc_done += 1
                        with _cp_lock:
                            cp_segments_done.add(idx)
                            cp["segments_done"] = list(cp_segments_done)
                            if cp_redis:
                                _cp_write(cp_redis, lesson_id, cp)
                        _checkpoint("encoding", enc_done, total_slides)
                except GenerationCancelled:
                    # Stop feeding the pools; queued work is dropped, threads
                    # already running finish their current slide and exit.
                    tts_pool.shutdown(wait=False, cancel_futures=True)
                    enc_pool.shutdown(wait=False, cancel_futures=True)
                    raise

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

            # Notify the owner via email (separate celery_email queue). Failure
            # here must never undo the published status.
            _enqueue_video_ready_email(session, owner_lesson, owner_course.owner_id)

            # Remove checkpoint on clean completion — no longer needed.
            if cp_redis:
                _cp_delete(cp_redis, lesson_id)

            _success = True
            return {"status": "ok", "video_id": video_id, "video_url": video_url}

        except GenerationCancelled:
            spent = _current_spent()
            processed = len(_voiced_idx)
            logger.info(
                "video_pipeline_cancelled",
                lesson_id=lesson_id,
                processed_slides=processed,
                credits_spent=spent,
            )
            try:
                # ≥1 processed slide burns the trial slot; an untouched run refunds it.
                _settle(spent=spent, keep_trial_slot=processed >= 1)
            except Exception:
                logger.exception("credit_finalize_failed", lesson_id=lesson_id)
            _spent_now = spent
            _set_status(session, lesson_uuid, LessonStatus.cancelled)
            _publish(lesson_id, {"status": "cancelled", "credits_spent": spent})
            # Keep the checkpoint — a future re-run reuses the synthesized slides.
            return {"status": "cancelled", "credits_spent": spent}

        except Exception as exc:
            logger.exception("video_pipeline_failed", lesson_id=lesson_id)
            _set_status(session, lesson_uuid, LessonStatus.error)
            _publish(lesson_id, {"status": "error"})
            # Do NOT delete the checkpoint here — it enables the next retry to resume.
            return {"status": "error", "error": str(exc)}

        finally:
            # Settle billing before cleanup: full charge on success, full
            # release on failure (the cancel handler settled its partial charge
            # already — _settle is a no-op then).
            try:
                _settle(spent=_estimate if _success else 0, keep_trial_slot=_success)
            except Exception:
                logger.exception("credit_finalize_failed", lesson_id=lesson_id)

            if work_dir and os.path.exists(work_dir):
                if _success:
                    shutil.rmtree(work_dir, ignore_errors=True)
                else:
                    logger.warning("work_dir_retained", path=work_dir)
