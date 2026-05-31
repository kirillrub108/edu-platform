import structlog
import os
import re
import tempfile
import wave

import httpx
import numpy as np

from app.config import settings
from app.constants import SILERO_MAX_CHARS

logger = structlog.get_logger()


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
        elif provider == "yandex":
            raise NotImplementedError("Yandex SpeechKit TTS is not configured yet")
        else:
            return self._synthesize_stub(text, output_path)

    def _synthesize_silero(self, text: str, output_path: str, voice: str) -> str:
        """Send text to Silero TTS, splitting into chunks if too long."""
        plain = _strip_ssml_tags(text)
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
