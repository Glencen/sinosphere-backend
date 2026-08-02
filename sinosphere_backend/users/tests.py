from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from dictionary.models import Word
from dictionary.serializers import WordSerializer
from learning.models import MemoryCard, MemoryReview
from users.models import UserProfile, UserWord
from users.serializers import UserWordListSerializer, UserWordSerializer


User = get_user_model()


class WordContractSerializerTests(APITestCase):
    def test_word_serializer_exposes_pinyin_aliases(self):
        word = Word.objects.create(
            hanzi='你',
            pinyin_numeric='ni3',
            pinyin_graphic='nǐ',
            translation='ты; вы',
            difficulty=1,
        )

        data = WordSerializer(word).data

        self.assertEqual(data['hanzi'], '你')
        self.assertEqual(data['pinyin'], 'nǐ')
        self.assertEqual(data['pinyin_graphic'], 'nǐ')
        self.assertEqual(data['pinyin_numeric'], 'ni3')

    def test_user_word_serializers_are_dictionary_membership_only(self):
        user = User.objects.create_user(username='alice', password='pass12345')
        word = Word.objects.create(
            hanzi='好',
            pinyin_numeric='hao3',
            pinyin_graphic='hǎo',
            translation='хороший; хорошо',
            difficulty=1,
        )
        user_word = UserWord.objects.create(user=user, word=word, notes='saved')

        create_data = UserWordSerializer(user_word).data
        list_data = UserWordListSerializer(user_word).data

        for data in (create_data, list_data):
            self.assertIsInstance(data['word'], dict)
            self.assertEqual(data['word']['hanzi'], '好')
            self.assertEqual(data['word']['pinyin'], 'hǎo')
            self.assertEqual(data['notes'], 'saved')
            self.assertNotIn('word_info', data)
            self.assertNotIn('word_detail', data)
            self.assertNotIn('due', data)
            self.assertNotIn('state', data)
            self.assertNotIn('review_urgency', data)
            self.assertNotIn('fsrs_state', data)


class UserDictionaryApiContractTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='pass12345')
        UserProfile.objects.get_or_create(user=self.user)
        self.word = Word.objects.create(
            hanzi='学',
            pinyin_numeric='xue2',
            pinyin_graphic='xué',
            translation='учиться; изучать',
            difficulty=1,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_add_word_returns_dictionary_membership(self):
        response = self.client.post(
            '/api/me/dictionary/',
            {'word_id': self.word.id, 'notes': 'important'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['word']['hanzi'], '学')
        self.assertEqual(response.data['notes'], 'important')
        self.assertNotIn('word_info', response.data)
        self.assertNotIn('word_detail', response.data)
        self.assertNotIn('due', response.data)
        self.assertFalse(MemoryCard.objects.filter(user=self.user, learning_item=self.word).exists())

    def test_add_word_rejects_duplicates(self):
        UserWord.objects.create(user=self.user, word=self.word)

        response = self.client.post('/api/me/dictionary/', {'word_id': self.word.id}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('word_id', response.data)

    def test_add_word_requires_existing_word_id(self):
        missing_response = self.client.post('/api/me/dictionary/', {}, format='json')
        unknown_response = self.client.post('/api/me/dictionary/', {'word_id': 999999}, format='json')

        self.assertEqual(missing_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unknown_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('word_id', missing_response.data)
        self.assertIn('word_id', unknown_response.data)

    def test_dictionary_list_is_membership_only_and_review_queue_uses_memory_cards(self):
        user_word = UserWord.objects.create(user=self.user, word=self.word, notes='saved')
        card = MemoryCard.objects.create(
            user=self.user,
            learning_item=self.word,
            direction=MemoryCard.DIRECTION_CN_TO_RU,
            due_at=timezone.now() - timedelta(minutes=1),
        )

        dictionary_response = self.client.get('/api/me/dictionary/')
        review_response = self.client.get('/api/me/review/words/')

        self.assertEqual(dictionary_response.status_code, status.HTTP_200_OK)
        self.assertEqual(review_response.status_code, status.HTTP_200_OK)

        entry = dictionary_response.data[0]
        self.assertEqual(entry['id'], user_word.id)
        self.assertEqual(entry['word']['hanzi'], '学')
        self.assertEqual(entry['notes'], 'saved')
        self.assertNotIn('next_review', entry)
        self.assertNotIn('due', entry)

        review_entry = review_response.data['words_for_review'][0]
        self.assertEqual(review_entry['id'], card.id)
        self.assertEqual(review_entry['word']['hanzi'], '学')
        self.assertEqual(review_entry['direction'], MemoryCard.DIRECTION_CN_TO_RU)
        self.assertIn('next_review', review_entry)
        self.assertNotIn('fsrs_state', review_entry)
        self.assertEqual(review_response.data['total_for_review'], 1)

    def test_review_logs_are_memory_reviews_without_private_state(self):
        card = MemoryCard.objects.create(
            user=self.user,
            learning_item=self.word,
            direction=MemoryCard.DIRECTION_CN_TO_RU,
            due_at=timezone.now(),
        )
        MemoryReview.objects.create(
            memory_card=card,
            rating=3,
            reviewed_at=timezone.now(),
            duration_ms=1200,
            previous_state={'hidden': True},
            resulting_state={'hidden': True},
            fsrs_log={'hidden': True},
            scheduler_version='fsrs-py',
            parameter_set_version=1,
        )

        response = self.client.get('/api/me/review/logs/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['card']['word']['hanzi'], '学')
        self.assertNotIn('previous_state', response.data[0])
        self.assertNotIn('resulting_state', response.data[0])
        self.assertNotIn('fsrs_log', response.data[0])

    def test_review_queue_query_count_is_bounded(self):
        for index in range(20):
            word = Word.objects.create(
                hanzi=f'词{index}',
                pinyin_numeric=f'ci2-{index}',
                pinyin_graphic=f'cí-{index}',
                translation=f'слово-{index}',
                difficulty=1,
            )
            card = MemoryCard.objects.create(
                user=self.user,
                learning_item=word,
                direction=MemoryCard.DIRECTION_CN_TO_RU,
                due_at=timezone.now() - timedelta(minutes=index + 1),
            )
            MemoryReview.objects.create(
                memory_card=card,
                rating=3,
                reviewed_at=timezone.now() - timedelta(days=1),
                duration_ms=1000,
                scheduler_version='fsrs-py',
                parameter_set_version=1,
            )

        with self.assertNumQueries(6):
            response = self.client.get('/api/me/review/words/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_for_review'], 20)

    def test_removed_user_review_routes_return_404(self):
        responses = [
            self.client.get('/api/dictionary/'),
            self.client.get('/api/words-for-review/'),
            self.client.get(f'/api/check-word/{self.word.id}/'),
            self.client.post('/api/me/dictionary/1/review/', {}),
            self.client.post('/api/me/optimize-fsrs/', {}),
            self.client.post('/api/me/words/1/reset/', {}),
        ]

        for response in responses:
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_dictionary_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get('/api/me/dictionary/')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(JWT_REFRESH_COOKIE_NAME='test_refresh')
class JwtCookieAuthTests(APITestCase):
    def test_login_sets_refresh_cookie_and_refresh_uses_cookie_only(self):
        User.objects.create_user(username='alice', password='pass12345')

        login_response = self.client.post(
            '/api/login/',
            {'username': 'alice', 'password': 'pass12345'},
            format='json',
        )

        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertIn('access', login_response.data)
        self.assertNotIn('refresh', login_response.data)
        self.assertIn('test_refresh', login_response.cookies)
        self.assertTrue(login_response.cookies['test_refresh']['httponly'])

        self.client.cookies['test_refresh'] = login_response.cookies['test_refresh'].value
        refresh_response = self.client.post('/api/token/refresh/', {}, format='json')

        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        self.assertIn('access', refresh_response.data)
        self.assertNotIn('refresh', refresh_response.data)

    def test_refresh_without_cookie_is_rejected(self):
        response = self.client.post('/api/token/refresh/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
