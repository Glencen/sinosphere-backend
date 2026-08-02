from dictionary.models import Word

from learning.models import ExerciseAttempt

from ..exercise_handler import ExerciseHandler
from ..dto import ExerciseGenerationContext, GeneratedExercise, GradeResult, ItemGradeResult
from ..exceptions import InvalidExerciseAnswerError, InvalidExerciseConfigError


def _normalize(value):
    return str(value or '').strip()


def _first_translation(value):
    translations = [item.strip() for item in str(value or '').split(';') if item.strip()]
    return translations[0] if translations else str(value or '')


class TranslationCnHandler(ExerciseHandler):
    kind = 'translation_cn'
    version = 1

    def validate_config(self, config: dict) -> None:
        if not isinstance(config, dict):
            raise InvalidExerciseConfigError('Exercise config must be an object.')

    def generate(self, context: ExerciseGenerationContext) -> GeneratedExercise:
        self.validate_config(context.config)
        word = context.word or self._word_from_items(context)
        if not word:
            raise InvalidExerciseConfigError('No word is available for translation_cn exercise.')

        prompt_translation = _first_translation(word.translation)
        public_payload = {
            'type': self.kind,
            'kind': self.kind,
            'handler_version': self.version,
            'word_id': word.id,
            'question': f'Translate into Chinese: **{prompt_translation}**',
            'options': [],
            'hint': word.pinyin_graphic,
            'difficulty': word.difficulty,
            'pairs': [],
        }
        private_state = {
            'word_id': word.id,
            'memory_card_id': context.learning_items[0].item_id if context.learning_items else None,
            'accepted_answers': [word.hanzi],
            'correct_answer': word.hanzi,
            'prompt_translation': prompt_translation,
            'normalization': 'strip_exact',
        }
        metadata = {
            'kind': self.kind,
            'handler_version': self.version,
            'source_item_ids': [context.learning_items[0].item_id] if context.learning_items else [word.id],
        }
        return GeneratedExercise(public_payload, private_state, metadata)

    def validate_answer(self, attempt: ExerciseAttempt, answer: dict) -> None:
        value = answer.get('text') if isinstance(answer, dict) else answer
        if value is None:
            raise InvalidExerciseAnswerError('translation_cn answer must contain text.')

    def grade(self, attempt: ExerciseAttempt, answer: dict) -> GradeResult:
        value = answer.get('text') if isinstance(answer, dict) else answer
        private_state = attempt.private_state or attempt.grading_payload or {}
        accepted = private_state.get('accepted_answers') or []
        correct_answer = private_state.get('correct_answer') or ''
        is_correct = _normalize(value) in accepted
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