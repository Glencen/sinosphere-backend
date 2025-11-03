from django.core.management.base import BaseCommand
from django.db import connection, transaction
from dictionary.models import Word, DictionaryEntry

class Command(BaseCommand):
    help = 'Удаляет все слова из словарей'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--keep-global-dict',
            action='store_true',
            help='Не удалять слова из глобального словаря'
        )
        parser.add_argument(
            '--keep-user-dicts', 
            action='store_true',
            help='Не удалять слова из пользовательских словарей'
        )
    
    def handle(self, *args, **options):
        keep_global_dict = options['keep_global_dict']
        keep_user_dicts = options['keep_user_dicts']
        
        self.stdout.write('Начинаем очистку слов из словарей...')
        
        with transaction.atomic():
            total_entries_before = DictionaryEntry.objects.count()
            total_words_before = Word.objects.count()
            entries_to_delete = DictionaryEntry.objects.all()
            
            if keep_global_dict and keep_user_dicts:
                self.stdout.write('Сохраняем все слова во всех словарях. Ничего не удаляем.')
                return
            elif keep_global_dict:
                entries_to_delete = entries_to_delete.filter(dictionary__dictionary_type='user')
                self.stdout.write('Удаляем слова только из пользовательских словарей...')
            elif keep_user_dicts:
                entries_to_delete = entries_to_delete.filter(dictionary__dictionary_type='global')
                self.stdout.write('Удаляем слова только из глобального словаря...')
            else:
                self.stdout.write('Удаляем слова из всех словарей...')
            
            deleted_entries_count = entries_to_delete.delete()[0]
            self.stdout.write(f'Удалено записей словаря: {deleted_entries_count}')
            self.delete_unused_words()
            self.reset_auto_increment()
        
        self.stdout.write(
            self.style.SUCCESS('Очистка словарей завершена!')
        )
    
    def delete_unused_words(self):
        unused_words = Word.objects.filter(dictionary_entries__isnull=True)
        deleted_words_count = unused_words.delete()[0]
        self.stdout.write(f'Удалено неиспользуемых слов: {deleted_words_count}')
        return deleted_words_count
    
    def reset_auto_increment(self):
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE dictionary_word AUTO_INCREMENT = 1")
            cursor.execute("ALTER TABLE dictionary_dictionaryentry AUTO_INCREMENT = 1")
            self.stdout.write('Автоинкремент сброшен для слов и записей словаря.')