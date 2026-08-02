from .registry import registry
from .handlers.multiple_choice import MultipleChoiceHandler

registry.register(MultipleChoiceHandler())

__all__ = ['registry']
