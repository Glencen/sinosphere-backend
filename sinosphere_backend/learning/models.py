from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from dictionary.models import Word, Topic

class FSRSSchedulerProfile(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='fsrs_scheduler_profiles'
    )
    parameters = models.JSONField(default=list, blank=True)
    desired_retention = models.DecimalField(max_digits=4, decimal_places=3, default=0.9)
    learning_steps = models.JSONField(default=list, blank=True)
    relearning_steps = models.JSONField(default=list, blank=True)
    maximum_interval_days = models.PositiveIntegerField(default=36500)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'version'],
                name='unique_fsrs_profile_user_version'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'is_active'], name='idx_fsrs_profile_user_active'),
        ]


class MemoryCard(models.Model):
    DIRECTION_CN_TO_RU = 'cn_to_ru'
    DIRECTION_RU_TO_CN = 'ru_to_cn'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memory_cards')
    learning_item = models.ForeignKey(Word, on_delete=models.CASCADE, related_name='memory_cards')
    direction = models.CharField(max_length=32)
    fsrs_state = models.JSONField(default=dict, blank=True)
    due_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_review_at = models.DateTimeField(null=True, blank=True)
    scheduler_version = models.CharField(max_length=32, default='fsrs-py')
    parameter_set_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'learning_item', 'direction'],
                name='unique_memory_card_direction'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'due_at'], name='idx_memory_card_user_due'),
            models.Index(fields=['user', 'direction'], name='idx_memory_card_user_direction'),
        ]


class MemoryReview(models.Model):
    memory_card = models.ForeignKey(MemoryCard, on_delete=models.CASCADE, related_name='reviews')
    exercise_attempt = models.ForeignKey(
        'ExerciseAttempt',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='memory_reviews'
    )
    rating = models.PositiveIntegerField()
    reviewed_at = models.DateTimeField()
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    previous_state = models.JSONField(default=dict, blank=True)
    resulting_state = models.JSONField(default=dict, blank=True)
    fsrs_log = models.JSONField(default=dict, blank=True)
    scheduler_version = models.CharField(max_length=32)
    parameter_set_version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['memory_card', 'exercise_attempt'],
                name='unique_memory_review_card_attempt'
            )
        ]
        indexes = [
            models.Index(fields=['memory_card', 'reviewed_at'], name='idx_memory_review_card_time'),
            models.Index(fields=['exercise_attempt'], name='idx_memory_review_attempt'),
        ]


class ExerciseEventConsumerReceipt(models.Model):
    consumer_name = models.CharField(max_length=128)
    event_id = models.UUIDField()
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['consumer_name', 'event_id'],
                name='unique_exercise_event_consumer_receipt'
            )
        ]
        indexes = [
            models.Index(fields=['consumer_name', 'processed_at'], name='idx_evt_receipt_cons_time'),
        ]

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
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='daily_goals'
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
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'date'],
                name='unique_user_daily_goal'
            )
        ]
    
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


