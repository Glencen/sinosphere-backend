from dictionary.models import Word

from learning.models import ExerciseAttempt

from ..base import ExerciseHandler
from ..dto import ExerciseGenerationContext, GeneratedExercise, GradeResult, ItemGradeResult
from ..exceptions import InvalidExerciseAnswerError, InvalidExerciseConfigError


def _first_translation(value):
    translations = [item.strip() for item in str(value or '').split(';') if item.strip()]
    return translations[0] if translations else str(value or '')


def _normalize(value):
    return str(value or '').strip().lower()


class MatchingHandler(ExerciseHandler):
    kind = 'matching'
    version = 1

    def validate_config(self, config: dict) -> None:
        if not isinstance(config, dict):
            raise InvalidExerciseConfigError('Exercise config must be an object.')
        items_count = config.get('items_count', 4)
        if not isinstance(items_count, int) or items_count < 2:
            raise InvalidExerciseConfigError('items_count must be an integer >= 2.')

    def generate(self, context: ExerciseGenerationContext) -> GeneratedExercise:
        self.validate_config(context.config)
        words = self._words_from_context(context)
        if len(words) < 2:
            raise InvalidExerciseConfigError('matching exercise requires at least 2 words.')

        pairs = []
        for word in words:
            pairs.append({
                'word_id': word.id,
                'chinese': word.hanzi,
                'pinyin': word.pinyin_graphic,
                'translation': _first_translation(word.translation),
            })

        public_pairs = [
            {
                'word_id': pair['word_id'],
                'chinese': pair['chinese'],
                'pinyin': pair['pinyin'],
            }
            for pair in pairs
        ]
        public_payload = {
            'type': self.kind,
            'kind': self.kind,
            'handler_version': self.version,
            'word_id': words[0].id,
            'question': 'Match Chinese words with their translations',
            'instructions': 'Match Chinese words with their translations',
            'options': [],
            'hint': '',
            'difficulty': max(word.difficulty for word in words),
            'pairs': public_pairs,
        }
        private_state = {
            'word_ids': [word.id for word in words],
            'pairs': pairs,
            'accepted_translations': [_normalize(pair['translation']) for pair in pairs],
            'normalization': 'ordered_strip_lower',
        }
        metadata = {
            'kind': self.kind,
            'handler_version': self.version,
            'source_item_ids': [word.id for word in words],
        }
        return GeneratedExercise(public_payload, private_state, metadata)

    def validate_answer(self, attempt: ExerciseAttempt, answer: dict) -> None:
        values = self._answer_values(answer)
        if not isinstance(values, list):
            raise InvalidExerciseAnswerError('matching answer must be a list of translations.')

    def grade(self, attempt: ExerciseAttempt, answer: dict) -> GradeResult:
        values = self._answer_values(answer)
        private_state = attempt.private_state or attempt.grading_payload or {}
        expected = private_state.get('accepted_translations') or []
        word_ids = private_state.get('word_ids') or []
        pairs = private_state.get('pairs') or []
        submitted = [_normalize(item) for item in values]

        item_results = []
        for index, expected_value in enumerate(expected):
            actual = submitted[index] if index < len(submitted) else ''
            is_correct = actual == expected_value
            item_results.append(ItemGradeResult(
                source_item_id=word_ids[index] if index < len(word_ids) else index,
                is_correct=is_correct,
                score=1.0 if is_correct else 0.0,
            ))

        score = (sum(item.score for item in item_results) / len(item_results)) if item_results else 0.0
        is_fully_correct = bool(item_results) and all(item.is_correct for item in item_results)
        correct_answer = '; '.join(pair.get('translation', '') for pair in pairs)
        return GradeResult(
            score=score,
            is_fully_correct=is_fully_correct,
            item_results=tuple(item_results),
            feedback={
                'correct_answer': correct_answer,
                'explanation': '' if is_fully_correct else 'Not all pairs were matched correctly.',
            },
        )

    def _answer_values(self, answer):
        if isinstance(answer, dict):
            return answer.get('translations')
        return answer

    def _words_from_context(self, context: ExerciseGenerationContext):
        if context.learning_items:
            ids = [item.item_id for item in context.learning_items]
            words_by_id = {word.id: word for word in Word.objects.filter(id__in=ids)}
            return [words_by_id[item_id] for item_id in ids if item_id in words_by_id]
        if context.word:
            return [context.word]
        return []
