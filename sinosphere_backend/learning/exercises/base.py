from abc import ABC, abstractmethod

from learning.models import ExerciseAttempt

from .dto import ExerciseGenerationContext, GeneratedExercise, GradeResult


class ExerciseHandler(ABC):
    kind: str
    version: int

    @abstractmethod
    def validate_config(self, config: dict) -> None:
        raise NotImplementedError

    @abstractmethod
    def generate(self, context: ExerciseGenerationContext) -> GeneratedExercise:
        raise NotImplementedError

    @abstractmethod
    def validate_answer(self, attempt: ExerciseAttempt, answer: dict) -> None:
        raise NotImplementedError

    @abstractmethod
    def grade(self, attempt: ExerciseAttempt, answer: dict) -> GradeResult:
        raise NotImplementedError
