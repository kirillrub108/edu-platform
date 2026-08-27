"""Degenerate-narration detection.

Asked for more words than a slide can carry, qwen-vl stops writing and loops
fullwidth CJK punctuation. The sample below is the real stored text from the
lesson that surfaced this — it is non-empty and passes every other check, so
only the letter ratio tells it apart from narration.
"""

from __future__ import annotations

import pytest

from app.services.vision_analysis import _looks_degenerate

pytestmark = pytest.mark.unit


# Verbatim from slide_texts after a 578-word budget landed on a title slide.
DEGENERATE_SAMPLE = (
    "Представьте себе ， ， ， —— “ ”， ， ： ？ ？ “ ”？\n\n"
    " ， ， —— ， ， ： ， ？ ， “ ”\n\n"
    " ， —— ， ， ， “ ” ， “ ” ， ， ，\n\n"
    " ， ， ， （ ）， “ ”\n\n "
)

HEALTHY_SAMPLE = (
    "Давайте теперь подробно разберём внешние особенности скатов, которые "
    "делают их уникальными обитателями морского дна. Обратите внимание на "
    "широкие грудные плавники — именно они позволяют скату буквально летать "
    "под водой, а не отталкиваться хвостом, как это делает большинство рыб."
)


def test_detects_the_punctuation_loop() -> None:
    assert _looks_degenerate(DEGENERATE_SAMPLE) is True


def test_healthy_narration_passes() -> None:
    assert _looks_degenerate(HEALTHY_SAMPLE) is False


def test_short_text_is_never_flagged() -> None:
    """Below the length floor the letter ratio is too noisy to judge."""
    assert _looks_degenerate("Скаты!") is False
    assert _looks_degenerate("") is False


def test_heavily_punctuated_but_real_narration_passes() -> None:
    """Dashes, quotes and numbers are normal in narration — only a collapse
    to near-zero letters counts as degenerate."""
    text = (
        "Скаты — это хрящевые рыбы (класс «хондрихтис»), и их скелет, "
        "в отличие от костных рыб, состоит из хряща: лёгкого, гибкого, прочного."
    )
    assert _looks_degenerate(text) is False


def test_digits_and_symbols_alone_are_degenerate() -> None:
    """Same collapse, different alphabet — a numeric loop is no better."""
    assert _looks_degenerate("1234567890 ... --- ??? !!! 42 %%% ### @@@ &&& 0987654321 ***") is True


def test_length_floor_is_what_spares_short_symbol_runs() -> None:
    """Just under the floor the same shape is left alone — deliberate: a few
    characters carry too little signal to call a generation failed."""
    assert _looks_degenerate("... --- ??? !!! %%% ### @@@") is False
