import random
from django.db.models import Count
from typing import List, Dict
from django.utils import timezone
from dictionary.models import Word
from users.models import UserWord, UserTopicProgress
from .fsrs_optimizer import FSRSOptimizer

class ExerciseGenerator:
    """
    Генератор заданий для обучения
    """
    
    def __init__(self, user, topic_id=None):
        self.user = user
        self.topic_id = topic_id
        self.fsrs = FSRSOptimizer()
        
    def get_next_exercise(self, exercise_type=None):
        """Получить следующее задание для пользователя"""
        if not exercise_type:
            exercise_type = self._select_exercise_type()
        
        words = self._select_words_for_exercise(exercise_type)
        
        if not words:
            return None
        
        exercise = self._generate_exercise(exercise_type, words)
        return exercise
    
    def _select_exercise_type(self) -> str:
        """Выбрать тип задания на основе истории пользователя"""
        from users.models import UserExerciseHistory
        
        history = UserExerciseHistory.objects.filter(user=self.user)
        
        if not history.exists():
            return random.choice(['translation_ru', 'multiple_choice'])
        
        type_counts = history.values('exercise_type').annotate(count=Count('id'))
        least_used = min(type_counts, key=lambda x: x['count'])['exercise_type']
        
        if random.random() < 0.7:
            return least_used
        else:
            return random.choice([
                'translation_ru', 'translation_cn', 'matching',
                'multiple_choice', 'writing'
            ])
    
    def _select_words_for_exercise(self, exercise_type: str) -> List[Word]:
        """Выбрать слова для задания"""
        words = []
        
        review_words = self._get_words_for_review()
        new_word_ratio = self._calculate_new_word_ratio()
        
        if review_words:
            words.extend(random.sample(
                review_words,
                min(len(review_words), 3 if exercise_type == 'matching' else 1)
            ))
        
        if random.random() < new_word_ratio and len(words) < 4:
            new_words = self._get_new_words()
            if new_words:
                words.append(random.choice(new_words))
        
        if exercise_type == 'matching' and len(words) < 4:
            additional_words = self._get_additional_words(len(words))
            words.extend(additional_words)
        
        return words
    
    def _get_words_for_review(self) -> List[Word]:
        """Получить слова для повторения"""
        user_words = UserWord.objects.filter(
            user=self.user,
            due__lte=timezone.now()
        ).select_related('word')
        
        if self.topic_id:
            user_words = user_words.filter(
                word__word_tags__tag__topic_id=self.topic_id
            ).distinct()
        
        sorted_words = sorted(
            user_words,
            key=lambda uw: uw.get_review_urgency(),
            reverse=True
        )
        
        return [uw.word for uw in sorted_words[:10]]
    
    def _calculate_new_word_ratio(self) -> float:
        """Рассчитать соотношение новых слов на основе прогресса"""
        pending_reviews = UserWord.objects.filter(
            user=self.user,
            due__lte=timezone.now()
        ).count()
        
        base_ratio = 0.3
        
        if pending_reviews > 20:
            return base_ratio * 0.3
        elif pending_reviews > 10:
            return base_ratio * 0.6
        elif pending_reviews > 5:
            return base_ratio * 0.8
        else:
            return base_ratio
    
    def _get_new_words(self) -> List[Word]:
        """Получить новые слова для пользователя"""
        user_word_ids = UserWord.objects.filter(
            user=self.user
        ).values_list('word_id', flat=True)
        
        query = Word.objects.exclude(id__in=user_word_ids)
        
        if self.topic_id:
            query = query.filter(
                word_tags__tag__topic_id=self.topic_id
            ).distinct()
        else:
            active_topics = UserTopicProgress.objects.filter(
                user=self.user,
                is_active=True
            ).values_list('topic_id', flat=True)
            
            if active_topics:
                query = query.filter(
                    word_tags__tag__topic_id__in=active_topics
                ).distinct()
        
        query = query.order_by('difficulty', 'hanzi')
        
        if not user_word_ids.exists():
            basic_words = query.filter(difficulty=1)[:20]
            return list(basic_words)
        
        return list(query[:10])
    
    def _get_additional_words(self, count_needed: int) -> List[Word]:
        """Получить дополнительные слова для заданий"""
        user_word_ids = UserWord.objects.filter(
            user=self.user
        ).values_list('word_id', flat=True)
        
        query = Word.objects.filter(
            word_tags__tag__topic_id=self.topic_id
        ) if self.topic_id else Word.objects.all()
        
        query = query.exclude(id__in=user_word_ids)
        
        return list(query.order_by('?')[:count_needed])
    
    def _generate_exercise(self, exercise_type: str, words: List[Word]) -> Dict:
        """Сгенерировать конкретное задание"""
        if exercise_type == 'translation_ru':
            return self._generate_translation_exercise(words[0], direction='cn_to_ru')
        elif exercise_type == 'translation_cn':
            return self._generate_translation_exercise(words[0], direction='ru_to_cn')
        elif exercise_type == 'matching':
            return self._generate_matching_exercise(words)
        elif exercise_type == 'multiple_choice':
            return self._generate_multiple_choice_exercise(words[0])
        elif exercise_type == 'writing':
            return self._generate_writing_exercise(words[0])
        else:
            return self._generate_translation_exercise(words[0], direction='cn_to_ru')
    
    def _generate_translation_exercise(self, word: Word, direction: str) -> Dict:
        """Сгенерировать задание на перевод"""
        if direction == 'cn_to_ru':
            question = f"Переведите слово: **{word.hanzi}** ({word.pinyin_graphic})"
            correct_answer = self._get_random_translation(word.translation)
        else:
            translations = word.translation.split(';')
            correct_translation = random.choice(translations).strip()
            question = f"Как будет **{correct_translation}** по-китайски?"
            correct_answer = word.hanzi
        
        return {
            'type': 'translation',
            'direction': direction,
            'word_id': word.id,
            'question': question,
            'correct_answer': correct_answer,
            'hint': word.pinyin_graphic if direction == 'ru_to_cn' else None,
            'difficulty': word.difficulty
        }
    
    def _generate_matching_exercise(self, words: List[Word]) -> Dict:
        """Сгенерировать задание на сопоставление"""
        if len(words) < 4:
            additional = self._get_additional_words(4 - len(words))
            words.extend(additional)
        
        random.shuffle(words)
        
        pairs = []
        for word in words[:4]:
            translation = self._get_random_translation(word.translation)
            pairs.append({
                'chinese': word.hanzi,
                'pinyin': word.pinyin_graphic,
                'translation': translation
            })
        
        correct_pairs = [(i, i) for i in range(len(pairs))]
        
        return {
            'type': 'matching',
            'pairs': pairs,
            'correct_pairs': correct_pairs,
            'instructions': 'Сопоставьте китайские слова с их переводами'
        }
    
    def _generate_multiple_choice_exercise(self, word: Word) -> Dict:
        """Сгенерировать задание с множественным выбором"""
        correct_translation = self._get_random_translation(word.translation)
        
        incorrect_options = self._get_wrong_translations(word, 3)
        
        options = [correct_translation] + incorrect_options
        random.shuffle(options)
        
        correct_index = options.index(correct_translation)
        
        return {
            'type': 'multiple_choice',
            'word_id': word.id,
            'question': f"Выберите правильный перевод слова: **{word.hanzi}** ({word.pinyin_graphic})",
            'options': options,
            'correct_index': correct_index,
            'hint': f"Сложность: HSK {word.difficulty}"
        }
    
    def _generate_writing_exercise(self, word: Word) -> Dict:
        """Сгенерировать задание на написание иероглифов"""
        return {
            'type': 'writing',
            'word_id': word.id,
            'hanzi': word.hanzi,
            'pinyin': word.pinyin_graphic,
            'translation': self._get_random_translation(word.translation),
            'stroke_data': self._get_stroke_data(word),
            'instructions': 'Повторите написание иероглифов в правильной последовательности'
        }
    
    def _get_random_translation(self, translation_text: str) -> str:
        """Получить случайный перевод из строки с несколькими переводами"""
        translations = [t.strip() for t in translation_text.split(';') if t.strip()]
        return random.choice(translations) if translations else translation_text
    
    def _get_wrong_translations(self, correct_word: Word, count: int) -> List[str]:
        """Получить неправильные варианты перевода"""
        if self.topic_id:
            other_words = Word.objects.filter(
                word_tags__tag__topic_id=self.topic_id
            ).exclude(id=correct_word.id).order_by('?')[:10]
        else:
            other_words = Word.objects.exclude(id=correct_word.id).order_by('?')[:10]
        
        wrong_translations = []
        for word in other_words:
            if len(wrong_translations) >= count:
                break
            translation = self._get_random_translation(word.translation)
            if translation and translation not in wrong_translations:
                wrong_translations.append(translation)
        
        return wrong_translations
    
    def _get_stroke_data(self, word: Word) -> Dict:
        """Получить данные о штрихах иероглифа"""
        return {
            'character': word.hanzi,
            'stroke_count': len(word.hanzi),
            'medians': []
        }
    
    def auto_add_word_to_dictionary(self, word: Word):
        """Автоматически добавить слово в словарь пользователя"""
        if not UserWord.objects.filter(user=self.user, word=word).exists():
            user_word = UserWord.objects.create(
                user=self.user,
                word=word,
                state=0,
                difficulty=word.difficulty,
                stability=1.0
            )
            return user_word
        return None