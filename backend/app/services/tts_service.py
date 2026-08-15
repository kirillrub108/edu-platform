import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import wave

import httpx
import numpy as np
import structlog

from app.config import settings
from app.constants import (
    POLZA_MAX_CHARS,
    POLZA_TTS_MAX_RETRIES,
    POLZA_TTS_VOICES,
    SILERO_MAX_CHARS,
    TTS_CHUNK_CACHE_DIR_NAME,
    TTS_CHUNK_CACHE_ENABLED,
    YANDEX_TTS_MAX_CHARS,
    YANDEX_TTS_MAX_RETRIES,
    YANDEX_TTS_ROLES_BY_VOICE,
    YANDEX_TTS_RUB_PER_MCHAR,
    YANDEX_TTS_VOICES,
)
from app.services import usage_service

logger = structlog.get_logger()


_LLM_TAIL_RE = re.compile(
    r"(?:^|\n)"
    r"(?:"
    # Russian variants
    r"Пожалуйста[,\s].{0,80}(?:уточни|измени|добави|напиши|сообщи|скажи|задай).{0,60}"
    r"|Если\s+(?:вы\s+)?(?:хотите|нужно|требуется|необходимо).{0,120}"
    r"|Не\s+стесняйтесь.{0,120}"
    r"|Обращайтесь.{0,80}"
    r"|(?:Если\s+)?[Уу]точните.{0,80}"
    r"|[Нн]адеюсь[,\s].{0,120}"
    r"|Рад(?:\s+буду)?\s+помочь.{0,80}"
    r"|Спросите[,\s].{0,80}"
    # English variants
    r"|Please\s+(?:let\s+me\s+know|feel\s+free|clarify|specify|tell\s+me).{0,120}"
    r"|Feel\s+free\s+to.{0,120}"
    r"|(?:Don't|Do\s+not)\s+hesitate\s+to.{0,120}"
    r"|(?:Let\s+me\s+know|If\s+you\s+(?:want|need|have|wish)).{0,120}"
    r"|(?:I\s+)?[Hh]ope\s+(?:this|that).{0,120}"
    r"|Happy\s+to\s+help.{0,80}"
    r")"
    r"[^\n]*",
    re.MULTILINE | re.IGNORECASE,
)

_BLANK_LINES_RE = re.compile(r"\n{3,}")

# LLM (qwen) occasionally leaks CJK characters into Russian narration
# ("…мы должны产出 (выдать) уникальный продукт…"). Silero rejects them with
# "Invalid XML format" → HTTP 500; polza (openai/tts-1) tries to pronounce them
# mid-speech. Never pronounceable in our content — replace with a space.
_CJK_RE = re.compile(
    r"[ᄀ-ᇿ"  # Hangul Jamo
    r"　-ヿ"  # CJK punctuation, Hiragana, Katakana
    r"㄰-㆏"  # Hangul Compatibility Jamo
    r"ㇰ-ㇿ"  # Katakana Phonetic Extensions
    r"㐀-䶿"  # CJK Unified Ideographs Extension A
    r"一-鿿"  # CJK Unified Ideographs
    r"가-힯"  # Hangul Syllables
    r"豈-﫿"  # CJK Compatibility Ideographs
    r"･-ﾟ"  # Halfwidth Katakana
    r"]+"
)


