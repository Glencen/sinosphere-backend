import random

from dictionary.models import Word

from learning.models import ExerciseAttempt

from ..base import ExerciseHandler
from ..dto import ExerciseGenerationContext, GeneratedExercise, GradeResult, ItemGradeResult
from ..exceptions import InvalidExerciseAnswerError, InvalidExerciseConfigError


class MultipleChoiceHandler(ExerciseHandler):
    kind = 'multiple_choice'
    version = 1

    def validate_config(self, config: dict) -> None:
        if not isinstance(config, dict):
            raise InvalidExerciseConfigError('Exercise config must be an object.')

        options_count = config.get('options_count', 4)
        if not isinstance(options_count, int) or options_count < 2:
            raise InvalidExerciseConfigError('options_count must be an integer >= 2.')

    def generate(self, context: ExerciseGenerationContext) -> GeneratedExercise:
        self.validate_config(context.config)
        word = context.word or self._select_word(context)
        if not word:
            raise InvalidExerciseConfigError('No word is available for multiple choice exercise.')

        options_count = context.config.get('options_count', 4)
        correct_translation = self._first_translation(word.translation)
        wrong_options = self._wrong_translations(word, options_count - 1, context.topic_id)
        options = [correct_translation, *wrong_options]
        random.shuffle(options)
        correct_index = options.index(correct_translation)

        public_payload = {
            'type': self.kind,
            'kind': self.kind,
            'handler_version': self.version,
            'word_id': word.id,
            'question': f'Choose the correct translation for: **{word.hanzi}** ({word.pinyin_graphic})',
            'options': options,
            'hint': f'HSK {word.difficulty}',
            'difficulty': word.difficulty,
            'pairs': [],
        }
        private_state = {
            'word_id': word.id,
            'options': options,
            'correct_index': correct_index,
            'correct_answer': correct_translation,
            'normalization': 'integer_index',
        }
        metadata = {
            'kind': self.kind,
            'handler_version': self.version,
            'source_item_ids': [word.id],
        }
        return GeneratedExercise(public_payload, private_state, metadata)

    def validate_answer(self, attempt: ExerciseAttempt, answer: dict) -> None:
        self._answer_index(answer)

    def grade(self, attempt: ExerciseAttempt, answer: dict) -> GradeResult:
        selected_index = self._answer_index(answer)
        private_state = attempt.private_state or attempt.grading_payload or {}
        options = private_state.get('options') or []
        correct_index = private_state.get('correct_index')

        try:
            correct_index = int(correct_index)
        except (TypeError, ValueError) as exc:
            raise InvalidExerciseConfigError('Attempt private state has no valid correct_index.') from exc

        is_correct = selected_index == correct_index
        correct_answer = ''
        if 0 <= correct_index < len(options):
            correct_answer = options[correct_index]

        score = 1.0 if is_correct else 0.0
        item_result = ItemGradeResult(
            source_item_id=private_state.get('word_id') or attempt.word_id or attempt.id,
            is_correct=is_correct,
            score=score,
        )
        return GradeResult(
            score=score,
            is_fully_correct=is_correct,
            item_results=(item_result,),
            feedback={
                'correct_answer': correct_answer,
                'explanation': '' if is_correct else f'Correct answer: {correct_answer}',
            },
        )

    def _answer_index(self, answer):
        if isinstance(answer, dict):
            raw_index = answer.get('selected_index')
        else:
            raw_index = answer

        try:
            selected_index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise InvalidExerciseAnswerError('multiple_choice answer must contain selected_index.') from exc

        if selected_index < 0:
            raise InvalidExerciseAnswerError('selected_index must be >= 0.')
        return selected_index

    def _select_word(self, context: ExerciseGenerationContext):
        if context.learning_items:
            word = Word.objects.filter(id=context.learning_items[0].item_id).first()
            if word:
                return word
        query = Word.objects.all()
        if context.topic_id:
            query = query.filter(word_tags__tag__topic_id=context.topic_id).distinct()
        return query.order_by('difficulty', 'hanzi').first()

    def _wrong_translations(self, correct_word: Word, count: int, topic_id=None):
        query = Word.objects.exclude(id=correct_word.id)
        if topic_id:
            query = query.filter(word_tags__tag__topic_id=topic_id).distinct()

        wrong = []
        for word in query.order_by('?')[: max(count * 3, 6)]:
            translation = self._first_translation(word.translation)
            if translation and translation not in wrong:
                wrong.append(translation)
            if len(wrong) >= count:
                break

        while len(wrong) < count:
            wrong.append(f'Option {len(wrong) + 1}')
        return wrong

    def _first_translation(self, translation: str) -> str:
        translations = [item.strip() for item in str(translation or '').split(';') if item.strip()]
        return translations[0] if translations else str(translation or '')
