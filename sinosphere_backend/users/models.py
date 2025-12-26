from django.db import models
from django.contrib.auth.models import User
from dictionary.models import Word

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
        on_delete = models.CASCADE,
        related_name='words'
    )
    word = models.ForeignKey(
        Word,
        on_delete = models.CASCADE,
        related_name='user_words'
    )
    added_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(max_length=255, blank=True)
    is_learned = models.BooleanField(default=False)
    last_reviewed = models.DateTimeField(null=True, blank=True)
    review_count = models.IntegerField(default=0)
    ease_factor = models.FloatField(default=2.5)

    class Meta:
        verbose_name = 'Слово пользователя'
        verbose_name_plural = 'Слова пользователя'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'word'],
                name='unique_user_word'
            )
        ]
    
    def __str__(self):
        return f"Слово {self.word} содержится в личном словаре пользователя {self.user}"