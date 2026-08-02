import random

from learning.practice.handler_versions import active_handler_version


class ExerciseTypeSelectionPolicy:
    DEFAULT_ALLOWED_TYPES = ('multiple_choice', 'translation_ru', 'translation_cn', 'matching', 'writing')

    def __init__(self, *, handler_registry, rng=None):
        self.handler_registry = handler_registry
        self.rng = rng or random.Random()

    def select(self, *, learning_item, allowed_types=None, recent_types=(), remaining_items_count=1):
        allowed = tuple(allowed_types or self.DEFAULT_ALLOWED_TYPES)
        candidates = [
            kind for kind in allowed
            if self.handler_registry.has(kind, active_handler_version(kind)) and self._is_supported(kind, learning_item, remaining_items_count)
        ]
        if not candidates:
            candidates = [kind for kind in self.DEFAULT_ALLOWED_TYPES if self.handler_registry.has(kind, active_handler_version(kind))]

        weights = [self._weight(kind, learning_item, recent_types, remaining_items_count) for kind in candidates]
        return self.rng.choices(candidates, weights=weights, k=1)[0]

    def _is_supported(self, kind, learning_item, remaining_items_count):
        requirements = {
            'multiple_choice': lambda: learning_item.item_type in ('word', 'memory_card'),
            'translation_ru': lambda: learning_item.item_type in ('word', 'memory_card'),
            'matching': lambda: learning_item.item_type in ('word', 'memory_card') and remaining_items_count >= 2,
            'translation_cn': lambda: learning_item.item_type in ('word', 'memory_card'),
            'writing': lambda: learning_item.item_type in ('word', 'memory_card'),
        }
        return requirements.get(kind, lambda: False)()

    def _weight(self, kind, learning_item, recent_types, remaining_items_count):
        base = {
            'multiple_choice': 3,
            'translation_ru': 3,
            'matching': 2 if remaining_items_count >= 2 else 0,
            'translation_cn': 2,
            'writing': 1,
        }.get(kind, 1)
        recent_penalty = recent_types.count(kind)
        difficulty = learning_item.payload.get('difficulty') or 1
        difficulty_bonus = 1 if kind == 'multiple_choice' and difficulty <= 2 else 0
        return max(1, base + difficulty_bonus - recent_penalty)
