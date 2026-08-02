from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from dictionary.models import Word
from learning.application.use_cases import StartExerciseUseCase
from learning.exercises.base import ExerciseHandler
from learning.exercises.dto import ExerciseGenerationContext, GeneratedExercise, GradeResult, ItemGradeResult
from learning.exercises.exceptions import InvalidExerciseConfigError, UnknownExerciseHandlerError
from learning.exercises.handlers.multiple_choice import MultipleChoiceHandler
from learning.exercises.registry import ExerciseHandlerRegistry
from learning.models import ExerciseAttempt, PracticeSession
from users.models import UserExerciseHistory, UserProfile, UserWord


User = get_user_model()


class DummyHandler(ExerciseHandler):
    kind = 'dummy'
    version = 1

    def validate_config(self, config: dict) -> None:
        return None

    def generate(self, context: ExerciseGenerationContext) -> GeneratedExercise:
        return GeneratedExercise(public_payload={}, private_state={}, metadata={})

    def validate_answer(self, attempt: ExerciseAttempt, answer: dict) -> None:
        return None

    def grade(self, attempt: ExerciseAttempt, answer: dict) -> GradeResult:
        return GradeResult(
            score=1.0,
            is_fully_correct=True,
            item_results=(ItemGradeResult(source_item_id='dummy', is_correct=True, score=1.0),),
            feedback={},
        )


class ExerciseHandlerRegistryTests(TestCase):
    def test_register_get_duplicate_and_unknown_handler(self):
        registry = ExerciseHandlerRegistry()
        handler = DummyHandler()

        registry.register(handler)

        self.assertIs(registry.get('dummy', 1), handler)
        with self.assertRaises(ValueError):
            registry.register(handler)
        with self.assertRaises(UnknownExerciseHandlerError):
            registry.get('dummy', 2)


class MultipleChoiceHandlerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='pass12345')
        self.word = Word.objects.create(
            hanzi='ni',
            pinyin_numeric='ni3',
            pinyin_graphic='ni',
            translation='you; thou',
            difficulty=1,
        )
        Word.objects.create(
            hanzi='hao',
            pinyin_numeric='hao3',
            pinyin_graphic='hao',
            translation='good',
            difficulty=1,
        )

    def test_generate_splits_public_and_private_state(self):
        handler = MultipleChoiceHandler()
        generated = handler.generate(ExerciseGenerationContext(user=self.user, word=self.word, config={}))

        self.assertEqual(generated.public_payload['type'], 'multiple_choice')
        self.assertIn('options', generated.public_payload)
        self.assertNotIn('correct_index', generated.public_payload)
        self.assertNotIn('correct_answer', generated.public_payload)
        self.assertIn('correct_index', generated.private_state)
        self.assertEqual(generated.metadata['source_item_ids'], [self.word.id])

    def test_grade_returns_item_level_result(self):
        handler = MultipleChoiceHandler()
        session = PracticeSession.objects.create(user=self.user)
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.word,
            exercise_type='multiple_choice',
            kind='multiple_choice',
            handler_version=1,
            private_state={'word_id': self.word.id, 'options': ['wrong', 'you'], 'correct_index': 1},
            grading_payload={'word_id': self.word.id, 'options': ['wrong', 'you'], 'correct_index': 1},
        )

        result = handler.grade(attempt, {'selected_index': 1})

        self.assertTrue(result.is_fully_correct)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.item_results[0].source_item_id, self.word.id)

    def test_validate_config_rejects_invalid_options_count(self):
        with self.assertRaises(InvalidExerciseConfigError):
            MultipleChoiceHandler().validate_config({'options_count': 1})


class PracticeSessionAttemptApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='pass12345')
        self.other_user = User.objects.create_user(username='bob', password='pass12345')
        UserProfile.objects.get_or_create(user=self.user)
        UserProfile.objects.get_or_create(user=self.other_user)
        self.word = Word.objects.create(
            hanzi='ni',
            pinyin_numeric='ni3',
            pinyin_graphic='ni',
            translation='you; thou',
            difficulty=1,
        )
        Word.objects.create(
            hanzi='hao',
            pinyin_numeric='hao3',
            pinyin_graphic='hao',
            translation='good',
            difficulty=1,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _generated_exercise(self, exercise_type='multiple_choice'):
        if exercise_type == 'translation_ru':
            return {
                'type': 'translation_ru',
                'word_id': self.word.id,
                'question': 'Translate ni',
                'correct_answer': 'you',
                'hint': '',
                'difficulty': 1,
                'options': [],
                'pairs': [],
            }
        if exercise_type == 'matching':
            return {
                'type': 'matching',
                'word_id': self.word.id,
                'question': 'Match words',
                'instructions': 'Match words',
                'pairs': [
                    {'chinese': 'ni', 'pinyin': 'ni', 'translation': 'you'},
                ],
                'correct_pairs': [[0, 0]],
                'difficulty': 2,
            }
        return {
            'type': 'multiple_choice',
            'word_id': self.word.id,
            'question': 'Choose translation',
            'options': ['wrong', 'you'],
            'correct_index': 1,
            'hint': '',
            'difficulty': 1,
            'pairs': [],
        }

    def test_start_exercise_use_case_persists_attempt_without_exposing_private_state(self):
        session = PracticeSession.objects.create(user=self.user)

        result = StartExerciseUseCase().execute(
            user=self.user,
            session=session,
            kind='multiple_choice',
            config={'handler_version': 1},
            order=0,
            word=self.word,
        )

        attempt = result.attempt
        self.assertEqual(attempt.kind, 'multiple_choice')
        self.assertEqual(attempt.handler_version, 1)
        self.assertEqual(attempt.status, ExerciseAttempt.STATUS_PENDING)
        self.assertIn('correct_index', attempt.private_state)
        self.assertNotIn('correct_index', result.public_payload)
        self.assertNotIn('private_state', result.public_payload)

    def test_practice_session_persists_attempts_and_hides_answers(self):
        response = self.client.post(
            '/api/learning/practice/session/',
            {'count': 2, 'type': 'mixed', 'exercise_types': ['multiple_choice']},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(PracticeSession.objects.count(), 1)
        self.assertEqual(ExerciseAttempt.objects.count(), 2)

        exercise = response.data['exercises'][0]
        self.assertIn('attempt_id', exercise)
        self.assertIn('session_id', exercise)
        self.assertIn('options', exercise)
        self.assertNotIn('correct_answer', exercise)
        self.assertNotIn('correct_index', exercise)
        self.assertNotIn('correct_pairs', exercise)
        self.assertNotIn('private_state', exercise)

        attempt = ExerciseAttempt.objects.get(id=exercise['attempt_id'])
        self.assertEqual(attempt.public_payload, exercise)
        self.assertEqual(attempt.kind, 'multiple_choice')
        self.assertEqual(attempt.handler_version, 1)
        self.assertIn('correct_index', attempt.private_state)
        self.assertNotIn('correct_index', attempt.public_payload)

    def test_practice_session_caps_count_and_rejects_unknown_topic(self):
        capped_response = self.client.post(
            '/api/learning/practice/session/',
            {'count': 100, 'type': 'mixed', 'exercise_types': ['multiple_choice']},
            format='json',
        )

        unknown_topic_response = self.client.post(
            '/api/learning/practice/session/',
            {'topic_id': 999999, 'count': 1},
            format='json',
        )

        self.assertEqual(capped_response.status_code, status.HTTP_200_OK)
        self.assertEqual(capped_response.data['count'], 50)
        self.assertEqual(unknown_topic_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_session_detail_returns_only_pending_attempts(self):
        session = PracticeSession.objects.create(user=self.user, requested_count=2)
        pending = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.word,
            exercise_type='multiple_choice',
            order=0,
            public_payload={'attempt_id': 1, 'type': 'multiple_choice', 'word_id': self.word.id},
            grading_payload={'correct_index': 0, 'options': ['you']},
        )
        ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.word,
            exercise_type='multiple_choice',
            order=1,
            public_payload={'attempt_id': 2, 'type': 'multiple_choice', 'word_id': self.word.id},
            grading_payload={'correct_index': 0, 'options': ['you']},
            is_correct=True,
            submitted_at=timezone.now(),
        )

        response = self.client.get(f'/api/learning/practice/session/{session.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['exercises'][0], pending.public_payload)

    def test_submit_attempt_grades_on_server_and_updates_progress(self):
        session = PracticeSession.objects.create(user=self.user, requested_count=1)
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.word,
            exercise_type='multiple_choice',
            order=0,
            public_payload={'attempt_id': 1, 'type': 'multiple_choice', 'word_id': self.word.id, 'options': ['wrong', 'you']},
            grading_payload={'correct_index': 1, 'options': ['wrong', 'you'], 'word_id': self.word.id},
        )

        response = self.client.post(
            '/api/learning/exercises/submit/',
            {'attempt_id': attempt.id, 'answer': '1', 'time_spent': 2.5},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_correct'])
        self.assertEqual(response.data['correct_answer'], 'you')

        attempt.refresh_from_db()
        session.refresh_from_db()
        user_word = UserWord.objects.get(user=self.user, word=self.word)

        self.assertTrue(attempt.is_correct)
        self.assertEqual(attempt.answer, '1')
        self.assertEqual(attempt.status, ExerciseAttempt.STATUS_SUBMITTED)
        self.assertEqual(session.status, PracticeSession.STATUS_COMPLETED)
        self.assertEqual(user_word.total_attempts, 1)
        self.assertEqual(user_word.correct_attempts, 1)

    def test_submit_attempt_is_idempotent_for_handler_attempt(self):
        session = PracticeSession.objects.create(user=self.user, requested_count=1)
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.word,
            exercise_type='multiple_choice',
            kind='multiple_choice',
            handler_version=1,
            order=0,
            private_state={'correct_index': 1, 'options': ['wrong', 'you'], 'word_id': self.word.id},
            grading_payload={'correct_index': 1, 'options': ['wrong', 'you'], 'word_id': self.word.id},
        )

        first_response = self.client.post(
            '/api/learning/exercises/submit/',
            {'attempt_id': attempt.id, 'answer': {'selected_index': 1}, 'time_spent': 2},
            format='json',
        )
        second_response = self.client.post(
            '/api/learning/exercises/submit/',
            {'attempt_id': attempt.id, 'answer': {'selected_index': 1}, 'time_spent': 2},
            format='json',
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertTrue(second_response.data['is_correct'])
        self.assertEqual(UserExerciseHistory.objects.filter(user=self.user).count(), 1)
        self.assertEqual(UserWord.objects.get(user=self.user, word=self.word).total_attempts, 1)

    def test_submit_rolls_back_when_handler_fails(self):
        session = PracticeSession.objects.create(user=self.user)
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.word,
            exercise_type='multiple_choice',
            kind='multiple_choice',
            handler_version=1,
            private_state={'word_id': self.word.id, 'options': ['wrong', 'you'], 'correct_index': 1},
        )

        with patch.object(MultipleChoiceHandler, 'grade', side_effect=InvalidExerciseConfigError('broken state')):
            response = self.client.post(
                '/api/learning/exercises/submit/',
                {'attempt_id': attempt.id, 'answer': {'selected_index': 1}, 'time_spent': 2},
                format='json',
            )

        attempt.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNone(attempt.answer)
        self.assertIsNone(attempt.is_correct)
        self.assertEqual(attempt.status, ExerciseAttempt.STATUS_PENDING)

    def test_submit_attempt_rejects_duplicate_and_other_user_for_legacy_handler(self):
        session = PracticeSession.objects.create(user=self.user, requested_count=1)
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.word,
            exercise_type='translation_ru',
            order=0,
            public_payload={'attempt_id': 1, 'type': 'translation_ru', 'word_id': self.word.id},
            grading_payload={'correct_answer': 'you'},
            is_correct=True,
            submitted_at=timezone.now(),
        )

        duplicate_response = self.client.post(
            '/api/learning/exercises/submit/',
            {'attempt_id': attempt.id, 'answer': 'you', 'time_spent': 1},
            format='json',
        )

        self.client.force_authenticate(self.other_user)
        other_user_response = self.client.post(
            '/api/learning/exercises/submit/',
            {'attempt_id': attempt.id, 'answer': 'you', 'time_spent': 1},
            format='json',
        )

        self.assertEqual(duplicate_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(other_user_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_submit_denies_other_user_handler_attempt(self):
        session = PracticeSession.objects.create(user=self.user)
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.word,
            exercise_type='multiple_choice',
            kind='multiple_choice',
            handler_version=1,
            private_state={'word_id': self.word.id, 'options': ['wrong', 'you'], 'correct_index': 1},
        )

        self.client.force_authenticate(self.other_user)
        response = self.client.post(
            '/api/learning/exercises/submit/',
            {'attempt_id': attempt.id, 'answer': {'selected_index': 1}, 'time_spent': 2},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_submit_requires_attempt_id_for_generated_contract(self):
        response = self.client.post(
            '/api/learning/exercises/submit/',
            {'answer': 'you', 'time_spent': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('attempt_id', response.data)

    def test_translation_and_matching_edge_cases(self):
        submit_view = __import__('learning.views', fromlist=['SubmitExerciseView']).SubmitExerciseView()

        translation_session = PracticeSession.objects.create(user=self.user)
        translation_attempt = ExerciseAttempt.objects.create(
            session=translation_session,
            user=self.user,
            word=self.word,
            exercise_type='translation_ru',
            order=0,
            grading_payload={'correct_answer': 'you'},
        )
        matching_attempt = ExerciseAttempt.objects.create(
            session=translation_session,
            user=self.user,
            word=self.word,
            exercise_type='matching',
            order=1,
            grading_payload={'pairs': [{'translation': 'you'}]},
        )

        self.assertTrue(submit_view._check_attempt_answer(translation_attempt, ' Thou ')['is_correct'])
        self.assertFalse(submit_view._check_attempt_answer(translation_attempt, 'teacher')['is_correct'])
        self.assertTrue(submit_view._check_attempt_answer(matching_attempt, ['you'])['is_correct'])
        self.assertFalse(submit_view._check_attempt_answer(matching_attempt, ['teacher'])['is_correct'])

    def test_legacy_translation_attempt_still_uses_old_contract(self):
        session = PracticeSession.objects.create(user=self.user)
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.word,
            exercise_type='translation_ru',
            kind='translation_ru',
            handler_version=1,
            grading_payload={'correct_answer': 'you'},
        )

        response = self.client.post(
            '/api/learning/exercises/submit/',
            {'attempt_id': attempt.id, 'answer': 'you', 'time_spent': 2},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_correct'])
        self.assertEqual(response.data['correct_answer'], 'you')
