from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from dictionary.models import Word, Topic

class Lesson(models.Model):
    """
    Урок - набор заданий по определенной теме
    """
    title = models.CharField(max_length=128, verbose_name='Название урока')
    description = models.TextField(blank=True, verbose_name='Описание')
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name='lessons',
        verbose_name='Тема'
    )
    difficulty = models.PositiveSmallIntegerField(
        default=1,
        verbose_name='Сложность урока',
        help_text='1-легкий, 2-средний, 3-сложный'
    )
    order = models.IntegerField(default=0, verbose_name='Порядок в теме')
    is_active = models.BooleanField(default=True, verbose_name='Активен')
    estimated_time = models.IntegerField(
        default=10,
        verbose_name='Примерное время выполнения (минуты)'
    )
    xp_reward = models.IntegerField(default=100, verbose_name='Награда за прохождение (XP)')
    
    class Meta:
        verbose_name = 'Урок'
        verbose_name_plural = 'Уроки'
        ordering = ['topic', 'order', 'difficulty']
    
    def __str__(self):
        return f"{self.topic.name} - {self.title}"


class Exercise(models.Model):
    """
    Упражнение (задание) в рамках урока
    """
    EXERCISE_TYPES = [
        ('translation_ru', 'Перевод на русский'),
        ('translation_cn', 'Перевод на китайский'),
        ('matching', 'Сопоставление'),
        ('writing', 'Написание иероглифов'),
        ('listening', 'Аудирование'),
        ('multiple_choice', 'Множественный выбор'),
        ('fill_gap', 'Заполнение пропусков'),
    ]
    
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name='exercises',
        verbose_name='Урок'
    )
    exercise_type = models.CharField(
        max_length=20,
        choices=EXERCISE_TYPES,
        verbose_name='Тип задания'
    )
    question = models.TextField(verbose_name='Вопрос/задание')
    correct_answer = models.TextField(verbose_name='Правильный ответ')
    options = models.JSONField(
        default=list,
        blank=True,
        verbose_name='Варианты ответов (JSON)',
        help_text='Для заданий с выбором'
    )
    word = models.ForeignKey(
        Word,
        on_delete=models.CASCADE,
        related_name='exercises',
        null=True,
        blank=True,
        verbose_name='Основное слово'
    )
    additional_words = models.ManyToManyField(
        Word,
        related_name='exercise_additional',
        blank=True,
        verbose_name='Дополнительные слова'
    )
    difficulty = models.PositiveSmallIntegerField(default=1, verbose_name='Сложность')
    explanation = models.TextField(blank=True, verbose_name='Объяснение')
    order = models.IntegerField(default=0, verbose_name='Порядок в уроке')
    
    class Meta:
        verbose_name = 'Упражнение'
        verbose_name_plural = 'Упражнения'
        ordering = ['lesson', 'order']
    
    def __str__(self):
        return f"{self.lesson.title} - {self.get_exercise_type_display()}"


class UserLessonProgress(models.Model):
    """
    Прогресс пользователя по уроку
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lesson_progress')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='user_progress')
    completed = models.BooleanField(default=False, verbose_name='Завершен')
    score = models.FloatField(default=0.0, verbose_name='Оценка за урок')
    started_at = models.DateTimeField(auto_now_add=True, verbose_name='Начало')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='Завершение')
    attempts = models.IntegerField(default=0, verbose_name='Попытки')
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'lesson'],
                name='unique_user_lesson'
            )
        ]
        verbose_name = 'Прогресс урока'
        verbose_name_plural = 'Прогресс уроков'
    
    def __str__(self):
        status = "✓" if self.completed else "→"
        return f"{self.user.username} {status} {self.lesson.title}"


class DailyGoal(models.Model):
    """
    Дневная цель пользователя
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='daily_goal'
    )
    target_xp = models.IntegerField(default=100, verbose_name='Цель по XP')
    target_words = models.IntegerField(default=10, verbose_name='Цель по словам')
    target_time = models.IntegerField(default=30, verbose_name='Цель по времени (минуты)')
    current_xp = models.IntegerField(default=0, verbose_name='Текущий XP')
    current_words = models.IntegerField(default=0, verbose_name='Текущие слова')
    current_time = models.IntegerField(default=0, verbose_name='Текущее время (минуты)')
    date = models.DateField(default=timezone.now, verbose_name='Дата')
    completed = models.BooleanField(default=False, verbose_name='Выполнено')
    
    class Meta:
        verbose_name = 'Дневная цель'
        verbose_name_plural = 'Дневные цели'
    
    def __str__(self):
        return f"{self.user.username} - {self.date}"
    
    def update_progress(self, xp=0, words=0, time_minutes=0):
        """Обновить прогресс дневной цели"""
        self.current_xp += xp
        self.current_words += words
        self.current_time += time_minutes
        
        if (self.current_xp >= self.target_xp and 
            self.current_words >= self.target_words and
            self.current_time >= self.target_time):
            self.completed = True
        
        self.save()