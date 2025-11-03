from django.db import models
from django.core.exceptions import ValidationError

class Word(models.Model):
    traditional = models.CharField(max_length=20, verbose_name="Традиционный")
    simplified = models.CharField(max_length=20, verbose_name="Упрощенный")
    pinyin = models.CharField(max_length=255, verbose_name="Пиньинь")
    translation = models.TextField(verbose_name="Перевод")
    
    class Meta:
        verbose_name = 'Слово'
        verbose_name_plural = 'Слова'
        indexes = [
            models.Index(fields=['simplified']),
            models.Index(fields=['traditional']),
            models.Index(fields=['pinyin']),
        ]
    
    def __str__(self):
        return f"{self.simplified} ({self.pinyin})"

class Dictionary(models.Model):
    DICTIONARY_TYPES = [
        ('global', 'Общий словарь'),
        ('user', 'Пользовательский словарь'),
    ]
    
    name = models.CharField(max_length=100, verbose_name="Название")
    dictionary_type = models.CharField(
        max_length=10, 
        choices=DICTIONARY_TYPES,
        default='user'
    )
    
    class Meta:
        verbose_name = 'Словарь'
        verbose_name_plural = 'Словари'
    
    def clean(self):
        if self.dictionary_type == 'global':
            existing_global = Dictionary.objects.filter(
                dictionary_type='global'
            ).exclude(pk=self.pk)
            
            if existing_global.exists():
                raise ValidationError({
                    'dictionary_type': 'Может существовать только один глобальный словарь'
                })
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.dictionary_type == 'global':
            raise ValidationError("Нельзя удалить глобальный словарь")
        super().delete(*args, **kwargs)
    
    def __str__(self):
        return self.name

class DictionaryEntry(models.Model):
    dictionary = models.ForeignKey(
        Dictionary, 
        on_delete=models.CASCADE,
        related_name='entries'
    )
    word = models.ForeignKey(
        Word, 
        on_delete=models.CASCADE,
        related_name='dictionary_entries'
    )
    added_date = models.DateTimeField(auto_now_add=True, verbose_name="Дата добавления")
    notes = models.TextField(blank=True, verbose_name="Заметки пользователя")
    
    class Meta:
        verbose_name = 'Запись словаря'
        verbose_name_plural = 'Записи словаря'
        unique_together = ['dictionary', 'word']
    
    def __str__(self):
        return f"{self.dictionary.name} - {self.word.simplified}"
    
def ensure_global_dictionary_exists():
    from django.db import transaction
    with transaction.atomic():
        if not Dictionary.objects.filter(dictionary_type='global').exists():
            Dictionary.objects.create(
                name='Глобальный словарь',
                dictionary_type='global'
            )
