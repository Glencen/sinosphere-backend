from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from dictionary.models import Word
from dictionary.serializers import WordSerializer
from users.models import UserProfile, UserWord
from users.serializers import UserWordListSerializer, UserWordSerializer


User = get_user_model()


class WordContractSerializerTests(TestCase):
    def test_word_serializer_exposes_pinyin_aliases(self):
        word = Word.objects.create(
            hanzi='你',
            pinyin_numeric='ni3',
            pinyin_graphic='nǐ',
            translation='you',
            difficulty=1,
        )

        data = WordSerializer(word).data

        self.assertEqual(data['hanzi'], '你')
        self.assertEqual(data['pinyin'], 'nǐ')
        self.assertEqual(data['pinyin_graphic'], 'nǐ')
        self.assertEqual(data['pinyin_numeric'], 'ni3')

    def test_user_word_serializers_use_same_nested_word_contract(self):
        user = User.objects.create_user(username='alice', password='pass12345')
        word = Word.objects.create(
            hanzi='好',
            pinyin_numeric='hao3',
            pinyin_graphic='hǎo',
            translation='good; well',
            difficulty=1,
        )
        user_word = UserWord.objects.create(user=user, word=word)

        create_data = UserWordSerializer(user_word).data
        list_data = UserWordListSerializer(user_word).data

        for data in (create_data, list_data):
            self.assertIsInstance(data['word'], dict)
            self.assertEqual(data['word']['hanzi'], '好')
            self.assertEqual(data['word']['pinyin'], 'hǎo')
            self.assertNotIn('word_info', data)
            self.assertNotIn('word_detail', data)


class UserDictionaryApiContractTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='pass12345')
        UserProfile.objects.get_or_create(user=self.user)
        self.word = Word.objects.create(
            hanzi='学',
            pinyin_numeric='xue2',
            pinyin_graphic='xué',
            translation='study; learn',
            difficulty=1,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_add_word_returns_unified_word_objects(self):
        response = self.client.post('/api/me/dictionary/', {'word_id': self.word.id}, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['word']['hanzi'], '学')
        self.assertEqual(response.data['word']['pinyin'], 'xué')
        self.assertNotIn('word_info', response.data)
        self.assertNotIn('word_detail', response.data)

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

    def test_dictionary_list_and_review_payloads_are_consistent(self):
        due_word = UserWord.objects.create(
            user=self.user,
            word=self.word,
            due=timezone.now() - timedelta(minutes=1),
            state=1,
        )

        dictionary_response = self.client.get('/api/me/dictionary/')
        review_response = self.client.get('/api/me/review/words/')

        self.assertEqual(dictionary_response.status_code, status.HTTP_200_OK)
        self.assertEqual(review_response.status_code, status.HTTP_200_OK)

        entry = dictionary_response.data[0]
        self.assertEqual(entry['id'], due_word.id)
        self.assertEqual(entry['word']['hanzi'], '学')
        self.assertNotIn('word_info', entry)
        self.assertIn('next_review', entry)
        self.assertIn('due', entry)

        review_entry = review_response.data['words_for_review'][0]
        self.assertEqual(review_entry['word']['hanzi'], '学')
        self.assertNotIn('word_info', review_entry)
        self.assertEqual(review_response.data['total_for_review'], 1)


    def test_legacy_user_dictionary_routes_are_removed(self):
        dictionary_response = self.client.get('/api/dictionary/')
        review_response = self.client.get('/api/words-for-review/')
        check_response = self.client.get(f'/api/check-word/{self.word.id}/')

        self.assertEqual(dictionary_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(review_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(check_response.status_code, status.HTTP_404_NOT_FOUND)
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