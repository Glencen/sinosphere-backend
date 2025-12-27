from django.core.management.base import BaseCommand
from django.utils import timezone
from users.models import LearningScheduler, ReviewLog
from django.contrib.auth.models import User
from datetime import timedelta

class Command(BaseCommand):
    help = 'Оптимизировать параметры FSRS для активных пользователей'
    
    def handle(self, *args, **kwargs):
        week_ago = timezone.now() - timedelta(days=7)
        
        active_users = User.objects.filter(
            reviewlog__review_date__gte=week_ago
        ).distinct()
        
        for user in active_users:
            review_count = ReviewLog.objects.filter(
                user_word__user=user
            ).count()
            
            if review_count >= 100:
                self.stdout.write(f'Оптимизация FSRS для пользователя {user.username}...')
                
                try:
                    weights = LearningScheduler.optimize_for_user(user.id)
                    if weights:
                        self.stdout.write(
                            self.style.SUCCESS(f'  Оптимизированы веса FSRS')
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(f'  Недостаточно данных для оптимизации')
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'  Ошибка оптимизации: {e}')
                    )
        
        self.stdout.write(self.style.SUCCESS('Оптимизация FSRS завершена'))