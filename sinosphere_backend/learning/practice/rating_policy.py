class FSRSRating:
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class BaseRatingPolicy:
    version = 1

    def rating_for(self, *, item_result, attempt, explicit_rating=None):
        if not item_result.is_correct:
            return FSRSRating.AGAIN
        if explicit_rating in (FSRSRating.HARD, FSRSRating.GOOD, FSRSRating.EASY):
            return explicit_rating
        if item_result.used_hint or item_result.attempts_count > 1:
            return FSRSRating.HARD
        return FSRSRating.GOOD


class MultipleChoiceRatingPolicy(BaseRatingPolicy):
    kind = 'multiple_choice'


class TranslationRatingPolicy(BaseRatingPolicy):
    kind = 'translation_ru'


class TranslationCnRatingPolicy(BaseRatingPolicy):
    kind = 'translation_cn'


class MatchingRatingPolicy(BaseRatingPolicy):
    kind = 'matching'


class WritingRatingPolicy(BaseRatingPolicy):
    kind = 'writing'


class RatingPolicyRegistry:
    def __init__(self):
        self._policies = {}
        self._default = BaseRatingPolicy()

    def register(self, policy):
        self._policies[policy.kind] = policy

    def get(self, kind):
        return self._policies.get(kind, self._default)


rating_policy_registry = RatingPolicyRegistry()
rating_policy_registry.register(MultipleChoiceRatingPolicy())
rating_policy_registry.register(TranslationRatingPolicy())
rating_policy_registry.register(TranslationCnRatingPolicy())
rating_policy_registry.register(MatchingRatingPolicy())
rating_policy_registry.register(WritingRatingPolicy())