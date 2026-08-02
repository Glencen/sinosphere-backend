import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from dictionary.models import Tag, Topic, Translation, Word, WordTag
from learning.models import FSRSSchedulerProfile, Lesson, PracticeConfiguration


class CurriculumSeedImportTests(TestCase):
    def setUp(self):
        self.word = Word.objects.create(
            hanzi='爱',
            traditional='愛',
            pinyin_numeric='ai4',
            pinyin_graphic='ài',
            translation='to love',
            difficulty=1,
        )
        Translation.objects.create(language='en', text='to love')

    def test_import_curriculum_seed_creates_topics_lessons_links_and_config(self):
        path = self._seed_file({
            'schema_version': 1,
            'topics': [
                {
                    'slug': 'basics',
                    'name': 'Basics',
                    'description': 'Core beginner words',
                    'order': 1,
                    'difficulty_level': 1,
                    'tags': [{'slug': 'hsk-1', 'name': 'HSK 1'}],
                }
            ],
            'topic_words': [
                {
                    'topic_slug': 'basics',
                    'word': {'hanzi': '爱', 'pinyin_numeric': 'ai4'},
                }
            ],
            'lessons': [
                {
                    'slug': 'basics-love',
                    'topic_slug': 'basics',
                    'title': 'Love',
                    'word_refs': [{'hanzi': '爱', 'pinyin_numeric': 'ai4'}],
                }
            ],
            'practice_defaults': {
                'requested_cards_count': 10,
                'include_review': True,
                'include_new': True,
            },
            'active_handler_versions': {
                'translation_ru': 1,
                'translation_cn': 1,
                'multiple_choice': 1,
                'writing': 1,
                'matching': 2,
            },
            'learning_profile_defaults': {
                'new_cards_per_day': 10,
                'reviews_per_day': 50,
            },
            'fsrs_scheduler_profiles': [
                {
                    'version': 1,
                    'is_active': True,
                    'parameters': [],
                    'desired_retention': '0.900',
                }
            ],
        })

        call_command('import_curriculum_seed', str(path), stdout=StringIO())

        topic = Topic.objects.get(slug='basics')
        self.assertEqual(topic.name, 'Basics')
        self.assertTrue(Tag.objects.filter(slug='topic-basics', topic=topic).exists())
        self.assertTrue(Tag.objects.filter(slug='hsk-1', topic=topic).exists())
        self.assertTrue(WordTag.objects.filter(word=self.word, tag__slug='topic-basics').exists())
        self.assertTrue(Lesson.objects.filter(slug='basics-love', topic=topic).exists())
        self.assertEqual(PracticeConfiguration.objects.get(key='practice-defaults').value['requested_cards_count'], 10)
        self.assertEqual(PracticeConfiguration.objects.get(key='active-handler-versions').value['matching'], 2)
        self.assertTrue(FSRSSchedulerProfile.objects.filter(user=None, version=1, is_active=True).exists())

    def test_curriculum_seed_import_is_idempotent(self):
        path = self._seed_file({
            'schema_version': 1,
            'topics': [{'slug': 'basics', 'name': 'Basics'}],
            'topic_words': [{'topic_slug': 'basics', 'word': {'hanzi': '爱', 'pinyin_numeric': 'ai4'}}],
            'lessons': [{'slug': 'basics-love', 'topic_slug': 'basics', 'title': 'Love'}],
            'practice_defaults': {'requested_cards_count': 10},
        })

        call_command('import_curriculum_seed', str(path), stdout=StringIO())
        call_command('import_curriculum_seed', str(path), stdout=StringIO())

        self.assertEqual(Topic.objects.filter(slug='basics').count(), 1)
        self.assertEqual(Tag.objects.filter(slug='topic-basics').count(), 1)
        self.assertEqual(WordTag.objects.filter(word=self.word, tag__slug='topic-basics').count(), 1)
        self.assertEqual(Lesson.objects.filter(slug='basics-love').count(), 1)
        self.assertEqual(PracticeConfiguration.objects.filter(key='practice-defaults').count(), 1)

    def _seed_file(self, payload):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'curriculum.json'
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return path
