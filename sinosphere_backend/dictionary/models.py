from django.db import models

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
        
        if self.position > len(self.child_word.hanzi):
            raise ValidationError(
                f"Позиция {self.position} превышает длину слова '{self.child_word.hanzi}'"
            )
        
        expected_hanzi = self.child_word.hanzi[self.position - 1]
        if self.parent_word.hanzi != expected_hanzi:
            raise ValidationError(
                f"Иероглиф '{self.parent_word.hanzi}' не совпадает с иероглифом "
                f"'{expected_hanzi}' на позиции {self.position} в слове '{self.child_word.hanzi}'"
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Слово {self.child_word} содержит слово {self.parent_word} (позиция: {self.position})"

class Tag(models.Model):
    name = models.CharField(max_length=32, unique=True, verbose_name='Название тэга')

    class Meta:
        indexes = [
            models.Index(fields=['name'], name='idx_tag_name')
        ]

        verbose_name = 'Тэг'
        verbose_name_plural = 'Тэги'

    def __str__(self):
        return self.name

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
        on_delete = models.CASCADE,
        related_name='tags'
    )
    tag = models.ForeignKey(
        Tag,
        on_delete = models.CASCADE,
        related_name='tagged_words'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['word', 'tag'],
                name='unique_word_tag'
            )
        ]

    def __str__(self):
        return f"Слово {self.word} имеет тэг \"{self.tag}\""

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