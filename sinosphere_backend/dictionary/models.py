from django.db import models
from django.utils import timezone

class Word(models.Model):
    hanzi = models.CharField(max_length=32, default='', verbose_name="Иероглифы")
    pinyin_numeric = models.CharField(max_length=255, default='', verbose_name="Пиньинь с цифровым представлением тонов")
    pinyin_graphic = models.CharField(max_length=255, default='', verbose_name="Пиньинь с тональными символами")
    translation = models.TextField(default='', verbose_name="Перевод")
    difficulty = models.PositiveSmallIntegerField(default=0, verbose_name="Сложность слова по стандарту HSK (от 2021 года)")
    
    class Meta:
        verbose_name = 'Слово'
        verbose_name_plural = 'Слова'
        indexes = [
            models.Index(fields=['hanzi'], name='idx_word_hanzi'),
            models.Index(fields=['pinyin_numeric'], name='idx_word_pinyin_numeric'),
            models.Index(fields=['difficulty'], name='idx_word_difficulty')
        ]
    
    def __str__(self):
        return f"{self.hanzi} ({self.pinyin_graphic})"

class WordComposition(models.Model):
    child_word = models.ForeignKey(
        Word,
        on_delete=models.CASCADE,
        related_name='components'
    )
    parent_word = models.ForeignKey(
        Word,
        on_delete=models.CASCADE,
        related_name='used_in_words'
    )
    position = models.PositiveSmallIntegerField(
        default=1,
        help_text='Позиция parent_word в child_word'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['child_word', 'position'],
                name='unique_position_in_word'
            )
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.parent_word == self.child_word:
            raise ValidationError("Слово не может быть компонентом самого себя")
        
        if len(self.parent_word.hanzi) > 1:
            raise ValidationError("Родительское слово должно содержать только один иероглиф")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Слово {self.child_word} содержит слово {self.parent_word} (позиция: {self.position})"
    
class Topic(models.Model):
    name = models.CharField(max_length=64, unique=True, verbose_name='Название темы')
    description = models.TextField(blank=True, verbose_name='Описание')
    parent_topic = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subtopics',
        verbose_name='Родительская тема'
    )
    weight = models.FloatField(
        default=1.0,
        verbose_name='Вес темы',
        help_text='Используется для приоритизации в обучении'
    )
    icon = models.CharField(
        max_length=32,
        blank=True,
        verbose_name='Иконка темы'
    )
    difficulty_level = models.PositiveSmallIntegerField(
        default=1,
        verbose_name='Уровень сложности темы',
        help_text='1-6 (по аналогии с HSK)'
    )
    is_active = models.BooleanField(default=True, verbose_name='Активна')
    order = models.IntegerField(default=0, verbose_name='Порядок отображения')
    
    class Meta:
        verbose_name = 'Тема'
        verbose_name_plural = 'Темы'
        ordering = ['order', 'name']
        indexes = [
            models.Index(fields=['name'], name='idx_topic_name'),
            models.Index(fields=['difficulty_level'], name='idx_topic_difficulty'),
            models.Index(fields=['is_active'], name='idx_topic_active'),
        ]
    
    def __str__(self):
        return self.name
    
    def get_all_tags(self):
        return self.tags.all()

class Tag(models.Model):
    name = models.CharField(max_length=32, unique=True, verbose_name='Название тэга')
    topic = models.ForeignKey(
        Topic,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tags',
        verbose_name='Тема'
    )
    description = models.TextField(blank=True, verbose_name='Описание')
    weight = models.FloatField(
        default=1.0,
        verbose_name='Вес тэга',
        help_text='Используется для приоритизации в обучении'
    )
    frequency_rank = models.IntegerField(
        default=0,
        verbose_name='Ранг частотности',
        help_text='Чем меньше, тем чаще встречается'
    )
    
    class Meta:
        verbose_name = 'Тэг'
        verbose_name_plural = 'Тэги'
        indexes = [
            models.Index(fields=['name'], name='idx_tag_name'),
            models.Index(fields=['weight'], name='idx_tag_weight'),
            models.Index(fields=['frequency_rank'], name='idx_tag_frequency'),
        ]
    
    def __str__(self):
        return f"{self.name}"
    
class ExampleSentence(models.Model):
    word = models.ForeignKey(
        Word,
        on_delete=models.CASCADE,
        related_name='examples',
        verbose_name='Слово'
    )
    chinese_sentence = models.TextField(verbose_name='Предложение на китайском')
    pinyin_sentence = models.TextField(verbose_name='Пиньинь')
    translation = models.TextField(verbose_name='Перевод')
    difficulty = models.PositiveSmallIntegerField(
        default=1,
        verbose_name='Сложность предложения'
    )
    
    class Meta:
        verbose_name = 'Пример предложения'
        verbose_name_plural = 'Примеры предложений'
    
    def __str__(self):
        return f"{self.word.hanzi}: {self.chinese_sentence[:50]}..."

class PartOfSpeech(models.Model):
    name = models.CharField(max_length=32, unique=True, verbose_name='Название части слова')

    class Meta:
        indexes = [
            models.Index(fields=['name'], name='idx_part_of_speech_name')
        ]

        verbose_name = 'Часть речи'
        verbose_name_plural = 'Части речи'

    def __str__(self):
        return self.name

class WordTag(models.Model):
    word = models.ForeignKey(
        Word,
        on_delete=models.CASCADE,
        related_name='word_tags'
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.CASCADE,
        related_name='tagged_words'
    )
    added_date = models.DateTimeField(
        default=timezone.now,
        verbose_name='Дата добавления'
    )
    relevance_score = models.FloatField(
        default=1.0,
        verbose_name='Релевантность слова для тега',
        help_text='Насколько хорошо слово соответствует тегу (0-1)'
    )
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['word', 'tag'],
                name='unique_word_tag'
            )
        ]
        verbose_name = 'Связь слова с тегом'
        verbose_name_plural = 'Связи слов с тегами'
        indexes = [
            models.Index(fields=['word', 'tag'], name='idx_word_tag'),
        ]
    
    def __str__(self):
        return f"Слово {self.word.hanzi} имеет тэг {self.tag.name}"

class WordPartOfSpeech(models.Model):
    word = models.ForeignKey(
        Word,
        on_delete = models.CASCADE,
        related_name='parts_of_speech'
    )
    part_of_speech = models.ForeignKey(
        PartOfSpeech,
        on_delete = models.CASCADE,
        related_name='as_words'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['word', 'part_of_speech'],
                name='unique_word_part_of_speech'
            )
        ]

    def __str__(self):
        return f"Слово {self.word} является частью речи: {self.part_of_speech}"