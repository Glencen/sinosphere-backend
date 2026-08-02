from .registry import registry
from .handlers.matching import MatchingHandler
from .handlers.multiple_choice import MultipleChoiceHandler
from .handlers.translation_ru import TranslationRuHandler

registry.register(MultipleChoiceHandler())
registry.register(TranslationRuHandler())
registry.register(MatchingHandler())

__all__ = ['registry']
