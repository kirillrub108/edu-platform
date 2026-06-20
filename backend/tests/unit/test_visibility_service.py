"""Unit tests for visibility_service — the enrolled-student visibility rule.

The rule decouples course.is_published from access: for an already-enrolled
student a lesson is visible iff module.is_published AND lesson.is_published.
course.is_published is NOT part of the rule (it gates discovery / new-enroll).
Pure in-memory ORM objects — no DB.
"""

from __future__ import annotations

import pytest

from app.models.course import Course
from app.models.lesson import Lesson, Module
from app.services.visibility_service import (
    lesson_visible_to_student,
    module_visible_to_student,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("module_published", "expected"), [(True, True), (False, False)])
def test_module_visible_only_when_module_published(
    module_published: bool, expected: bool
) -> None:
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
