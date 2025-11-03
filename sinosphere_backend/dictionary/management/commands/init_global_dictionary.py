from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Инициализирует глобальный словарь если он не существует'

    def handle(self, *args, **options):
        from dictionary.utils import get_or_create_global_dictionary
        try:
            global_dict = get_or_create_global_dictionary()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Глобальный словарь: {global_dict.name} (ID: {global_dict.id})'
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Ошибка при создании глобального словаря: {e}')
            )
