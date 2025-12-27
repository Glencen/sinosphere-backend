from users.models import UserWord

class DifficultyEstimator:
    """
    Оценщик сложности упражнений на основе истории пользователя
    """
    
    @staticmethod
    def estimate_word_difficulty_for_user(user, word, exercise_type=None):
        """
        Оценить сложность слова для конкретного пользователя
        Возвращает оценку от 1 (легко) до 10 (очень сложно)
        """
        try:
            user_word = UserWord.objects.get(user=user, word=word)
            time_score = min(user_word.avg_response_time / 10, 1.0) * 4
            
            if user_word.total_attempts > 0:
                accuracy = user_word.correct_attempts / user_word.total_attempts
                accuracy_score = (1 - accuracy) * 4
            else:
                accuracy_score = 4
            
            stability_score = max(0, (365 - user_word.stability) / 365) * 2
            total_difficulty = time_score + accuracy_score + stability_score
            
            return min(10, max(1, total_difficulty))
            
        except UserWord.DoesNotExist:
            base_difficulty = word.difficulty
            
            if exercise_type == 'translation_cn':
                base_difficulty += 2
            elif exercise_type == 'writing':
                base_difficulty += 3
            
            return min(10, base_difficulty)
    
    @staticmethod
    def adjust_exercise_parameters(user, word, exercise_type, base_parameters):
        """
        Настроить параметры упражнения на основе истории пользователя
        """
        difficulty = DifficultyEstimator.estimate_word_difficulty_for_user(
            user, word, exercise_type
        )
        
        adjusted_params = base_parameters.copy()
        
        if 'time_limit' in adjusted_params:
            time_multiplier = 1.0 + (difficulty - 5) * 0.1
            adjusted_params['time_limit'] = int(
                adjusted_params['time_limit'] * time_multiplier
            )
        
        if difficulty > 7:
            adjusted_params['hints_available'] = 2
        elif difficulty > 5:
            adjusted_params['hints_available'] = 1
        else:
            adjusted_params['hints_available'] = 0
        
        if exercise_type == 'translation_ru':
            if difficulty > 8:
                adjusted_params['show_pinyin'] = True
                adjusted_params['show_character'] = True
            elif difficulty > 6:
                adjusted_params['show_pinyin'] = True
                adjusted_params['show_character'] = False
            else:
                adjusted_params['show_pinyin'] = False
                adjusted_params['show_character'] = False
        
        return adjusted_params