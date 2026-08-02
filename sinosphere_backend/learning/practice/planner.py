from django.utils import timezone

from dictionary.models import Word
from learning.exercises.dto import LearningItemRef
from learning.models import FSRSSchedulerProfile, MemoryCard


class PracticeSessionPlanner:
    DEFAULT_DIRECTION = MemoryCard.DIRECTION_CN_TO_RU

    def plan(self, *, user, requested_cards_count: int, topic_id=None, include_review=True, include_new=True, config=None):
        config = config or {}
        limit = max(1, int(requested_cards_count))
        direction = config.get('direction') or self.DEFAULT_DIRECTION
        selected = []
        selected_ids = set()

        if include_review:
            for card in self._due_cards(user=user, topic_id=topic_id, direction=direction, limit=limit):
                selected.append(self._item(card, source='due'))
                selected_ids.add(card.id)
                if len(selected) >= limit:
                    return tuple(selected)

        if include_new and len(selected) < limit:
            new_limit = min(limit - len(selected), self._new_cards_limit(user, config))
            for card in self._new_cards(user=user, topic_id=topic_id, direction=direction, limit=new_limit):
                if card.id in selected_ids:
                    continue
                selected.append(self._item(card, source='new'))
                selected_ids.add(card.id)
                if len(selected) >= limit:
                    break

        return tuple(selected)

    def _due_cards(self, *, user, topic_id, direction, limit):
        queryset = MemoryCard.objects.filter(user=user, direction=direction, due_at__lte=timezone.now()).select_related('learning_item')
        if topic_id:
            queryset = queryset.filter(learning_item__word_tags__tag__topic_id=topic_id).distinct()
        return list(queryset.order_by('due_at', 'id')[:limit])

    def _new_cards(self, *, user, topic_id, direction, limit):
        if limit <= 0:
            return []
        existing_word_ids = MemoryCard.objects.filter(user=user, direction=direction).values_list('learning_item_id', flat=True)
        queryset = Word.objects.exclude(id__in=existing_word_ids)
        if topic_id:
            queryset = queryset.filter(word_tags__tag__topic_id=topic_id).distinct()
        words = list(queryset.order_by('difficulty', 'hanzi')[:limit])
        cards = []
        now = timezone.now()
        for word in words:
            card, _ = MemoryCard.objects.get_or_create(
                user=user,
                learning_item=word,
                direction=direction,
                defaults={
                    'due_at': now,
                    'scheduler_version': 'fsrs-py-v1',
                    'parameter_set_version': self._active_profile_version(user),
                },
            )
            cards.append(card)
        return cards

    def _new_cards_limit(self, user, config):
        configured = config.get('new_cards_limit')
        if configured is not None:
            return max(0, int(configured))
        profile = FSRSSchedulerProfile.objects.filter(user=user, is_active=True).order_by('-version').first()
        if profile:
            return int(config.get('new_cards_per_session', 10))
        return int(config.get('new_cards_per_session', 10))

    def _active_profile_version(self, user):
        profile = FSRSSchedulerProfile.objects.filter(user=user, is_active=True).order_by('-version').first()
        if profile:
            return profile.version
        profile = FSRSSchedulerProfile.objects.filter(user__isnull=True, is_active=True).order_by('-version').first()
        return profile.version if profile else 1

    def _item(self, card, source):
        word = card.learning_item
        return LearningItemRef(
            item_type='memory_card',
            item_id=card.id,
            payload={
                'source': source,
                'word_id': word.id,
                'direction': card.direction,
                'difficulty': word.difficulty,
                'material_type': 'word',
            },
        )
