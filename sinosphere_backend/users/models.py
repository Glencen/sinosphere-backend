from django.db import models
from django.contrib.auth.models import User
from dictionary.models import Dictionary

class UserProfile(models.Model):
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE,
        related_name='profile'
    )
    personal_dictionary = models.OneToOneField(
        Dictionary,
        on_delete=models.CASCADE,
        related_name='user_profile'
    )
    
    class Meta:
        verbose_name = 'Профиль пользователя'
        verbose_name_plural = 'Профили пользователей'
    
    def __str__(self):
        return f"Профиль: {self.user.username}"