from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from dictionary.models import Word
from learning.application.use_cases import StartExerciseUseCase, SubmitExerciseAnswerUseCase
from learning.exercises.base import ExerciseHandler
from learning.exercises.dto import ExerciseGenerationContext, GeneratedExercise, GradeResult, ItemGradeResult, LearningItemRef
from learning.exercises.exceptions import InvalidExerciseAnswerError, InvalidExerciseConfigError, UnknownExerciseHandlerError
from learning.exercises.handlers.multiple_choice import MultipleChoiceHandler
from learning.exercises.handlers.translation_cn import TranslationCnHandler
from learning.exercises.handlers.writing import WritingHandler
from learning.application.rating_policy import FSRSRating, rating_policy_registry
from learning.application.spaced_repetition import FSRSService, SpacedRepetitionReviewResult
from learning.application.events import LearningProgressConsumer, build_exercise_submitted_event
from learning.exercises.registry import ExerciseHandlerRegistry
from learning.models import AttemptMemoryCard, ExerciseEventConsumerReceipt, FSRSSchedulerProfile, MemoryCard, MemoryReview, ExerciseAttempt, PracticeSession
from users.models import UserExerciseHistory, UserLearningStats, UserProfile, UserWord


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
            position=1,
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

        with self.captureOnCommitCallbacks(execute=True):
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
        self.assertTrue(attempt.is_correct)
        self.assertEqual(attempt.answer, '1')
        self.assertEqual(attempt.status, ExerciseAttempt.STATUS_SUBMITTED)
        self.assertEqual(session.status, PracticeSession.STATUS_COMPLETED)
        self.assertEqual(UserExerciseHistory.objects.filter(user=self.user, word=self.word).count(), 1)
        self.assertEqual(UserLearningStats.objects.get(user=self.user).total_exercises_completed, 1)

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

        with self.captureOnCommitCallbacks(execute=True):
            first_response = self.client.post(
                '/api/learning/exercises/submit/',
                {'attempt_id': attempt.id, 'answer': {'selected_index': 1}, 'time_spent': 2},
                format='json',
            )
        with self.captureOnCommitCallbacks(execute=True):
            second_response = self.client.post(
                '/api/learning/exercises/submit/',
                {'attempt_id': attempt.id, 'answer': {'selected_index': 1}, 'time_spent': 2},
                format='json',
            )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertTrue(second_response.data['is_correct'])
        self.assertEqual(UserExerciseHistory.objects.filter(user=self.user).count(), 1)
        self.assertEqual(ExerciseEventConsumerReceipt.objects.filter(consumer_name='learning_progress_v1').count(), 1)

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
            handler_version=0,
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
            position=1,
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
            handler_version=0,
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

    def test_legacy_submit_endpoint_accepts_scalar_writing_answer_for_compatibility(self):
        handler = WritingHandler()
        generated = handler.generate(ExerciseGenerationContext(user=self.user, word=self.word, config={}))
        session = PracticeSession.objects.create(user=self.user)
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.word,
            exercise_type=handler.kind,
            kind=handler.kind,
            handler_version=handler.version,
            public_payload=generated.public_payload,
            private_state=generated.private_state,
        )

        response = self.client.post(
            '/api/learning/exercises/submit/',
            {'attempt_id': attempt.id, 'answer': '', 'time_spent': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_correct'])

from datetime import timedelta
import random

from django.db import IntegrityError
from learning.application.composer import ExerciseComposer
from learning.application.selection_policy import ExerciseTypeSelectionPolicy
from learning.exercises import registry as exercise_registry


class PracticeSessionPlanningApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='session-user', password='pass12345')
        self.other_user = User.objects.create_user(username='other-session-user', password='pass12345')
        UserProfile.objects.get_or_create(user=self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.words = []
        for index in range(6):
            self.words.append(Word.objects.create(
                hanzi=f'w{index}',
                pinyin_numeric=f'w{index}',
                pinyin_graphic=f'w{index}',
                translation=f'translation-{index}',
                difficulty=1,
            ))

    def assertPublicExerciseContract(self, payload):
        self.assertIsInstance(payload, dict)
        self.assertIn('kind', payload)
        self.assertIn('handler_version', payload)
        self.assertIn('attempt_id', payload)
        self.assertIn('session_id', payload)
        self.assertNotIn('private_state', payload)
        self.assertNotIn('accepted_answers', payload)
        self.assertNotIn('correct_index', payload)
        self.assertNotIn('correct_pairs', payload)
        self.assertNotIn('memory_card_id', payload)
        self.assertNotIn('fsrs_state', payload)
        self.assertNotIn('due_at', payload)

    def test_create_session_from_requested_learning_items(self):
        response = self.client.post(
            '/api/practice-sessions/',
            {
                'requested_cards_count': 3,
                'allowed_types': ['multiple_choice'],
                'rng_seed': 1,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['learning_items_count'], 3)
        self.assertEqual(response.data['visual_exercises_count'], 3)
        self.assertEqual(response.data['status'], PracticeSession.STATUS_IN_PROGRESS)
        self.assertIn('current_exercise', response.data)
        self.assertPublicExerciseContract(response.data['current_exercise'])
        self.assertEqual(response.data['current_exercise']['kind'], 'multiple_choice')
        self.assertEqual(response.data['current_exercise'].get('type'), 'multiple_choice')

        session = PracticeSession.objects.get(id=response.data['session_id'])
        self.assertEqual(session.requested_cards_count, 3)
        self.assertEqual(session.generated_exercises_count, 3)
        self.assertEqual(session.attempts.count(), 3)

    def test_create_session_response_contract(self):
        response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 1, 'allowed_types': ['multiple_choice'], 'rng_seed': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], PracticeSession.STATUS_IN_PROGRESS)
        self.assertIn('session_id', response.data)
        self.assertIn('current_attempt_id', response.data)
        self.assertIn('current_exercise', response.data)
        self.assertIn('progress', response.data)
        self.assertPublicExerciseContract(response.data['current_exercise'])

    def test_session_detail_response_contract(self):
        create_response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 1, 'allowed_types': ['multiple_choice'], 'rng_seed': 1},
            format='json',
        )

        response = self.client.get(f"/api/practice-sessions/{create_response.data['session_id']}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['current_attempt_id'], create_response.data['current_attempt_id'])
        self.assertIn('progress', response.data)
        self.assertPublicExerciseContract(response.data['current_exercise'])

    def test_current_exercise_response_contract(self):
        create_response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 1, 'allowed_types': ['multiple_choice'], 'rng_seed': 1},
            format='json',
        )

        response = self.client.get(f"/api/practice-sessions/{create_response.data['session_id']}/current-exercise/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], PracticeSession.STATUS_IN_PROGRESS)
        self.assertIn('progress', response.data)
        self.assertPublicExerciseContract(response.data['current_exercise'])

    def test_writing_api_payload_and_submit_contract_for_confirmation_mode(self):
        create_response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 1, 'allowed_types': ['writing'], 'rng_seed': 1},
            format='json',
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        exercise = create_response.data['current_exercise']
        self.assertPublicExerciseContract(exercise)
        self.assertEqual(exercise['kind'], 'writing')
        self.assertEqual(exercise['submission_mode'], 'confirmation')

        submit_response = self.client.post(
            f"/api/exercise-attempts/{exercise['attempt_id']}/submit/",
            {'answer': {'completed': True}, 'duration_ms': 1000},
            format='json',
        )

        self.assertEqual(submit_response.status_code, status.HTTP_200_OK)
        self.assertTrue(submit_response.data['is_correct'])
        self.assertIn('session_status', submit_response.data)
        self.assertIn('progress', submit_response.data)

    def test_writing_api_payload_and_submit_contract_for_text_mode(self):
        create_response = self.client.post(
            '/api/practice-sessions/',
            {
                'requested_cards_count': 1,
                'allowed_types': ['writing'],
                'handler_config': {'submission_mode': 'text'},
                'rng_seed': 1,
            },
            format='json',
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        exercise = create_response.data['current_exercise']
        attempt = ExerciseAttempt.objects.get(id=exercise['attempt_id'])
        self.assertPublicExerciseContract(exercise)
        self.assertEqual(exercise['kind'], 'writing')
        self.assertEqual(exercise['submission_mode'], 'text')

        submit_response = self.client.post(
            f"/api/exercise-attempts/{exercise['attempt_id']}/submit/",
            {'answer': {'text': attempt.private_state['correct_answer']}, 'duration_ms': 1000},
            format='json',
        )

        self.assertEqual(submit_response.status_code, status.HTTP_200_OK)
        self.assertTrue(submit_response.data['is_correct'])

    def test_writing_api_rejects_invalid_and_ambiguous_answers(self):
        confirmation_response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 1, 'allowed_types': ['writing'], 'rng_seed': 1},
            format='json',
        )
        confirmation_attempt_id = confirmation_response.data['current_exercise']['attempt_id']

        wrong_confirmation = self.client.post(
            f'/api/exercise-attempts/{confirmation_attempt_id}/submit/',
            {'answer': {'text': 'anything'}, 'duration_ms': 1000},
            format='json',
        )
        ambiguous_confirmation = self.client.post(
            f'/api/exercise-attempts/{confirmation_attempt_id}/submit/',
            {'answer': {'text': 'anything', 'completed': True}, 'duration_ms': 1000},
            format='json',
        )

        text_response = self.client.post(
            '/api/practice-sessions/',
            {
                'requested_cards_count': 1,
                'allowed_types': ['writing'],
                'handler_config': {'submission_mode': 'text'},
                'rng_seed': 2,
            },
            format='json',
        )
        text_attempt_id = text_response.data['current_exercise']['attempt_id']
        wrong_text = self.client.post(
            f'/api/exercise-attempts/{text_attempt_id}/submit/',
            {'answer': {'completed': True}, 'duration_ms': 1000},
            format='json',
        )

        self.assertEqual(wrong_confirmation.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ambiguous_confirmation.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(wrong_text.status_code, status.HTTP_400_BAD_REQUEST)

    def test_matching_session_separates_cards_count_from_visual_exercises_count(self):
        response = self.client.post(
            '/api/practice-sessions/',
            {
                'requested_cards_count': 5,
                'allowed_types': ['matching'],
                'rng_seed': 2,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['learning_items_count'], 5)
        self.assertLess(response.data['visual_exercises_count'], 5)

        session = PracticeSession.objects.get(id=response.data['session_id'])
        matching_attempt = session.attempts.order_by('position').first()
        self.assertEqual(matching_attempt.kind, 'matching')
        self.assertGreater(len(matching_attempt.learning_items), 1)
        self.assertIn('accepted_translations', matching_attempt.private_state)
        self.assertNotIn('accepted_translations', matching_attempt.public_payload)

    def test_controlled_randomness_in_type_policy(self):
        items = tuple(
            LearningItemRef(item_type='word', item_id=word.id, payload={'difficulty': word.difficulty})
            for word in self.words[:4]
        )
        first_policy = ExerciseTypeSelectionPolicy(handler_registry=exercise_registry, rng=random.Random(123))
        second_policy = ExerciseTypeSelectionPolicy(handler_registry=exercise_registry, rng=random.Random(123))

        first_specs = ExerciseComposer(selection_policy=first_policy).compose(
            learning_items=items,
            allowed_types=['multiple_choice', 'translation_ru'],
        )
        second_specs = ExerciseComposer(selection_policy=second_policy).compose(
            learning_items=items,
            allowed_types=['multiple_choice', 'translation_ru'],
        )

        self.assertEqual([spec.kind for spec in first_specs], [spec.kind for spec in second_specs])
        self.assertGreater(len({spec.kind for spec in first_specs}), 1)

    def test_get_session_does_not_regenerate_attempts(self):
        create_response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 3, 'allowed_types': ['multiple_choice'], 'rng_seed': 1},
            format='json',
        )
        session_id = create_response.data['session_id']
        attempts_count = ExerciseAttempt.objects.filter(session_id=session_id).count()

        first_get = self.client.get(f'/api/practice-sessions/{session_id}/')
        second_get = self.client.get(f'/api/practice-sessions/{session_id}/')

        self.assertEqual(first_get.status_code, status.HTTP_200_OK)
        self.assertEqual(second_get.status_code, status.HTTP_200_OK)
        self.assertEqual(ExerciseAttempt.objects.filter(session_id=session_id).count(), attempts_count)
        self.assertEqual(first_get.data['current_exercise'], second_get.data['current_exercise'])

    def test_terminal_session_detail_does_not_return_current_exercise(self):
        for terminal_status in (
            PracticeSession.STATUS_COMPLETED,
            PracticeSession.STATUS_EXPIRED,
            PracticeSession.STATUS_ABANDONED,
        ):
            session = PracticeSession.objects.create(
                user=self.user,
                status=terminal_status,
                requested_cards_count=1,
                generated_exercises_count=1,
            )
            ExerciseAttempt.objects.create(
                session=session,
                user=self.user,
                word=self.words[0],
                exercise_type='multiple_choice',
                kind='multiple_choice',
                handler_version=1,
                position=0,
                order=0,
                public_payload={'kind': 'multiple_choice', 'type': 'multiple_choice'},
                private_state={'word_id': self.words[0].id, 'options': ['wrong', 'translation-0'], 'correct_index': 1},
            )

            response = self.client.get(f'/api/practice-sessions/{session.id}/')

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data['status'], terminal_status)
            self.assertIsNone(response.data['current_attempt_id'])
            self.assertIsNone(response.data['current_exercise'])

    def test_terminal_current_exercise_endpoint_returns_null(self):
        for terminal_status in (
            PracticeSession.STATUS_COMPLETED,
            PracticeSession.STATUS_EXPIRED,
            PracticeSession.STATUS_ABANDONED,
        ):
            session = PracticeSession.objects.create(user=self.user, status=terminal_status)
            ExerciseAttempt.objects.create(
                session=session,
                user=self.user,
                word=self.words[0],
                exercise_type='multiple_choice',
                kind='multiple_choice',
                handler_version=1,
                position=0,
                order=0,
                public_payload={'kind': 'multiple_choice', 'type': 'multiple_choice'},
                private_state={'word_id': self.words[0].id, 'options': ['wrong', 'translation-0'], 'correct_index': 1},
            )

            response = self.client.get(f'/api/practice-sessions/{session.id}/current-exercise/')

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data['status'], terminal_status)
            self.assertIsNone(response.data['current_exercise'])

    def test_in_progress_session_returns_current_exercise(self):
        session = PracticeSession.objects.create(
            user=self.user,
            status=PracticeSession.STATUS_IN_PROGRESS,
            requested_cards_count=1,
            generated_exercises_count=1,
        )
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.words[0],
            exercise_type='multiple_choice',
            kind='multiple_choice',
            handler_version=1,
            position=0,
            order=0,
            public_payload={'kind': 'multiple_choice', 'type': 'multiple_choice'},
            private_state={'word_id': self.words[0].id, 'options': ['wrong', 'translation-0'], 'correct_index': 1},
        )

        detail_response = self.client.get(f'/api/practice-sessions/{session.id}/')
        current_response = self.client.get(f'/api/practice-sessions/{session.id}/current-exercise/')

        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(current_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['current_attempt_id'], attempt.id)
        self.assertEqual(current_response.data['current_exercise']['attempt_id'], attempt.id)
        self.assertPublicExerciseContract(detail_response.data['current_exercise'])
        self.assertPublicExerciseContract(current_response.data['current_exercise'])

    def test_session_without_pending_attempt_returns_null_current_exercise(self):
        session = PracticeSession.objects.create(
            user=self.user,
            status=PracticeSession.STATUS_IN_PROGRESS,
            requested_cards_count=1,
            generated_exercises_count=1,
        )
        ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.words[0],
            exercise_type='multiple_choice',
            kind='multiple_choice',
            handler_version=1,
            position=0,
            order=0,
            is_correct=True,
            status=ExerciseAttempt.STATUS_SUBMITTED,
            public_payload={'kind': 'multiple_choice', 'type': 'multiple_choice'},
            private_state={'word_id': self.words[0].id, 'options': ['wrong', 'translation-0'], 'correct_index': 1},
        )

        detail_response = self.client.get(f'/api/practice-sessions/{session.id}/')
        current_response = self.client.get(f'/api/practice-sessions/{session.id}/current-exercise/')

        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(current_response.status_code, status.HTTP_200_OK)
        self.assertIsNone(detail_response.data['current_attempt_id'])
        self.assertIsNone(detail_response.data['current_exercise'])
        self.assertIsNone(current_response.data['current_exercise'])

    def test_unique_position_inside_session(self):
        session = PracticeSession.objects.create(user=self.user, status=PracticeSession.STATUS_IN_PROGRESS)
        ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.words[0],
            exercise_type='multiple_choice',
            kind='multiple_choice',
            position=0,
            order=0,
        )

        with self.assertRaises(IntegrityError):
            ExerciseAttempt.objects.create(
                session=session,
                user=self.user,
                word=self.words[1],
                exercise_type='multiple_choice',
                kind='multiple_choice',
                position=0,
                order=1,
            )

    def test_restore_current_exercise_for_unfinished_session(self):
        create_response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 2, 'allowed_types': ['multiple_choice'], 'rng_seed': 1},
            format='json',
        )
        session_id = create_response.data['session_id']

        response = self.client.get(f'/api/practice-sessions/{session_id}/current-exercise/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], PracticeSession.STATUS_IN_PROGRESS)
        self.assertEqual(response.data['current_exercise']['position'], 0)
        self.assertPublicExerciseContract(response.data['current_exercise'])

    def test_session_completion_is_idempotent(self):
        create_response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 2, 'allowed_types': ['translation_ru'], 'rng_seed': 1},
            format='json',
        )
        session = PracticeSession.objects.get(id=create_response.data['session_id'])
        attempts = list(session.attempts.order_by('position'))

        for attempt in attempts:
            response = self.client.post(
                f'/api/exercise-attempts/{attempt.id}/submit/',
                {'answer': {'text': attempt.private_state['correct_answer']}, 'duration_ms': 1000},
                format='json',
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn('attempt_id', response.data)
            self.assertIn('session_id', response.data)
            self.assertIn('is_correct', response.data)
            self.assertIn('score', response.data)
            self.assertIn('correct_answer', response.data)
            self.assertIn('explanation', response.data)
            self.assertIn('item_results', response.data)
            self.assertIn('session_status', response.data)
            self.assertIn('progress', response.data)

        session.refresh_from_db()
        self.assertEqual(session.status, PracticeSession.STATUS_COMPLETED)
        completed_at = session.completed_at

        repeat_response = self.client.post(
            f'/api/exercise-attempts/{attempts[-1].id}/submit/',
            {'answer': {'text': attempts[-1].private_state['correct_answer']}, 'duration_ms': 1000},
            format='json',
        )

        session.refresh_from_db()
        self.assertEqual(repeat_response.status_code, status.HTTP_200_OK)
        self.assertEqual(session.status, PracticeSession.STATUS_COMPLETED)
        self.assertEqual(session.completed_at, completed_at)

    def test_expired_session_blocks_submit(self):
        session = PracticeSession.objects.create(
            user=self.user,
            status=PracticeSession.STATUS_IN_PROGRESS,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.words[0],
            exercise_type='multiple_choice',
            kind='multiple_choice',
            handler_version=1,
            position=0,
            order=0,
            private_state={'word_id': self.words[0].id, 'options': ['wrong', 'translation-0'], 'correct_index': 1},
        )

        response = self.client.post(
            f'/api/exercise-attempts/{attempt.id}/submit/',
            {'answer': {'selected_index': 1}, 'duration_ms': 1000},
            format='json',
        )

        session.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertEqual(session.status, PracticeSession.STATUS_EXPIRED)
        self.assertEqual(attempt.status, ExerciseAttempt.STATUS_EXPIRED)

    def test_rollback_when_handler_generation_fails(self):
        with patch.object(MultipleChoiceHandler, 'generate', side_effect=InvalidExerciseConfigError('broken handler')):
            response = self.client.post(
                '/api/practice-sessions/',
                {'requested_cards_count': 2, 'allowed_types': ['multiple_choice'], 'rng_seed': 1},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PracticeSession.objects.filter(user=self.user).count(), 0)
        self.assertEqual(ExerciseAttempt.objects.filter(user=self.user).count(), 0)

class FakeSpacedRepetitionService:
    def __init__(self, fail_on_card_id=None):
        self.reviewed_card_ids = []
        self.fail_on_card_id = fail_on_card_id

    def review(self, *, card, rating, reviewed_at, duration_ms):
        self.reviewed_card_ids.append(card.id)
        if self.fail_on_card_id == card.id:
            raise RuntimeError('fsrs failed')
        previous = dict(card.fsrs_state or {})
        resulting = {**previous, 'last_rating': rating, 'reviewed': True}
        return SpacedRepetitionReviewResult(
            previous_state=previous,
            resulting_state=resulting,
            due_at=timezone.now() + timedelta(days=rating),
            fsrs_log={'fake': True, 'rating': rating},
            scheduler_version='fake-fsrs',
            parameter_set_version=7,
        )


class MemoryCardFSRSIntegrationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='fsrs-user', password='pass12345')
        UserProfile.objects.get_or_create(user=self.user)
        FSRSSchedulerProfile.objects.create(user=None, version=7, is_active=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.words = [
            Word.objects.create(
                hanzi=f'm{index}',
                pinyin_numeric=f'm{index}',
                pinyin_graphic=f'm{index}',
                translation=f'meaning-{index}',
                difficulty=1,
            )
            for index in range(5)
        ]

    def _card(self, word, direction=MemoryCard.DIRECTION_CN_TO_RU, due_offset_minutes=-1):
        return MemoryCard.objects.create(
            user=self.user,
            learning_item=word,
            direction=direction,
            due_at=timezone.now() + timedelta(minutes=due_offset_minutes),
            parameter_set_version=7,
        )

    def test_create_memory_card_and_independent_directions(self):
        cn_to_ru = self._card(self.words[0], MemoryCard.DIRECTION_CN_TO_RU)
        ru_to_cn = self._card(self.words[0], MemoryCard.DIRECTION_RU_TO_CN)

        self.assertNotEqual(cn_to_ru.id, ru_to_cn.id)
        self.assertEqual(MemoryCard.objects.filter(user=self.user, learning_item=self.words[0]).count(), 2)

    def test_planner_selects_due_cards_before_new_cards(self):
        due_card = self._card(self.words[0])

        response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 3, 'allowed_types': ['multiple_choice'], 'rng_seed': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        session = PracticeSession.objects.get(id=response.data['session_id'])
        linked_card_ids = list(AttemptMemoryCard.objects.filter(attempt__session=session).values_list('memory_card_id', flat=True))
        self.assertIn(due_card.id, linked_card_ids)
        self.assertEqual(len(set(linked_card_ids)), 3)
        self.assertEqual(MemoryCard.objects.filter(user=self.user).count(), 3)

    def test_rating_policy_mapping(self):
        policy = rating_policy_registry.get('multiple_choice')
        attempt = ExerciseAttempt(exercise_type='multiple_choice', kind='multiple_choice')

        wrong = ItemGradeResult(source_item_id=1, is_correct=False, score=0)
        hinted = ItemGradeResult(source_item_id=1, is_correct=True, score=1, used_hint=True)
        retried = ItemGradeResult(source_item_id=1, is_correct=True, score=1, attempts_count=2)
        correct = ItemGradeResult(source_item_id=1, is_correct=True, score=1)

        self.assertEqual(policy.rating_for(item_result=wrong, attempt=attempt), FSRSRating.AGAIN)
        self.assertEqual(policy.rating_for(item_result=hinted, attempt=attempt), FSRSRating.HARD)
        self.assertEqual(policy.rating_for(item_result=retried, attempt=attempt), FSRSRating.HARD)
        self.assertEqual(policy.rating_for(item_result=correct, attempt=attempt), FSRSRating.GOOD)
        self.assertEqual(policy.rating_for(item_result=correct, attempt=attempt, explicit_rating=FSRSRating.EASY), FSRSRating.EASY)
        self.assertEqual(policy.rating_for(item_result=wrong, attempt=attempt, explicit_rating=FSRSRating.EASY), FSRSRating.AGAIN)

    def test_submit_updates_one_memory_card_and_creates_review(self):
        card = self._card(self.words[0])
        session = PracticeSession.objects.create(user=self.user, status=PracticeSession.STATUS_IN_PROGRESS)
        started = StartExerciseUseCase().execute(
            user=self.user,
            session=session,
            kind='multiple_choice',
            config={'handler_version': 1},
            order=0,
            learning_items=(LearningItemRef('memory_card', card.id, {'word_id': self.words[0].id, 'difficulty': 1}),),
        )
        correct_index = started.attempt.private_state['correct_index']
        service = FakeSpacedRepetitionService()

        result = SubmitExerciseAnswerUseCase(spaced_repetition_service=service).execute(
            user=self.user,
            attempt_id=started.attempt.id,
            answer={'selected_index': correct_index},
            duration_ms=1200,
        )

        card.refresh_from_db()
        link = AttemptMemoryCard.objects.get(attempt=started.attempt, memory_card=card)
        review = MemoryReview.objects.get(memory_card=card, exercise_attempt=started.attempt)
        self.assertTrue(result.grade.is_fully_correct)
        self.assertEqual(card.fsrs_state['reviewed'], True)
        self.assertEqual(link.fsrs_rating, FSRSRating.GOOD)
        self.assertEqual(review.scheduler_version, 'fake-fsrs')
        self.assertEqual(review.parameter_set_version, 7)

    def test_matching_updates_each_memory_card_independently(self):
        cards = [self._card(word) for word in self.words[:4]]
        session = PracticeSession.objects.create(user=self.user, status=PracticeSession.STATUS_IN_PROGRESS)
        items = tuple(
            LearningItemRef('memory_card', card.id, {'word_id': card.learning_item_id, 'difficulty': 1})
            for card in cards
        )
        started = StartExerciseUseCase().execute(
            user=self.user,
            session=session,
            kind='matching',
            config={'handler_version': 1},
            order=0,
            learning_items=items,
        )
        translations = [pair['translation'] for pair in started.attempt.private_state['pairs']]
        translations[1] = 'wrong-answer'
        service = FakeSpacedRepetitionService()

        SubmitExerciseAnswerUseCase(spaced_repetition_service=service).execute(
            user=self.user,
            attempt_id=started.attempt.id,
            answer={'translations': translations},
            duration_ms=2000,
        )

        ratings = list(AttemptMemoryCard.objects.filter(attempt=started.attempt).order_by('position').values_list('fsrs_rating', flat=True))
        self.assertEqual(ratings[0], FSRSRating.GOOD)
        self.assertEqual(ratings[1], FSRSRating.AGAIN)
        self.assertEqual(MemoryReview.objects.filter(exercise_attempt=started.attempt).count(), 4)

    def test_rollback_when_one_card_review_fails(self):
        cards = [self._card(word) for word in self.words[:2]]
        session = PracticeSession.objects.create(user=self.user, status=PracticeSession.STATUS_IN_PROGRESS)
        items = tuple(
            LearningItemRef('memory_card', card.id, {'word_id': card.learning_item_id, 'difficulty': 1})
            for card in cards
        )
        started = StartExerciseUseCase().execute(
            user=self.user,
            session=session,
            kind='matching',
            config={'handler_version': 1},
            order=0,
            learning_items=items,
        )
        translations = [pair['translation'] for pair in started.attempt.private_state['pairs']]
        service = FakeSpacedRepetitionService(fail_on_card_id=cards[1].id)

        with self.assertRaises(RuntimeError):
            SubmitExerciseAnswerUseCase(spaced_repetition_service=service).execute(
                user=self.user,
                attempt_id=started.attempt.id,
                answer={'translations': translations},
                duration_ms=2000,
            )

        started.attempt.refresh_from_db()
        self.assertIsNone(started.attempt.is_correct)
        self.assertEqual(MemoryReview.objects.filter(exercise_attempt=started.attempt).count(), 0)
        self.assertFalse(AttemptMemoryCard.objects.filter(attempt=started.attempt, fsrs_rating__isnull=False).exists())

    def test_idempotent_resubmit_does_not_create_second_review(self):
        card = self._card(self.words[0])
        session = PracticeSession.objects.create(user=self.user, status=PracticeSession.STATUS_IN_PROGRESS)
        started = StartExerciseUseCase().execute(
            user=self.user,
            session=session,
            kind='multiple_choice',
            config={'handler_version': 1},
            order=0,
            learning_items=(LearningItemRef('memory_card', card.id, {'word_id': self.words[0].id, 'difficulty': 1}),),
        )
        answer = {'selected_index': started.attempt.private_state['correct_index']}
        service = FakeSpacedRepetitionService()
        use_case = SubmitExerciseAnswerUseCase(spaced_repetition_service=service)

        use_case.execute(user=self.user, attempt_id=started.attempt.id, answer=answer, duration_ms=1000)
        due_after_first = MemoryCard.objects.get(id=card.id).due_at
        use_case.execute(user=self.user, attempt_id=started.attempt.id, answer=answer, duration_ms=1000)

        self.assertEqual(MemoryReview.objects.filter(memory_card=card, exercise_attempt=started.attempt).count(), 1)
        self.assertEqual(MemoryCard.objects.get(id=card.id).due_at, due_after_first)
        self.assertEqual(service.reviewed_card_ids, [card.id])

    def test_card_locks_are_requested_in_stable_id_order(self):
        cards = [self._card(word) for word in self.words[:3]]
        reversed_cards = tuple(reversed(cards))
        session = PracticeSession.objects.create(user=self.user, status=PracticeSession.STATUS_IN_PROGRESS)
        items = tuple(
            LearningItemRef('memory_card', card.id, {'word_id': card.learning_item_id, 'difficulty': 1})
            for card in reversed_cards
        )
        started = StartExerciseUseCase().execute(
            user=self.user,
            session=session,
            kind='matching',
            config={'handler_version': 1},
            order=0,
            learning_items=items,
        )
        translations = [pair['translation'] for pair in started.attempt.private_state['pairs']]
        service = FakeSpacedRepetitionService()

        SubmitExerciseAnswerUseCase(spaced_repetition_service=service).execute(
            user=self.user,
            attempt_id=started.attempt.id,
            answer={'translations': translations},
            duration_ms=2000,
        )

        self.assertEqual(service.reviewed_card_ids, sorted(card.id for card in cards))

    def test_fsrs_adapter_uses_timezone_aware_datetime(self):
        card = self._card(self.words[0])
        result = FSRSService().review(
            card=card,
            rating=FSRSRating.GOOD,
            reviewed_at=timezone.now(),
            duration_ms=1000,
        )

        self.assertTrue(timezone.is_aware(result.due_at))
        self.assertEqual(result.parameter_set_version, 7)

    def test_api_does_not_expose_fsrs_state(self):
        card = self._card(self.words[0])
        response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 1, 'allowed_types': ['multiple_choice'], 'rng_seed': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = response.data['current_exercise']
        self.assertNotIn('fsrs_state', payload)
        self.assertNotIn('due_at', payload)
        self.assertNotIn('memory_card_id', payload)
        self.assertNotIn('private_state', payload)


class RemainingExerciseHandlersTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='handler-user', password='pass12345')
        self.word = Word.objects.create(
            hanzi='猫',
            pinyin_numeric='mao1',
            pinyin_graphic='mao',
            translation='cat; kitten',
            difficulty=1,
        )
        self.session = PracticeSession.objects.create(user=self.user, status=PracticeSession.STATUS_IN_PROGRESS)

    def test_translation_cn_handler_generates_private_answer_and_item_result(self):
        handler = TranslationCnHandler()
        generated = handler.generate(ExerciseGenerationContext(user=self.user, word=self.word, config={}))
        self.assertNotIn('accepted_answers', generated.public_payload)
        self.assertEqual(generated.private_state['correct_answer'], '猫')
        attempt = ExerciseAttempt.objects.create(
            session=self.session,
            user=self.user,
            word=self.word,
            exercise_type=handler.kind,
            kind=handler.kind,
            handler_version=handler.version,
            private_state=generated.private_state,
        )

        grade = handler.grade(attempt, {'text': '猫'})

        self.assertTrue(grade.is_fully_correct)
        self.assertEqual(len(grade.item_results), 1)
        self.assertEqual(grade.item_results[0].source_item_id, self.word.id)

    def test_writing_handler_accepts_completed_flag_without_exposing_private_state(self):
        handler = WritingHandler()
        generated = handler.generate(ExerciseGenerationContext(user=self.user, word=self.word, config={}))
        self.assertIn('stroke_data', generated.public_payload)
        self.assertEqual(generated.public_payload['kind'], 'writing')
        self.assertEqual(generated.public_payload['submission_mode'], 'confirmation')
        self.assertNotIn('correct_answer', generated.public_payload)
        attempt = ExerciseAttempt.objects.create(
            session=self.session,
            user=self.user,
            word=self.word,
            exercise_type=handler.kind,
            kind=handler.kind,
            handler_version=handler.version,
            private_state=generated.private_state,
        )

        grade = handler.grade(attempt, {'completed': True})

        self.assertTrue(grade.is_fully_correct)
        self.assertEqual(grade.item_results[0].source_item_id, self.word.id)

    def test_writing_handler_public_payload_supports_text_mode(self):
        handler = WritingHandler()

        generated = handler.generate(ExerciseGenerationContext(
            user=self.user,
            word=self.word,
            config={'submission_mode': 'text'},
        ))

        self.assertEqual(generated.public_payload['kind'], 'writing')
        self.assertEqual(generated.public_payload['type'], 'writing')
        self.assertEqual(generated.public_payload['submission_mode'], 'text')
        self.assertEqual(generated.private_state['submission_mode'], 'text')
        self.assertNotIn('private_state', generated.public_payload)
        self.assertNotIn('accepted_answers', generated.public_payload)
        self.assertNotIn('correct_index', generated.public_payload)
        self.assertNotIn('correct_pairs', generated.public_payload)
        self.assertNotIn('memory_card_id', generated.public_payload)
        self.assertNotIn('fsrs_state', generated.public_payload)
        self.assertNotIn('due_at', generated.public_payload)

    def test_writing_handler_accepts_text_answer_in_text_mode(self):
        handler = WritingHandler()
        generated = handler.generate(ExerciseGenerationContext(
            user=self.user,
            word=self.word,
            config={'submission_mode': 'text'},
        ))
        attempt = ExerciseAttempt.objects.create(
            session=self.session,
            user=self.user,
            word=self.word,
            exercise_type=handler.kind,
            kind=handler.kind,
            handler_version=handler.version,
            public_payload=generated.public_payload,
            private_state=generated.private_state,
        )

        grade = handler.grade(attempt, {'text': 'зЊ«'})

        self.assertTrue(grade.is_fully_correct)

    def test_writing_handler_rejects_wrong_format_for_text_mode(self):
        handler = WritingHandler()
        generated = handler.generate(ExerciseGenerationContext(
            user=self.user,
            word=self.word,
            config={'submission_mode': 'text'},
        ))
        attempt = ExerciseAttempt.objects.create(
            session=self.session,
            user=self.user,
            word=self.word,
            exercise_type=handler.kind,
            kind=handler.kind,
            handler_version=handler.version,
            public_payload=generated.public_payload,
            private_state=generated.private_state,
        )

        with self.assertRaises(InvalidExerciseAnswerError):
            handler.validate_answer(attempt, {'completed': True})

    def test_writing_handler_rejects_wrong_format_for_confirmation_mode(self):
        handler = WritingHandler()
        generated = handler.generate(ExerciseGenerationContext(user=self.user, word=self.word, config={}))
        attempt = ExerciseAttempt.objects.create(
            session=self.session,
            user=self.user,
            word=self.word,
            exercise_type=handler.kind,
            kind=handler.kind,
            handler_version=handler.version,
            public_payload=generated.public_payload,
            private_state=generated.private_state,
        )

        with self.assertRaises(InvalidExerciseAnswerError):
            handler.validate_answer(attempt, {'text': 'зЊ«'})

    def test_writing_handler_rejects_ambiguous_answer(self):
        handler = WritingHandler()
        generated = handler.generate(ExerciseGenerationContext(user=self.user, word=self.word, config={}))
        attempt = ExerciseAttempt.objects.create(
            session=self.session,
            user=self.user,
            word=self.word,
            exercise_type=handler.kind,
            kind=handler.kind,
            handler_version=handler.version,
            public_payload=generated.public_payload,
            private_state=generated.private_state,
        )

        with self.assertRaises(InvalidExerciseAnswerError):
            handler.validate_answer(attempt, {'text': 'зЊ«', 'completed': True})


class ExerciseSystemEndToEndTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='e2e-user', password='pass12345')
        self.other_user = User.objects.create_user(username='e2e-other', password='pass12345')
        UserProfile.objects.get_or_create(user=self.user)
        FSRSSchedulerProfile.objects.create(user=None, version=9, is_active=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.words = [
            Word.objects.create(
                hanzi=f'e{index}',
                pinyin_numeric=f'e{index}',
                pinyin_graphic=f'e{index}',
                translation=f'e2e-meaning-{index}',
                difficulty=1,
            )
            for index in range(6)
        ]
        self.due_card = MemoryCard.objects.create(
            user=self.user,
            learning_item=self.words[0],
            direction=MemoryCard.DIRECTION_CN_TO_RU,
            due_at=timezone.now() - timedelta(minutes=5),
            parameter_set_version=9,
        )

    def _answer_for_attempt(self, attempt):
        if attempt.kind == 'multiple_choice':
            return {'selected_index': attempt.private_state['correct_index']}
        if attempt.kind in ('translation_ru', 'translation_cn'):
            return {'text': attempt.private_state['correct_answer']}
        if attempt.kind == 'matching':
            return {'translations': [pair['translation'] for pair in attempt.private_state['pairs']]}
        if attempt.kind == 'writing':
            return {'completed': True}
        raise AssertionError(f'Unhandled attempt kind {attempt.kind}')

    def test_full_session_flow_updates_fsrs_events_and_is_idempotent(self):
        response = self.client.post(
            '/api/practice-sessions/',
            {
                'requested_cards_count': 4,
                'allowed_types': ['translation_ru', 'translation_cn', 'multiple_choice', 'writing'],
                'rng_seed': 11,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('private_state', response.data['current_exercise'])
        self.assertNotIn('fsrs_state', response.data['current_exercise'])

        session = PracticeSession.objects.get(id=response.data['session_id'])
        self.assertGreaterEqual(session.attempts.values('kind').distinct().count(), 2)
        self.assertTrue(AttemptMemoryCard.objects.filter(attempt__session=session, memory_card=self.due_card).exists())

        first_attempt_id = session.attempts.order_by('position').first().id
        for attempt in session.attempts.order_by('position'):
            with self.captureOnCommitCallbacks(execute=True):
                submit = self.client.post(
                    f'/api/exercise-attempts/{attempt.id}/submit/',
                    {'answer': self._answer_for_attempt(attempt), 'duration_ms': 1000},
                    format='json',
                )
            self.assertEqual(submit.status_code, status.HTTP_200_OK)
            self.assertIn('item_results', submit.data)

        session.refresh_from_db()
        self.assertEqual(session.status, PracticeSession.STATUS_COMPLETED)
        self.assertEqual(MemoryReview.objects.filter(exercise_attempt__session=session).count(), AttemptMemoryCard.objects.filter(attempt__session=session).count())
        self.assertEqual(UserExerciseHistory.objects.filter(user=self.user).count(), session.attempts.count())
        self.assertEqual(ExerciseEventConsumerReceipt.objects.filter(consumer_name='learning_progress_v1').count(), session.attempts.count())
        self.assertEqual(UserLearningStats.objects.get(user=self.user).total_exercises_completed, session.attempts.count())

        first_attempt = ExerciseAttempt.objects.get(id=first_attempt_id)
        duplicate = self.client.post(
            f'/api/exercise-attempts/{first_attempt.id}/submit/',
            {'answer': self._answer_for_attempt(first_attempt), 'duration_ms': 1000},
            format='json',
        )
        self.assertEqual(duplicate.status_code, status.HTTP_200_OK)
        self.assertEqual(MemoryReview.objects.filter(exercise_attempt=first_attempt).count(), first_attempt.memory_card_links.count())
        self.assertEqual(UserExerciseHistory.objects.filter(user=self.user).count(), session.attempts.count())

        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        denied = other_client.post(
            f'/api/exercise-attempts/{first_attempt.id}/submit/',
            {'answer': self._answer_for_attempt(first_attempt), 'duration_ms': 1000},
            format='json',
        )
        self.assertEqual(denied.status_code, status.HTTP_404_NOT_FOUND)

    def test_consumer_reprocessing_same_event_is_safe(self):
        session = PracticeSession.objects.create(user=self.user, status=PracticeSession.STATUS_IN_PROGRESS)
        started = StartExerciseUseCase().execute(
            user=self.user,
            session=session,
            kind='translation_ru',
            config={'handler_version': 1},
            order=0,
            learning_items=(LearningItemRef('memory_card', self.due_card.id, {'word_id': self.words[0].id, 'difficulty': 1}),),
        )
        SubmitExerciseAnswerUseCase(spaced_repetition_service=FakeSpacedRepetitionService()).execute(
            user=self.user,
            attempt_id=started.attempt.id,
            answer={'text': started.attempt.private_state['correct_answer']},
            duration_ms=1000,
        )
        attempt = ExerciseAttempt.objects.get(id=started.attempt.id)
        event = build_exercise_submitted_event(attempt)
        consumer = LearningProgressConsumer()

        before = UserExerciseHistory.objects.filter(user=self.user, word=self.words[0]).count()
        self.assertTrue(consumer.handle(event))
        self.assertFalse(consumer.handle(event))
        self.assertEqual(UserExerciseHistory.objects.filter(user=self.user, word=self.words[0]).count(), before + 1)
