"""Effective student visibility for the course → module → lesson chain.

A module/lesson is shown to a student only when its entire publish chain is
published: ``course.is_published AND module.is_published AND lesson.is_published``.
Teachers/owners bypass this and see drafts. Keep the AND-rule here as the single
source of truth so callers never re-derive it inline.

Unpublishing a parent does NOT clear the children's flags — the flags are
independent; hiding is purely a read-time effect of this AND.
"""

from app.models.course import Course
from app.models.lesson import Lesson, Module
from app.schemas.course import LessonShort, ModuleOut


def module_visible_to_student(course: Course, module: Module) -> bool:
    return bool(course.is_published and module.is_published)


def lesson_visible_to_student(course: Course, module: Module, lesson: Lesson) -> bool:
    return module_visible_to_student(course, module) and bool(lesson.is_published)


def visible_module_tree(course: Course) -> list[ModuleOut]:
    """Prune a loaded course's modules/lessons to the student-visible chain.

    Expects ``course.modules`` (and each ``module.lessons``) eagerly loaded.
    Returns DTOs, so the caller never mutates the ORM relationship collections
    (which would risk delete-orphan cascades).
    """
    tree: list[ModuleOut] = []
    for module in course.modules:
        if not module_visible_to_student(course, module):
            continue
        out = ModuleOut.model_validate(module)
        out.lessons = [
            LessonShort.model_validate(lesson)
            for lesson in module.lessons
            if lesson_visible_to_student(course, module, lesson)
        ]
        tree.append(out)
    return tree
