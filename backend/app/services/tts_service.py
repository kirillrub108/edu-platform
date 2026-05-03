import logging
import os
import re
import wave

import httpx
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


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


class TTSService:
    def synthesize(self, text: str, output_path: str, voice: str | None = None) -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        provider = settings.TTS_PROVIDER
        effective_voice = voice or settings.SILERO_TTS_VOICE
        logger.info("TTS synthesize — provider=%s, voice=%s, output=%s", provider, effective_voice, output_path)

        if provider == "silero":
            return self._synthesize_silero(text, output_path, effective_voice)
        elif provider == "yandex":
            raise NotImplementedError("Yandex SpeechKit TTS is not configured yet")
        else:
            return self._synthesize_stub(text, output_path)

    def _synthesize_silero(self, text: str, output_path: str, voice: str) -> str:
        """Send SSML content to Silero TTS. The container wraps it in <speak>...</speak> automatically."""
        # Guard: if the text has no readable content after stripping SSML tags,
        # Silero returns HTTP 500. Use a silent stub instead.
        plain = _strip_ssml_tags(text)
        if not plain:
            logger.warning(
                "Empty SSML chunk detected (raw=%r); generating silent placeholder at %s",
                text[:80],
                output_path,
            )
            return self._synthesize_stub(text, output_path)

        url = f"{settings.SILERO_TTS_URL}/process"
        params = {
            "INPUT_TEXT": plain,  # Silero expects plain text, not SSML/HTML
            "VOICE": voice,
        }
        try:
            response = httpx.get(url, params=params, timeout=60)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Silero TTS request failed ({settings.SILERO_TTS_URL}): {exc}"
            ) from exc

        with open(output_path, "wb") as f:
            f.write(response.content)

        return output_path

    def _synthesize_stub(self, text: str, output_path: str) -> str:
        sample_rate = 22050
        words_per_second = 2.5

        logger.warning("TTS stub — generating silent placeholder for %s", output_path)

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
