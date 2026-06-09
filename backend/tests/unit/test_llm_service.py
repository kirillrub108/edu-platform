"""Unit tests for app.services.llm_service.LLMService.

We patch the underlying OpenAI client so no network is touched. The
service decodes the JSON the LLM returned and decides whether to use
its output or fall back to a deterministic sentence-based split.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.llm_service import llm_service

pytestmark = pytest.mark.unit


def _llm_response(content: str) -> SimpleNamespace:
    """Shape that mirrors openai.types.chat.ChatCompletion."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _make_completions_stub(return_content: str | Exception) -> Any:
    """Return a stub `client.chat.completions` object whose .create() returns
    a fake response (or raises)."""

    async def _create(**_kwargs: Any) -> SimpleNamespace:
        if isinstance(return_content, Exception):
            raise return_content
        return _llm_response(return_content)

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )


async def test_split_and_annotate_returns_chunks_when_count_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps({"chunks": ["<p>one</p>", "<p>two</p>", "<p>three</p>"]})
    monkeypatch.setattr(llm_service, "client", _make_completions_stub(payload))

    chunks, warning = await llm_service.split_and_annotate_ssml(
        script="One two three.", slides_count=3
    )
    assert len(chunks) == 3
    assert warning is None
    assert all(c.strip() for c in chunks)


async def test_split_and_annotate_falls_back_when_too_few_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps({"chunks": ["<p>only one</p>"]})
    monkeypatch.setattr(llm_service, "client", _make_completions_stub(payload))

    chunks, warning = await llm_service.split_and_annotate_ssml(
        script="Sentence one. Sentence two. Sentence three.", slides_count=3
    )
    assert len(chunks) == 3
    assert warning is not None
    assert "1" in warning and "3" in warning


async def test_split_and_annotate_falls_back_when_too_many_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps(
        {"chunks": ["<p>a</p>", "<p>b</p>", "<p>c</p>", "<p>d</p>"]}
    )
    monkeypatch.setattr(llm_service, "client", _make_completions_stub(payload))

    chunks, warning = await llm_service.split_and_annotate_ssml(
        script="Alpha. Beta. Gamma.", slides_count=3
    )
    assert len(chunks) == 3
    assert warning is not None


async def test_split_and_annotate_handles_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_service, "client", _make_completions_stub("not-json-at-all")
    )

    chunks, warning = await llm_service.split_and_annotate_ssml(
        script="One sentence. Two sentence.", slides_count=2
    )
    # Fallback path; no warning is set on JSON-decode errors (logged instead).
    assert len(chunks) == 2
    assert warning is None


def test_fallback_ssml_produces_n_nonempty_chunks() -> None:
    text = (
        "First sentence. Second sentence. Third sentence. "
        "Fourth sentence. Fifth sentence. Sixth sentence."
    )
    chunks = llm_service._fallback_ssml(text, 2)
    assert len(chunks) == 2
    assert all(c.startswith("<p>") and c.endswith("</p>") for c in chunks)
    assert all(c.strip() != "<p></p>" for c in chunks)


def test_fallback_ssml_with_empty_script_uses_placeholder() -> None:
    chunks = llm_service._fallback_ssml("", 3)
    assert len(chunks) == 3
    # When there are no sentences, fallback uses "Слайд N" placeholders.
    for i, c in enumerate(chunks, start=1):
        assert f"Слайд {i}" in c


def test_strip_think_removes_think_block() -> None:
    raw = "<think>internal</think>visible text"
    assert llm_service._strip_think(raw) == "visible text"


def test_strip_code_fences_removes_json_fence() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert llm_service._strip_code_fences(raw) == '{"a": 1}'


def test_strip_code_fences_noop_on_plain_json() -> None:
    assert llm_service._strip_code_fences('{"a": 1}') == '{"a": 1}'


async def test_split_and_annotate_strips_json_code_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud models may wrap the JSON in a ```json fence despite json_object
    mode — it must be stripped before json.loads, not dropped to the fallback."""
    fenced = "```json\n" + json.dumps({"chunks": ["<p>a</p>", "<p>b</p>"]}) + "\n```"
    monkeypatch.setattr(llm_service, "client", _make_completions_stub(fenced))

    chunks, warning = await llm_service.split_and_annotate_ssml(
        script="A. B.", slides_count=2
    )
    # Exact match proves the fence was stripped: the fallback path would instead
    # mechanically split the raw (fenced) text, never yielding these exact chunks.
    assert chunks == ["<p>a</p>", "<p>b</p>"]
    assert warning is None


def test_llm_client_uses_cloud_retry_tuning() -> None:
    from app.constants import LLM_MAX_RETRIES

    assert llm_service.client.max_retries == LLM_MAX_RETRIES
