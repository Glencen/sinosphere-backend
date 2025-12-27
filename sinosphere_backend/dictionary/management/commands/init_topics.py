from django.core.management.base import BaseCommand
from dictionary.models import Topic, Tag

class Command(BaseCommand):
    help = 'Инициализация базовых тем и тегов для изучения китайского'
    
    def handle(self, *args, **kwargs):
        topics_data = [
            {
                'name': 'Основы',
                'description': 'Базовые слова и выражения',
                'icon': '📚',
                'difficulty_level': 1,
                'order': 1,
                'tags': ['greeting', 'number', 'time', 'date', 'color']
            },
            {
                'name': 'Еда',
                'description': 'Слова связанные с едой и напитками',
                'icon': '🍜',
                'difficulty_level': 2,
                'order': 2,
                'tags': ['fruit', 'vegetable', 'drink', 'restaurant', 'kitchen']
            },
            {
                'name': 'Семья',
                'description': 'Семейные отношения и родственники',
                'icon': '👨‍👩‍👧‍👦',
                'difficulty_level': 2,
                'order': 3,
                'tags': ['relatives', 'age', 'appearance', 'character']
            },
            {
                'name': 'Спорт',
                'description': 'Спортивные термины и активность',
                'icon': '⚽',
                'difficulty_level': 3,
                'order': 4,
                'tags': ['sport', 'sport equipment', 'sport competition', 'health']
            },
            {
                'name': 'Путешествия',
                'description': 'Слова для путешествий и транспорта',
                'icon': '✈️',
                'difficulty_level': 3,
                'order': 5,
                'tags': ['transport', 'orientation', 'living', 'site']
            }
        ]
        
        for topic_data in topics_data:
            tags = topic_data.pop('tags')
            topic, created = Topic.objects.get_or_create(
                name=topic_data['name'],
                defaults=topic_data
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'Создана тема: {topic.name}'))
            
            for tag_name in tags:
                tag, tag_created = Tag.objects.get_or_create(
                    name=tag_name,
                    defaults={'topic': topic}
                )
                if tag_created:
                    self.stdout.write(f'  Создан тег: {tag.name}')
        
        self.stdout.write(self.style.SUCCESS('Базовые темы и теги успешно созданы!'))