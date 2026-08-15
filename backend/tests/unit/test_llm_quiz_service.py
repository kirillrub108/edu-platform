"""Unit tests for the quiz-facing half of app.services.llm_service.

Everything here stubs `llm_service.client`, so no network is touched. The
subject under test is what the service does with what the model returned:
payload validation (`_parse_payload_v2`), the requested type distribution,
the one-shot retry in `_chat_json_validated`, and the anti-hallucination
guards (ids come from our input, not from the model's echo).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

import pytest

from app.constants import (
    QUIZ_LLM_OPEN_MAX_TOKENS,
    QUIZ_LLM_TEMPERATURE,
    QUIZ_MIN_FOR_DISTRIBUTION,
)
from app.services.llm_service import (
    LLMOutputError,
    _compute_type_counts,
    _parse_payload_v2,
    llm_service,
)

pytestmark = pytest.mark.unit


def _llm_response(content: str) -> SimpleNamespace:
    """Shape that mirrors openai.types.chat.ChatCompletion."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class _RecordingClient:
    """Replays queued contents and records every request kwargs dict.

    A single queued content is repeated for every call, so the retry path can
    be exercised without duplicating the payload.
    """

    def __init__(self, contents: list[str]) -> None:
        self._contents = contents
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self._contents) - 1)
        return _llm_response(self._contents[idx])

    def user_message(self, call: int = 0) -> str:
        return str(self.calls[call]["messages"][1]["content"])


@pytest.fixture()
def stub_llm(monkeypatch: pytest.MonkeyPatch) -> Callable[..., _RecordingClient]:
    def _install(*contents: str) -> _RecordingClient:
        client = _RecordingClient(list(contents))
        monkeypatch.setattr(llm_service, "client", client)
        return client

    return _install


def _q(qtype: str, **extra: Any) -> dict[str, Any]:
    return {"type": qtype, "prompt": f"Вопрос про {qtype}?", **extra}


_SINGLE = _q("single_choice", options=["a", "b", "c"], correct_index=1)
_MULTI = _q("multiple_choice", options=["a", "b", "c"], correct_indices=[0, 2])
_TF = _q("true_false", correct=True)
_SHORT = _q("short_answer", reference_answer="ответ", rubric="критерий")


# ── _compute_type_counts ──────────────────────────────────────────────────────


def test_type_counts_below_threshold_all_go_to_first_type() -> None:
    n = QUIZ_MIN_FOR_DISTRIBUTION - 1
    counts = _compute_type_counts(n, ["single_choice", "true_false"])
    assert counts == {"single_choice": n}


def test_type_counts_single_type_takes_everything() -> None:
    assert _compute_type_counts(10, ["true_false"]) == {"true_false": 10}


def test_type_counts_distribute_and_sum_to_n() -> None:
    types = ["single_choice", "multiple_choice", "true_false", "short_answer"]
    counts = _compute_type_counts(10, types)
    assert sum(counts.values()) == 10
    assert counts["single_choice"] == 5
    assert counts["multiple_choice"] == 3
    # short_answer is last in `ordered`, so it absorbs the rounding remainder.
    assert counts["short_answer"] == 10 - 5 - 3 - counts["true_false"]


def test_type_counts_unknown_types_fall_back_to_first() -> None:
    """Only the four `ordered` types participate; anything else degrades."""
    assert _compute_type_counts(10, ["essay", "matching"]) == {"essay": 10}


def test_type_counts_never_negative() -> None:
    counts = _compute_type_counts(4, ["single_choice", "multiple_choice", "short_answer"])
    assert all(c >= 0 for c in counts.values())
    assert sum(counts.values()) == 4


# ── _parse_payload_v2 / _check_options ────────────────────────────────────────


