import random
import secrets

from dictionary.models import Word

from learning.models import ExerciseAttempt

from ..exercise_handler import ExerciseHandler
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
            'memory_card_ids': [item.item_id for item in context.learning_items] if context.learning_items else [word.id for word in words],
            'pairs': pairs,
            'accepted_translations': [_normalize(pair['translation']) for pair in pairs],
            'normalization': 'ordered_strip_lower',
        }
        metadata = {
            'kind': self.kind,
            'handler_version': self.version,
            'source_item_ids': [item.item_id for item in context.learning_items] if context.learning_items else [word.id for word in words],
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
        memory_card_ids = private_state.get('memory_card_ids') or word_ids
        pairs = private_state.get('pairs') or []
        submitted = [_normalize(item) for item in values]

        item_results = []
        for index, expected_value in enumerate(expected):
            actual = submitted[index] if index < len(submitted) else ''
            is_correct = actual == expected_value
            item_results.append(ItemGradeResult(
                source_item_id=memory_card_ids[index] if index < len(memory_card_ids) else index,
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
            ids = [item.payload.get('word_id') or item.item_id for item in context.learning_items]
            words_by_id = {word.id: word for word in Word.objects.filter(id__in=ids)}
            return [words_by_id[item_id] for item_id in ids if item_id in words_by_id]
        if context.word:
            return [context.word]
        return []


class MatchingHandlerV2(MatchingHandler):
    version = 2

    def generate(self, context: ExerciseGenerationContext) -> GeneratedExercise:
        self.validate_config(context.config)
        words = self._words_from_context(context)
        if len(words) < 2:
            raise InvalidExerciseConfigError('matching exercise requires at least 2 words.')

        source_item_ids = [
            item.item_id
            for item in context.learning_items
        ] if context.learning_items else [word.id for word in words]

        left_items = []
        right_items = []
        correct_matches = {}
        left_item_sources = {}
        right_item_sources = {}

        used_ids = set()
        for index, word in enumerate(words):
            left_id = self._public_id('left', used_ids)
            right_id = self._public_id('right', used_ids)
            translation = _first_translation(word.translation)
            source_item_id = source_item_ids[index] if index < len(source_item_ids) else word.id

            left_items.append({
                'id': left_id,
                'chinese': word.hanzi,
                'pinyin': word.pinyin_graphic,
            })
            right_items.append({
                'id': right_id,
                'text': translation,
            })
            correct_matches[left_id] = right_id
            left_item_sources[left_id] = source_item_id
            right_item_sources[right_id] = source_item_id

        random.SystemRandom().shuffle(right_items)

        public_payload = {
            'type': self.kind,
            'kind': self.kind,
            'handler_version': self.version,
            'question': 'Match Chinese words with their translations',
            'instructions': 'Match Chinese words with their translations',
            'hint': '',
            'difficulty': max(word.difficulty for word in words),
            'left_items': left_items,
            'right_items': right_items,
        }
        private_state = {
            'correct_matches': correct_matches,
            'left_item_sources': left_item_sources,
            'right_item_sources': right_item_sources,
            'left_ids': [item['id'] for item in left_items],
            'right_ids': [item['id'] for item in right_items],
            'correct_answer': self._correct_answer(words),
        }
        metadata = {
            'kind': self.kind,
            'handler_version': self.version,
            'source_item_ids': source_item_ids,
        }
        return GeneratedExercise(public_payload, private_state, metadata)

    def validate_answer(self, attempt: ExerciseAttempt, answer: dict) -> None:
        matches = self._answer_matches(answer)
        if not isinstance(matches, dict):
            raise InvalidExerciseAnswerError('matching:2 answer must contain a matches object.')

        private_state = attempt.private_state or attempt.grading_payload or {}
        expected_left_ids = set(private_state.get('left_ids') or private_state.get('correct_matches', {}).keys())
        expected_right_ids = set(private_state.get('right_ids') or private_state.get('correct_matches', {}).values())
        submitted_left_ids = set(matches.keys())
        submitted_right_ids = list(matches.values())

        if submitted_left_ids != expected_left_ids:
            raise InvalidExerciseAnswerError('matching:2 answer must match every left item exactly once.')
        if any(not isinstance(left_id, str) or not isinstance(right_id, str) for left_id, right_id in matches.items()):
            raise InvalidExerciseAnswerError('matching:2 IDs must be strings.')
        if any(right_id not in expected_right_ids for right_id in submitted_right_ids):
            raise InvalidExerciseAnswerError('matching:2 answer contains an unknown right item ID.')
        if len(set(submitted_right_ids)) != len(submitted_right_ids):
            raise InvalidExerciseAnswerError('matching:2 right item IDs cannot be reused.')

    def grade(self, attempt: ExerciseAttempt, answer: dict) -> GradeResult:
        self.validate_answer(attempt, answer)
        matches = self._answer_matches(answer)
        private_state = attempt.private_state or attempt.grading_payload or {}
        correct_matches = private_state.get('correct_matches') or {}
        left_item_sources = private_state.get('left_item_sources') or {}

        item_results = []
        for left_id in private_state.get('left_ids') or list(correct_matches.keys()):
            is_correct = matches.get(left_id) == correct_matches.get(left_id)
            item_results.append(ItemGradeResult(
                source_item_id=left_item_sources.get(left_id, left_id),
                is_correct=is_correct,
                score=1.0 if is_correct else 0.0,
            ))

        score = (sum(item.score for item in item_results) / len(item_results)) if item_results else 0.0
        is_fully_correct = bool(item_results) and all(item.is_correct for item in item_results)
        return GradeResult(
            score=score,
            is_fully_correct=is_fully_correct,
            item_results=tuple(item_results),
            feedback={
                'correct_answer': private_state.get('correct_answer', ''),
                'explanation': '' if is_fully_correct else 'Not all pairs were matched correctly.',
            },
        )

    def _answer_matches(self, answer):
        if isinstance(answer, dict):
            return answer.get('matches')
        return None

    def _public_id(self, prefix, used_ids):
        while True:
            value = f'{prefix}-{secrets.token_hex(4)}'
            if value not in used_ids:
                used_ids.add(value)
                return value

    def _correct_answer(self, words):
        return '; '.join(_first_translation(word.translation) for word in words)
