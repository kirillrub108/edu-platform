"""Unit tests for app.services.vision_analysis.VisionAnalysisService."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from app.services import vision_analysis as vis_mod
from app.services.vision_analysis import VisionAnalysisService, vision_analysis_service

pytestmark = pytest.mark.unit


@pytest.fixture()
def slide_png(tmp_path: Path) -> Path:
    p = tmp_path / "slide.png"
    Image.new("RGB", (100, 100), (200, 200, 200)).save(p, format="PNG")
    return p


def _llm_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _stub_ollama_client(content: str | Exception):
    async def _create(**_kwargs: Any) -> SimpleNamespace:
        if isinstance(content, Exception):
            raise content
        return _llm_response(content)

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )


def test_cache_key_is_deterministic(slide_png: Path) -> None:
    svc = VisionAnalysisService()
    k1 = svc._cache_key(str(slide_png))
    k2 = svc._cache_key(str(slide_png))
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex


def test_cache_key_changes_with_content(tmp_path: Path) -> None:
    svc = VisionAnalysisService()
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(a, format="PNG")
    Image.new("RGB", (10, 10), (255, 255, 255)).save(b, format="PNG")
    assert svc._cache_key(str(a)) != svc._cache_key(str(b))


async def test_analyze_slide_returns_text_from_ollama(
    monkeypatch: pytest.MonkeyPatch, slide_png: Path
) -> None:
    svc = VisionAnalysisService()
    monkeypatch.setattr(svc, "_ollama_client", _stub_ollama_client("narration"))

    result = await svc.analyze_slide(
        slide_image_path=str(slide_png),
        slide_number=1,
        total_slides=1,
        course_title="Course",
        previous_context="",
    )
    assert result == "narration"


async def test_analyze_slide_returns_empty_when_llm_yields_empty(
    monkeypatch: pytest.MonkeyPatch, slide_png: Path
) -> None:
    svc = VisionAnalysisService()
    monkeypatch.setattr(svc, "_ollama_client", _stub_ollama_client(""))

    # Real behaviour: returns "" (whitespace-stripped). NOT ValueError.
    result = await svc.analyze_slide(
        slide_image_path=str(slide_png),
        slide_number=1,
        total_slides=1,
        course_title="Course",
    )
    assert result == ""


def test_cache_key_changes_with_different_model(slide_png: Path) -> None:
    """Changing the model must invalidate the cache (different key)."""
    svc = VisionAnalysisService()
    original = svc._model
    try:
        svc._model = "model-a"
        key_a = svc._cache_key(str(slide_png))
        svc._model = "model-b"
        key_b = svc._cache_key(str(slide_png))
    finally:
        svc._model = original
    assert key_a != key_b


async def test_summarize_presentation_cache_miss_writes_cache_file(
    monkeypatch: pytest.MonkeyPatch, slide_png: Path, tmp_path: Path
) -> None:
    """On a cache miss the result is persisted to a .txt file in SUMMARY_CACHE_DIR."""
    cache_dir = tmp_path / "summaries_cache"
    monkeypatch.setattr(vis_mod, "SUMMARY_CACHE_DIR", str(cache_dir))

    svc = VisionAnalysisService()
    monkeypatch.setattr(svc, "_ollama_client", _stub_ollama_client("written text"))

    await svc.summarize_presentation([str(slide_png)])

    cache_files = list(Path(str(cache_dir)).glob("*.txt"))
    assert len(cache_files) == 1
    assert cache_files[0].read_text(encoding="utf-8") == "written text"


async def test_call_ollama_payload_has_no_ollama_only_fields(
    monkeypatch: pytest.MonkeyPatch, slide_png: Path
) -> None:
    """The generic OpenAI branch must NOT leak Ollama-only fields (options /
    keep_alive / num_ctx / num_predict) — Polza & Yandex AI Studio 400 on them.
    Reasoning flag pinned off: this is the clean-baseline payload check."""
    from app.services.vision_analysis import settings as vis_settings

    monkeypatch.setattr(vis_settings, "VISION_REASONING_DISABLED", False)
    monkeypatch.setattr(vis_settings, "VISION_PROVIDER_ORDER", "")
    svc = VisionAnalysisService()
    captured: dict[str, Any] = {}

    async def _create(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return _llm_response("narration")

    monkeypatch.setattr(
        svc,
        "_ollama_client",
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
        ),
    )

    await svc.analyze_slide(
        slide_image_path=str(slide_png),
        slide_number=1,
        total_slides=1,
        course_title="Course",
    )

    assert set(captured) <= {"model", "messages", "temperature", "max_tokens"}
    for banned in ("options", "keep_alive", "num_ctx", "num_predict", "raw"):
        assert banned not in captured


async def test_call_ollama_reasoning_flag_adds_extra_body(
    monkeypatch: pytest.MonkeyPatch, slide_png: Path
) -> None:
    """VISION_REASONING_DISABLED=True must send the OpenRouter-style switch;
    False (default, Ollama/Yandex) must not send the field at all."""
    from app.services.vision_analysis import settings as vis_settings

    monkeypatch.setattr(vis_settings, "VISION_PROVIDER_ORDER", "")
    svc = VisionAnalysisService()
    captured: dict[str, Any] = {}

    async def _create(**kwargs: Any) -> SimpleNamespace:
        captured.clear()
        captured.update(kwargs)
        return _llm_response("narration")

    monkeypatch.setattr(
        svc,
        "_ollama_client",
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
        ),
    )

    monkeypatch.setattr(vis_settings, "VISION_REASONING_DISABLED", True)
    await svc.analyze_slide(
        slide_image_path=str(slide_png), slide_number=1, total_slides=1, course_title="C"
    )
    assert captured["extra_body"] == {"reasoning": {"enabled": False}}

    monkeypatch.setattr(vis_settings, "VISION_REASONING_DISABLED", False)
    await svc.analyze_slide(
        slide_image_path=str(slide_png), slide_number=1, total_slides=1, course_title="C"
    )
    assert "extra_body" not in captured


async def test_call_ollama_pins_provider_when_configured(
    monkeypatch: pytest.MonkeyPatch, slide_png: Path
) -> None:
    """VISION_PROVIDER_ORDER pins the Polza upstream provider via extra_body and
    merges with the reasoning switch when both are active."""
    from app.services.vision_analysis import settings as vis_settings

    monkeypatch.setattr(vis_settings, "VISION_REASONING_DISABLED", True)
    monkeypatch.setattr(vis_settings, "VISION_PROVIDER_ORDER", "Chutes")
    svc = VisionAnalysisService()
    captured: dict[str, Any] = {}

    async def _create(**kwargs: Any) -> SimpleNamespace:
        captured.clear()
        captured.update(kwargs)
        return _llm_response("narration")

    monkeypatch.setattr(
        svc,
        "_ollama_client",
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
        ),
    )

    await svc.analyze_slide(
        slide_image_path=str(slide_png), slide_number=1, total_slides=1, course_title="C"
    )
    assert captured["extra_body"] == {
        "reasoning": {"enabled": False},
        "provider": {"order": ["Chutes"], "allow_fallbacks": True},
    }


def test_vision_client_uses_cloud_retry_tuning() -> None:
    from app.constants import VISION_MAX_RETRIES

    svc = VisionAnalysisService()
    assert svc.provider == "ollama"  # default branch under test
    assert svc._ollama_client is not None
    assert svc._ollama_client.max_retries == VISION_MAX_RETRIES


async def test_summarize_presentation_uses_disk_cache(
    monkeypatch: pytest.MonkeyPatch, slide_png: Path, tmp_path: Path
) -> None:
    """First call hits the LLM; second call must read the cached file."""
    cache_dir = tmp_path / "summaries_cache"
    monkeypatch.setattr(vis_mod, "SUMMARY_CACHE_DIR", str(cache_dir))

    svc = VisionAnalysisService()
    call_count = {"n": 0}

    async def _counting_create(**_kwargs: Any) -> SimpleNamespace:
        call_count["n"] += 1
        return _llm_response("summary one")

    monkeypatch.setattr(
        svc,
        "_ollama_client",
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=_counting_create))
        ),
    )

    result_1 = await svc.summarize_presentation([str(slide_png)])
    result_2 = await svc.summarize_presentation([str(slide_png)])

    assert result_1 == ["summary one"]
    assert result_2 == ["summary one"]
    assert call_count["n"] == 1  # second call served from cache
