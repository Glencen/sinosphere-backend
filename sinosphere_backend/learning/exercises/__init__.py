from .registry import registry
from .handlers.matching import MatchingHandler
from .handlers.multiple_choice import MultipleChoiceHandler
from .handlers.translation_ru import TranslationRuHandler
from .handlers.translation_cn import TranslationCnHandler
from .handlers.writing import WritingHandler

registry.register(MultipleChoiceHandler())
registry.register(TranslationRuHandler())
registry.register(TranslationCnHandler())
registry.register(MatchingHandler())
registry.register(WritingHandler())

__all__ = ['registry']
