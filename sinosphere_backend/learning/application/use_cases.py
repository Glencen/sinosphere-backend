import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from django.db import transaction
from django.utils import timezone

from learning.models import AttemptMemoryCard, ExerciseAttempt, MemoryCard, MemoryReview

from learning.exercises.dto import ExerciseGenerationContext, GradeResult, LearningItemRef
from learning.exercises.exceptions import (
    ExerciseAttemptAccessDeniedError,
    ExerciseAttemptAlreadySubmittedError,
    ExerciseAttemptExpiredError,
)
from learning.exercises.registry import ExerciseHandlerRegistry, registry
from learning.application.rating_policy import rating_policy_registry
from learning.application.spaced_repetition import FSRSService
from learning.application.events import build_exercise_submitted_event, publish_exercise_submitted


logger = logging.getLogger(__name__)


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

    def execute(self, *, user, session, kind: str, config: dict, order: int, topic_id=None, word=None, position=None, learning_items=()) -> StartExerciseResult:
        handler = self.registry.get(kind, int(config.get('handler_version', 1)))
        handler.validate_config(config)
        generated = handler.generate(
            ExerciseGenerationContext(
                user=user,
                config=config,
                topic_id=topic_id,
                session=session,
                word=word,
                learning_items=tuple(learning_items or ()),
            )
        )

        source_item_ids = generated.metadata.get('source_item_ids', [None])
        first_item = (learning_items or [None])[0] if (learning_items or None) else None
        word_id = generated.public_payload.get('word_id') or (first_item.payload.get('word_id') if first_item else None)
        attempt_position = order if position is None else position
        item_payload = [
            {'item_type': item.item_type, 'item_id': item.item_id, 'payload': item.payload}
            for item in (learning_items or ())
        ] or [{'item_type': 'word', 'item_id': item_id, 'payload': {}} for item_id in source_item_ids if item_id is not None]
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=user,
            word_id=word_id,
            exercise_type=handler.kind,
            kind=handler.kind,
            handler_version=handler.version,
            order=order,
            position=attempt_position,
            learning_items=item_payload,
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
        self._create_memory_card_links(attempt, learning_items or ())
        return StartExerciseResult(attempt=attempt, public_payload=public_payload, metadata=generated.metadata)

    def _create_memory_card_links(self, attempt, learning_items):
        logger.info(
            'exercise_attempt_generated session_id=%s user_id=%s kind=%s attempt_id=%s',
            attempt.session_id,
            attempt.user_id,
            attempt.kind or attempt.exercise_type,
            attempt.id,
        )
        links = []
        for position, item in enumerate(learning_items):
            if item.item_type != 'memory_card':
                continue
            links.append(AttemptMemoryCard(
                attempt=attempt,
                memory_card_id=item.item_id,
                position=position,
            ))
        if links:
            AttemptMemoryCard.objects.bulk_create(links)


class SubmitExerciseAnswerUseCase:
    def __init__(self, handler_registry: ExerciseHandlerRegistry = registry, spaced_repetition_service=None, rating_policies=None):
        self.registry = handler_registry
        self.spaced_repetition_service = spaced_repetition_service or FSRSService()
        self.rating_policies = rating_policies or rating_policy_registry

    def execute(
        self,
        *,
        user,
        attempt_id: int,
        answer: Any,
        duration_ms: int | None = None,
        on_graded: Callable[[ExerciseAttempt, GradeResult], None] | None = None,
    ) -> SubmitExerciseResult:
        pre_attempt = ExerciseAttempt.objects.select_related('session').get(id=attempt_id)
        if pre_attempt.user_id != user.id:
            raise ExerciseAttemptAccessDeniedError()
        if pre_attempt.session.is_expired:
            pre_attempt.session.mark_expired()
            pre_attempt.status = ExerciseAttempt.STATUS_EXPIRED
            pre_attempt.save(update_fields=['status'])
            raise ExerciseAttemptExpiredError()

        with transaction.atomic():
            attempt = ExerciseAttempt.objects.select_for_update().select_related('session', 'word').get(id=attempt_id)
            if attempt.user_id != user.id:
                raise ExerciseAttemptAccessDeniedError()

            if attempt.status == ExerciseAttempt.STATUS_SUBMITTED or attempt.is_correct is not None:
                logger.info('exercise_submit_idempotent attempt_id=%s user_id=%s', attempt.id, user.id)
                return SubmitExerciseResult(
                    attempt=attempt,
                    grade=self._grade_from_saved_attempt(attempt),
                    already_submitted=True,
                )

            kind = attempt.kind or attempt.exercise_type
            version = attempt.handler_version if attempt.handler_version is not None else 1
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

            self._review_memory_cards(attempt=attempt, grade=grade, duration_ms=duration_ms)
            event = build_exercise_submitted_event(attempt)
            transaction.on_commit(lambda event=event: publish_exercise_submitted(event))
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

    def _review_memory_cards(self, *, attempt, grade, duration_ms):
        links_by_card_id = {
            link.memory_card_id: link
            for link in attempt.memory_card_links.select_related('memory_card').all()
        }
        if not links_by_card_id:
            return

        card_ids = sorted(links_by_card_id.keys())
        cards = list(MemoryCard.objects.select_for_update().filter(id__in=card_ids).order_by('id'))
        item_results = {str(item.source_item_id): item for item in grade.item_results}
        item_results.update({item.source_item_id: item for item in grade.item_results})
        policy = self.rating_policies.get(attempt.kind or attempt.exercise_type)
        reviewed_at = timezone.now()

        for card in cards:
            link = links_by_card_id[card.id]
            item_result = item_results.get(card.id) or item_results.get(str(card.id))
            if item_result is None:
                continue
            if MemoryReview.objects.filter(memory_card=card, exercise_attempt=attempt).exists():
                continue

            rating = policy.rating_for(item_result=item_result, attempt=attempt)
            review_result = self.spaced_repetition_service.review(
                card=card,
                rating=rating,
                reviewed_at=reviewed_at,
                duration_ms=duration_ms,
            )
            card.fsrs_state = review_result.resulting_state
            card.due_at = review_result.due_at
            card.last_review_at = reviewed_at
            card.scheduler_version = review_result.scheduler_version
            card.parameter_set_version = review_result.parameter_set_version
            card.save(update_fields=[
                'fsrs_state', 'due_at', 'last_review_at',
                'scheduler_version', 'parameter_set_version',
            ])
            MemoryReview.objects.create(
                memory_card=card,
                exercise_attempt=attempt,
                rating=rating,
                reviewed_at=reviewed_at,
                duration_ms=duration_ms,
                previous_state=review_result.previous_state,
                resulting_state=review_result.resulting_state,
                fsrs_log=review_result.fsrs_log,
                scheduler_version=review_result.scheduler_version,
                parameter_set_version=review_result.parameter_set_version,
            )
            link.is_correct = item_result.is_correct
            link.score = Decimal(str(round(item_result.score, 4)))
            link.duration_ms = item_result.duration_ms if item_result.duration_ms is not None else duration_ms
            link.fsrs_rating = rating
            link.error_code = item_result.error_code or ''
            link.save(update_fields=['is_correct', 'score', 'duration_ms', 'fsrs_rating', 'error_code'])
