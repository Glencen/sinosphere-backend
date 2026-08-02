from dictionary.models import Word

from learning.models import ExerciseAttempt

from ..base import ExerciseHandler
from ..dto import ExerciseGenerationContext, GeneratedExercise, GradeResult, ItemGradeResult
from ..exceptions import InvalidExerciseAnswerError, InvalidExerciseConfigError


def _normalize(value):
    return str(value or '').strip()


def _first_translation(value):
    translations = [item.strip() for item in str(value or '').split(';') if item.strip()]
    return translations[0] if translations else str(value or '')


class WritingHandler(ExerciseHandler):
    kind = 'writing'
    version = 1

    def validate_config(self, config: dict) -> None:
        if not isinstance(config, dict):
            raise InvalidExerciseConfigError('Exercise config must be an object.')

    def generate(self, context: ExerciseGenerationContext) -> GeneratedExercise:
        self.validate_config(context.config)
        word = context.word or self._word_from_items(context)
        if not word:
            raise InvalidExerciseConfigError('No word is available for writing exercise.')

        public_payload = {
            'type': self.kind,
            'kind': self.kind,
            'handler_version': self.version,
            'word_id': word.id,
            'question': 'Practice writing the character',
            'instructions': 'Practice writing the character',
            'hanzi': word.hanzi,
            'pinyin': word.pinyin_graphic,
            'translation': _first_translation(word.translation),
            'stroke_data': {
                'character': word.hanzi,
                'stroke_count': len(word.hanzi),
                'medians': [],
            },
            'options': [],
            'hint': word.pinyin_graphic,
            'difficulty': word.difficulty,
            'pairs': [],
        }
        private_state = {
            'word_id': word.id,
            'memory_card_id': context.learning_items[0].item_id if context.learning_items else None,
            'correct_answer': word.hanzi,
            'normalization': 'strip_exact_or_ack',
        }
        metadata = {
            'kind': self.kind,
            'handler_version': self.version,
            'source_item_ids': [context.learning_items[0].item_id] if context.learning_items else [word.id],
        }
        return GeneratedExercise(public_payload, private_state, metadata)

    def validate_answer(self, attempt: ExerciseAttempt, answer: dict) -> None:
        if isinstance(answer, dict) and (answer.get('text') is not None or answer.get('completed') is not None):
            return
        if not isinstance(answer, dict) and answer is not None:
            return
        raise InvalidExerciseAnswerError('writing answer must contain text or completed flag.')

    def grade(self, attempt: ExerciseAttempt, answer: dict) -> GradeResult:
        private_state = attempt.private_state or attempt.grading_payload or {}
        correct_answer = private_state.get('correct_answer') or ''
        if isinstance(answer, dict):
            value = answer.get('text')
            completed = bool(answer.get('completed'))
        else:
            value = answer
            completed = False
        is_correct = completed or _normalize(value) == correct_answer
        score = 1.0 if is_correct else 0.0
        item = ItemGradeResult(
            source_item_id=private_state.get('memory_card_id') or private_state.get('word_id') or attempt.word_id or attempt.id,
            is_correct=is_correct,
            score=score,
        )
        return GradeResult(
            score=score,
            is_fully_correct=is_correct,
            item_results=(item,),
            feedback={
                'correct_answer': correct_answer,
                'explanation': '' if is_correct else f'Correct answer: {correct_answer}',
            },
        )

    def _word_from_items(self, context):
        if context.learning_items:
            item = context.learning_items[0]
            return Word.objects.filter(id=item.payload.get('word_id') or item.item_id).first()
        return None