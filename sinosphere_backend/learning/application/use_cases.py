from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from django.db import transaction
from django.utils import timezone

from learning.models import ExerciseAttempt

from learning.exercises.dto import ExerciseGenerationContext, GradeResult
from learning.exercises.exceptions import (
    ExerciseAttemptAccessDeniedError,
    ExerciseAttemptAlreadySubmittedError,
)
from learning.exercises.registry import ExerciseHandlerRegistry, registry


@dataclass(frozen=True)
class StartExerciseResult:
    attempt: ExerciseAttempt
    public_payload: dict
    metadata: dict


@dataclass(frozen=True)
class SubmitExerciseResult:
    attempt: ExerciseAttempt
    grade: GradeResult
    already_submitted: bool = False

    @property
    def dto(self) -> dict:
        feedback = self.grade.feedback or {}
        return {
            'attempt_id': self.attempt.id,
            'session_id': self.attempt.session_id,
            'is_correct': self.grade.is_fully_correct,
            'score': float(self.grade.score),
            'correct_answer': feedback.get('correct_answer', ''),
            'explanation': feedback.get('explanation', ''),
            'item_results': [
                {
                    'source_item_id': item.source_item_id,
                    'is_correct': item.is_correct,
                    'score': item.score,
                    'duration_ms': item.duration_ms,
                    'used_hint': item.used_hint,
                    'attempts_count': item.attempts_count,
                    'error_code': item.error_code,
                }
                for item in self.grade.item_results
            ],
        }


class StartExerciseUseCase:
    def __init__(self, handler_registry: ExerciseHandlerRegistry = registry):
        self.registry = handler_registry

    def execute(self, *, user, session, kind: str, config: dict, order: int, topic_id=None, word=None) -> StartExerciseResult:
        handler = self.registry.get(kind, int(config.get('handler_version', 1)))
        handler.validate_config(config)
        generated = handler.generate(
            ExerciseGenerationContext(
                user=user,
                config=config,
                topic_id=topic_id,
                session=session,
                word=word,
            )
        )

        word_id = generated.metadata.get('source_item_ids', [None])[0]
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=user,
            word_id=word_id,
            exercise_type=handler.kind,
            kind=handler.kind,
            handler_version=handler.version,
            order=order,
            public_payload={},
            grading_payload=generated.private_state,
            private_state=generated.private_state,
            status=ExerciseAttempt.STATUS_PENDING,
        )
        public_payload = {
            **generated.public_payload,
            'attempt_id': attempt.id,
            'session_id': session.id,
        }
        attempt.public_payload = public_payload
        attempt.save(update_fields=['public_payload'])
        return StartExerciseResult(attempt=attempt, public_payload=public_payload, metadata=generated.metadata)


class SubmitExerciseAnswerUseCase:
    def __init__(self, handler_registry: ExerciseHandlerRegistry = registry):
        self.registry = handler_registry

    @transaction.atomic
    def execute(
        self,
        *,
        user,
        attempt_id: int,
        answer: Any,
        duration_ms: int | None = None,
        on_graded: Callable[[ExerciseAttempt, GradeResult], None] | None = None,
    ) -> SubmitExerciseResult:
        attempt = ExerciseAttempt.objects.select_for_update().select_related('session', 'word').get(id=attempt_id)
        if attempt.user_id != user.id:
            raise ExerciseAttemptAccessDeniedError()

        if attempt.status == ExerciseAttempt.STATUS_SUBMITTED or attempt.is_correct is not None:
            return SubmitExerciseResult(
                attempt=attempt,
                grade=self._grade_from_saved_attempt(attempt),
                already_submitted=True,
            )

        kind = attempt.kind or attempt.exercise_type
        version = attempt.handler_version or 1
        handler = self.registry.get(kind, version)
        handler.validate_answer(attempt, answer)
        grade = handler.grade(attempt, answer)

        attempt.answer = answer
        attempt.result = self._result_payload(grade)
        attempt.score = Decimal(str(round(grade.score, 4)))
        attempt.is_correct = grade.is_fully_correct
        attempt.duration_ms = duration_ms
        attempt.time_spent = (duration_ms or 0) / 1000
        attempt.error_code = self._first_error_code(grade)
        attempt.status = ExerciseAttempt.STATUS_SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=[
            'answer', 'result', 'score', 'is_correct', 'duration_ms',
            'time_spent', 'error_code', 'status', 'submitted_at',
        ])

        if on_graded:
            on_graded(attempt, grade)

        attempt.session.update_status_from_attempts()
        return SubmitExerciseResult(attempt=attempt, grade=grade, already_submitted=False)

    def _grade_from_saved_attempt(self, attempt: ExerciseAttempt) -> GradeResult:
        from learning.exercises.dto import ItemGradeResult

        result = attempt.result or {}
        item_results = tuple(
            ItemGradeResult(**item)
            for item in result.get('item_results', [])
        )
        return GradeResult(
            score=float(result.get('score', attempt.score or 0)),
            is_fully_correct=bool(result.get('is_fully_correct', attempt.is_correct)),
            item_results=item_results,
            feedback=result.get('feedback', {}),
        )

    def _result_payload(self, grade: GradeResult) -> dict:
        return {
            'score': grade.score,
            'is_fully_correct': grade.is_fully_correct,
            'item_results': [
                {
                    'source_item_id': item.source_item_id,
                    'is_correct': item.is_correct,
                    'score': item.score,
                    'duration_ms': item.duration_ms,
                    'used_hint': item.used_hint,
                    'attempts_count': item.attempts_count,
                    'error_code': item.error_code,
                }
                for item in grade.item_results
            ],
            'feedback': grade.feedback,
        }

    def _first_error_code(self, grade: GradeResult) -> str:
        for item in grade.item_results:
            if item.error_code:
                return item.error_code
        return ''
