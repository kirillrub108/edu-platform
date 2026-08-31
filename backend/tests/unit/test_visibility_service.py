"""Unit tests for visibility_service — the enrolled-student visibility rule.

The rule decouples course.is_published from access: for an already-enrolled
student a lesson is visible iff module.is_published AND lesson.is_published.
course.is_published is NOT part of the rule (it gates discovery / new-enroll).
Pure in-memory ORM objects — no DB.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.course import Course
from app.models.lesson import Lesson, Module
from app.services.visibility_service import (
    lesson_hidden_by_author,
    lesson_visible_to_student,
    module_visible_to_student,
    visible_module_tree,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("module_published", "expected"), [(True, True), (False, False)])
def test_module_visible_only_when_module_published(module_published: bool, expected: bool) -> None:
    module = Module(is_published=module_published)
    assert module_visible_to_student(module) is expected


@pytest.mark.parametrize(
    ("module_published", "lesson_published", "expected"),
    [
        (True, True, True),
        (True, False, False),
        (False, True, False),
        (False, False, False),
    ],
)
def test_lesson_visible_is_module_and_lesson(
    module_published: bool, lesson_published: bool, expected: bool
) -> None:
    module = Module(is_published=module_published)
    lesson = Lesson(is_published=lesson_published)
    assert lesson_visible_to_student(module, lesson) is expected


@pytest.mark.parametrize("course_published", [True, False])
def test_course_publish_flag_does_not_affect_visibility(course_published: bool) -> None:
    """Decoupling guarantee: course.is_published never changes the outcome for an
    enrolled student — a published module/lesson stays visible either way."""
    course = Course(is_published=course_published)
    module = Module(is_published=True, course=course)
    lesson = Lesson(is_published=True, module=module)
    assert module_visible_to_student(module) is True
    assert lesson_visible_to_student(module, lesson) is True


# ── Retained-progress exception ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("module_published", "lesson_published"),
    [(True, False), (False, True), (False, False)],
)
def test_progress_keeps_an_unpublished_lesson_visible(
    module_published: bool, lesson_published: bool
) -> None:
    module = Module(is_published=module_published)
    lesson = Lesson(is_published=lesson_published)
    assert lesson_visible_to_student(module, lesson) is False
    assert lesson_visible_to_student(module, lesson, has_progress=True) is True


def test_published_lesson_is_not_flagged_hidden() -> None:
    module = Module(is_published=True)
    lesson = Lesson(is_published=True)
    assert lesson_hidden_by_author(module, lesson) is False
    assert lesson_visible_to_student(module, lesson, has_progress=True) is True


def test_module_stays_visible_when_it_holds_a_progressed_lesson() -> None:
    module = Module(is_published=False)
    assert module_visible_to_student(module) is False
    assert module_visible_to_student(module, has_progressed_lesson=True) is True


def _tree_course(module_published: bool) -> tuple[Course, Lesson, Lesson]:
    course = Course(is_published=True)
    module = Module(id=uuid4(), title="M", order=0, is_published=module_published, course=course)
    touched = Lesson(
        id=uuid4(),
        title="touched",
        order=0,
        content_type="video",
        status="draft",
        is_published=True,
        module=module,
    )
    untouched = Lesson(
        id=uuid4(),
        title="untouched",
        order=1,
        content_type="video",
        status="draft",
        is_published=True,
        module=module,
    )
    module.lessons = [touched, untouched]
    course.modules = [module]
    return course, touched, untouched


def test_tree_keeps_only_the_progressed_lesson_of_a_draft_module() -> None:
    course, touched, untouched = _tree_course(module_published=False)

    assert visible_module_tree(course) == []

    tree = visible_module_tree(course, {touched.id})
    assert len(tree) == 1
    assert tree[0].hidden_by_author is True
    assert [lesson.id for lesson in tree[0].lessons] == [touched.id]
    assert tree[0].lessons[0].hidden_by_author is True
    assert untouched.id not in {lesson.id for lesson in tree[0].lessons}


def test_tree_of_a_published_module_carries_no_hidden_flag() -> None:
    course, touched, untouched = _tree_course(module_published=True)

    tree = visible_module_tree(course, {touched.id})
    assert len(tree) == 1
    assert tree[0].hidden_by_author is False
    assert [lesson.hidden_by_author for lesson in tree[0].lessons] == [False, False]
