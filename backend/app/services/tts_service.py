import structlog
import base64
import os
import re
import subprocess
import tempfile
import time
import wave

import httpx
import numpy as np

from app.config import settings
from app.constants import (
    POLZA_MAX_CHARS,
    POLZA_OPENAI_DEFAULT_VOICE,
    POLZA_TTS_MAX_RETRIES,
    POLZA_VOICE_MAP,
    POLZA_VOICE_MAP_OPENAI,
    SILERO_MAX_CHARS,
)

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
# "Invalid XML format" → HTTP 500; polza/ElevenLabs tries to pronounce them
# mid-speech. Never pronounceable in our content — replace with a space.
_CJK_RE = re.compile(
    r"[ᄀ-ᇿ"   # Hangul Jamo
    r"　-ヿ"    # CJK punctuation, Hiragana, Katakana
    r"㄰-㆏"    # Hangul Compatibility Jamo
    r"ㇰ-ㇿ"    # Katakana Phonetic Extensions
    r"㐀-䶿"    # CJK Unified Ideographs Extension A
    r"一-鿿"    # CJK Unified Ideographs
    r"가-힯"    # Hangul Syllables
    r"豈-﫿"    # CJK Compatibility Ideographs
    r"･-ﾟ"    # Halfwidth Katakana
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
    """Convert provider audio (mp3 from polza/ElevenLabs) to 48 kHz mono 16-bit WAV.

    Uniform params across chunks are required by _concat_wav; 48 kHz matches
    Silero output so the downstream FFmpeg encode needs no resampling.
    """
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", "pipe:0", "-ar", "48000", "-ac", "1",
         "-c:a", "pcm_s16le", output_path],
        input=audio,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Polza TTS audio transcode failed: "
            f"{result.stderr.decode(errors='replace')[:200]}"
        )


class TTSService:
    def synthesize(self, text: str, output_path: str, voice: str | None = None) -> str:
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
            raise NotImplementedError("Yandex SpeechKit TTS is not configured yet")
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

        url = f"{settings.SILERO_TTS_URL}/process"
        tmp_paths: list[str] = []

        try:
            for i, chunk in enumerate(chunks):
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                tmp_paths.append(tmp.name)

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

            _concat_wav(tmp_paths, output_path)
        finally:
            for p in tmp_paths:
                if os.path.exists(p) and p != output_path:
                    os.unlink(p)

        return output_path

    def _synthesize_polza(self, text: str, output_path: str, voice: str) -> str:
        """Send text to polza.ai /audio/speech (ElevenLabs Turbo), chunking if long.

        ElevenLabs models on polza return mp3 only (no response_format control),
        so each chunk is transcoded to WAV before _concat_wav.
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

        # OpenAI and ElevenLabs models on polza have disjoint voice catalogs —
        # resolve the frontend (Silero) voice name against the active model's map.
        if settings.POLZA_TTS_MODEL.startswith("openai/"):
            voice_map = POLZA_VOICE_MAP_OPENAI
            polza_voice = voice_map.get(voice, POLZA_OPENAI_DEFAULT_VOICE)
        else:
            voice_map = POLZA_VOICE_MAP
            polza_voice = voice_map.get(voice, settings.POLZA_DEFAULT_VOICE)
        if voice not in voice_map:
            logger.info("tts_polza_voice_fallback", requested=voice, used=polza_voice)

        tmp_paths: list[str] = []
        try:
            for chunk in chunks:
                audio = self._polza_speech_request(chunk, polza_voice)
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                tmp_paths.append(tmp.name)
                _transcode_to_wav(audio, tmp.name)

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
        # language_code and the tuning sliders are ElevenLabs-only params —
        # OpenAI models on polza reject unknown fields with 400.
        if not settings.POLZA_TTS_MODEL.startswith("openai/"):
            if settings.POLZA_LANGUAGE_CODE:
                body["language_code"] = settings.POLZA_LANGUAGE_CODE
            # Optional ElevenLabs voice tuning — sent only when set in .env.
            for key, value in (
                ("speed", settings.POLZA_TTS_SPEED),
                ("stability", settings.POLZA_TTS_STABILITY),
                ("similarity_boost", settings.POLZA_TTS_SIMILARITY),
                ("style", settings.POLZA_TTS_STYLE),
            ):
                if value is not None:
                    body[key] = value

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
            raise RuntimeError(
                f"Polza TTS returned non-JSON body: {response.text[:200]}"
            ) from exc

        audio_field = payload.get("audio") if isinstance(payload, dict) else None
        if not isinstance(audio_field, str) or not audio_field:
            raise RuntimeError(
                f"Polza TTS returned no audio: {response.text[:200]}"
            )

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
