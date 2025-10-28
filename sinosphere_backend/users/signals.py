from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from dictionary.models import Dictionary
from .models import UserProfile

@receiver(post_save, sender=User)
def create_user_profile_and_dictionary(sender, instance, created, **kwargs):
    if created:
        personal_dict = Dictionary.objects.create(
            name=f"Личный словарь {instance.username}",
            dictionary_type='user',
            description=f"Персональный словарь пользователя {instance.username}"
        )
        UserProfile.objects.create(
            user=instance,
            personal_dictionary=personal_dict
        )