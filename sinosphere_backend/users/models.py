from django.db import models
from datetime import timedelta
from django.utils import timezone
import json
from fsrs import Card, Scheduler
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
        
        learned_words_count = UserWord.objects.filter(
            user=self.user,
            word__word_tags__tag_id__in=tag_ids,
            is_learned=True
        ).distinct().count()
        
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
    
    due = models.DateTimeField(
        default=timezone.now,
        verbose_name='Время следующего повторения'
    )
    stability = models.FloatField(
        default=0.0,
        verbose_name='Стабильность запоминания'
    )
    difficulty = models.FloatField(
        default=8.0,
        verbose_name='Сложность слова'
    )
    elapsed_days = models.IntegerField(
        default=0,
        verbose_name='Дней с последнего повторения'
    )
    scheduled_days = models.IntegerField(
        default=0,
        verbose_name='Запланировано дней до след. повторения'
    )
    reps = models.IntegerField(
        default=0,
        verbose_name='Количество повторений'
    )
    lapses = models.IntegerField(
        default=0,
        verbose_name='Количество ошибок'
    )
    state = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Состояние (0=new, 1=learning, 2=review, 3=relearning)'
    )
    last_review = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Время последнего повторения'
    )
    
    total_attempts = models.IntegerField(default=0, verbose_name='Всего попыток')
    correct_attempts = models.IntegerField(default=0, verbose_name='Правильных попыток')
    avg_response_time = models.FloatField(default=0, verbose_name='Среднее время ответа (сек)')
    consecutive_correct = models.IntegerField(default=0, verbose_name='Подряд правильных ответов')
    
    class Meta:
        verbose_name = 'Слово пользователя'
        verbose_name_plural = 'Слова пользователя'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'word'],
                name='unique_user_word'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'due'], name='idx_user_due'),
            models.Index(fields=['due'], name='idx_due'),
            models.Index(fields=['state'], name='idx_state'),
        ]
    
    def __str__(self):
        return f"{self.user.username}: {self.word.hanzi} (state: {self.state})"
    
    def to_fsrs_card(self) -> Card:
        """Конвертировать модель в объект Card FSRS"""
        from fsrs import Card, State
        
        try:
            self._old_state = self.state
            
            if hasattr(State, '_value2member_map_'):
                try:
                    fsrs_state = State(self.state)
                except ValueError:
                    fsrs_state = State.Learning
            else:
                fsrs_state = self.state
        except:
            fsrs_state = State.Learning if hasattr(State, 'Learning') else 1
        
        return Card(
            card_id=self.id,
            due=self.due,
            stability=self.stability if self.stability != 0 else None,
            difficulty=self.difficulty if self.difficulty != 8.0 else None,
            state=fsrs_state,
            last_review=self.last_review,
            step=None
        )
    
    def from_fsrs_card(self, card: Card):
        """Обновить модель из объекта Card FSRS"""
        self.due = card.due
        self.stability = card.stability if card.stability is not None else self.stability
        self.difficulty = card.difficulty if card.difficulty is not None else self.difficulty
        
        if hasattr(card.state, 'value'):
            self.state = card.state.value
        else:
            self.state = card.state
        
        self.last_review = timezone.now()
        
        if self.state in [2, 3]:
            self.reps = (self.reps if self.reps else 0) + 1
        elif self.state == 1 and (not self.reps or self.reps == 0):
            self.reps = 1
        
        old_state = getattr(self, '_old_state', None)
        if old_state == 2 and self.state == 3:
            self.lapses = (self.lapses if self.lapses else 0) + 1
        
        if hasattr(self, '_old_state'):
            delattr(self, '_old_state')
        
        if self.last_review and self.due:
            time_diff = self.due - self.last_review
            self.scheduled_days = max(0, time_diff.days)
            
            self.elapsed_days = 0
    
    def calculate_automatic_rating(self, is_correct: bool, response_time: float, exercise_type: str) -> int:
        """
        Автоматически рассчитывает рейтинг FSRS (1-4) на основе ответа
        
        Args:
            is_correct: Правильный ли ответ
            response_time: Время ответа в секундах
            exercise_type: Тип упражнения
            
        Returns:
            int: Рейтинг FSRS (1=again, 2=hard, 3=good, 4=easy)
        """
        if not is_correct:
            return 1
        
        time_thresholds = {
            'translation_ru': 5.0,
            'translation_cn': 7.0,
            'multiple_choice': 3.0,
            'matching': 10.0,
            'writing': 15.0,
        }
        
        expected_time = time_thresholds.get(exercise_type, 5.0)
        
        difficulty_factor = 1.0
        if self.reps > 0:
            accuracy = self.correct_attempts / self.total_attempts if self.total_attempts > 0 else 0
            if accuracy < 0.5:
                difficulty_factor = 1.2
            elif accuracy > 0.9:
                difficulty_factor = 0.8
        
        adjusted_time = expected_time * difficulty_factor
        
        if response_time <= adjusted_time * 0.5:
            return 4
        elif response_time <= adjusted_time * 0.8:
            return 3
        elif response_time <= adjusted_time * 1.2:
            return 2
        else:
            return 2
    
    def update_review(self, is_correct: bool, response_time: float, exercise_type: str):
        """Обновить состояние после выполнения упражнения"""
        self.total_attempts += 1
        if is_correct:
            self.correct_attempts += 1
            self.consecutive_correct += 1
        else:
            self.consecutive_correct = 0
        
        if self.total_attempts == 1:
            self.avg_response_time = response_time
        else:
            self.avg_response_time = (
                self.avg_response_time * (self.total_attempts - 1) + response_time
            ) / self.total_attempts

        rating = self.calculate_automatic_rating(is_correct, response_time, exercise_type)
        
        review_log = ReviewLog.objects.create(
            user_word=self,
            rating=rating,
            is_correct=is_correct,
            response_time=response_time,
            exercise_type=exercise_type,
            review_date=timezone.now()
        )
        
        try:
            scheduler = LearningScheduler.get_scheduler(user=self.user)
            
            fsrs_card = self.to_fsrs_card()
            
            from fsrs import Rating
            fsrs_rating = Rating(rating)
            
            updated_card, fsrs_review_log = scheduler.review_card(
                fsrs_card, 
                fsrs_rating, 
                review_datetime=timezone.now(),
                review_duration=int(response_time * 1000)
            )
            
            self.from_fsrs_card(updated_card)
            
            if fsrs_review_log and hasattr(fsrs_review_log, 'scheduled_days'):
                review_log.scheduled_days = fsrs_review_log.scheduled_days
                review_log.save()
                
        except Exception as e:
            print(f"Error using FSRS scheduler: {e}")
            self.last_review = timezone.now()
            
            if is_correct:
                if self.state == 0:
                    self.state = 1
                    self.due = timezone.now() + timedelta(minutes=10)
                    self.reps = 1
                elif self.state == 1:
                    self.state = 2
                    self.due = timezone.now() + timedelta(days=1)
                    self.reps += 1
                elif self.state == 2:
                    current_interval = self.scheduled_days if self.scheduled_days > 0 else 1
                    new_interval = min(current_interval * 2, 365)
                    self.due = timezone.now() + timedelta(days=new_interval)
                    self.reps += 1
                    self.scheduled_days = new_interval
            else:
                if self.state == 2:
                    self.state = 3
                    self.lapses += 1
                self.due = timezone.now() + timedelta(minutes=10)
        
        self.save()
        
        return rating
    
    def get_review_urgency(self) -> float:
        """Получить срочность повторения (0-10)"""
        if self.state == 0:
            return 10.0
        
        now = timezone.now()
        if self.due <= now:
            hours_overdue = (now - self.due).total_seconds() / 3600
            return min(10.0, 5.0 + hours_overdue / 24)
        
        hours_until_due = (self.due - now).total_seconds() / 3600
        if hours_until_due < 24:
            return 5.0
        elif hours_until_due < 48:
            return 3.0
        else:
            return 1.0
    
    @property
    def mastery_score(self) -> float:
        """Оценка владения словом (0-100)"""
        if self.total_attempts == 0:
            return 0
        
        accuracy = self.correct_attempts / self.total_attempts * 100
        stability_factor = min(self.stability / 365, 1.0) * 20
        difficulty_factor = max(0, (10 - self.difficulty) / 10 * 20)
        reps_factor = min(self.reps / 10, 1.0) * 20
        
        recent_success_factor = 0
        if self.consecutive_correct >= 3:
            recent_success_factor = min(self.consecutive_correct / 10, 1.0) * 20
        
        score = (accuracy * 0.4 + stability_factor + difficulty_factor + 
                reps_factor * 0.1 + recent_success_factor * 0.1)
        
        return min(score, 100)
    
    @property
    def is_learned(self) -> bool:
        """Слово считается изученным"""
        return self.mastery_score >= 70 and self.reps >= 5
    
