import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from dictionary.models import (
    ExampleSentence,
    PartOfSpeech,
    Tag,
    Translation,
    Word,
    WordComposition,
    WordPartOfSpeech,
    WordStructure,
    WordStructureType,
    WordTranslation,
)


class DictionarySeedImportTests(TestCase):
    def test_import_dictionary_seed_creates_normalized_dictionary_data(self):
        path = self._seed_file({
            'schema_version': 1,
            'entries': [
                {
                    'simplified': '爱',
                    'traditional': '愛',
                    'pinyin_numeric': 'ai4',
                    'pinyin_graphic': 'ài',
                    'translations': ['to love', 'love'],
                    'part_of_speech': ['v'],
                    'examples': [
                        {
                            'chinese': '我爱你',
                            'pinyin': 'wǒ ài nǐ',
                            'translation': 'I love you',
                        }
                    ],
                    'components': ['爫', '友'],
                    'structure': {
                        'type': 'top-bottom',
                        'description': 'Top and bottom character structure.',
                    },
                    'tags': {
                        'hsk': {'version_2_0': 'old-1', 'version_3_0': 'new-1'},
                        'frequency_rank': 4902,
                        'radical': '爫',
                    },
                }
            ],
        })

        call_command('import_dictionary_seed', str(path), stdout=StringIO())

        word = Word.objects.get(hanzi='爱', pinyin_numeric='ai4')
        self.assertEqual(word.traditional, '愛')
        self.assertEqual(word.pinyin_graphic, 'ài')
        self.assertEqual(word.translation, 'to love; love')
        self.assertEqual(word.frequency_rank, 4902)
        self.assertEqual(word.radical, '爫')

        self.assertEqual(Translation.objects.filter(language='en').count(), 2)
        self.assertEqual(
            list(word.word_translations.order_by('order').values_list('translation__text', flat=True)),
            ['to love', 'love'],
        )
        self.assertTrue(WordTranslation.objects.get(word=word, translation__text='to love').is_primary)
        self.assertTrue(PartOfSpeech.objects.filter(name='v').exists())
        self.assertTrue(WordPartOfSpeech.objects.filter(word=word, part_of_speech__name='v').exists())
        self.assertTrue(ExampleSentence.objects.filter(word=word, chinese_sentence='我爱你').exists())
        self.assertEqual(list(word.components.order_by('position').values_list('parent_word__hanzi', flat=True)), ['爫', '友'])
        self.assertEqual(word.structure.structure_type.slug, 'top-bottom')

    def test_dictionary_seed_import_is_idempotent(self):
        path = self._seed_file([
            {
                'simplified': '好',
                'traditional': '好',
                'pinyin_numeric': 'hao3',
                'pinyin_graphic': 'hǎo',
                'translations': [{'language': 'en', 'text': 'good'}],
                'parts_of_speech': ['adj'],
                'components': ['女', '子'],
                'structure': {'type': 'left-right'},
            }
        ])

        call_command('import_dictionary_seed', str(path), stdout=StringIO())
        call_command('import_dictionary_seed', str(path), stdout=StringIO())

        word = Word.objects.get(hanzi='好')
        self.assertEqual(Word.objects.filter(hanzi='好').count(), 1)
        self.assertEqual(Translation.objects.filter(text='good').count(), 1)
        self.assertEqual(WordTranslation.objects.filter(word=word).count(), 1)
        self.assertEqual(WordComposition.objects.filter(child_word=word).count(), 2)
        self.assertEqual(WordStructure.objects.filter(word=word).count(), 1)
        self.assertEqual(WordStructureType.objects.filter(slug='left-right').count(), 1)

    def test_dictionary_seed_import_uses_unique_slugs_for_radical_tags(self):
        path = self._seed_file([
            {
                'simplified': 'з€±',
                'pinyin_numeric': 'ai4',
                'translations': ['to love'],
                'tags': {'radical': 'з€«'},
            },
            {
                'simplified': 'еҐЅ',
                'pinyin_numeric': 'hao3',
                'translations': ['good'],
                'tags': {'radical': 'еҐі'},
            },
        ])

        call_command('import_dictionary_seed', str(path), stdout=StringIO())

        self.assertEqual(Tag.objects.filter(name__startswith='radical:').count(), 2)
        self.assertEqual(Tag.objects.filter(slug__startswith='radical-').count(), 2)

    def _seed_file(self, payload):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'dictionary.json'
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return path
