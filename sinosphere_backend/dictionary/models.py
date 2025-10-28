from django.db import models

class Word(models.Model):
    traditional = models.CharField(max_length=10, verbose_name="Традиционный")
    simplified = models.CharField(max_length=10, verbose_name="Упрощенный")
    pinyin = models.CharField(max_length=50, verbose_name="Пиньинь")
    translation = models.TextField(verbose_name="Перевод")
    
    class Meta:
        verbose_name = 'Слово'
        verbose_name_plural = 'Слова'
    
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