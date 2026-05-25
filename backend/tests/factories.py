"""Async object factories for tests. Keep them dumb: take a session, build
an instance with sensible defaults, allow overrides via kwargs, persist.

Each factory commits so the SAVEPOINT-rollback fixture catches the writes
on teardown.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.enrollment import Enrollment, LessonProgress
from app.models.lesson import (
    ContentType,
    CreationMode,
    Lesson,
    LessonStatus,
    Module,
    QuizQuestion,
)
from app.models.slide_text import SlideText
from app.models.user import User


async def make_course(
    db: AsyncSession, owner: User, **overrides: Any
) -> Course:
    defaults: dict[str, Any] = {
        "title": f"Course {uuid.uuid4().hex[:6]}",
        "description": "Test course",
        "is_published": False,
        "owner_id": owner.id,
    }
    defaults.update(overrides)
    course = Course(**defaults)
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def make_module(
    db: AsyncSession, course: Course, **overrides: Any
) -> Module:
    defaults: dict[str, Any] = {
        "title": f"Module {uuid.uuid4().hex[:6]}",
        "order": 0,
        "course_id": course.id,
    }
    defaults.update(overrides)
    module = Module(**defaults)
    db.add(module)
    await db.commit()
    await db.refresh(module)
    return module


async def make_lesson(
    db: AsyncSession, module: Module, **overrides: Any
) -> Lesson:
    defaults: dict[str, Any] = {
        "title": f"Lesson {uuid.uuid4().hex[:6]}",
        "order": 0,
        "module_id": module.id,
        "content_type": ContentType.video,
        "creation_mode": CreationMode.presentation_and_text,
        "status": LessonStatus.draft,
    }
    defaults.update(overrides)
    lesson = Lesson(**defaults)
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def make_enrollment(
    db: AsyncSession, student: User, course: Course, **overrides: Any
) -> Enrollment:
    defaults: dict[str, Any] = {"student_id": student.id, "course_id": course.id}
    defaults.update(overrides)
    enrollment = Enrollment(**defaults)
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


async def make_quiz_question(
    db: AsyncSession, lesson: Lesson, **overrides: Any
) -> QuizQuestion:
    defaults: dict[str, Any] = {
        "lesson_id": lesson.id,
        "question": f"Question {uuid.uuid4().hex[:6]}?",
        "options": ["Option A", "Option B", "Option C", "Option D"],
        "correct_index": 0,
        "order": 0,
    }
    defaults.update(overrides)
    q = QuizQuestion(**defaults)
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


async def make_slide_text(
    db: AsyncSession, lesson: Lesson, slide_number: int = 1, **overrides: Any
) -> SlideText:
    defaults: dict[str, Any] = {
        "lesson_id": lesson.id,
        "slide_number": slide_number,
        "generated_text": "Generated text for slide",
        "edited_text": None,
        "image_path": f"lessons/{lesson.id}/slides/slide_{slide_number:04d}.png",
    }
    defaults.update(overrides)
    row = SlideText(**defaults)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def make_published_course_with_lesson(
    db: AsyncSession, owner: User
) -> tuple[Course, Module, Lesson]:
    """Common scaffold: published course → 1 module → 1 video lesson."""
    course = await make_course(db, owner, is_published=True)
    module = await make_module(db, course)
    lesson = await make_lesson(db, module, status=LessonStatus.published)
    return course, module, lesson
