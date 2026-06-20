"""Effective student visibility for the module → lesson chain.

For an **already-enrolled** student a module is shown only when
``module.is_published``; a lesson only when ``module.is_published AND
lesson.is_published``. ``course.is_published`` is intentionally NOT part of this
rule: it gates course *discovery* and *new enrollment* (catalog / preview /
enroll), not the access of a student who is already enrolled. Unpublishing a
course therefore hides it from the catalog and blocks new enrollments while
preserving access for everyone already enrolled — unpublishing a *module/lesson*
stays the lever for hiding content from all students. Teachers/owners bypass this
and see drafts. Keep the AND-rule here as the single source of truth so callers
never re-derive it inline.

Unpublishing a parent does NOT clear the children's flags — the flags are
independent; hiding is purely a read-time effect of this AND.
"""

from app.models.course import Course
from app.models.lesson import Lesson, Module
from app.schemas.course import LessonShort, ModuleOut


def module_visible_to_student(module: Module) -> bool:
    return bool(module.is_published)


def lesson_visible_to_student(module: Module, lesson: Lesson) -> bool:
    return module_visible_to_student(module) and bool(lesson.is_published)


def visible_module_tree(course: Course) -> list[ModuleOut]:
    """Prune a loaded course's modules/lessons to the student-visible chain.

    Expects ``course.modules`` (and each ``module.lessons``) eagerly loaded.
    Returns DTOs, so the caller never mutates the ORM relationship collections
    (which would risk delete-orphan cascades).
    """
    tree: list[ModuleOut] = []
    for module in course.modules:
        if not module_visible_to_student(module):
            continue
        out = ModuleOut.model_validate(module)
        out.lessons = [
            LessonShort.model_validate(lesson)
            for lesson in module.lessons
            if lesson_visible_to_student(module, lesson)
        ]
        tree.append(out)
    return tree
