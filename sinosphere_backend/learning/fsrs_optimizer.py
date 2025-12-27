import math
from datetime import timedelta
from django.utils import timezone
from users.models import UserWord

class FSRSOptimizer:
    """
    Реализация алгоритма FSRS (Free Spaced Repetition Scheduler)
    """
    
    def __init__(self, w=None):
        self.w = w or [
            -0.5, -0.9, 0.2, -1.4, -0.7, 0.4, -0.6, 0.8, -0.7, -0.5,
            0.3, -0.6, 0.5, 0.7, 0.3, -0.3, -0.3, 0.3, 0.3
        ]
        
    @staticmethod
    def _forgetting_curve(elapsed_days, stability):
        """Кривая забывания"""
        return math.exp(math.log(0.9) * elapsed_days / stability)
    
    def _next_interval(self, stability, difficulty, rating):
        """Вычисление следующего интервала"""
        if rating <= 1:
            return 1
        
        hard_interval = max(1, round(stability * math.exp(self.w[8]) * difficulty))
        good_interval = max(hard_interval, round(stability * math.exp(self.w[9]) * difficulty))
        easy_interval = max(good_interval, round(stability * math.exp(self.w[10]) * difficulty))
        
        intervals = [1, hard_interval, good_interval, easy_interval]
        return intervals[min(rating, 3)]
    
    def update_card(self, user_word, rating):
        """Обновить карточку после ответа пользователя"""
        user_word.reps += 1
        
        if rating <= 1:
            user_word.lapses += 1
            user_word.state = 1
            user_word.difficulty = min(10, user_word.difficulty + 0.2)
            user_word.stability = max(0.1, user_word.stability * 0.8)
        else:
            difficulty_change = self.w[4] * (rating - 3)
            user_word.difficulty = max(0.1, min(10, user_word.difficulty + difficulty_change))
            
            if user_word.state == 0:
                user_word.stability = self.w[0]
                user_word.state = 1
            elif user_word.state == 1:
                if rating >= 3:
                    user_word.stability = self.w[1] * user_word.difficulty + self.w[2]
                    user_word.state = 2
            else:
                recall = 1.0 if rating >= 3 else 0.0
                stability_change = self.w[5] * math.exp(self.w[6] * (1 - recall))
                user_word.stability = max(0.1, user_word.stability * stability_change)
        
        next_interval = self._next_interval(
            user_word.stability,
            user_word.difficulty,
            rating
        )
        
        now = timezone.now()
        user_word.last_review = now
        user_word.next_review = now + timedelta(days=next_interval)
        user_word.scheduled_days = next_interval
        user_word.elapsed_days = 0
        
        if user_word.reps >= 5 and user_word.lapses <= 2:
            user_word.is_learned = True
    
    def get_review_schedule(self, user_words):
        """Получить расписание повторений для пользователя"""
        schedule = {
            'today': [],
            'tomorrow': [],
            'this_week': [],
            'next_week': [],
            'future': []
        }
        
        now = timezone.now()
        tomorrow = now + timedelta(days=1)
        next_week = now + timedelta(days=7)
        two_weeks = now + timedelta(days=14)
        
        for word in user_words:
            if not word.next_review:
                schedule['today'].append(word)
            elif word.next_review <= now:
                schedule['today'].append(word)
            elif word.next_review <= tomorrow:
                schedule['tomorrow'].append(word)
            elif word.next_review <= next_week:
                schedule['this_week'].append(word)
            elif word.next_review <= two_weeks:
                schedule['next_week'].append(word)
            else:
                schedule['future'].append(word)
        
        return schedule