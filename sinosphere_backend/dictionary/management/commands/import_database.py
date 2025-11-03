import os
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from dictionary.models import Word, Dictionary, DictionaryEntry
from dictionary.utils import get_or_create_global_dictionary

class Command(BaseCommand):
    help = 'Импортирует словарь CC-CEDICT в базу данных'
    
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
            default=500,
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
            word_data_batch = []
            
            for line_num, line in enumerate(file, 1):
                if line.startswith('#') or not line.strip():
                    continue
                
                try:
                    word_data = self.parse_line(line)
                    if word_data:
                        word_data_batch.append(word_data)
                        
                        if len(word_data_batch) >= batch_size:
                            created_count = self.process_batch(word_data_batch, global_dict)
                            imported_count += created_count
                            word_data_batch = []
                            self.stdout.write(f'Импортировано: {imported_count} слов...')
                        
                        if limit and imported_count >= limit:
                            break
                            
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'Ошибка в строке {line_num}: {e}')
                    )
                    skipped_count += 1
                    continue
            
            if word_data_batch:
                created_count = self.process_batch(word_data_batch, global_dict)
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
    
    def process_batch(self, word_data_batch, global_dict):
        created_count = 0
        
        with transaction.atomic():
            new_words = []
            for word_data in word_data_batch:
                if not Word.objects.filter(
                    simplified=word_data['simplified'],
                    pinyin=word_data['pinyin']
                ).exists():
                    new_words.append(Word(**word_data))
            
            if new_words:
                Word.objects.bulk_create(new_words)
                created_count += len(new_words)
            
            for word_data in word_data_batch:
                word = Word.objects.get(
                    simplified=word_data['simplified'],
                    pinyin=word_data['pinyin']
                )
                if not DictionaryEntry.objects.filter(
                    dictionary=global_dict,
                    word=word
                ).exists():
                    DictionaryEntry.objects.create(
                        dictionary=global_dict,
                        word=word
                    )
        
        return created_count