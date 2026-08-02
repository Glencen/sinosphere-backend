import logging

from .base import ExerciseHandler
from .exceptions import UnknownExerciseHandlerError


logger = logging.getLogger(__name__)


class ExerciseHandlerRegistry:
    def __init__(self):
        self._handlers: dict[tuple[str, int], ExerciseHandler] = {}

    def register(self, handler: ExerciseHandler) -> None:
        key = (handler.kind, handler.version)
        if key in self._handlers:
            raise ValueError(f'Exercise handler is already registered: {handler.kind}:{handler.version}')
        self._handlers[key] = handler

    def get(self, kind: str, version: int) -> ExerciseHandler:
        key = (kind, version)
        try:
            return self._handlers[key]
        except KeyError as exc:
            raise UnknownExerciseHandlerError(f'Unknown exercise handler: {kind}:{version}') from exc

    def has(self, kind: str, version: int) -> bool:
        return (kind, version) in self._handlers


registry = ExerciseHandlerRegistry()
