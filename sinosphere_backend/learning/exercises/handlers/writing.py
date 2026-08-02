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
    SUBMISSION_MODE_TEXT = 'text'
    SUBMISSION_MODE_CONFIRMATION = 'confirmation'
    SUBMISSION_MODES = {SUBMISSION_MODE_TEXT, SUBMISSION_MODE_CONFIRMATION}

    def validate_config(self, config: dict) -> None:
        if not isinstance(config, dict):
            raise InvalidExerciseConfigError('Exercise config must be an object.')
        submission_mode = config.get('submission_mode', self.SUBMISSION_MODE_CONFIRMATION)
        if submission_mode not in self.SUBMISSION_MODES:
            raise InvalidExerciseConfigError('submission_mode must be "text" or "confirmation".')

    def generate(self, context: ExerciseGenerationContext) -> GeneratedExercise:
        self.validate_config(context.config)
        word = context.word or self._word_from_items(context)
        if not word:
            raise InvalidExerciseConfigError('No word is available for writing exercise.')
        submission_mode = context.config.get('submission_mode', self.SUBMISSION_MODE_CONFIRMATION)

        public_payload = {
            'type': self.kind,
            'kind': self.kind,
            'handler_version': self.version,
            'submission_mode': submission_mode,
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
            'submission_mode': submission_mode,
            'normalization': 'strip_exact_or_ack',
        }
        metadata = {
            'kind': self.kind,
            'handler_version': self.version,
            'source_item_ids': [context.learning_items[0].item_id] if context.learning_items else [word.id],
        }
        return GeneratedExercise(public_payload, private_state, metadata)

    def validate_answer(self, attempt: ExerciseAttempt, answer: dict) -> None:
        if not isinstance(answer, dict):
            raise InvalidExerciseAnswerError('writing answer must be an object.')

        has_text = 'text' in answer
        has_completed = 'completed' in answer
        if has_text and has_completed:
            raise InvalidExerciseAnswerError('writing answer cannot contain both text and completed.')

        submission_mode = self._submission_mode(attempt)
        if submission_mode == self.SUBMISSION_MODE_TEXT:
            if not has_text or has_completed:
                raise InvalidExerciseAnswerError('writing text mode answer must contain only text.')
            if not isinstance(answer.get('text'), str):
                raise InvalidExerciseAnswerError('writing text mode answer text must be a string.')
            return

        if not has_completed or has_text:
            raise InvalidExerciseAnswerError('writing confirmation mode answer must contain only completed.')
        if answer.get('completed') is not True:
            raise InvalidExerciseAnswerError('writing confirmation mode completed must be true.')

    def grade(self, attempt: ExerciseAttempt, answer: dict) -> GradeResult:
        self.validate_answer(attempt, answer)
        private_state = attempt.private_state or attempt.grading_payload or {}
        correct_answer = private_state.get('correct_answer') or ''
        if self._submission_mode(attempt) == self.SUBMISSION_MODE_TEXT:
            value = answer.get('text')
            is_correct = _normalize(value) == correct_answer
        else:
            is_correct = True
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

    def _submission_mode(self, attempt):
        public_payload = attempt.public_payload or {}
        private_state = attempt.private_state or attempt.grading_payload or {}
        return (
            public_payload.get('submission_mode')
            or private_state.get('submission_mode')
            or self.SUBMISSION_MODE_CONFIRMATION
        )
