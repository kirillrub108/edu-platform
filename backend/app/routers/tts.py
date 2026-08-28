"""Voice sample preview: synthesize a short fixed sentence in the teacher's
selected voice/role so they can hear it before generating a full lesson.

No credits are reserved/charged — the sample is a handful of fixed characters
and reuses tts_service's existing chunk-level disk cache, so repeat requests
for the same voice never re-hit the provider. Anti-abuse is the rate limit
below, same as other AI-triggering endpoints.
"""

from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.constants import (
    POLZA_TTS_VOICES,
    TTS_SAMPLE_TEXT,
    YANDEX_TTS_ROLES_BY_VOICE,
    YANDEX_TTS_VOICES,
)
from app.dependencies import require_verified_teacher
from app.limiter import limiter
from app.models.user import User
from app.services.tts_service import tts_service

router = APIRouter(prefix="/api/v1", tags=["tts"])


def _validate_voice_role(voice: str, role: str | None) -> None:
    """Strict validation against the active provider's known-good lists —
    unlike VideoGenerateRequest (schemas/lesson.py), which lets tts_service
    silently fall back on an unsupported role since a full generation job
    shouldn't die over a cosmetic mismatch. A cheap preview call can just 422."""
    provider = settings.TTS_PROVIDER
    if provider == "yandex":
        if voice not in YANDEX_TTS_VOICES:
            raise HTTPException(422, "Неизвестный голос")
        allowed = YANDEX_TTS_ROLES_BY_VOICE.get(voice, ())
        if role is not None and role not in allowed:
            raise HTTPException(422, "Амплуа не поддерживается для этого голоса")
    elif provider == "polza":
        if voice not in POLZA_TTS_VOICES:
            raise HTTPException(422, "Неизвестный голос")
        if role is not None:
            raise HTTPException(422, "Провайдер не поддерживает амплуа")
    elif provider == "silero":
        if voice != settings.SILERO_TTS_VOICE:
            raise HTTPException(422, "Неизвестный голос")
        if role is not None:
            raise HTTPException(422, "Провайдер не поддерживает амплуа")
    else:
        raise HTTPException(422, "TTS провайдер не настроен")


@router.get("/tts/sample")
@limiter.limit("10/minute")
async def get_voice_sample(
    request: Request,
    voice: str = Query(...),
    role: str | None = Query(None),
    _user: User = Depends(require_verified_teacher),
) -> Response:
    _validate_voice_role(voice, role)

    fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        await run_in_threadpool(tts_service.synthesize, TTS_SAMPLE_TEXT, tmp_path, voice, role)
        with open(tmp_path, "rb") as f:
            audio = f.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return Response(content=audio, media_type="audio/wav")
