import asyncio
import logging
from uuid import UUID

from app.celery_app import celery_app
from app.models.lesson import Lesson
from app.services.llm_service import LLMOutputError, llm_service
from app.services.quiz_service import (
    EmptyMaterialError,
    assemble_material_sync,
    replace_questions_sync,
)
from app.tasks.video_pipeline import SyncSession

logger = logging.getLogger(__name__)


def _clear_task_id(session, lesson_id: UUID) -> None:
    lesson = session.get(Lesson, lesson_id)
    if lesson is not None:
        lesson.quiz_task_id = None
        session.commit()


@celery_app.task(bind=True, name="generate_quiz", queue="vision")
def generate_quiz_task(
    self,
    lesson_id: str,
    num_questions: int,
    num_options: int,
) -> dict:
    lesson_uuid = UUID(lesson_id)

    def _progress(step: str, done: int, total: int) -> None:
        self.update_state(
            state="PROGRESS",
            meta={"step": step, "done": done, "total": total},
        )

    with SyncSession() as session:
        try:
            _progress("material", 0, 3)
            material = assemble_material_sync(session, lesson_uuid)

            _progress("llm", 1, 3)
            questions = asyncio.run(
                llm_service.generate_quiz(
                    material,
                    num_questions=num_questions,
                    num_options=num_options,
                )
            )

            _progress("persist", 2, 3)
            replace_questions_sync(session, lesson_uuid, questions)
            _clear_task_id(session, lesson_uuid)
            session.commit()

            _progress("persist", 3, 3)
            return {"status": "ok", "total": len(questions)}

        except EmptyMaterialError as exc:
            session.rollback()
            _clear_task_id(session, lesson_uuid)
            logger.warning("quiz generation: empty material for lesson %s", lesson_id)
            return {"status": "error", "error": str(exc)}
        except LLMOutputError as exc:
            session.rollback()
            _clear_task_id(session, lesson_uuid)
            logger.error("quiz generation: LLM output invalid: %s", exc)
            return {"status": "error", "error": str(exc)}
        except Exception as exc:
            session.rollback()
            _clear_task_id(session, lesson_uuid)
            logger.exception("quiz generation failed for lesson %s", lesson_id)
            return {"status": "error", "error": str(exc)}
