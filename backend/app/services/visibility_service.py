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

**Retained-progress exception.** A student who already worked through a lesson
keeps it: the effective rule is ``(module.is_published AND lesson.is_published)
OR has_progress``, where *has_progress* is the existence of a ``LessonProgress``
row for that student — the only "the student really interacted with this lesson"
signal the system records. Such a lesson is flagged ``hidden_by_author`` in the
DTOs so the UI can mark it. This is a publish-flag exception only: soft-delete /
purge / content edits are unaffected, there are no content snapshots.
"""

from uuid import UUID

from sqlalchemy import ColumnElement, select

from app.models.course import Course
from app.models.enrollment import Enrollment, LessonProgress
from app.models.lesson import Lesson, Module
from app.schemas.course import (
    LessonShort,
    ModuleOut,
    PreviewLessonRead,
    PreviewModuleRead,
)


def lesson_progress_exists(
    lesson_id: ColumnElement[UUID] | UUID, student_id: UUID
) -> ColumnElement[bool]:
    """SQL half of the retained-progress exception, as a correlated EXISTS so
    callers can fold it into a query they already run instead of round-tripping.
    """
    return (
        select(LessonProgress.id)
        .join(Enrollment, LessonProgress.enrollment_id == Enrollment.id)
        .where(
            LessonProgress.lesson_id == lesson_id,
            Enrollment.student_id == student_id,
        )
        .exists()
    )


def lesson_hidden_by_author(module: Module, lesson: Lesson) -> bool:
    """The bare publish AND-rule: the author currently hides this lesson.
    Combined with progress this is what makes a lesson "hidden but retained"."""
    return not (bool(module.is_published) and bool(lesson.is_published))


def module_visible_to_student(module: Module, has_progressed_lesson: bool = False) -> bool:
    return bool(module.is_published) or has_progressed_lesson


def lesson_visible_to_student(module: Module, lesson: Lesson, has_progress: bool = False) -> bool:
    return not lesson_hidden_by_author(module, lesson) or has_progress


def visible_module_tree(
    course: Course, progressed_lesson_ids: frozenset[UUID] | set[UUID] = frozenset()
) -> list[ModuleOut]:
    """Prune a loaded course's modules/lessons to the student-visible chain.

    Expects ``course.modules`` (and each ``module.lessons``) eagerly loaded, and
    ``progressed_lesson_ids`` — the lessons this student has a ``LessonProgress``
    row for, which the callers already load for their own progress payload.
    Returns DTOs, so the caller never mutates the ORM relationship collections
    (which would risk delete-orphan cascades).
    """
    tree: list[ModuleOut] = []
    for module in course.modules:
        lessons: list[LessonShort] = []
        for lesson in module.lessons:
            if not lesson_visible_to_student(module, lesson, lesson.id in progressed_lesson_ids):
                continue
            lesson_out = LessonShort.model_validate(lesson)
            lesson_out.hidden_by_author = lesson_hidden_by_author(module, lesson)
            lessons.append(lesson_out)
        if not module_visible_to_student(module, bool(lessons)):
            continue
        out = ModuleOut.model_validate(module)
        out.hidden_by_author = not module.is_published
        out.lessons = lessons
        tree.append(out)
    return tree


def annotated_module_tree(course: Course) -> list[PreviewModuleRead]:
    """Owner preview ('view as student'): the FULL tree, nothing pruned, with
    each node annotated with its effective student visibility.

    Same eager-loading expectations as `visible_module_tree`.
    """
    tree: list[PreviewModuleRead] = []
    for module in course.modules:
        out = PreviewModuleRead.model_validate(module)
        out.visible_to_student = module_visible_to_student(module)
        lessons: list[PreviewLessonRead] = []
        for lesson in module.lessons:
            lesson_out = PreviewLessonRead.model_validate(lesson)
            lesson_out.visible_to_student = lesson_visible_to_student(module, lesson)
            lessons.append(lesson_out)
        out.lessons = lessons
        tree.append(out)
    return tree
