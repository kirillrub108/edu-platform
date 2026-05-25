"""Deterministic grading for all closed-form question types + aggregation.

Open-form types (short_answer / essay) are not graded here — they go through
`llm_service.grade_open_answer` and `tasks.quiz_pipeline.grade_attempt_task`.

Snapshot format:
    {"version": 1, "pointers": [{"question_id", "version", "order"}, ...]}

Snapshots store only POINTERS into the immutable, versioned `quiz_questions`
table. Routers/Celery call `quiz_resolver.resolve_snapshot[_sync]` to fetch
the actual payloads/types/weights for the pinned (id, version) pairs. This
module stays pure — it works on already-resolved questions, which keeps the
grading logic decoupled from the DB.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class GradingResult:
    awarded_score: Decimal      # 0..max_score
    max_score: Decimal
    is_correct: bool | None     # None for open-form (set later by LLM/teacher)
    needs_review: bool          # True for open-form until graded


@dataclass(frozen=True)
class ResolvedQuestion:
    """A snapshot pointer with its payload/type/weight materialized from DB.

    `order` comes from the snapshot (frozen at attempt start);
    `payload`/`type`/`weight` come from the (id, version) row, which is also
    immutable.
    """
    id: UUID
    version: int
    type: str
    payload: dict[str, Any]
    weight: Decimal
    order: int


_ZERO = Decimal("0")
_ONE = Decimal("1")


def _norm(s: Any) -> str:
    """Lower-case + collapse internal whitespace + strip — for text comparisons."""
    if s is None:
        return ""
    return " ".join(str(s).lower().split())


# ── Per-type graders ────────────────────────────────────────────────────────


def _grade_single_choice(payload: dict[str, Any], response: dict[str, Any]) -> GradingResult:
    selected = response.get("selected_index")
    correct = isinstance(selected, int) and selected == payload.get("correct_index")
    return GradingResult(
        awarded_score=_ONE if correct else _ZERO,
        max_score=_ONE,
        is_correct=bool(correct),
        needs_review=False,
    )


def _grade_multiple_choice(payload: dict[str, Any], response: dict[str, Any]) -> GradingResult:
    raw = response.get("selected_indices") or []
    if not isinstance(raw, list):
        raw = []
    selected = {i for i in raw if isinstance(i, int)}
    correct = set(payload.get("correct_indices") or [])
    if not correct:
        return GradingResult(_ZERO, _ONE, False, False)
    if not selected:
        return GradingResult(_ZERO, _ONE, False, False)
    # Jaccard with explicit max(0, …) guard so a malformed response can never
    # produce a negative score.
    inter = len(selected & correct)
    union = len(selected | correct)
    score = Decimal(inter) / Decimal(union) if union else _ZERO
    score = max(_ZERO, score)
    return GradingResult(
        awarded_score=score,
        max_score=_ONE,
        is_correct=(selected == correct),
        needs_review=False,
    )


def _grade_true_false(payload: dict[str, Any], response: dict[str, Any]) -> GradingResult:
    selected = response.get("selected")
    correct = isinstance(selected, bool) and selected == bool(payload.get("correct"))
    return GradingResult(_ONE if correct else _ZERO, _ONE, bool(correct), False)


def _grade_matching(payload: dict[str, Any], response: dict[str, Any]) -> GradingResult:
    correct_pairs = {
        (int(li), int(ri)) for li, ri in (payload.get("correct_pairs") or [])
    }
    raw = response.get("pairs") or []
    if not isinstance(raw, list):
        raw = []
    submitted = set()
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                submitted.add((int(item[0]), int(item[1])))
            except (ValueError, TypeError):
                continue
    if not correct_pairs:
        return GradingResult(_ZERO, _ONE, False, False)
    inter = len(submitted & correct_pairs)
    score = Decimal(inter) / Decimal(len(correct_pairs))
    return GradingResult(
        awarded_score=max(_ZERO, score),
        max_score=_ONE,
        is_correct=(submitted == correct_pairs),
        needs_review=False,
    )


def _grade_ordering(payload: dict[str, Any], response: dict[str, Any]) -> GradingResult:
    correct = payload.get("correct_order") or []
    submitted = response.get("order") or []
    if not isinstance(submitted, list) or len(submitted) != len(correct):
        return GradingResult(_ZERO, _ONE, False, False)
    matches = sum(1 for a, b in zip(submitted, correct, strict=False) if a == b)
    score = Decimal(matches) / Decimal(len(correct)) if correct else _ZERO
    return GradingResult(
        awarded_score=max(_ZERO, score),
        max_score=_ONE,
        is_correct=(matches == len(correct)),
        needs_review=False,
    )


def _grade_fill_blank(payload: dict[str, Any], response: dict[str, Any]) -> GradingResult:
    blanks = payload.get("blanks") or []
    case_insensitive = bool(payload.get("case_insensitive", True))
    submitted = response.get("answers") or []
    if not isinstance(submitted, list) or not blanks:
        return GradingResult(_ZERO, _ONE, False, False)

    def norm(s: Any) -> str:
        return _norm(s) if case_insensitive else " ".join(str(s).split()).strip()

    correct_count = 0
    for idx, alternatives in enumerate(blanks):
        if idx >= len(submitted):
            continue
        given = norm(submitted[idx])
        if any(norm(alt) == given for alt in alternatives):
            correct_count += 1
    score = Decimal(correct_count) / Decimal(len(blanks))
    return GradingResult(
        awarded_score=max(_ZERO, score),
        max_score=_ONE,
        is_correct=(correct_count == len(blanks)),
        needs_review=False,
    )


def _open_form_placeholder(_payload: dict[str, Any], _response: dict[str, Any]) -> GradingResult:
    # Open-form: deterministic pass marks it for LLM grading, no points yet.
    return GradingResult(
        awarded_score=_ZERO,
        max_score=_ONE,
        is_correct=None,
        needs_review=True,
    )


_GRADERS = {
    "single_choice": _grade_single_choice,
    "multiple_choice": _grade_multiple_choice,
    "true_false": _grade_true_false,
    "matching": _grade_matching,
    "ordering": _grade_ordering,
    "fill_blank": _grade_fill_blank,
    "short_answer": _open_form_placeholder,
    "essay": _open_form_placeholder,
}


def grade_question(
    question_type: str,
    payload: dict[str, Any],
    response: dict[str, Any] | None,
) -> GradingResult:
    """Dispatch a single answer to the matching grader. Missing response →
    zero score / needs_review=False (for closed) or True (for open)."""
    grader = _GRADERS.get(question_type)
    if grader is None:
        raise ValueError(f"unsupported question type: {question_type!r}")
    return grader(payload, response or {})


def is_open_type(question_type: str) -> bool:
    return question_type in ("short_answer", "essay")


# ── Attempt-level aggregation ───────────────────────────────────────────────


@dataclass(frozen=True)
class AggregateResult:
    score: Decimal      # 0..1, weighted
    passed: bool
    weight_total: Decimal


def aggregate_score(
    items: list[tuple[Decimal, Decimal, Decimal]],
    pass_threshold: Decimal,
) -> AggregateResult:
    """Weighted average across (weight, awarded, max) triples.

    Open-form questions whose `awarded` is still None are excluded by the
    caller (passes `Decimal(0)` for `awarded` and counts them as needs_review
    instead). For determinism we use Decimal throughout.
    """
    total_weight = sum((w for w, _a, _m in items), start=_ZERO)
    if total_weight == 0:
        return AggregateResult(score=_ZERO, passed=False, weight_total=_ZERO)
    weighted = _ZERO
    for w, awarded, max_score in items:
        if max_score == 0:
            continue
        ratio = (awarded / max_score) if max_score else _ZERO
        weighted += w * ratio
    score = weighted / total_weight
    if score < _ZERO:
        score = _ZERO
    elif score > _ONE:
        score = _ONE
    return AggregateResult(
        score=score,
        passed=score >= pass_threshold,
        weight_total=total_weight,
    )


# ── Snapshot helpers (pointer format) ───────────────────────────────────────

SNAPSHOT_VERSION = 1


def build_snapshot(questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a lightweight pointer snapshot from a list of current question
    rows. Each `q` dict needs `id`, `version`, `order`. Payload/weight/type
    are NOT copied — they live in the immutable quiz_questions row.
    """
    return {
        "version": SNAPSHOT_VERSION,
        "pointers": [
            {
                "question_id": str(q["id"]),
                "version": int(q["version"]),
                "order": int(q["order"]),
            }
            for q in questions
        ],
    }


def snapshot_pointers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the raw pointer list, tolerating the absence of the field."""
    return list(snapshot.get("pointers") or [])


def resolved_index(items: list[ResolvedQuestion]) -> dict[UUID, ResolvedQuestion]:
    return {q.id: q for q in items}