def strip_tts_artifacts(text: str) -> str:
    """Remove markdown formatting and LLM tail phrases before sending to TTS."""
    if not text:
        return text

    # Strip markdown: headings, bold/italic, horizontal rules, inline code
    t = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    t = re.sub(r"\*{2}(.+?)\*{2}", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    t = re.sub(r"^-{3,}$", "", t, flags=re.MULTILINE)

    # Remove LLM tail phrases
    t = _LLM_TAIL_RE.sub("", t)

    # Replace leaked CJK runs with a space, then collapse doubled spaces
    # (only spaces — newlines are handled by _BLANK_LINES_RE below)
    t = _CJK_RE.sub(" ", t)
    t = re.sub(r" {2,}", " ", t)

    # Collapse 3+ blank lines → single blank line, then strip
    t = _BLANK_LINES_RE.sub("\n\n", t)
    return t.strip()


def _strip_ssml_tags(text: str) -> str:
    """Return plain text after removing all XML/SSML tags.

    Block/line tags (<br>, </p>, </speak>) are replaced with a space first so
    adjacent words are not concatenated (e.g. "Тема: Скаты<br>Предмет:" →
    "Тема: Скаты Предмет:").
    """
    text = re.sub(r"<br\s*/?>|</?p>|</?speak>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _split_for_tts(text: str, max_chars: int = SILERO_MAX_CHARS) -> list[str]:
    """Split text into chunks ≤ max_chars, breaking at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    # Split at sentence endings first, then at commas/semicolons if needed.
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        candidate = (current + " " + sentence).strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # Sentence itself too long — split at commas/semicolons
            if len(sentence) > max_chars:
                parts = re.split(r"(?<=[,;])\s+", sentence)
                current = ""
                for part in parts:
                    candidate2 = (current + " " + part).strip() if current else part
                    if len(candidate2) <= max_chars:
                        current = candidate2
                    else:
                        if current:
                            chunks.append(current)
                        current = part
            else:
                current = sentence

    if current:
        chunks.append(current)

    return [c for c in chunks if c.strip()]


def _concat_wav(paths: list[str], output_path: str) -> None:
    """Concatenate WAV files (same params) into output_path."""
    if len(paths) == 1:
        import shutil

        shutil.move(paths[0], output_path)
        return

    frames_list: list[bytes] = []
    params = None
    for path in paths:
        with wave.open(path, "rb") as w:
            if params is None:
                params = w.getparams()
            frames_list.append(w.readframes(w.getnframes()))

    with wave.open(output_path, "wb") as w:
        w.setparams(params)  # type: ignore[arg-type]
        for frames in frames_list:
            w.writeframes(frames)


def _transcode_to_wav(audio: bytes, output_path: str) -> None:
    """Convert provider audio (mp3 from polza/openai-tts) to 48 kHz mono 16-bit WAV.

    Uniform params across chunks are required by _concat_wav; 48 kHz matches
    Silero output so the downstream FFmpeg encode needs no resampling.
    """
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            "pipe:0",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            output_path,
        ],
        input=audio,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Polza TTS audio transcode failed: {result.stderr.decode(errors='replace')[:200]}"
        )


# ── Chunk-level TTS disk cache ───────────────────────────────────────────────
# Cache path: storage/tts_chunk_cache/{sha256[:2]}/{sha256}.wav — mirrors the
# slides_cache / summaries_cache layout (two-level dir to avoid one directory
# accumulating thousands of files). Key covers every parameter that affects the
# resulting audio, so different providers/voices/models/speeds never collide.


def _chunk_cache_key(chunk: str, provider: str, voice: str, model: str, speed: float | None) -> str:
    h = hashlib.sha256()
    h.update(chunk.encode("utf-8"))
    for part in (provider, voice, model or "", "" if speed is None else str(speed)):
        h.update(b"|")
        h.update(part.encode("utf-8"))
    return h.hexdigest()


def _chunk_cache_path(cache_key: str) -> str:
    cache_dir = os.path.join(settings.STORAGE_PATH, TTS_CHUNK_CACHE_DIR_NAME, cache_key[:2])
    return os.path.join(cache_dir, f"{cache_key}.wav")


def _read_chunk_cache(cache_path: str) -> bytes | None:
    try:
        if os.path.getsize(cache_path) == 0:
            return None
        with open(cache_path, "rb") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return None


def _write_chunk_cache(cache_path: str, data: bytes) -> None:
    """Write atomically: a sibling tts_pool thread may be reading this same key
    concurrently, so the file must never be observed half-written."""
    cache_dir = os.path.dirname(cache_path)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp_path, cache_path)
        except Exception:
            os.unlink(tmp_path)
            raise
    except Exception:
        logger.warning("tts_chunk_cache_write_failed", path=cache_path)


class TTSService:
    def synthesize(
        self,
        text: str,
        output_path: str,
        voice: str | None = None,
        role: str | None = None,
    ) -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        provider = settings.TTS_PROVIDER
        effective_voice = voice or settings.SILERO_TTS_VOICE
        logger.info(
            "tts_synthesize",
            provider=provider,
            voice=effective_voice,
            output=output_path,
        )

        if provider == "silero":
            return self._synthesize_silero(text, output_path, effective_voice)
        elif provider == "polza":
            return self._synthesize_polza(text, output_path, effective_voice)
        elif provider == "yandex":
            return self._synthesize_yandex(text, output_path, effective_voice, role)
        else:
            return self._synthesize_stub(text, output_path)

    def _synthesize_silero(self, text: str, output_path: str, voice: str) -> str:
        """Send text to Silero TTS, splitting into chunks if too long."""
        plain = strip_tts_artifacts(_strip_ssml_tags(text))
        # Silero's process_ssml (multi_acc_v3_package) wraps the input in
        # <speak> and rejects ANY form of & or non-tag < — even valid XML
        # entities (&amp;, &lt;) — with "Invalid XML format" → HTTP 500
        # (verified empirically; > is accepted). Escaping cannot help, so
        # replace these never-pronounced characters with a space.
        plain = re.sub(r"\s{2,}", " ", re.sub(r"[&<]", " ", plain)).strip()
        if not plain:
            logger.warning(
                "tts_empty_ssml_chunk",
                raw=repr(text[:80]),
                output=output_path,
            )
            return self._synthesize_stub(text, output_path)

        chunks = _split_for_tts(plain)
        if len(chunks) > 1:
            logger.info("tts_splitting", chars=len(plain), chunks=len(chunks))
        # Self-hosted Silero has no provider bill — chars journaled with cost 0.
        usage_service.record_tts_usage("silero", len(plain), billable=False)

        url = f"{settings.SILERO_TTS_URL}/process"
        tmp_paths: list[str] = []

        try:
            for i, chunk in enumerate(chunks):
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                tmp_paths.append(tmp.name)

                cache_path = (
                    _chunk_cache_path(_chunk_cache_key(chunk, "silero", voice, "", None))
                    if TTS_CHUNK_CACHE_ENABLED
                    else None
                )
                cached = _read_chunk_cache(cache_path) if cache_path else None

                if cached is not None:
                    logger.info("tts_chunk_cache_hit", chunk=i)
                    with open(tmp.name, "wb") as f:
                        f.write(cached)
                else:
                    try:
                        response = httpx.get(
                            url,
                            params={"INPUT_TEXT": chunk, "VOICE": voice},
                            timeout=120,
                        )
                        response.raise_for_status()
                    except httpx.HTTPError as exc:
                        raise RuntimeError(
                            f"Silero TTS request failed ({settings.SILERO_TTS_URL}): {exc}"
                        ) from exc

                    with open(tmp.name, "wb") as f:
                        f.write(response.content)

                    if cache_path:
                        _write_chunk_cache(cache_path, response.content)

            _concat_wav(tmp_paths, output_path)
        finally:
            for p in tmp_paths:
                if os.path.exists(p) and p != output_path:
                    os.unlink(p)

        return output_path

    def _synthesize_polza(self, text: str, output_path: str, voice: str) -> str:
        """Send text to polza.ai /audio/speech (openai/tts-1), chunking if long.

        openai/tts-1 returns mp3, so each chunk is transcoded to WAV before
        _concat_wav.
        """
        if not settings.POLZA_API_KEY:
            raise RuntimeError(
                "Polza TTS is selected (TTS_PROVIDER=polza) but POLZA_API_KEY is not set"
            )

        plain = strip_tts_artifacts(_strip_ssml_tags(text))
        if not plain:
            logger.warning(
                "tts_empty_ssml_chunk",
                raw=repr(text[:80]),
                output=output_path,
            )
            return self._synthesize_stub(text, output_path)

        chunks = _split_for_tts(plain, max_chars=POLZA_MAX_CHARS)
        if len(chunks) > 1:
            logger.info("tts_splitting", chars=len(plain), chunks=len(chunks))
        usage_service.record_tts_usage(settings.POLZA_TTS_MODEL, len(plain))

        # The frontend sends an openai/tts-1 voice name directly; an unknown
        # value falls back to the configured default (also a valid tts-1 voice).
        if voice in POLZA_TTS_VOICES:
            polza_voice = voice
        else:
            polza_voice = settings.POLZA_DEFAULT_VOICE
            logger.info("tts_polza_voice_fallback", requested=voice, used=polza_voice)

        tmp_paths: list[str] = []
        try:
            for chunk in chunks:
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                tmp_paths.append(tmp.name)

                cache_key = _chunk_cache_key(
                    chunk, "polza", polza_voice, settings.POLZA_TTS_MODEL, settings.POLZA_TTS_SPEED
                )
                cache_path = _chunk_cache_path(cache_key) if TTS_CHUNK_CACHE_ENABLED else None
                cached = _read_chunk_cache(cache_path) if cache_path else None

                if cached is not None:
                    logger.info("tts_chunk_cache_hit", provider="polza")
                    with open(tmp.name, "wb") as f:
                        f.write(cached)
                else:
                    # Result is cached post-transcode (WAV) so a hit skips both
                    # the HTTP call and the ffmpeg transcode below.
                    audio = self._polza_speech_request(chunk, polza_voice)
                    _transcode_to_wav(audio, tmp.name)
                    if cache_path:
                        with open(tmp.name, "rb") as f:
                            _write_chunk_cache(cache_path, f.read())

            _concat_wav(tmp_paths, output_path)
        finally:
            for p in tmp_paths:
                if os.path.exists(p) and p != output_path:
                    os.unlink(p)

        return output_path

    def _polza_speech_request(self, chunk: str, polza_voice: str) -> bytes:
        """POST one chunk to polza /audio/speech, return the audio bytes (mp3).

        The endpoint answers with JSON: {"audio": <base64 OR CDN URL>, ...} —
        both variants are handled. 429/5xx/network errors are retried with
        exponential backoff; other 4xx fail fast.
        """
        url = f"{settings.POLZA_BASE_URL}/audio/speech"
        headers = {"Authorization": f"Bearer {settings.POLZA_API_KEY}"}
        body: dict[str, str | float] = {
            "model": settings.POLZA_TTS_MODEL,
            "input": chunk,
            "voice": polza_voice,
        }
        # openai/tts-1 supports `speed` (0.25–4.0); sent only when set in .env.
        if settings.POLZA_TTS_SPEED is not None:
            body["speed"] = settings.POLZA_TTS_SPEED

        last_error = ""
        for attempt in range(POLZA_TTS_MAX_RETRIES + 1):
            if attempt:
                time.sleep(2 ** (attempt - 1))
            try:
                response = httpx.post(
                    url, json=body, headers=headers, timeout=settings.POLZA_TIMEOUT
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                continue
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Polza TTS request failed ({url}): "
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
            return self._polza_extract_audio(response)

        raise RuntimeError(
            f"Polza TTS request failed ({url}) after "
            f"{POLZA_TTS_MAX_RETRIES + 1} attempts: {last_error}"
        )

    def _polza_extract_audio(self, response: httpx.Response) -> bytes:
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Polza TTS returned non-JSON body: {response.text[:200]}") from exc

        audio_field = payload.get("audio") if isinstance(payload, dict) else None
        if not isinstance(audio_field, str) or not audio_field:
            raise RuntimeError(f"Polza TTS returned no audio: {response.text[:200]}")

        if audio_field.startswith(("http://", "https://")):
            try:
                download = httpx.get(audio_field, timeout=settings.POLZA_TIMEOUT)
                download.raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"Polza TTS audio download failed ({audio_field}): {exc}"
                ) from exc
            data = download.content
        else:
            try:
                data = base64.b64decode(audio_field)
            except ValueError as exc:
                raise RuntimeError("Polza TTS returned malformed base64 audio") from exc

        if not data:
            raise RuntimeError("Polza TTS returned empty audio payload")
        return data

    def _synthesize_yandex(
        self, text: str, output_path: str, voice: str, role: str | None = None
    ) -> str:
        """Send text to Yandex SpeechKit API v3, chunking if long.

        v3 is priced per 250-char request unit (~half the cost of v1's
        per-character billing). The request body caps at 250 chars per unit
        too, so chunks stay well under that. Response is streamed as
        newline-delimited JSON objects, each holding one base64 audio
        fragment — not a single JSON document.

        outputAudioSpec.containerAudio (WAV) comes back at 22050 Hz and takes
        no sample-rate argument — but that is the voices' native rate, not a
        downgrade: measured 2026-08-16, every voice in YANDEX_TTS_VOICES rolls
        off at ~11 kHz. Switching to rawAudio at 48 kHz only makes SpeechKit
        resample server-side — 2.2x the bytes for zero extra bandwidth. Keep
        the container. Rationale and measurements in docs/DECISIONS.md.
        """
        if not settings.YANDEX_API_KEY:
            raise RuntimeError(
                "Yandex TTS is selected (TTS_PROVIDER=yandex) but YANDEX_API_KEY is not set"
            )
        plain = strip_tts_artifacts(_strip_ssml_tags(text))
        if not plain:
            logger.warning("tts_empty_ssml_chunk", raw=repr(text[:80]), output=output_path)
            return self._synthesize_stub(text, output_path)
        chunks = _split_for_tts(plain, max_chars=YANDEX_TTS_MAX_CHARS)
        if len(chunks) > 1:
            logger.info("tts_splitting", chars=len(plain), chunks=len(chunks))
        usage_service.record_tts_usage(
            "yandex-speechkit-v3", len(plain), rub_per_mchar=YANDEX_TTS_RUB_PER_MCHAR
        )
        if voice in YANDEX_TTS_VOICES:
            ya_voice = voice
        else:
            ya_voice = settings.YANDEX_TTS_VOICE
            logger.info("tts_yandex_voice_fallback", requested=voice, used=ya_voice)
        # A role the chosen voice doesn't support is a 400 from the API, not a
        # silent ignore — validate against the known-good table before it
        # reaches the request, and fall back to "no role" rather than fail
        # the whole synthesis over a cosmetic mismatch.
        allowed_roles = YANDEX_TTS_ROLES_BY_VOICE.get(ya_voice, ())
        ya_role = role if role in allowed_roles else None
        if role and ya_role is None:
            logger.info("tts_yandex_role_unsupported", voice=ya_voice, requested=role)
        tmp_paths: list[str] = []
        try:
            for chunk in chunks:
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                tmp_paths.append(tmp.name)
                cache_key = _chunk_cache_key(
                    chunk,
                    "yandex",
                    f"{ya_voice}:{ya_role or '-'}",
                    "speechkit-v3",
                    settings.YANDEX_TTS_SPEED,
                )
                cache_path = _chunk_cache_path(cache_key) if TTS_CHUNK_CACHE_ENABLED else None
                cached = _read_chunk_cache(cache_path) if cache_path else None
                if cached is not None:
                    logger.info("tts_chunk_cache_hit", provider="yandex")
                    with open(tmp.name, "wb") as f:
                        f.write(cached)
                else:
                    audio = self._yandex_speech_request_v3(chunk, ya_voice, ya_role)
                    with open(tmp.name, "wb") as f:
                        f.write(audio)
                    if cache_path:
                        _write_chunk_cache(cache_path, audio)
            _concat_wav(tmp_paths, output_path)
        finally:
            for p in tmp_paths:
                if os.path.exists(p) and p != output_path:
                    os.unlink(p)
        return output_path

    def _yandex_speech_request_v3(self, chunk: str, ya_voice: str, ya_role: str | None) -> bytes:
        """POST one chunk to SpeechKit v3, return WAV bytes at 48 kHz.

        v3's response is server-streamed: one JSON object per line, each
        carrying a base64 audio fragment in result.audioChunk.data. All
        fragments concatenate (post-decode) into one valid WAV — the WAV
        header only appears in the first chunk, exactly like a normal
        streamed WAV write.
        """
        url = "https://tts.api.cloud.yandex.net:443/tts/v3/utteranceSynthesis"
        headers = {
            "Authorization": f"Api-Key {settings.YANDEX_API_KEY}",
            "Content-Type": "application/json",
        }
        hints: list[dict[str, str | float]] = [{"voice": ya_voice}]
        if ya_role:
            hints.append({"role": ya_role})
        if settings.YANDEX_TTS_SPEED is not None:
            hints.append({"speed": settings.YANDEX_TTS_SPEED})
        body = {
            "text": chunk,
            "hints": hints,
            "outputAudioSpec": {"containerAudio": {"containerAudioType": "WAV"}},
        }

        last_error = ""
        for attempt in range(YANDEX_TTS_MAX_RETRIES + 1):
            if attempt:
                time.sleep(2 ** (attempt - 1))
            try:
                response = httpx.post(
                    url, json=body, headers=headers, timeout=settings.YANDEX_TTS_TIMEOUT
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                continue
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Yandex SpeechKit v3 request failed ({url}): "
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
            audio = bytearray()
            for line in response.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                data = obj.get("result", {}).get("audioChunk", {}).get("data")
                if data:
                    audio.extend(base64.b64decode(data))
            if not audio:
                raise RuntimeError(
                    f"Yandex SpeechKit v3 returned no audio chunks: {response.text[:200]}"
                )
            return bytes(audio)

        raise RuntimeError(
            f"Yandex SpeechKit v3 request failed ({url}) after "
            f"{YANDEX_TTS_MAX_RETRIES + 1} attempts: {last_error}"
        )

    def _synthesize_stub(self, text: str, output_path: str) -> str:
        sample_rate = 48000  # match Silero output rate → no resampling in FFmpeg
        words_per_second = 2.5

        logger.warning("tts_stub_placeholder", output_path=output_path)

        word_count = max(len(text.split()), 1)
        duration_seconds = max(word_count / words_per_second, 1.0)
        n_samples = int(sample_rate * duration_seconds)

        silence = np.zeros(n_samples, dtype=np.int16)

        with wave.open(output_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(silence.tobytes())

        return output_path


tts_service = TTSService()
