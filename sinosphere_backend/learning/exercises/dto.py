from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LearningItemRef:
    item_type: str
    item_id: int | str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExerciseSpec:
    kind: str
    handler_version: int
    learning_items: tuple[LearningItemRef, ...]
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExerciseGenerationContext:
    user: Any
    config: dict = field(default_factory=dict)
    topic_id: int | None = None
    session: Any | None = None
    word: Any | None = None
    learning_items: tuple[LearningItemRef, ...] = ()


@dataclass(frozen=True)
class GeneratedExercise:
    public_payload: dict
    private_state: dict
    metadata: dict


@dataclass(frozen=True)
class ItemGradeResult:
    source_item_id: int | str
    is_correct: bool
    score: float
    duration_ms: int | None = None
    used_hint: bool = False
    attempts_count: int = 1
    error_code: str | None = None


@dataclass(frozen=True)
class GradeResult:
    score: float
    is_fully_correct: bool
    item_results: tuple[ItemGradeResult, ...]
    feedback: dict
