import os
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from dictionary.models import Word, Dictionary, DictionaryEntry
from dictionary.utils import get_or_create_global_dictionary

class Command(BaseCommand):
    help = 'Импортирует словарь в формате CC-CEDICT в базу данных'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'file_path',
            type=str,
            help='Путь к файлу CC-CEDICT'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Ограничить количество импортируемых записей'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Размер батча для массового создания'
        )
    
    def handle(self, *args, **options):
        file_path = options['file_path']
        limit = options['limit']
        batch_size = options['batch_size']
        
        if not os.path.exists(file_path):
            self.stdout.write(
                self.style.ERROR(f'Файл не найден: {file_path}')
            )
            return
        
        global_dict = get_or_create_global_dictionary()
        
        self.stdout.write(f'Начинаем импорт из: {file_path}')
        self.stdout.write(f'Глобальный словарь: {global_dict.name}')
        
        imported_count = 0
        skipped_count = 0
        
        with open(file_path, 'r', encoding='utf-8') as file:
            words_to_create = []
            entries_to_create = []
            
            for line_num, line in enumerate(file, 1):
                if line.startswith('#') or not line.strip():
                    continue
                
                try:
                    word_data = self.parse_line(line)
                    if word_data:
                        word = Word(**word_data)
                        words_to_create.append(word)
                        entries_to_create.append(
                            DictionaryEntry(dictionary=global_dict, word=word)
                        )
                        
                        if len(words_to_create) >= batch_size:
                            created_count = self.bulk_create_words_and_entries(
                                words_to_create, entries_to_create
                            )
                            imported_count += created_count
                            words_to_create = []
                            entries_to_create = []
                            
                            self.stdout.write(f'Импортировано: {imported_count} слов...')
                        
                        if limit and imported_count >= limit:
                            break
                            
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'Ошибка в строке {line_num}: {e}')
                    )
                    skipped_count += 1
                    continue
            
            if words_to_create:
                created_count = self.bulk_create_words_and_entries(
                    words_to_create, entries_to_create
                )
                imported_count += created_count
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Импорт завершен! Импортировано: {imported_count}, Пропущено: {skipped_count}'
            )
        )
    
    def parse_line(self, line):
        line = line.strip()
        pattern = r'^(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+/(.+)/$'
        match = re.match(pattern, line)
        
        if not match:
            return None
        
        traditional, simplified, pinyin, translation = match.groups()
        clean_translation = self.clean_translation(translation)
        
        return {
            'traditional': traditional,
            'simplified': simplified,
            'pinyin': pinyin,
            'translation': clean_translation,
        }
    
    def clean_translation(self, translation):
        translations = translation.split('/')
        translations = [t.strip() for t in translations if t.strip()]
        return '; '.join(translations)
    
    def bulk_create_words_and_entries(self, words, entries):
        with transaction.atomic():
            created_words = Word.objects.bulk_create(words, ignore_conflicts=True)
            DictionaryEntry.objects.bulk_create(entries, ignore_conflicts=True)
            return len(created_words)