import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone

from dictionary.models import Topic, WordTag
from learning.models import DailyGoal, ExerciseAttempt, ExerciseEventConsumerReceipt
from users.models import UserExerciseHistory, UserLearningStats, UserTopicProgress

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExerciseSubmitted:
    event_id: UUID
    attempt_id: int
    user_id: int
    session_id: int
    score: float
    submitted_at: datetime


def build_exercise_submitted_event(attempt: ExerciseAttempt) -> ExerciseSubmitted:
    return ExerciseSubmitted(
        event_id=uuid4(),
        attempt_id=attempt.id,
        user_id=attempt.user_id,
        session_id=attempt.session_id,
        score=float(attempt.score or 0),
        submitted_at=attempt.submitted_at or timezone.now(),
    )


def publish_exercise_submitted(event: ExerciseSubmitted) -> None:
    logger.info(
        'exercise_submitted_event_publish event_id=%s attempt_id=%s user_id=%s session_id=%s',
        event.event_id,
        event.attempt_id,
        event.user_id,
        event.session_id,
    )
    LearningProgressConsumer().handle(event)


class LearningProgressConsumer:
    consumer_name = 'learning_progress_v1'

    def handle(self, event: ExerciseSubmitted) -> bool:
        try:
            with transaction.atomic():
                ExerciseEventConsumerReceipt.objects.create(
                    consumer_name=self.consumer_name,
                    event_id=event.event_id,
                )
                attempt = ExerciseAttempt.objects.select_related('word', 'user').get(id=event.attempt_id)
                self._record_history(attempt)
                self._update_daily_goal(attempt)
                self._update_learning_stats(attempt)
                self._update_topic_progress(attempt)
        except IntegrityError:
            logger.info(
                'exercise_submitted_event_duplicate event_id=%s consumer=%s',
                event.event_id,
                self.consumer_name,
            )
            return False

        logger.info(
            'exercise_submitted_event_consumed event_id=%s consumer=%s',
            event.event_id,
            self.consumer_name,
        )
        return True

    def _record_history(self, attempt):
        if not attempt.word_id:
            return
        UserExerciseHistory.objects.create(
            user=attempt.user,
            exercise_type=attempt.kind or attempt.exercise_type,
            word=attempt.word,
            is_correct=bool(attempt.is_correct),
            time_spent=attempt.time_spent or 0,
            difficulty=attempt.word.difficulty,
        )

    def _update_daily_goal(self, attempt):
        today = timezone.now().date()
        daily_goal, _ = DailyGoal.objects.get_or_create(
            user=attempt.user,
            date=today,
            defaults={
                'target_xp': 100,
                'target_words': 10,
                'target_time': 30,
            },
        )
        daily_goal.update_progress(
            xp=15 if attempt.is_correct else 5,
            words=0,
            time_minutes=(attempt.time_spent or 0) / 60.0,
        )

    def _update_learning_stats(self, attempt):
        stats, _ = UserLearningStats.objects.get_or_create(user=attempt.user)
        stats.update_streak()
        stats.total_exercises_completed += 1
        stats.total_time_spent += int(attempt.time_spent or 0)
        stats.xp_points += 15 if attempt.is_correct else 5
        required_xp = stats.level * 100
        while stats.xp_points >= required_xp:
            stats.level += 1
            stats.xp_points -= required_xp
            required_xp = stats.level * 100
        stats.save()

    def _update_topic_progress(self, attempt):
        if not attempt.word_id:
            return
        topics = Topic.objects.filter(tags__tagged_words__word=attempt.word).distinct()
        for topic in topics:
            progress, created = UserTopicProgress.objects.get_or_create(
                user=attempt.user,
                topic=topic,
                defaults={
                    'total_words': self._words_count_in_topic(topic),
                    'is_active': True,
                    'last_practiced': timezone.now(),
                },
            )
            total_attempts = getattr(progress, 'total_attempts', 0) + 1
            total_correct = getattr(progress, 'total_correct', 0) + (1 if attempt.is_correct else 0)
            progress.total_attempts = total_attempts
            progress.total_correct = total_correct
            progress.accuracy = (total_correct / total_attempts * 100) if total_attempts else 0
            progress.last_practiced = timezone.now()
            progress.words_learned = 0
            if progress.accuracy >= 90:
                progress.mastery_level = 5
            elif progress.accuracy >= 75:
                progress.mastery_level = 4
            elif progress.accuracy >= 60:
                progress.mastery_level = 3
            elif progress.accuracy >= 40:
                progress.mastery_level = 2
            elif progress.accuracy > 0:
                progress.mastery_level = 1
            else:
                progress.mastery_level = 0
            progress.save()

    def _words_count_in_topic(self, topic):
        tag_ids = topic.tags.values_list('id', flat=True)
        return WordTag.objects.filter(tag_id__in=tag_ids).values('word').distinct().count()