import random
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from dictionary.models import Word
from learning.application.sessions import GetPracticeSessionSummaryUseCase
from learning.application.use_cases import StartExerciseUseCase, SubmitExerciseAnswerUseCase
from learning.exercises.base import ExerciseHandler
from learning.exercises.dto import ExerciseGenerationContext, GeneratedExercise, GradeResult, ItemGradeResult, LearningItemRef
from learning.exercises.exceptions import InvalidExerciseAnswerError, InvalidExerciseConfigError, UnknownExerciseHandlerError
from learning.exercises.handlers.multiple_choice import MultipleChoiceHandler
from learning.exercises.handlers.matching import MatchingHandler, MatchingHandlerV2
from learning.exercises.handlers.translation_cn import TranslationCnHandler
from learning.exercises.handlers.writing import WritingHandler
from learning.application.handler_versions import ACTIVE_HANDLER_VERSIONS
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


class MatchingHandlerV2Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='matching-v2-user', password='pass12345')
        self.words = [
            Word.objects.create(
                hanzi=f'm{index}',
                pinyin_numeric=f'm{index}',
                pinyin_graphic=f'm{index}',
                translation=translation,
                difficulty=1,
            )
            for index, translation in enumerate(['same', 'same', 'third'])
        ]
        self.session = PracticeSession.objects.create(user=self.user, status=PracticeSession.STATUS_IN_PROGRESS)
        self.cards = [
            MemoryCard.objects.create(
                user=self.user,
                learning_item=word,
                direction=MemoryCard.DIRECTION_CN_TO_RU,
                due_at=timezone.now(),
            )
            for word in self.words
        ]
        self.items = tuple(
            LearningItemRef('memory_card', card.id, {'word_id': card.learning_item_id, 'difficulty': 1})
            for card in self.cards
        )
        self.handler = MatchingHandlerV2()

    def _generated(self):
        return self.handler.generate(ExerciseGenerationContext(
            user=self.user,
            config={},
            learning_items=self.items,
        ))

    def _attempt(self, generated=None):
        generated = generated or self._generated()
        position = self.session.attempts.count()
        return ExerciseAttempt.objects.create(
            session=self.session,
            user=self.user,
            exercise_type='matching',
            kind='matching',
            handler_version=2,
            position=position,
            order=position,
            public_payload=generated.public_payload,
            private_state=generated.private_state,
            grading_payload=generated.private_state,
        )

    def _correct_answer(self, attempt):
        return {'matches': dict(attempt.private_state['correct_matches'])}

    def test_generate_uses_unique_opaque_ids_without_private_state_in_public_payload(self):
        generated = self._generated()
        payload = generated.public_payload
        left_ids = [item['id'] for item in payload['left_items']]
        right_ids = [item['id'] for item in payload['right_items']]

        self.assertEqual(payload['kind'], 'matching')
        self.assertEqual(payload['handler_version'], 2)
        self.assertEqual(len(left_ids), len(set(left_ids)))
        self.assertEqual(len(right_ids), len(set(right_ids)))
        self.assertTrue(all(item_id.startswith('left-') for item_id in left_ids))
        self.assertTrue(all(item_id.startswith('right-') for item_id in right_ids))
        self.assertNotIn('word_id', payload)
        self.assertNotIn('pairs', payload)
        self.assertNotIn('correct_matches', payload)
        self.assertNotIn('private_state', payload)
        self.assertFalse(set(left_ids + right_ids) & {str(word.id) for word in self.words})
        self.assertFalse(set(left_ids + right_ids) & {str(card.id) for card in self.cards})
        self.assertIn('correct_matches', generated.private_state)
        same_text_items = [item for item in payload['right_items'] if item['text'] == 'same']
        self.assertEqual(len(same_text_items), 2)
        self.assertNotEqual(same_text_items[0]['id'], same_text_items[1]['id'])

    def test_grade_accepts_full_answer_and_returns_item_level_results(self):
        attempt = self._attempt()
        grade = self.handler.grade(attempt, self._correct_answer(attempt))

        self.assertTrue(grade.is_fully_correct)
        self.assertEqual(grade.score, 1.0)
        self.assertEqual(len(grade.item_results), 3)
        self.assertEqual(
            [item.source_item_id for item in grade.item_results],
            [card.id for card in self.cards],
        )

    def test_grade_partial_answer_scores_each_item_independently(self):
        attempt = self._attempt()
        answer = self._correct_answer(attempt)
        first_left, second_left = attempt.private_state['left_ids'][:2]
        first_right = attempt.private_state['correct_matches'][first_left]
        second_right = attempt.private_state['correct_matches'][second_left]
        answer['matches'][first_left] = second_right
        answer['matches'][second_left] = first_right

        grade = self.handler.grade(attempt, answer)

        self.assertFalse(grade.is_fully_correct)
        self.assertEqual(grade.score, 1 / 3)
        self.assertEqual([item.is_correct for item in grade.item_results].count(False), 2)

    def test_validate_rejects_unknown_duplicate_incomplete_extra_and_wrong_type_answers(self):
        attempt = self._attempt()
        answer = self._correct_answer(attempt)
        left_ids = attempt.private_state['left_ids']
        right_ids = list(attempt.private_state['correct_matches'].values())

        with self.assertRaises(InvalidExerciseAnswerError):
            self.handler.validate_answer(attempt, {'translations': ['same', 'same', 'third']})
        with self.assertRaises(InvalidExerciseAnswerError):
            self.handler.validate_answer(attempt, ['not-an-object'])
        with self.assertRaises(InvalidExerciseAnswerError):
            self.handler.validate_answer(attempt, {'matches': {**answer['matches'], 'left-unknown': right_ids[0]}})
        unknown_right = {'matches': dict(answer['matches'])}
        unknown_right['matches'][left_ids[0]] = 'right-unknown'
        with self.assertRaises(InvalidExerciseAnswerError):
            self.handler.validate_answer(attempt, unknown_right)
        duplicate_right = {'matches': dict(answer['matches'])}
        duplicate_right['matches'][left_ids[1]] = duplicate_right['matches'][left_ids[0]]
        with self.assertRaises(InvalidExerciseAnswerError):
            self.handler.validate_answer(attempt, duplicate_right)
        incomplete = {'matches': dict(answer['matches'])}
        incomplete['matches'].pop(left_ids[0])
        with self.assertRaises(InvalidExerciseAnswerError):
            self.handler.validate_answer(attempt, incomplete)

    def test_reordering_public_arrays_does_not_change_answer_correctness(self):
        generated = self._generated()
        generated.public_payload['left_items'] = list(reversed(generated.public_payload['left_items']))
        generated.public_payload['right_items'] = list(reversed(generated.public_payload['right_items']))
        attempt = self._attempt(generated)

        grade = self.handler.grade(attempt, self._correct_answer(attempt))

        self.assertTrue(grade.is_fully_correct)

    def test_v1_and_v2_answer_contracts_are_not_interchangeable(self):
        v1 = MatchingHandler()
        v1_generated = v1.generate(ExerciseGenerationContext(user=self.user, config={}, learning_items=self.items[:2]))
        v1_attempt = ExerciseAttempt.objects.create(
            session=self.session,
            user=self.user,
            exercise_type='matching',
            kind='matching',
            handler_version=1,
            private_state=v1_generated.private_state,
        )
        v2_attempt = self._attempt()

        v1.validate_answer(v1_attempt, {'translations': [pair['translation'] for pair in v1_attempt.private_state['pairs']]})
        with self.assertRaises(InvalidExerciseAnswerError):
            v1.validate_answer(v1_attempt, self._correct_answer(v2_attempt))
        with self.assertRaises(InvalidExerciseAnswerError):
            self.handler.validate_answer(v2_attempt, {'translations': ['same', 'same', 'third']})


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

    def test_legacy_practice_routes_return_404(self):
        session = PracticeSession.objects.create(user=self.user)
        routes = [
            ('get', '/api/learning/exercises/generate/'),
            ('post', '/api/learning/exercises/submit/'),
            ('post', '/api/learning/practice/session/'),
            ('get', f'/api/learning/practice/session/{session.id}/'),
        ]

        for method, route in routes:
            response = getattr(self.client, method)(route, {}, format='json')
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, route)

    def test_removed_legacy_routes_do_not_create_attempts_or_update_fsrs(self):
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
        before_attempts = ExerciseAttempt.objects.count()
        before_history = UserExerciseHistory.objects.count()
        before_reviews = MemoryReview.objects.count()

        response = self.client.post(
            '/api/learning/exercises/submit/',
            {'attempt_id': attempt.id, 'answer': {'selected_index': 1}, 'time_spent': 2},
            format='json',
        )

        attempt.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(ExerciseAttempt.objects.count(), before_attempts)
        self.assertEqual(UserExerciseHistory.objects.count(), before_history)
        self.assertEqual(MemoryReview.objects.count(), before_reviews)
        self.assertEqual(attempt.status, ExerciseAttempt.STATUS_PENDING)
        self.assertIsNone(attempt.is_correct)

    def test_persisted_practice_endpoint_is_not_marked_as_legacy(self):
        response = self.client.post(
            '/api/practice-sessions/',
            {'requested_cards_count': 1, 'allowed_types': ['multiple_choice'], 'rng_seed': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('Deprecation', response)
        self.assertNotIn('X-Sinosphere-Deprecated-Endpoint', response)

    def test_persisted_create_rejects_legacy_alias_fields(self):
        response = self.client.post(
            '/api/practice-sessions/',
            {
                'count': 1,
                'type': 'mixed',
                'exercise_types': ['multiple_choice'],
                'includeReview': True,
                'includeNew': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('count', response.data)
        self.assertIn('exercise_types', response.data)
        self.assertIn('includeReview', response.data)

    def test_persisted_submit_rejects_legacy_body_fields(self):
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

        response = self.client.post(
            f'/api/exercise-attempts/{attempt.id}/submit/',
            {
                'attempt_id': attempt.id,
                'answer': {'selected_index': 1},
                'time_spent': 2,
                'exercise_type': 'multiple_choice',
            },
            format='json',
        )

        attempt.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('attempt_id', response.data)
        self.assertIn('time_spent', response.data)
        self.assertIsNone(attempt.is_correct)

    def test_matching_v1_attempt_still_submits_through_persisted_endpoint(self):
        handler = MatchingHandler()
        words = [
            self.word,
            Word.objects.get(hanzi='hao'),
        ]
        cards = [
            MemoryCard.objects.create(
                user=self.user,
                learning_item=word,
                direction=MemoryCard.DIRECTION_CN_TO_RU,
                due_at=timezone.now(),
            )
            for word in words
        ]
        items = tuple(
            LearningItemRef('memory_card', card.id, {'word_id': card.learning_item_id, 'difficulty': 1})
            for card in cards
        )
        generated = handler.generate(ExerciseGenerationContext(user=self.user, config={}, learning_items=items))
        session = PracticeSession.objects.create(user=self.user, requested_cards_count=2, generated_exercises_count=1)
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            exercise_type='matching',
            kind='matching',
            handler_version=1,
            public_payload=generated.public_payload,
            private_state=generated.private_state,
        )
        for index, card in enumerate(cards):
            AttemptMemoryCard.objects.create(attempt=attempt, memory_card=card, position=index)

        response = self.client.post(
            f'/api/exercise-attempts/{attempt.id}/submit/',
            {'answer': {'translations': [pair['translation'] for pair in generated.private_state['pairs']]}, 'duration_ms': 1000},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_correct'])
        self.assertEqual(MemoryReview.objects.filter(exercise_attempt=attempt).count(), 2)
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
        self.assertEqual(matching_attempt.handler_version, 2)
        self.assertGreater(len(matching_attempt.learning_items), 1)
        self.assertIn('correct_matches', matching_attempt.private_state)
        self.assertNotIn('correct_matches', matching_attempt.public_payload)
        self.assertIn('left_items', matching_attempt.public_payload)
        self.assertIn('right_items', matching_attempt.public_payload)
        self.assertNotIn('pairs', matching_attempt.public_payload)

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

        grade = handler.grade(attempt, {'text': self.word.hanzi})

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


class PracticeSessionSummaryApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='summary-user', password='pass12345')
        self.other_user = User.objects.create_user(username='summary-other', password='pass12345')
        UserProfile.objects.get_or_create(user=self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.words = [
            Word.objects.create(
                hanzi=f's{index}',
                pinyin_numeric=f's{index}',
                pinyin_graphic=f's{index}',
                translation=f'summary-{index}',
                difficulty=1,
            )
            for index in range(4)
        ]
        self.cards = [
            MemoryCard.objects.create(
                user=self.user,
                learning_item=word,
                direction=MemoryCard.DIRECTION_CN_TO_RU,
                due_at=timezone.now() + timedelta(days=index + 1),
            )
            for index, word in enumerate(self.words)
        ]

    def _session(self, *, status=PracticeSession.STATUS_COMPLETED, requested_cards_count=4):
        return PracticeSession.objects.create(
            user=self.user,
            status=status,
            requested_cards_count=requested_cards_count,
            requested_count=requested_cards_count,
            generated_exercises_count=3,
            completed_at=timezone.now() if status == PracticeSession.STATUS_COMPLETED else None,
        )

    def _attempt(self, session, *, order, is_correct, score, item_results):
        attempt = ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            word=self.words[min(order, len(self.words) - 1)],
            exercise_type='matching' if len(item_results) > 1 else 'translation_ru',
            kind='matching' if len(item_results) > 1 else 'translation_ru',
            handler_version=2 if len(item_results) > 1 else 1,
            order=order,
            position=order,
            is_correct=is_correct,
            score=Decimal(str(score)),
            status=ExerciseAttempt.STATUS_SUBMITTED if is_correct is not None else ExerciseAttempt.STATUS_PENDING,
            submitted_at=timezone.now() if is_correct is not None else None,
            result={
                'score': score,
                'is_fully_correct': is_correct,
                'item_results': item_results,
                'feedback': {},
            } if is_correct is not None else {},
        )
        for index, item in enumerate(item_results):
            card = MemoryCard.objects.get(id=item['source_item_id'])
            AttemptMemoryCard.objects.create(
                attempt=attempt,
                memory_card=card,
                position=index,
                is_correct=item['is_correct'],
                score=Decimal(str(item['score'])),
                fsrs_rating=3 if item['is_correct'] else 1,
            )
        return attempt

    def test_summary_completed_session(self):
        session = self._session(requested_cards_count=4)
        self._attempt(session, order=0, is_correct=True, score=1, item_results=[
            {'source_item_id': self.cards[0].id, 'is_correct': True, 'score': 1.0},
        ])
        self._attempt(session, order=1, is_correct=False, score=0.5, item_results=[
            {'source_item_id': self.cards[1].id, 'is_correct': True, 'score': 1.0},
            {'source_item_id': self.cards[2].id, 'is_correct': False, 'score': 0.0},
        ])
        self._attempt(session, order=2, is_correct=True, score=1, item_results=[
            {'source_item_id': self.cards[3].id, 'is_correct': True, 'score': 1.0},
        ])

        response = self.client.get(f'/api/practice-sessions/{session.id}/summary/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['session_id'], session.id)
        self.assertEqual(response.data['status'], PracticeSession.STATUS_COMPLETED)
        self.assertEqual(response.data['learning_items_count'], 4)
        self.assertEqual(response.data['visual_exercises_count'], 3)
        self.assertEqual(response.data['completed_exercises_count'], 3)
        self.assertEqual(response.data['correct_exercises_count'], 2)
        self.assertEqual(response.data['incorrect_exercises_count'], 1)
        self.assertEqual(response.data['average_score'], 0.8333)
        self.assertEqual(response.data['item_results'], {'total': 4, 'correct': 3, 'incorrect': 1})
        self.assertEqual(response.data['reviews']['good'], 3)
        self.assertEqual(response.data['reviews']['again'], 1)
        self.assertIn('next_review_at', response.data)
        self.assertNotIn('xp_earned', response.data)
        self.assertNotIn('fsrs_state', response.data)

    def test_summary_in_progress_session_returns_partial_state(self):
        session = self._session(status=PracticeSession.STATUS_IN_PROGRESS, requested_cards_count=4)
        self._attempt(session, order=0, is_correct=True, score=1, item_results=[
            {'source_item_id': self.cards[0].id, 'is_correct': True, 'score': 1.0},
        ])
        ExerciseAttempt.objects.create(
            session=session,
            user=self.user,
            exercise_type='translation_ru',
            kind='translation_ru',
            handler_version=1,
            order=1,
            position=1,
            status=ExerciseAttempt.STATUS_PENDING,
        )

        response = self.client.get(f'/api/practice-sessions/{session.id}/summary/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], PracticeSession.STATUS_IN_PROGRESS)
        self.assertEqual(response.data['visual_exercises_count'], 2)
        self.assertEqual(response.data['completed_exercises_count'], 1)
        self.assertEqual(response.data['correct_exercises_count'], 1)
        self.assertEqual(response.data['item_results'], {'total': 1, 'correct': 1, 'incorrect': 0})

    def test_summary_access_denied_and_not_found(self):
        other_session = PracticeSession.objects.create(user=self.other_user, status=PracticeSession.STATUS_COMPLETED)

        missing_response = self.client.get('/api/practice-sessions/999999/summary/')
        denied_response = self.client.get(f'/api/practice-sessions/{other_session.id}/summary/')

        self.assertEqual(missing_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(denied_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_summary_empty_session(self):
        session = PracticeSession.objects.create(
            user=self.user,
            status=PracticeSession.STATUS_COMPLETED,
            requested_cards_count=0,
            requested_count=0,
            generated_exercises_count=0,
            completed_at=timezone.now(),
        )

        response = self.client.get(f'/api/practice-sessions/{session.id}/summary/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['visual_exercises_count'], 0)
        self.assertEqual(response.data['completed_exercises_count'], 0)
        self.assertIsNone(response.data['average_score'])
        self.assertEqual(response.data['item_results'], {'total': 0, 'correct': 0, 'incorrect': 0})

    def test_summary_query_count_does_not_grow_with_attempts(self):
        session = self._session(requested_cards_count=4)
        for index, card in enumerate(self.cards):
            self._attempt(session, order=index, is_correct=True, score=1, item_results=[
                {'source_item_id': card.id, 'is_correct': True, 'score': 1.0},
            ])

        with self.assertNumQueries(4):
            GetPracticeSessionSummaryUseCase().execute(user=self.user, session_id=session.id)


class ExerciseAttemptResultApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='result-user', password='pass12345')
        self.other_user = User.objects.create_user(username='result-other', password='pass12345')
        self.word = Word.objects.create(
            hanzi='r',
            pinyin_numeric='r',
            pinyin_graphic='r',
            translation='result',
            difficulty=1,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.session = PracticeSession.objects.create(
            user=self.user,
            status=PracticeSession.STATUS_IN_PROGRESS,
            requested_cards_count=1,
            generated_exercises_count=1,
        )

    def test_result_submitted_attempt(self):
        attempt = ExerciseAttempt.objects.create(
            session=self.session,
            user=self.user,
            word=self.word,
            exercise_type='translation_ru',
            kind='translation_ru',
            handler_version=1,
            status=ExerciseAttempt.STATUS_SUBMITTED,
            is_correct=True,
            score=Decimal('1.0'),
            submitted_at=timezone.now(),
            result={
                'score': 1.0,
                'is_fully_correct': True,
                'item_results': [{'source_item_id': self.word.id, 'is_correct': True, 'score': 1.0}],
                'feedback': {'correct_answer': 'result', 'explanation': 'Good'},
            },
            private_state={'accepted_answers': ['result']},
        )

        response = self.client.get(f'/api/exercise-attempts/{attempt.id}/result/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['attempt_id'], attempt.id)
        self.assertEqual(response.data['status'], ExerciseAttempt.STATUS_SUBMITTED)
        self.assertTrue(response.data['is_correct'])
        self.assertEqual(response.data['correct_answer'], 'result')
        self.assertEqual(response.data['explanation'], 'Good')
        self.assertEqual(len(response.data['item_results']), 1)
        self.assertIn('progress', response.data)
        self.assertNotIn('private_state', response.data)
        self.assertNotIn('fsrs_state', response.data)
        self.assertNotIn('memory_card_id', response.data)

    def test_result_pending_attempt_does_not_expose_feedback(self):
        attempt = ExerciseAttempt.objects.create(
            session=self.session,
            user=self.user,
            word=self.word,
            exercise_type='translation_ru',
            kind='translation_ru',
            handler_version=1,
            status=ExerciseAttempt.STATUS_PENDING,
            private_state={'correct_answer': 'secret'},
        )

        response = self.client.get(f'/api/exercise-attempts/{attempt.id}/result/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], ExerciseAttempt.STATUS_PENDING)
        self.assertNotIn('is_correct', response.data)
        self.assertNotIn('correct_answer', response.data)
        self.assertNotIn('explanation', response.data)
        self.assertNotIn('item_results', response.data)

    def test_result_access_denied_and_not_found(self):
        other_session = PracticeSession.objects.create(user=self.other_user)
        other_attempt = ExerciseAttempt.objects.create(
            session=other_session,
            user=self.other_user,
            exercise_type='translation_ru',
            kind='translation_ru',
        )

        missing_response = self.client.get('/api/exercise-attempts/999999/result/')
        denied_response = self.client.get(f'/api/exercise-attempts/{other_attempt.id}/result/')

        self.assertEqual(missing_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(denied_response.status_code, status.HTTP_404_NOT_FOUND)


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
            if attempt.handler_version == 2:
                return {'matches': dict(attempt.private_state['correct_matches'])}
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

    def test_new_matching_sessions_use_v2_and_submit_with_matches_map(self):
        cards = [
            MemoryCard.objects.get_or_create(
                user=self.user,
                learning_item=word,
                direction=MemoryCard.DIRECTION_CN_TO_RU,
                defaults={'due_at': timezone.now() - timedelta(minutes=5), 'parameter_set_version': 9},
            )[0]
            for word in self.words[:3]
        ]

        response = self.client.post(
            '/api/practice-sessions/',
            {
                'requested_cards_count': 3,
                'allowed_types': ['matching'],
                'include_review': True,
                'include_new': False,
                'rng_seed': 7,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = response.data['current_exercise']
        self.assertEqual(payload['kind'], 'matching')
        self.assertEqual(payload['handler_version'], ACTIVE_HANDLER_VERSIONS['matching'])
        self.assertEqual(payload['handler_version'], 2)
        self.assertIn('left_items', payload)
        self.assertIn('right_items', payload)
        self.assertNotIn('pairs', payload)
        self.assertNotIn('correct_matches', payload)
        self.assertNotIn('private_state', payload)

        session = PracticeSession.objects.get(id=response.data['session_id'])
        attempt = session.attempts.get()
        self.assertEqual(attempt.handler_version, 2)
        self.assertEqual(AttemptMemoryCard.objects.filter(attempt=attempt).count(), 3)

        with self.captureOnCommitCallbacks(execute=True):
            submit = self.client.post(
                f'/api/exercise-attempts/{attempt.id}/submit/',
                {'answer': {'matches': dict(attempt.private_state['correct_matches'])}, 'duration_ms': 1234},
                format='json',
            )

        self.assertEqual(submit.status_code, status.HTTP_200_OK)
        self.assertTrue(submit.data['is_correct'])
        self.assertEqual(len(submit.data['item_results']), 3)
        self.assertEqual(MemoryReview.objects.filter(exercise_attempt=attempt).count(), 3)
        self.assertEqual(
            sorted(MemoryReview.objects.filter(exercise_attempt=attempt).values_list('memory_card_id', flat=True)),
            sorted(card.id for card in cards),
        )

        restored = self.client.get(f'/api/practice-sessions/{session.id}/')
        self.assertEqual(restored.status_code, status.HTTP_200_OK)
        self.assertEqual(restored.data['status'], PracticeSession.STATUS_COMPLETED)
        self.assertIsNone(restored.data['current_exercise'])

        duplicate = self.client.post(
            f'/api/exercise-attempts/{attempt.id}/submit/',
            {'answer': {'matches': dict(attempt.private_state['correct_matches'])}, 'duration_ms': 1234},
            format='json',
        )
        self.assertEqual(duplicate.status_code, status.HTTP_200_OK)
        self.assertEqual(MemoryReview.objects.filter(exercise_attempt=attempt).count(), 3)

    def test_matching_v1_and_v2_attempts_coexist_with_separate_answer_contracts(self):
        cards = [
            MemoryCard.objects.get_or_create(
                user=self.user,
                learning_item=word,
                direction=MemoryCard.DIRECTION_CN_TO_RU,
                defaults={'due_at': timezone.now(), 'parameter_set_version': 9},
            )[0]
            for word in self.words[:2]
        ]
        session = PracticeSession.objects.create(user=self.user, status=PracticeSession.STATUS_IN_PROGRESS)
        items = tuple(
            LearningItemRef('memory_card', card.id, {'word_id': card.learning_item_id, 'difficulty': 1})
            for card in cards
        )
        v1_started = StartExerciseUseCase().execute(
            user=self.user,
            session=session,
            kind='matching',
            config={'handler_version': 1},
            order=0,
            learning_items=items,
        )
        v2_started = StartExerciseUseCase().execute(
            user=self.user,
            session=session,
            kind='matching',
            config={'handler_version': 2},
            order=1,
            learning_items=items,
        )

        self.assertEqual(v1_started.attempt.handler_version, 1)
        self.assertEqual(v2_started.attempt.handler_version, 2)

        v1_response = self.client.post(
            f'/api/exercise-attempts/{v1_started.attempt.id}/submit/',
            {
                'answer': {'translations': [pair['translation'] for pair in v1_started.attempt.private_state['pairs']]},
                'duration_ms': 1000,
            },
            format='json',
        )
        self.assertEqual(v1_response.status_code, status.HTTP_200_OK)

        v2_legacy_shape = self.client.post(
            f'/api/exercise-attempts/{v2_started.attempt.id}/submit/',
            {'answer': {'translations': ['wrong', 'shape']}, 'duration_ms': 1000},
            format='json',
        )
        self.assertEqual(v2_legacy_shape.status_code, status.HTTP_400_BAD_REQUEST)

        v2_response = self.client.post(
            f'/api/exercise-attempts/{v2_started.attempt.id}/submit/',
            {'answer': {'matches': dict(v2_started.attempt.private_state['correct_matches'])}, 'duration_ms': 1000},
            format='json',
        )
        self.assertEqual(v2_response.status_code, status.HTTP_200_OK)

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

