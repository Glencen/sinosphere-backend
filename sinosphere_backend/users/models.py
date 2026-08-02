from django.db import models
from datetime import timedelta
from django.utils import timezone
import json
from django.contrib.auth.models import User

class UserLearningStats(models.Model):
    """
    Статистика обучения пользователя
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='learning_stats'
    )
    total_lessons_completed = models.IntegerField(default=0, verbose_name='Всего пройдено уроков')
    total_exercises_completed = models.IntegerField(default=0, verbose_name='Всего выполнено заданий')
    total_time_spent = models.IntegerField(default=0, verbose_name='Общее время обучения (секунды)')
    current_streak = models.IntegerField(default=0, verbose_name='Текущая серия дней')
    longest_streak = models.IntegerField(default=0, verbose_name='Самая длинная серия дней')
    last_activity_date = models.DateField(null=True, blank=True, verbose_name='Дата последней активности')
    xp_points = models.IntegerField(default=0, verbose_name='Очки опыта')
    level = models.IntegerField(default=1, verbose_name='Уровень пользователя')
    
    class Meta:
        verbose_name = 'Статистика обучения'
        verbose_name_plural = 'Статистика обучения'
    
    def __str__(self):
        return f"Статистика: {self.user.username}"
    
    def update_streak(self):
        """Обновить серию дней обучения"""
        today = timezone.now().date()
        
        if not self.last_activity_date:
            self.current_streak = 1
        elif self.last_activity_date == today:
            pass
        elif self.last_activity_date == today - timedelta(days=1):
            self.current_streak += 1
        else:
            self.current_streak = 1
        
        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak
        
        self.last_activity_date = today
        self.save()


class UserTopicProgress(models.Model):
    """
    Прогресс пользователя по теме
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='topic_progress'
    )
    topic = models.ForeignKey(
        'dictionary.Topic',
        on_delete=models.CASCADE,
        related_name='user_progress'
    )
    words_learned = models.IntegerField(default=0, verbose_name='Слов изучено')
    total_words = models.IntegerField(default=0, verbose_name='Всего слов в теме')
    accuracy = models.FloatField(default=0.0, verbose_name='Точность ответов')
    total_attempts = models.IntegerField(default=0, verbose_name='Всего попыток')
    total_correct = models.IntegerField(default=0, verbose_name='Правильных попыток')
    last_practiced = models.DateTimeField(null=True, blank=True, verbose_name='Последняя практика')
    is_active = models.BooleanField(default=False, verbose_name='Активно изучается')
    mastery_level = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Уровень освоения',
        help_text='0-5 (0 - не начато, 5 - освоено)'
    )
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'topic'],
                name='unique_user_topic'
            )
        ]
        verbose_name = 'Прогресс по теме'
        verbose_name_plural = 'Прогресс по темам'
        indexes = [
            models.Index(fields=['user', 'mastery_level'], name='idx_user_mastery'),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.topic.name}"
    
    def update_progress(self):
        """Обновить прогресс по теме"""
        from dictionary.models import WordTag
        
        tag_ids = self.topic.tags.values_list('id', flat=True)
        total_words_count = WordTag.objects.filter(
            tag_id__in=tag_ids
        ).values('word').distinct().count()
        
        from learning.models import MemoryCard

        learned_words_count = MemoryCard.objects.filter(
            user=self.user,
            learning_item__word_tags__tag_id__in=tag_ids,
            reviews__isnull=False,
        ).values('learning_item').distinct().count()
        
        self.total_words = total_words_count
        self.words_learned = learned_words_count
        self.save()


class UserExerciseHistory(models.Model):
    """
    История выполненных упражнений
    """
    EXERCISE_TYPES = [
        ('translation', 'Перевод'),
        ('matching', 'Сопоставление'),
        ('writing', 'Написание иероглифов'),
        ('listening', 'Аудирование'),
        ('multiple_choice', 'Множественный выбор'),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='exercise_history'
    )
    exercise_type = models.CharField(max_length=20, choices=EXERCISE_TYPES, verbose_name='Тип задания')
    word = models.ForeignKey(
        'dictionary.Word',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Слово'
    )
    topic = models.ForeignKey(
        'dictionary.Topic',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Тема'
    )
    is_correct = models.BooleanField(verbose_name='Правильный ответ')
    time_spent = models.FloatField(default=0, verbose_name='Время выполнения (секунды)')
    difficulty = models.PositiveSmallIntegerField(default=1, verbose_name='Сложность задания')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время выполнения')
    
    class Meta:
        verbose_name = 'История заданий'
        verbose_name_plural = 'История заданий'
        indexes = [
            models.Index(fields=['user', 'created_at'], name='idx_user_exercise_time'),
            models.Index(fields=['user', 'exercise_type'], name='idx_user_exercise_type'),
            models.Index(fields=['user', 'is_correct'], name='idx_user_correctness'),
        ]
    
    def __str__(self):
        status = "✓" if self.is_correct else "✗"
        return f"{self.user.username}: {self.exercise_type} {status}"

class UserProfile(models.Model):
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE,
        related_name='profile'
    )
    
    class Meta:
        verbose_name = 'Профиль пользователя'
        verbose_name_plural = 'Профили пользователей'
    
    def __str__(self):
        return f"Профиль: {self.user.username}"
    
class UserWord(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='words'
    )
    word = models.ForeignKey(
        'dictionary.Word',
        on_delete=models.CASCADE,
        related_name='user_words'
    )
    added_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(max_length=255, blank=True)

    class Meta:
        verbose_name = 'User dictionary word'
        verbose_name_plural = 'User dictionary words'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'word'],
                name='unique_user_word'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'added_date'], name='idx_user_word_added'),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.word.hanzi}"


class UserLearningProfile(models.Model):
    """
    Профиль обучения пользователя с настройками FSRS
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='learning_profile'
    )
    fsrs_weights = models.TextField(
        default='[]',
        verbose_name='FSRS веса (JSON)',
        help_text='Оптимизированные веса для алгоритма FSRS'
    )
    new_cards_per_day = models.IntegerField(
        default=10,
        verbose_name='Новых карточек в день'
    )
    max_reviews_per_day = models.IntegerField(
        default=100,
        verbose_name='Максимум повторений в день'
    )
    learning_steps = models.JSONField(
        default=list,
        verbose_name='Шаги обучения'
    )
    re_learning_steps = models.JSONField(
        default=list,
        verbose_name='Шаги переобучения'
    )
    desired_retention = models.FloatField(
        default=0.9,
        verbose_name='Желаемое удержание знаний'
    )
    maximum_interval = models.IntegerField(
        default=36500,
        verbose_name='Максимальный интервал (дней)'
    )
    
    class Meta:
        verbose_name = 'Профиль обучения'
        verbose_name_plural = 'Профили обучения'
    
    def __str__(self):
        return f"Профиль обучения: {self.user.username}"
    
    def save(self, *args, **kwargs):
        if not self.pk:
            if self.learning_steps is None or self.learning_steps == []:
                self.learning_steps = [1, 10]
            if self.re_learning_steps is None or self.re_learning_steps == []:
                self.re_learning_steps = [10]
        super().save(*args, **kwargs)
    
    def get_fsrs_weights(self):
        """Получить FSRS веса как список"""
        try:
            return json.loads(self.fsrs_weights)
        except:
            return [
                0.4, 0.6, 2.4, 5.8, 4.93, 0.94, 0.86, 0.01,
                1.49, 0.14, 0.94, 2.18, 0.05, 0.34, 1.26,
                0.29, 2.61, 0.0, 0.0, 0.0
            ]