class PracticeSession(models.Model):
    STATUS_CREATED = 'created'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_ABANDONED = 'abandoned'
    STATUS_EXPIRED = 'expired'
    STATUS_ACTIVE = 'active'

    STATUS_CHOICES = [
        (STATUS_CREATED, 'Created'),
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_ABANDONED, 'Abandoned'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_ACTIVE, 'Active'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='practice_sessions'
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='practice_sessions'
    )
    session_type = models.CharField(max_length=32, default='mixed')
    requested_count = models.PositiveSmallIntegerField(default=10)
    requested_cards_count = models.PositiveIntegerField(default=10)
    generated_exercises_count = models.PositiveIntegerField(default=0)
    settings = models.JSONField(default=dict, blank=True)
    generation_config = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_CREATED)
    started_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status'], name='idx_practice_user_status'),
            models.Index(fields=['user', 'created_at'], name='idx_practice_user_created'),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.session_type} ({self.status})"

    def update_status_from_attempts(self):
        if self.status in [self.STATUS_COMPLETED, self.STATUS_ABANDONED, self.STATUS_EXPIRED]:
            return

        has_pending = self.attempts.filter(is_correct__isnull=True).exists()
        if not has_pending:
            self.mark_completed()
        elif self.status in [self.STATUS_CREATED, self.STATUS_ACTIVE]:
            self.status = self.STATUS_IN_PROGRESS
            self.save(update_fields=['status'])

    def mark_completed(self):
        if self.status == self.STATUS_COMPLETED:
            return
        self.status = self.STATUS_COMPLETED
        self.completed_at = self.completed_at or timezone.now()
        self.save(update_fields=['status', 'completed_at'])

    def mark_expired(self):
        if self.status in [self.STATUS_COMPLETED, self.STATUS_EXPIRED]:
            return
        self.status = self.STATUS_EXPIRED
        self.save(update_fields=['status'])

    def mark_abandoned(self):
        if self.status in [self.STATUS_COMPLETED, self.STATUS_EXPIRED, self.STATUS_ABANDONED]:
            return
        self.status = self.STATUS_ABANDONED
        self.save(update_fields=['status'])

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at <= timezone.now())


class ExerciseAttempt(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SUBMITTED = 'submitted'
    STATUS_EXPIRED = 'expired'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    session = models.ForeignKey(
        PracticeSession,
        on_delete=models.CASCADE,
        related_name='attempts'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='exercise_attempts'
    )
    word = models.ForeignKey(
        Word,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='exercise_attempts'
    )
    static_exercise = models.ForeignKey(
        Exercise,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attempts'
    )
    exercise_type = models.CharField(max_length=32)
    kind = models.CharField(max_length=64, default='', blank=True)
    handler_version = models.PositiveIntegerField(default=1)
    order = models.PositiveSmallIntegerField(default=0)
    position = models.PositiveIntegerField(default=0)
    learning_items = models.JSONField(default=list, blank=True)
    public_payload = models.JSONField(default=dict)
    grading_payload = models.JSONField(default=dict)
    private_state = models.JSONField(default=dict, blank=True)
    answer = models.JSONField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    score = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    time_spent = models.FloatField(default=0)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default='')
    fsrs_rating = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['session', 'order']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'order'],
                name='unique_session_attempt_order'
            ),
            models.UniqueConstraint(
                fields=['session', 'position'],
                name='unique_attempt_position_in_session'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'is_correct'], name='idx_attempt_user_correct'),
            models.Index(fields=['session', 'order'], name='idx_attempt_session_order'),
            models.Index(fields=['session', 'position'], name='idx_attempt_session_position'),
            models.Index(fields=['kind', 'handler_version'], name='idx_attempt_handler'),
            models.Index(fields=['user', 'status'], name='idx_attempt_user_status'),
        ]

    def __str__(self):
        status = 'pending' if self.is_correct is None else str(self.is_correct)
        return f"{self.user.username}: {self.exercise_type} #{self.order} ({status})"

class AttemptMemoryCard(models.Model):
    attempt = models.ForeignKey(
        ExerciseAttempt,
        related_name='memory_card_links',
        on_delete=models.CASCADE
    )
    memory_card = models.ForeignKey(
        MemoryCard,
        on_delete=models.PROTECT,
        related_name='attempt_links'
    )
    position = models.PositiveIntegerField()
    is_correct = models.BooleanField(null=True, blank=True)
    score = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    fsrs_rating = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['attempt', 'memory_card'],
                name='unique_attempt_memory_card'
            ),
            models.UniqueConstraint(
                fields=['attempt', 'position'],
                name='unique_attempt_memory_card_position'
            ),
        ]
        indexes = [
            models.Index(fields=['memory_card'], name='idx_attempt_memory_card'),
            models.Index(fields=['attempt', 'position'], name='idx_attempt_memory_position'),
        ]
