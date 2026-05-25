"""Unit tests for the LLM-side quiz helpers.

Focus: JSON shape validation and the retry-then-raise contract. The OpenAI
client is stubbed so we can hand back arbitrary content per attempt.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.quiz import GeneratedQuestion
from app.services.llm_service import LLMOutputError, llm_service

pytestmark = pytest.mark.unit


def _llm_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _client_with_sequence(payloads: list[str]) -> Any:
    """Stub client whose .create() yields successive payloads."""
    idx = {"i": 0}

    async def _create(**_kwargs: Any) -> SimpleNamespace:
        i = idx["i"]
        idx["i"] = i + 1
        return _llm_response(payloads[min(i, len(payloads) - 1)])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))


def _valid_question(correct_index: int = 0) -> dict[str, Any]:
    return {
        "question": "Что такое X?",
        "options": ["A", "B", "C", "D"],
        "correct_index": correct_index,
    }


# ── generate_quiz ────────────────────────────────────────────────────────────


async def test_generate_quiz_returns_validated_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"questions": [_valid_question(0), _valid_question(2)]})
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([payload]))

    questions = await llm_service.generate_quiz(
        "Material text", num_questions=2, num_options=4
    )
    assert len(questions) == 2
    assert all(isinstance(q, GeneratedQuestion) for q in questions)
    assert questions[0].correct_index == 0
    assert questions[1].correct_index == 2


async def test_generate_quiz_missing_field_retries_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = json.dumps({"questions": [{"options": ["A", "B"], "correct_index": 0}]})
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([bad, bad]))

    with pytest.raises(LLMOutputError):
        await llm_service.generate_quiz("Material", num_questions=1, num_options=2)


async def test_generate_quiz_wrong_option_count(monkeypatch: pytest.MonkeyPatch) -> None:
    bad_q = {"question": "Q?", "options": ["A", "B", "C"], "correct_index": 0}
    payload = json.dumps({"questions": [bad_q]})
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([payload, payload]))

    with pytest.raises(LLMOutputError):
        await llm_service.generate_quiz("Material", num_questions=1, num_options=4)


async def test_generate_quiz_correct_index_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    bad_q = {"question": "Q?", "options": ["A", "B", "C", "D"], "correct_index": 9}
    payload = json.dumps({"questions": [bad_q]})
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([payload, payload]))

    with pytest.raises(LLMOutputError):
        await llm_service.generate_quiz("Material", num_questions=1, num_options=4)


async def test_generate_quiz_duplicate_options(monkeypatch: pytest.MonkeyPatch) -> None:
    bad_q = {"question": "Q?", "options": ["A", "a", "B", "C"], "correct_index": 0}
    payload = json.dumps({"questions": [bad_q]})
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([payload, payload]))

    with pytest.raises(LLMOutputError):
        await llm_service.generate_quiz("Material", num_questions=1, num_options=4)


async def test_generate_quiz_retry_then_succeed(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = "not-json-at-all"
    good = json.dumps({"questions": [_valid_question(1)]})
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([bad, good]))

    questions = await llm_service.generate_quiz(
        "Material", num_questions=1, num_options=4
    )
    assert len(questions) == 1
    assert questions[0].correct_index == 1


async def test_generate_quiz_wrong_question_count(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"questions": [_valid_question(), _valid_question()]})
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([payload, payload]))

    with pytest.raises(LLMOutputError):
        await llm_service.generate_quiz("Material", num_questions=3, num_options=4)


# ── regenerate_quiz_question ─────────────────────────────────────────────────


async def test_regenerate_question_rephrase(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(_valid_question(0))
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([payload]))

    current = GeneratedQuestion(
        question="Old Q?", options=["X", "Y", "Z", "W"], correct_index=2
    )
    updated = await llm_service.regenerate_quiz_question(
        "Material", current, "rephrase", num_options=4
    )
    assert updated.question == "Что такое X?"


async def test_regenerate_improve_distractors_preserves_correct_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LLM "corrupted" the right answer text. Validator must catch this and trigger retry.
    bad = json.dumps(
        {"question": "Old Q?", "options": ["X", "Y", "Z", "DIFFERENT"], "correct_index": 3}
    )
    good = json.dumps(
        {"question": "Old Q?", "options": ["X", "Y", "Z", "RIGHT"], "correct_index": 3}
    )
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([bad, good]))

    current = GeneratedQuestion(
        question="Old Q?", options=["A", "B", "C", "RIGHT"], correct_index=3
    )
    updated = await llm_service.regenerate_quiz_question(
        "Material", current, "improve_distractors", num_options=4
    )
    assert updated.options[updated.correct_index].lower() == "right"


# ── qa_review_quiz ───────────────────────────────────────────────────────────


async def test_qa_review_returns_flag_per_question(monkeypatch: pytest.MonkeyPatch) -> None:
    qid1, qid2 = uuid.uuid4(), uuid.uuid4()
    payload = json.dumps(
        {
            "flags": [
                {"question_id": str(qid1), "kind": "ok", "note": ""},
                {"question_id": str(qid2), "kind": "ambiguous", "note": "two answers fit"},
            ]
        }
    )
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([payload]))

    flags = await llm_service.qa_review_quiz(
        "Material",
        [
            {"id": qid1, "question": "Q1?", "options": ["A", "B"], "correct_index": 0},
            {"id": qid2, "question": "Q2?", "options": ["A", "B"], "correct_index": 1},
        ],
    )
    assert [f.kind for f in flags] == ["ok", "ambiguous"]
    # UUIDs come from the input, not the LLM's echo.
    assert flags[0].question_id == qid1
    assert flags[1].question_id == qid2


async def test_qa_review_invalid_kind_retries_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    qid = uuid.uuid4()
    payload = json.dumps(
        {"flags": [{"question_id": str(qid), "kind": "garbage", "note": ""}]}
    )
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([payload, payload]))

    with pytest.raises(LLMOutputError):
        await llm_service.qa_review_quiz(
            "Material",
            [{"id": qid, "question": "Q?", "options": ["A", "B"], "correct_index": 0}],
        )


async def test_qa_review_wrong_length_retries_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    qid = uuid.uuid4()
    payload = json.dumps({"flags": []})
    monkeypatch.setattr(llm_service, "client", _client_with_sequence([payload, payload]))

    with pytest.raises(LLMOutputError):
        await llm_service.qa_review_quiz(
            "Material",
            [{"id": qid, "question": "Q?", "options": ["A", "B"], "correct_index": 0}],
        )


async def test_qa_review_empty_input_returns_empty_without_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"n": 0}

    async def _create(**_kwargs: Any) -> SimpleNamespace:
        called["n"] += 1
        return _llm_response("{}")

    monkeypatch.setattr(
        llm_service,
        "client",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create))),
    )
    assert await llm_service.qa_review_quiz("Material", []) == []
    assert called["n"] == 0
