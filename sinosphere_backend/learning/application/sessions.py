import logging
import random
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Avg, Count, Min, Q
from django.utils import timezone

from learning.models import AttemptMemoryCard, ExerciseAttempt, PracticeSession
from learning.exercises.registry import registry
from learning.application.composer import ExerciseComposer
from learning.application.planner import PracticeSessionPlanner
from learning.application.selection_policy import ExerciseTypeSelectionPolicy
from learning.application.use_cases import StartExerciseUseCase


logger = logging.getLogger(__name__)
TERMINAL_SESSION_STATUSES = {
    PracticeSession.STATUS_COMPLETED,
    PracticeSession.STATUS_EXPIRED,
    PracticeSession.STATUS_ABANDONED,
}


@dataclass(frozen=True)
class PracticeSessionResult:
    session: PracticeSession
    first_attempt: ExerciseAttempt | None

    @property
    def dto(self):
        return session_dto(self.session, first_attempt=self.first_attempt)


class StartPracticeSessionUseCase:
    def __init__(self, *, planner=None, composer=None, handler_registry=registry, rng=None):
        self.planner = planner or PracticeSessionPlanner()
        self.handler_registry = handler_registry
        self.rng = rng or random.Random()
        self.composer = composer or ExerciseComposer(
            selection_policy=ExerciseTypeSelectionPolicy(handler_registry=handler_registry, rng=self.rng)
        )
        self.start_exercise = StartExerciseUseCase(handler_registry=handler_registry)

    @transaction.atomic
    def execute(self, *, user, config):
        requested_cards_count = max(1, min(int(config.get('requested_cards_count') or config.get('count') or 10), 100))
        topic_id = config.get('topic_id')
        allowed_types = tuple(config.get('exercise_types') or config.get('allowed_types') or ()) or None
        include_review = config.get('includeReview', config.get('include_review', True))
        include_new = config.get('includeNew', config.get('include_new', True))
        expires_in_minutes = int(config.get('expires_in_minutes') or 24 * 60)

        logger.info('practice_session_create_requested user_id=%s requested_cards_count=%s topic_id=%s', user.id, requested_cards_count, topic_id)
        session = PracticeSession.objects.create(
            user=user,
            topic_id=topic_id or None,
            session_type=config.get('type', 'mixed'),
            requested_count=requested_cards_count,
            requested_cards_count=requested_cards_count,
            generation_config=config,
            settings=config,
            status=PracticeSession.STATUS_IN_PROGRESS,
            expires_at=timezone.now() + timedelta(minutes=expires_in_minutes),
        )

        learning_items = self.planner.plan(
            user=user,
            requested_cards_count=requested_cards_count,
            topic_id=topic_id,
            include_review=include_review,
            include_new=include_new,
            config=config,
        )
        specs = self.composer.compose(learning_items=learning_items, allowed_types=allowed_types)

        first_attempt = None
        for position, spec in enumerate(specs):
            started = self.start_exercise.execute(
                user=user,
                session=session,
                kind=spec.kind,
                config={
                    'handler_version': spec.handler_version,
                    **spec.metadata,
                    **config.get('handler_config', {}),
                },
                order=position,
                position=position,
                topic_id=topic_id,
                learning_items=spec.learning_items,
            )
            if first_attempt is None:
                first_attempt = started.attempt

        session.generated_exercises_count = len(specs)
        if not specs:
            session.mark_completed()
            session.generated_exercises_count = 0
            session.save(update_fields=['generated_exercises_count'])
        else:
            session.save(update_fields=['generated_exercises_count'])

        logger.info('practice_session_created session_id=%s user_id=%s learning_items=%s visual_exercises=%s', session.id, user.id, requested_cards_count, session.generated_exercises_count)
        return PracticeSessionResult(session=session, first_attempt=first_attempt)


class GetPracticeSessionUseCase:
    def execute(self, *, user, session_id):
        session = PracticeSession.objects.prefetch_related('attempts').get(id=session_id, user=user)
        if session.is_expired:
            session.mark_expired()
        return session


class GetCurrentExerciseUseCase:
    def execute(self, *, user, session_id):
        session = PracticeSession.objects.get(id=session_id, user=user)
        if session.is_expired:
            session.mark_expired()
            return session, None
        if session.status in TERMINAL_SESSION_STATUSES:
            return session, None
        attempt = session.attempts.filter(is_correct__isnull=True).order_by('position', 'order').first()
        return session, attempt


class GetPracticeSessionSummaryUseCase:
    def execute(self, *, user, session_id):
        session = PracticeSession.objects.prefetch_related('attempts').get(id=session_id, user=user)
        if session.is_expired:
            session.mark_expired()
        return session_summary(session)


def session_progress(session):
    total = session.generated_exercises_count or session.attempts.count()
    completed = session.attempts.filter(is_correct__isnull=False).count()
    return {
        'completed_exercises_count': completed,
        'visual_exercises_count': total,
        'learning_items_count': session.requested_cards_count,
        'remaining_exercises_count': max(total - completed, 0),
        'percentage': round((completed / total) * 100, 1) if total else 100,
    }


