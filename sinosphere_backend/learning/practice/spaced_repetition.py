import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from django.utils import timezone

from learning.models import FSRSSchedulerProfile, MemoryCard


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpacedRepetitionReviewResult:
    previous_state: dict
    resulting_state: dict
    due_at: datetime
    fsrs_log: dict
    scheduler_version: str
    parameter_set_version: int


class SpacedRepetitionService(Protocol):
    def review(self, *, card: MemoryCard, rating: int, reviewed_at: datetime, duration_ms: int | None) -> SpacedRepetitionReviewResult:
        ...


class FSRSService:
    scheduler_version = 'fsrs-py-v1'

    def review(self, *, card: MemoryCard, rating: int, reviewed_at: datetime, duration_ms: int | None) -> SpacedRepetitionReviewResult:
        reviewed_at = self._aware(reviewed_at)
        profile = self._active_profile(card.user_id)
        previous_state = dict(card.fsrs_state or {})

        try:
            result = self._review_with_library(card, rating, reviewed_at, duration_ms, profile)
        except Exception as exc:
            result = self._fallback_review(card, rating, reviewed_at, previous_state, profile, str(exc))

        return result

    def _review_with_library(self, card, rating, reviewed_at, duration_ms, profile):
        from fsrs import Card, Rating, Scheduler, State

        previous_state = dict(card.fsrs_state or {})
        state_value = previous_state.get('state', 1)
        try:
            fsrs_state = State(state_value)
        except Exception:
            fsrs_state = State.Learning

        fsrs_card = Card(
            card_id=card.id,
            due=card.due_at,
            stability=previous_state.get('stability'),
            difficulty=previous_state.get('difficulty'),
            state=fsrs_state,
            last_review=card.last_review_at,
            step=previous_state.get('step'),
        )
        scheduler = self._scheduler(profile)
        updated_card, review_log = scheduler.review_card(
            fsrs_card,
            Rating(int(rating)),
            review_datetime=reviewed_at,
            review_duration=duration_ms,
        )
        resulting_state = self._state_from_card(updated_card)
        return SpacedRepetitionReviewResult(
            previous_state=previous_state,
            resulting_state=resulting_state,
            due_at=self._aware(updated_card.due),
            fsrs_log=self._review_log_payload(review_log),
            scheduler_version=self.scheduler_version,
            parameter_set_version=profile.version,
        )

    def _fallback_review(self, card, rating, reviewed_at, previous_state, profile, error):
        interval_days = {1: 0, 2: 1, 3: 3, 4: 7}.get(int(rating), 1)
        due_at = reviewed_at + (timedelta(minutes=10) if interval_days == 0 else timedelta(days=interval_days))
        reps = int(previous_state.get('reps', 0)) + 1
        lapses = int(previous_state.get('lapses', 0)) + (1 if int(rating) == 1 else 0)
        resulting_state = {
            **previous_state,
            'state': 1 if int(rating) == 1 else 2,
            'reps': reps,
            'lapses': lapses,
            'last_rating': int(rating),
        }
        return SpacedRepetitionReviewResult(
            previous_state=previous_state,
            resulting_state=resulting_state,
            due_at=due_at,
            fsrs_log={'fallback': True, 'error': error},
            scheduler_version=self.scheduler_version,
            parameter_set_version=profile.version,
        )

    def _scheduler(self, profile):
        from fsrs import Scheduler

        if profile.parameters:
            return Scheduler(parameters=tuple(profile.parameters))
        return Scheduler()

    def _active_profile(self, user_id):
        profile = FSRSSchedulerProfile.objects.filter(user_id=user_id, is_active=True).order_by('-version').first()
        if profile:
            return profile
        profile = FSRSSchedulerProfile.objects.filter(user__isnull=True, is_active=True).order_by('-version').first()
        if profile:
            return profile
        return FSRSSchedulerProfile.objects.create(user=None, version=1, is_active=True)

    def _state_from_card(self, card):
        state = card.state.value if hasattr(card.state, 'value') else card.state
        return {
            'state': state,
            'stability': card.stability,
            'difficulty': card.difficulty,
            'step': card.step,
        }

    def _review_log_payload(self, review_log):
        payload = {}
        for key in ('rating', 'scheduled_days', 'elapsed_days', 'review'):
            if hasattr(review_log, key):
                value = getattr(review_log, key)
                payload[key] = value.value if hasattr(value, 'value') else value
        return payload

    def _aware(self, value):
        if value is None:
            return timezone.now()
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value
