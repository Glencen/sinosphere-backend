from django.utils import timezone

from dictionary.models import Word
from users.models import UserWord
from learning.exercises.dto import LearningItemRef


class PracticeSessionPlanner:
    def plan(self, *, user, requested_cards_count: int, topic_id=None, include_review=True, include_new=True, config=None):
        config = config or {}
        limit = max(1, int(requested_cards_count))
        selected = []
        selected_ids = set()

        if include_review:
            for word in self._review_words(user=user, topic_id=topic_id, limit=limit):
                if word.id not in selected_ids:
                    selected.append(self._item(word, source='review'))
                    selected_ids.add(word.id)
                if len(selected) >= limit:
                    return tuple(selected)

        if include_new and len(selected) < limit:
            for word in self._new_words(user=user, topic_id=topic_id, limit=limit * 2):
                if word.id not in selected_ids:
                    selected.append(self._item(word, source='new'))
                    selected_ids.add(word.id)
                if len(selected) >= limit:
                    break

        return tuple(selected)

    def _review_words(self, *, user, topic_id, limit):
        queryset = UserWord.objects.filter(user=user, due__lte=timezone.now()).select_related('word')
        if topic_id:
            queryset = queryset.filter(word__word_tags__tag__topic_id=topic_id).distinct()
        user_words = sorted(queryset, key=lambda item: item.get_review_urgency(), reverse=True)
        return [user_word.word for user_word in user_words[:limit]]

    def _new_words(self, *, user, topic_id, limit):
        user_word_ids = UserWord.objects.filter(user=user).values_list('word_id', flat=True)
        queryset = Word.objects.exclude(id__in=user_word_ids)
        if topic_id:
            queryset = queryset.filter(word_tags__tag__topic_id=topic_id).distinct()
        return list(queryset.order_by('difficulty', 'hanzi')[:limit])

    def _item(self, word, source):
        return LearningItemRef(
            item_type='word',
            item_id=word.id,
            payload={
                'source': source,
                'difficulty': word.difficulty,
                'material_type': 'word',
            },
        )