class ReviewLog(models.Model):
    """
    Журнал повторений для FSRS Optimizer
    """
    user_word = models.ForeignKey(
        UserWord,
        on_delete=models.CASCADE,
        related_name='review_logs'
    )
    rating = models.IntegerField(
        choices=[(1, 'Again'), (2, 'Hard'), (3, 'Good'), (4, 'Easy')],
        verbose_name='Рейтинг FSRS'
    )
    is_correct = models.BooleanField(verbose_name='Правильный ответ')
    response_time = models.FloatField(verbose_name='Время ответа (сек)')
    exercise_type = models.CharField(max_length=50, verbose_name='Тип упражнения')
    review_date = models.DateTimeField(default=timezone.now, verbose_name='Дата повторения')
    scheduled_days = models.IntegerField(default=0, verbose_name='Запланировано дней')
    
    class Meta:
        verbose_name = 'Запись повторения'
        verbose_name_plural = 'Записи повторений'
        indexes = [
            models.Index(fields=['user_word', 'review_date'], name='idx_review_log_date'),
        ]
    
    def __str__(self):
        rating_text = dict(self.rating.choices)[self.rating]
        return f"{self.user_word.word.hanzi} - {rating_text} ({self.review_date.date()})"


class LearningScheduler:
    """
    Класс-обертка для FSRS Scheduler с настройками
    """
    _scheduler = None
    _optimizer = None
    _default_scheduler = None
    
    @classmethod
    def get_scheduler(cls, user=None) -> Scheduler:
        """Получить экземпляр Scheduler для пользователя"""
        if user:
            try:
                from users.models import UserLearningProfile
                user_profile, created = UserLearningProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'fsrs_weights': '[]',
                        'new_cards_per_day': 10,
                        'max_reviews_per_day': 100,
                        'learning_steps': [1, 10],
                        're_learning_steps': [10],
                        'desired_retention': 0.9,
                        'maximum_interval': 36500,
                    }
                )
                
                weights = user_profile.get_fsrs_weights()
                
                if not weights or weights == []:
                    return cls._get_default_scheduler()
                
                if isinstance(weights, list):
                    weights = tuple(weights)
                
                from fsrs import Scheduler
                return Scheduler(parameters=weights)
                
            except Exception as e:
                print(f"Error getting user weights: {e}")
                return cls._get_default_scheduler()
        
        return cls._get_default_scheduler()
    
    @classmethod
    def _get_default_scheduler(cls):
        """Получить дефолтный шедулер"""
        if cls._default_scheduler is None:
            from fsrs import Scheduler
            cls._default_scheduler = Scheduler()
        return cls._default_scheduler

    @classmethod
    def get_optimizer(cls):
        """Получить экземпляр Optimizer"""
        if cls._optimizer is None:
            from fsrs import Optimizer
            cls._optimizer = Optimizer()
        return cls._optimizer
    
    @classmethod
    def optimize_for_user(cls, user_id):
        """
        Оптимизировать параметры FSRS для конкретного пользователя
        на основе его ReviewLog
        """
        from fsrs import Optimizer
        
        review_logs = ReviewLog.objects.filter(
            user_word__user_id=user_id
        ).select_related('user_word').order_by('review_date')
        
        if len(review_logs) < 50:
            return None
        
        cards_data = []
        reviews_data = []
        
        for log in review_logs:
            card = log.user_word.to_fsrs_card()
            cards_data.append(card)
            reviews_data.append((log.rating, log.review_date))
        
        optimizer = cls.get_optimizer()
        optimized_weights = optimizer.optimize(cards_data, reviews_data)
        
        user_profile, _ = UserLearningProfile.objects.get_or_create(
            user_id=user_id,
            defaults={'fsrs_weights': json.dumps(optimized_weights.tolist())}
        )
        user_profile.fsrs_weights = json.dumps(optimized_weights.tolist())
        user_profile.save()
        
        cls._scheduler = Scheduler(weights=optimized_weights)
        
        return optimized_weights
    
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