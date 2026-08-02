import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from dictionary.models import Tag, Topic, Word, WordTag
from learning.models import FSRSSchedulerProfile, Lesson, PracticeConfiguration
from learning.practice.handler_versions import ACTIVE_HANDLER_VERSIONS


class Command(BaseCommand):
    help = 'Import product/curriculum seed JSON with topics, lessons, word-topic links, and practice settings.'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--validate-only', action='store_true')

    def handle(self, *args, **options):
        path = Path(options['path'])
        if not path.exists():
            raise CommandError(f'Seed file does not exist: {path}')

        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except UnicodeDecodeError as exc:
            raise CommandError(f'Seed file must be valid UTF-8: {exc}') from exc
        except json.JSONDecodeError as exc:
            raise CommandError(f'Invalid JSON: {exc}') from exc

        self._validate(payload)
        if options['validate_only']:
            self.stdout.write(self.style.SUCCESS('Validated curriculum seed.'))
            return

        stats = {
            'topics': 0,
            'tags': 0,
            'word_tags': 0,
            'lessons': 0,
            'practice_configurations': 0,
            'fsrs_profiles': 0,
        }
        with transaction.atomic():
            self._import_topics(payload.get('topics') or [], stats)
            self._import_topic_words(payload.get('topic_words') or [], stats)
            self._import_lessons(payload.get('lessons') or [], stats)
            self._import_practice_configurations(payload, stats)
            self._import_fsrs_profiles(payload.get('fsrs_scheduler_profiles') or [], stats)
            if options['dry_run']:
                transaction.set_rollback(True)

        prefix = 'Dry-run ' if options['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(f'{prefix}imported curriculum seed: {stats}'))

    def _validate(self, payload):
        if not isinstance(payload, dict):
            raise CommandError('Curriculum seed must be a JSON object.')
        if payload.get('schema_version') not in (None, 1):
            raise CommandError('Unsupported curriculum seed schema_version.')
        for topic in payload.get('topics') or []:
            if not topic.get('slug') or not topic.get('name'):
                raise CommandError('Each topic must include "slug" and "name".')
        for item in payload.get('topic_words') or []:
            if not item.get('topic_slug'):
                raise CommandError('Each topic word must include "topic_slug".')
            self._word_ref(item.get('word') or item)
        for lesson in payload.get('lessons') or []:
            if not lesson.get('slug') or not lesson.get('topic_slug') or not lesson.get('title'):
                raise CommandError('Each lesson must include "slug", "topic_slug", and "title".')
        configured_versions = payload.get('active_handler_versions') or {}
        unknown = sorted(set(configured_versions) - set(ACTIVE_HANDLER_VERSIONS))
        if unknown:
            raise CommandError(f'Unknown handler kinds in active_handler_versions: {unknown}')

    def _import_topics(self, topics, stats):
        by_slug = {}
        for data in topics:
            parent = None
            parent_slug = data.get('parent_slug')
            if parent_slug:
                parent = by_slug.get(parent_slug) or Topic.objects.filter(slug=parent_slug).first()
                if parent is None:
                    raise CommandError(f'Unknown parent topic slug: {parent_slug}')
            topic, created = Topic.objects.update_or_create(
                slug=data['slug'],
                defaults={
                    'name': data['name'],
                    'description': data.get('description') or '',
                    'parent_topic': parent,
                    'weight': data.get('weight', 1.0),
                    'icon': data.get('icon') or '',
                    'difficulty_level': data.get('difficulty_level') or data.get('difficulty') or 1,
                    'is_active': data.get('is_active', True),
                    'order': data.get('order', 0),
                },
            )
            by_slug[topic.slug] = topic
            stats['topics'] += int(created)
            self._ensure_topic_tags(topic, data.get('tags') or [], stats)

    def _ensure_topic_tags(self, topic, tags, stats):
        tags = [{'slug': self._topic_tag_slug(topic), 'name': self._topic_tag_name(topic)}] + [
            item if isinstance(item, dict) else {'slug': self._slug(str(item)), 'name': self._tag_name(str(item))}
            for item in tags
        ]
        for data in tags:
            tag, created = Tag.objects.update_or_create(
                slug=self._slug(data['slug']),
                defaults={
                    'name': self._tag_name(data.get('name') or data['slug']),
                    'description': data.get('description') or '',
                    'topic': topic,
                    'weight': data.get('weight', 1.0),
                    'frequency_rank': data.get('frequency_rank', 0),
                },
            )
            stats['tags'] += int(created)

    def _import_topic_words(self, topic_words, stats):
        for data in topic_words:
            topic = Topic.objects.get(slug=data['topic_slug'])
            word = self._get_word(self._word_ref(data.get('word') or data))
            tag_slug = data.get('tag_slug') or self._topic_tag_slug(topic)
            tag = Tag.objects.get(slug=tag_slug)
            link, created = WordTag.objects.update_or_create(
                word=word,
                tag=tag,
                defaults={'relevance_score': data.get('relevance_score', 1.0)},
            )
            stats['word_tags'] += int(created)

    def _import_lessons(self, lessons, stats):
        for data in lessons:
            topic = Topic.objects.get(slug=data['topic_slug'])
            lesson, created = Lesson.objects.update_or_create(
                slug=data['slug'],
                defaults={
                    'title': data['title'],
                    'description': data.get('description') or '',
                    'topic': topic,
                    'difficulty': data.get('difficulty') or topic.difficulty_level,
                    'order': data.get('order', 0),
                    'is_active': data.get('is_active', True),
                    'estimated_time': data.get('estimated_time', 10),
                    'xp_reward': data.get('xp_reward', 100),
                },
            )
            for ref in data.get('word_refs') or []:
                self._get_word(self._word_ref(ref))
            stats['lessons'] += int(created)

    def _import_practice_configurations(self, payload, stats):
        configs = {
            'practice-defaults': payload.get('practice_defaults'),
            'active-handler-versions': payload.get('active_handler_versions'),
            'learning-profile-defaults': payload.get('learning_profile_defaults'),
        }
        for key, value in configs.items():
            if value is None:
                continue
            _, created = PracticeConfiguration.objects.update_or_create(
                key=key,
                defaults={'value': value, 'description': f'Imported from curriculum seed: {key}'},
            )
            stats['practice_configurations'] += int(created)

    def _import_fsrs_profiles(self, profiles, stats):
        for data in profiles:
            _, created = FSRSSchedulerProfile.objects.update_or_create(
                user=None,
                version=data.get('version', 1),
                defaults={
                    'parameters': data.get('parameters') or [],
                    'desired_retention': data.get('desired_retention', '0.900'),
                    'learning_steps': data.get('learning_steps') or [],
                    'relearning_steps': data.get('relearning_steps') or [],
                    'maximum_interval_days': data.get('maximum_interval_days', 36500),
                    'is_active': data.get('is_active', True),
                },
            )
            stats['fsrs_profiles'] += int(created)

    def _word_ref(self, value):
        if not isinstance(value, dict):
            raise CommandError('Word reference must be an object.')
        hanzi = value.get('hanzi') or value.get('simplified')
        if not hanzi:
            raise CommandError('Word reference must include "hanzi" or "simplified".')
        return {
            'hanzi': hanzi,
            'pinyin_numeric': value.get('pinyin_numeric') or '',
        }

    def _get_word(self, ref):
        queryset = Word.objects.filter(hanzi=ref['hanzi'])
        if ref['pinyin_numeric']:
            queryset = queryset.filter(pinyin_numeric=ref['pinyin_numeric'])
        word = queryset.first()
        if word is None:
            raise CommandError(f'Unknown dictionary word: {ref}')
        return word

    def _topic_tag_slug(self, topic):
        return self._slug(f'topic-{topic.slug}')

    def _topic_tag_name(self, topic):
        return self._tag_name(f'topic:{topic.slug}')

    def _slug(self, value):
        return (slugify(str(value)) or str(value))[:64]

    def _tag_name(self, value):
        return str(value)[:32]
