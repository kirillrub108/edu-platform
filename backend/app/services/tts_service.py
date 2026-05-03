import logging
import os
import wave

import httpx
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


class TTSService:
    def synthesize(self, text: str, output_path: str) -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        provider = settings.TTS_PROVIDER
        logger.info("TTS synthesize — provider=%s, output=%s", provider, output_path)

        if provider == "silero":
            return self._synthesize_silero(text, output_path)
        elif provider == "yandex":
            # TODO: wire up Yandex SpeechKit here using SDK yandex-cloud or REST v1
            raise NotImplementedError("Yandex SpeechKit TTS is not configured yet")
        else:  # "stub" or any unknown value
            return self._synthesize_stub(text, output_path)

    # ------------------------------------------------------------------

    def _synthesize_silero(self, text: str, output_path: str) -> str:
        url = f"{settings.SILERO_TTS_URL}/process"
        params = {
            "INPUT_TEXT": text,
            "VOICE": "aidar",
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