def test_parse_single_choice_strips_and_normalizes() -> None:
    payload = _parse_payload_v2(
        "single_choice",
        {"prompt": "  Вопрос?  ", "options": [" a ", "b", "c"], "correct_index": 2},
        3,
    )
    assert payload == {
        "type": "single_choice",
        "prompt": "Вопрос?",
        "options": ["a", "b", "c"],
        "correct_index": 2,
        "explanation": "",
    }


def test_parse_accepts_question_key_as_prompt_alias() -> None:
    payload = _parse_payload_v2("true_false", {"question": "Утверждение", "correct": False}, 3)
    assert payload["prompt"] == "Утверждение"
    assert payload["correct"] is False


@pytest.mark.parametrize("prompt", ["", "   ", None, 42])
def test_parse_rejects_empty_prompt(prompt: Any) -> None:
    with pytest.raises(ValueError, match="prompt"):
        _parse_payload_v2("true_false", {"prompt": prompt, "correct": True}, 3)


def test_parse_rejects_wrong_option_count() -> None:
    with pytest.raises(ValueError, match="exactly 4"):
        _parse_payload_v2("single_choice", _SINGLE, 4)


def test_parse_rejects_duplicate_options_case_insensitively() -> None:
    item = _q("single_choice", options=["Ответ", " ответ ", "c"], correct_index=0)
    with pytest.raises(ValueError, match="duplicate option"):
        _parse_payload_v2("single_choice", item, 3)


def test_parse_rejects_blank_option() -> None:
    item = _q("single_choice", options=["a", "   ", "c"], correct_index=0)
    with pytest.raises(ValueError, match="non-empty string"):
        _parse_payload_v2("single_choice", item, 3)


@pytest.mark.parametrize("bad_index", [3, -1, True, "1", None])
def test_parse_rejects_bad_correct_index(bad_index: Any) -> None:
    """`True` must be rejected too — bool is an int subclass and would silently
    read as index 1."""
    item = _q("single_choice", options=["a", "b", "c"], correct_index=bad_index)
    with pytest.raises(ValueError, match="correct_index"):
        _parse_payload_v2("single_choice", item, 3)


def test_parse_multiple_choice_dedupes_and_sorts_indices() -> None:
    item = _q("multiple_choice", options=["a", "b", "c"], correct_indices=[2, 0, 2])
    payload = _parse_payload_v2("multiple_choice", item, 3)
    assert payload["correct_indices"] == [0, 2]


def test_parse_multiple_choice_rejects_all_correct() -> None:
    item = _q("multiple_choice", options=["a", "b", "c"], correct_indices=[0, 1, 2])
    with pytest.raises(ValueError, match="all options correct"):
        _parse_payload_v2("multiple_choice", item, 3)


@pytest.mark.parametrize("indices", [[], "0,1", None])
def test_parse_multiple_choice_rejects_empty_indices(indices: Any) -> None:
    item = _q("multiple_choice", options=["a", "b", "c"], correct_indices=indices)
    with pytest.raises(ValueError, match="correct_indices"):
        _parse_payload_v2("multiple_choice", item, 3)


@pytest.mark.parametrize("correct", ["true", 1, None])
def test_parse_true_false_requires_real_boolean(correct: Any) -> None:
    with pytest.raises(ValueError, match="boolean"):
        _parse_payload_v2("true_false", _q("true_false", correct=correct), 3)


def test_parse_short_answer_defaults_rubric_to_empty() -> None:
    payload = _parse_payload_v2(
        "short_answer", {"prompt": "Что это?", "reference_answer": "  ответ "}, 3
    )
    assert payload == {
        "type": "short_answer",
        "prompt": "Что это?",
        "reference_answer": "ответ",
        "rubric": "",
    }


def test_parse_short_answer_requires_reference() -> None:
    with pytest.raises(ValueError, match="reference_answer"):
        _parse_payload_v2("short_answer", {"prompt": "Что это?", "rubric": "r"}, 3)


def test_parse_rejects_unsupported_type() -> None:
    with pytest.raises(ValueError, match="unsupported generated type"):
        _parse_payload_v2("essay", {"prompt": "Опишите", "rubric": "r"}, 3)