def session_summary(session):
    attempts = list(session.attempts.all())
    submitted_attempts = [attempt for attempt in attempts if attempt.is_correct is not None]
    attempts_summary = session.attempts.aggregate(
        visual_exercises_count=Count('id'),
        completed_exercises_count=Count('id', filter=Q(is_correct__isnull=False)),
        correct_exercises_count=Count('id', filter=Q(is_correct=True)),
        incorrect_exercises_count=Count('id', filter=Q(is_correct=False)),
        average_score=Avg('score', filter=Q(is_correct__isnull=False)),
    )
    item_total = 0
    item_correct = 0
    for attempt in submitted_attempts:
        result = attempt.result or {}
        item_results = result.get('item_results') or []
        item_total += len(item_results)
        item_correct += sum(1 for item in item_results if item.get('is_correct') is True)

    link_summary = AttemptMemoryCard.objects.filter(
        attempt__session=session,
        attempt__is_correct__isnull=False,
    ).aggregate(
        again=Count('id', filter=Q(fsrs_rating=1)),
        hard=Count('id', filter=Q(fsrs_rating=2)),
        good=Count('id', filter=Q(fsrs_rating=3)),
        easy=Count('id', filter=Q(fsrs_rating=4)),
        next_review_at=Min('memory_card__due_at'),
    )
    review_counts = {
        'again': link_summary['again'] or 0,
        'hard': link_summary['hard'] or 0,
        'good': link_summary['good'] or 0,
        'easy': link_summary['easy'] or 0,
    }
    next_review_at = link_summary['next_review_at']

    started_at = session.started_at
    completed_at = session.completed_at
    last_submitted_at = max((attempt.submitted_at for attempt in submitted_attempts if attempt.submitted_at), default=None)
    summary_end = completed_at or last_submitted_at
    duration_ms = None
    if started_at and summary_end:
        duration_ms = max(0, int((summary_end - started_at).total_seconds() * 1000))

    average_score = attempts_summary['average_score']
    return {
        'session_id': session.id,
        'status': session.status,
        'started_at': started_at,
        'completed_at': completed_at,
        'duration_ms': duration_ms,
        'learning_items_count': session.requested_cards_count,
        'visual_exercises_count': attempts_summary['visual_exercises_count'] or 0,
        'completed_exercises_count': attempts_summary['completed_exercises_count'] or 0,
        'correct_exercises_count': attempts_summary['correct_exercises_count'] or 0,
        'incorrect_exercises_count': attempts_summary['incorrect_exercises_count'] or 0,
        'average_score': round(float(average_score), 4) if average_score is not None else None,
        'item_results': {
            'total': item_total,
            'correct': item_correct,
            'incorrect': max(item_total - item_correct, 0),
        },
        'reviews': review_counts,
        'next_review_at': next_review_at,
    }


def exercise_attempt_result_dto(attempt):
    base = {
        'attempt_id': attempt.id,
        'session_id': attempt.session_id,
        'status': attempt.status,
        'kind': attempt.kind or attempt.exercise_type,
        'handler_version': attempt.handler_version,
        'submitted_at': attempt.submitted_at,
        'session_status': attempt.session.status,
        'progress': session_progress(attempt.session),
    }
    if attempt.status != ExerciseAttempt.STATUS_SUBMITTED or attempt.is_correct is None:
        return base

    result = attempt.result or {}
    feedback = result.get('feedback') or {}
    return {
        **base,
        'is_correct': bool(attempt.is_correct),
        'score': float(result.get('score', attempt.score or 0)),
        'correct_answer': feedback.get('correct_answer', ''),
        'explanation': feedback.get('explanation', ''),
        'item_results': result.get('item_results') or [],
    }


def public_attempt_payload(attempt):
    if not attempt:
        return None
    return {
        **(attempt.public_payload or {}),
        'attempt_id': attempt.id,
        'session_id': attempt.session_id,
        'position': attempt.position,
        'kind': attempt.kind or attempt.exercise_type,
        'handler_version': attempt.handler_version,
    }


def session_dto(session, *, first_attempt=None):
    if session.status in TERMINAL_SESSION_STATUSES:
        current = None
    else:
        current = first_attempt or session.attempts.filter(is_correct__isnull=True).order_by('position', 'order').first()
    return {
        'session_id': session.id,
        'status': session.status,
        'learning_items_count': session.requested_cards_count,
        'visual_exercises_count': session.generated_exercises_count or session.attempts.count(),
        'first_attempt_id': first_attempt.id if first_attempt else (current.id if current else None),
        'current_attempt_id': current.id if current else None,
        'current_exercise': public_attempt_payload(current),
        'progress': session_progress(session),
        'generation_config': session.generation_config,
        'started_at': session.started_at,
        'completed_at': session.completed_at,
        'expires_at': session.expires_at,
    }
