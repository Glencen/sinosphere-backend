class FSRSRating:
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class BaseRatingPolicy:
    def rating_for(self, *, item_result, attempt, explicit_rating=None):
        if not item_result.is_correct:
            return FSRSRating.AGAIN
        if explicit_rating in (FSRSRating.HARD, FSRSRating.GOOD, FSRSRating.EASY):
            return explicit_rating
        if item_result.used_hint or item_result.attempts_count > 1:
            return FSRSRating.HARD
        return FSRSRating.GOOD


class MultipleChoiceRatingPolicy(BaseRatingPolicy):
    pass


class TranslationRatingPolicy(BaseRatingPolicy):
    pass


class MatchingRatingPolicy(BaseRatingPolicy):
    pass


class RatingPolicyRegistry:
    def __init__(self):
        self._policies = {
            'multiple_choice': MultipleChoiceRatingPolicy(),
            'translation_ru': TranslationRatingPolicy(),
            'matching': MatchingRatingPolicy(),
        }
        self._default = BaseRatingPolicy()

    def get(self, kind):
        return self._policies.get(kind, self._default)


rating_policy_registry = RatingPolicyRegistry()
