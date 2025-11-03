from django.db.models.signals import post_migrate
from django.dispatch import receiver

@receiver(post_migrate)
def create_global_dictionary(sender, **kwargs):
    if sender.name == 'dictionary':
        from dictionary.utils import get_or_create_global_dictionary
        try:
            get_or_create_global_dictionary()
        except Exception:
            pass