# ── generate_quiz_v2 ──────────────────────────────────────────────────────────


async def test_generate_quiz_returns_ordered_weighted_questions(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    client = stub_llm(json.dumps({"questions": [_SINGLE, _MULTI, _TF, _SHORT]}))

    out = await llm_service.generate_quiz_v2(
        "Материал лекции про энтропию",
        num_questions=4,
        num_options=3,
        types=["single_choice", "multiple_choice", "true_false", "short_answer"],
    )

    assert [q["type"] for q in out] == [
        "single_choice",
        "multiple_choice",
        "true_false",
        "short_answer",
    ]
    assert [q["order"] for q in out] == [0, 1, 2, 3]
    assert {q["weight"] for q in out} == {"1.0"}
    assert out[0]["payload"]["correct_index"] == 1
    # The material must reach the model verbatim — grounding depends on it.
    assert "Материал лекции про энтропию" in client.user_message()


async def test_generate_quiz_retries_once_then_succeeds(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    client = stub_llm("<think>oops</think>not json", json.dumps({"questions": [_SINGLE]}))

    out = await llm_service.generate_quiz_v2(
        "Материал", num_questions=1, num_options=3, types=["single_choice"]
    )

    assert len(out) == 1
    assert len(client.calls) == 2


async def test_generate_quiz_raises_when_count_mismatches(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    """A short deck must not silently become a shorter quiz."""
    client = stub_llm(json.dumps({"questions": [_SINGLE, _SINGLE]}))

    with pytest.raises(LLMOutputError, match="expected 3 questions, got 2"):
        await llm_service.generate_quiz_v2(
            "Материал", num_questions=3, num_options=3, types=["single_choice"]
        )
    assert len(client.calls) == 2  # retry budget spent, then give up


async def test_generate_quiz_rejects_disallowed_type(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    stub_llm(json.dumps({"questions": [_TF]}))

    with pytest.raises(LLMOutputError, match="disallowed type"):
        await llm_service.generate_quiz_v2(
            "Материал", num_questions=1, num_options=3, types=["single_choice"]
        )


async def test_generate_quiz_rejects_non_object_question(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    stub_llm(json.dumps({"questions": ["просто строка"]}))

    with pytest.raises(LLMOutputError, match="not an object"):
        await llm_service.generate_quiz_v2(
            "Материал", num_questions=1, num_options=3, types=["single_choice"]
        )


@pytest.mark.parametrize("payload", [{}, {"questions": []}, {"questions": "nope"}])
async def test_generate_quiz_rejects_missing_questions_array(
    stub_llm: Callable[..., _RecordingClient], payload: dict[str, Any]
) -> None:
    stub_llm(json.dumps(payload))

    with pytest.raises(LLMOutputError, match="questions"):
        await llm_service.generate_quiz_v2(
            "Материал", num_questions=1, num_options=3, types=["single_choice"]
        )


async def test_generate_quiz_empty_types_defaults_to_single_choice(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    client = stub_llm(json.dumps({"questions": [_SINGLE]}))

    out = await llm_service.generate_quiz_v2("Материал", num_questions=1, num_options=3, types=[])

    assert out[0]["type"] == "single_choice"
    assert "single_choice" in client.user_message()


# ── grade_open_answer ─────────────────────────────────────────────────────────


async def test_grade_open_answer_returns_score_and_capped_feedback(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    client = stub_llm(json.dumps({"score": 0.75, "feedback": "  " + "д" * 900 + "  "}))

    score, feedback = await llm_service.grade_open_answer(
        {"type": "short_answer", "prompt": "Что такое энтропия?", "reference_answer": "мера"},
        "мера беспорядка",
    )

    assert score == 0.75
    assert len(feedback) == 600
    kwargs = client.calls[0]
    assert kwargs["max_tokens"] == QUIZ_LLM_OPEN_MAX_TOKENS
    assert kwargs["temperature"] == QUIZ_LLM_TEMPERATURE
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "мера беспорядка" in client.user_message()


async def test_grade_open_answer_marks_empty_student_answer(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    """An empty submission still reaches the grader, flagged as such."""
    client = stub_llm(json.dumps({"score": 0, "feedback": "пусто"}))

    score, _ = await llm_service.grade_open_answer({"type": "essay", "rubric": "r"}, "")

    assert score == 0.0
    assert "[пустой]" in client.user_message()


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"score": 1.5, "feedback": "ok"}),
        json.dumps({"score": -0.1, "feedback": "ok"}),
        json.dumps({"score": "0.5", "feedback": "ok"}),
        json.dumps({"score": 0.5, "feedback": {"not": "a string"}}),
        "не json",
    ],
)
async def test_grade_open_answer_rejects_malformed_verdicts(
    stub_llm: Callable[..., _RecordingClient], body: str
) -> None:
    client = stub_llm(body)

    with pytest.raises(LLMOutputError, match="grade_open_answer"):
        await llm_service.grade_open_answer({"type": "short_answer"}, "ответ")
    assert len(client.calls) == 2


async def test_grade_open_answer_retries_on_empty_content(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    """A reasoning model may emit only a <think> block; that is not a 0.0."""
    client = stub_llm("<think>hmm</think>", json.dumps({"score": 1, "feedback": "верно"}))

    score, feedback = await llm_service.grade_open_answer({"type": "short_answer"}, "ответ")

    assert (score, feedback) == (1.0, "верно")
    assert len(client.calls) == 2


# ── regenerate_quiz_question ──────────────────────────────────────────────────


async def test_regenerate_rejects_non_single_choice(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    client = stub_llm("{}")

    with pytest.raises(ValueError, match="only supported for single_choice"):
        await llm_service.regenerate_quiz_question("Материал", dict(_TF), "rephrase", 3)
    assert client.calls == []  # never spends an LLM call


async def test_regenerate_rejects_malformed_source_question(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    stub_llm("{}")
    broken = _q("single_choice", options=["a", "b"], correct_index=5)

    with pytest.raises(ValueError, match="malformed source question"):
        await llm_service.regenerate_quiz_question("Материал", broken, "rephrase", 2)


async def test_regenerate_rephrase_returns_new_payload(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    client = stub_llm(
        json.dumps({"question": "Иначе?", "options": ["x", "y", "z"], "correct_index": 0})
    )

    payload = await llm_service.regenerate_quiz_question("Материал", dict(_SINGLE), "rephrase", 3)

    assert payload["prompt"] == "Иначе?"
    assert payload["options"] == ["x", "y", "z"]
    assert payload["correct_index"] == 0
    assert "перефразируй" in client.calls[0]["messages"][0]["content"]


async def test_regenerate_improve_distractors_keeps_correct_option(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    stub_llm(json.dumps({"question": "Вопрос?", "options": ["x", "B", "z"], "correct_index": 1}))

    payload = await llm_service.regenerate_quiz_question(
        "Материал", dict(_SINGLE), "improve_distractors", 3
    )

    # Source correct option was "b"; the comparison is case-insensitive.
    assert payload["options"][payload["correct_index"]] == "B"


async def test_regenerate_improve_distractors_rejects_changed_answer(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    """Silently rewriting the correct answer would invalidate every attempt
    already graded against it."""
    client = stub_llm(
        json.dumps({"question": "Вопрос?", "options": ["x", "другое", "z"], "correct_index": 1})
    )

    with pytest.raises(LLMOutputError, match="preserve the correct option"):
        await llm_service.regenerate_quiz_question(
            "Материал", dict(_SINGLE), "improve_distractors", 3
        )
    assert len(client.calls) == 2


# ── qa_review_quiz ────────────────────────────────────────────────────────────


async def test_qa_review_empty_input_skips_the_llm(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    client = stub_llm("{}")

    assert await llm_service.qa_review_quiz("Материал", []) == []
    assert client.calls == []


async def test_qa_review_uses_our_ids_not_the_models_echo(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    q1, q2 = uuid4(), uuid4()
    questions = [
        {"id": q1, "type": "single_choice", "payload": _SINGLE},
        {"id": q2, "type": "true_false", "payload": _TF},
    ]
    stub_llm(
        json.dumps(
            {
                "flags": [
                    {"question_id": str(uuid4()), "kind": "ok", "note": ""},
                    {"question_id": "hallucinated", "kind": "wrong_answer", "note": "н" * 400},
                ]
            }
        )
    )

    flags = await llm_service.qa_review_quiz("Материал", questions)

    assert [f.question_id for f in flags] == [q1, q2]
    assert flags[1].kind == "wrong_answer"
    assert len(flags[1].note) == 300


async def test_qa_review_rejects_flag_count_mismatch(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    stub_llm(json.dumps({"flags": [{"question_id": str(uuid4()), "kind": "ok"}]}))

    with pytest.raises(LLMOutputError, match="expected 2 flags, got 1"):
        await llm_service.qa_review_quiz(
            "Материал",
            [
                {"id": uuid4(), "type": "true_false", "payload": _TF},
                {"id": uuid4(), "type": "true_false", "payload": _TF},
            ],
        )


@pytest.mark.parametrize(
    "flag",
    [
        {"question_id": "x", "kind": "totally_broken"},
        {"question_id": "x", "kind": "ok", "note": 42},
        "not an object",
    ],
)
async def test_qa_review_rejects_malformed_flag(
    stub_llm: Callable[..., _RecordingClient], flag: Any
) -> None:
    stub_llm(json.dumps({"flags": [flag]}))

    with pytest.raises(LLMOutputError, match="qa_review_quiz"):
        await llm_service.qa_review_quiz(
            "Материал", [{"id": uuid4(), "type": "true_false", "payload": _TF}]
        )


async def test_qa_review_rejects_missing_flags_array(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    stub_llm(json.dumps({"result": "ok"}))

    with pytest.raises(LLMOutputError, match="missing 'flags' array"):
        await llm_service.qa_review_quiz(
            "Материал", [{"id": uuid4(), "type": "true_false", "payload": _TF}]
        )


# ── narration helpers ─────────────────────────────────────────────────────────


async def test_enhance_lecture_text_passes_course_title_and_limits(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    from app.config import settings

    client = stub_llm("<think>plan</think>Расширенный текст")

    out = await llm_service.enhance_lecture_text("Черновик", course_title="Физика")

    assert out == "Расширенный текст"
    kwargs = client.calls[0]
    assert kwargs["max_tokens"] == settings.LLM_MAX_TOKENS
    assert kwargs["temperature"] == settings.LLM_TEMPERATURE
    assert "Курс: Физика" in client.user_message()
    assert "Черновик" in client.user_message()


async def test_enhance_lecture_text_without_course_title(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    client = stub_llm("Расширенный текст")

    await llm_service.enhance_lecture_text("Черновик")

    assert not client.user_message().startswith("Курс:")


async def test_refine_slide_narration_uses_the_requested_model(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    client = stub_llm("Чистая озвучка")

    out = await llm_service.refine_slide_narration("сырой текст", model="vision-model")

    assert out == "Чистая озвучка"
    assert client.calls[0]["model"] == "vision-model"
    # Thinking is off by default for this path.
    assert client.user_message().endswith("/no_think")


async def test_generate_script_from_slide_returns_narration(
    stub_llm: Callable[..., _RecordingClient],
) -> None:
    client = stub_llm("Текст озвучки слайда")

    out = await llm_service.generate_script_from_slide("Тезисы слайда")

    assert out == "Текст озвучки слайда"
    assert "Тезисы слайда" in client.user_message()
    assert client.calls[0]["model"] == llm_service.model
