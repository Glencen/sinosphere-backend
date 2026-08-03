import json
import re
from hashlib import sha1
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

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
    WordTag,
    WordTranslation,
)


class Command(BaseCommand):
    help = 'Import UTF-8 dictionary seed JSON with words, translations, examples, components, tags, and structures.'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--validate-only', action='store_true')
        parser.add_argument('--default-language', default='en')

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

        entries = self._entries(payload)
        self._validate(entries)
        if options['validate_only']:
            self.stdout.write(self.style.SUCCESS(f'Validated {len(entries)} dictionary entries.'))
            return

        stats = {
            'words': 0,
            'translations': 0,
            'word_translations': 0,
            'parts_of_speech': 0,
            'examples': 0,
            'components': 0,
            'structures': 0,
            'tags': 0,
        }

        with transaction.atomic():
            for entry in entries:
                self._import_entry(entry, default_language=options['default_language'], stats=stats)
            if options['dry_run']:
                transaction.set_rollback(True)

        prefix = 'Dry-run ' if options['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(f'{prefix}imported dictionary seed: {stats}'))

    def _entries(self, payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get('entries'), list):
            return payload['entries']
        raise CommandError('Dictionary seed must be a list or an object with an "entries" list.')

    def _validate(self, entries):
        if not entries:
            raise CommandError('Dictionary seed contains no entries.')
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise CommandError(f'Entry #{index} must be an object.')
            if not self._word_hanzi(entry):
                raise CommandError(f'Entry #{index} is missing "simplified" or "hanzi".')
            translations = entry.get('translations') or []
            if translations is not None and not isinstance(translations, list):
                raise CommandError(f'Entry #{index} translations must be a list.')

    def _import_entry(self, entry, *, default_language, stats):
        hanzi = self._word_hanzi(entry)
        translations = self._translation_items(entry.get('translations') or [], default_language)
        defaults = {
            'traditional': entry.get('traditional') or '',
            'pinyin_numeric': entry.get('pinyin_numeric') or '',
            'pinyin_graphic': entry.get('pinyin_graphic') or '',
            'translation': self._legacy_translation(translations),
            'difficulty': self._difficulty(entry),
            'frequency_rank': self._frequency_rank(entry),
            'radical': self._radical(entry),
        }
        word, created = Word.objects.update_or_create(
            hanzi=hanzi,
            pinyin_numeric=defaults['pinyin_numeric'],
            defaults=defaults,
        )
        stats['words'] += int(created)

        self._sync_translations(word, translations, stats)
        self._sync_parts_of_speech(word, entry.get('parts_of_speech') or entry.get('part_of_speech') or [], stats)
        self._sync_examples(word, entry.get('examples') or [], stats)
        self._sync_components(word, entry.get('components') or [], stats)
        self._sync_structure(word, entry.get('structure'), stats)
        self._sync_tags(word, entry.get('tags') or {}, stats)

    def _word_hanzi(self, entry):
        return entry.get('simplified') or entry.get('hanzi') or entry.get('word') or ''

    def _translation_items(self, raw_items, default_language):
        items = []
        for index, raw in enumerate(raw_items):
            if isinstance(raw, str):
                text = raw.strip()
                language = default_language
                is_primary = index == 0
                source = ''
            elif isinstance(raw, dict):
                text = str(raw.get('text') or '').strip()
                language = raw.get('language') or default_language
                is_primary = bool(raw.get('is_primary', index == 0))
                source = raw.get('source') or ''
            else:
                continue
            if text:
                items.append({
                    'language': language,
                    'text': text,
                    'order': index,
                    'is_primary': is_primary,
                    'source': source,
                })
        return items

    def _legacy_translation(self, translations):
        return '; '.join(item['text'] for item in translations)

    def _difficulty(self, entry):
        hsk = (entry.get('tags') or {}).get('hsk') or {}
        for key in ('version_3_0', 'version_2_0'):
            value = hsk.get(key)
            match = re.search(r'(\d+)$', str(value or ''))
            if match:
                return int(match.group(1))
        return int(entry.get('difficulty') or 0)

    def _frequency_rank(self, entry):
        value = (entry.get('tags') or {}).get('frequency_rank', entry.get('frequency_rank'))
        return int(value) if value not in (None, '') else None

    def _radical(self, entry):
        return (entry.get('tags') or {}).get('radical') or entry.get('radical') or ''

    def _sync_translations(self, word, translations, stats):
        seen_ids = []
        for item in translations:
            translation, created = Translation.objects.get_or_create(
                language=item['language'],
                text=item['text'],
            )
            stats['translations'] += int(created)
            link, link_created = WordTranslation.objects.update_or_create(
                word=word,
                translation=translation,
                defaults={
                    'order': item['order'],
                    'is_primary': item['is_primary'],
                    'source': item['source'],
                },
            )
            seen_ids.append(link.id)
            stats['word_translations'] += int(link_created)
        if seen_ids:
            WordTranslation.objects.filter(word=word).exclude(id__in=seen_ids).delete()

    def _sync_parts_of_speech(self, word, names, stats):
        seen_ids = []
        for name in names:
            name = str(name).strip()
            if not name:
                continue
            part, created = PartOfSpeech.objects.get_or_create(name=name)
            stats['parts_of_speech'] += int(created)
            link, _ = WordPartOfSpeech.objects.get_or_create(word=word, part_of_speech=part)
            seen_ids.append(link.id)
        if seen_ids:
            WordPartOfSpeech.objects.filter(word=word).exclude(id__in=seen_ids).delete()

    def _sync_examples(self, word, examples, stats):
        seen_ids = []
        for raw in examples:
            example = self._example_payload(raw)
            if not example:
                continue
            obj, created = ExampleSentence.objects.update_or_create(
                word=word,
                chinese_sentence=example['chinese_sentence'],
                defaults={
                    'pinyin_sentence': example['pinyin_sentence'],
                    'translation': example['translation'],
                    'difficulty': example['difficulty'],
                },
            )
            seen_ids.append(obj.id)
            stats['examples'] += int(created)
        if seen_ids:
            ExampleSentence.objects.filter(word=word).exclude(id__in=seen_ids).delete()

    def _example_payload(self, raw):
        if isinstance(raw, dict):
            chinese = raw.get('chinese') or raw.get('chinese_sentence')
            if not chinese:
                return None
            return {
                'chinese_sentence': chinese,
                'pinyin_sentence': raw.get('pinyin') or raw.get('pinyin_sentence') or '',
                'translation': raw.get('translation') or '',
                'difficulty': int(raw.get('difficulty') or 1),
            }
        if isinstance(raw, str):
            chinese, pinyin, translation = self._parse_example_string(raw)
            return {
                'chinese_sentence': chinese,
                'pinyin_sentence': pinyin,
                'translation': translation,
                'difficulty': 1,
            } if chinese else None
        return None

    def _parse_example_string(self, value):
        match = re.match(r'^\s*(.*?)\s*(?:\((.*?)\))?\s*(?:-\s*(.*))?$', value)
        if not match:
            return value.strip(), '', ''
        return (match.group(1) or '').strip(), (match.group(2) or '').strip(), (match.group(3) or '').strip()

    def _sync_components(self, word, components, stats):
        WordComposition.objects.filter(child_word=word).delete()
        for position, raw in enumerate(components, start=1):
            if isinstance(raw, dict):
                hanzi = raw.get('hanzi') or raw.get('component') or raw.get('parent_word_hanzi')
                component_position = int(raw.get('position') or position)
            else:
                hanzi = str(raw or '')
                component_position = position
            if not hanzi:
                continue
            component, _ = Word.objects.get_or_create(
                hanzi=hanzi,
                defaults={'pinyin_numeric': '', 'pinyin_graphic': '', 'translation': '', 'difficulty': 0},
            )
            WordComposition.objects.create(child_word=word, parent_word=component, position=component_position)
            stats['components'] += 1

    def _sync_structure(self, word, raw, stats):
        if not raw:
            return
        slug = raw.get('type') if isinstance(raw, dict) else str(raw)
        if not slug:
            return
        structure_type, _ = WordStructureType.objects.get_or_create(
            slug=slugify(slug) or slug,
            defaults={'name': slug.replace('-', ' ').title()},
        )
        _, created = WordStructure.objects.update_or_create(
            word=word,
            defaults={
                'structure_type': structure_type,
                'description': raw.get('description', '') if isinstance(raw, dict) else '',
            },
        )
        stats['structures'] += int(created)

    def _sync_tags(self, word, raw_tags, stats):
        names = []
        hsk = raw_tags.get('hsk') or {}
        for version, value in hsk.items():
            if value:
                names.append({
                    'name': f'hsk:{version}:{value}',
                    'slug': slugify(f'hsk-{version}-{value}')[:64],
                })
        radical = raw_tags.get('radical')
        if radical:
            names.append({
                'name': f'radical:{radical}',
                'slug': self._radical_tag_slug(radical),
            })

        for data in names:
            tag, created = self._sync_tag(data['slug'], data['name'])
            stats['tags'] += int(created)
            WordTag.objects.get_or_create(word=word, tag=tag)

    def _radical_tag_slug(self, radical):
        digest = sha1(str(radical).encode('utf-8')).hexdigest()[:12]
        return f'radical-{digest}'

    def _sync_tag(self, slug, name):
        tag = Tag.objects.filter(slug=slug).first() or Tag.objects.filter(name=name[:32]).first()
        if tag:
            changed = False
            if tag.slug != slug:
                tag.slug = slug
                changed = True
            if tag.name != name[:32]:
                tag.name = name[:32]
                changed = True
            if changed:
                tag.save(update_fields=['slug', 'name'])
            return tag, False
        return Tag.objects.create(slug=slug, name=name[:32]), True
