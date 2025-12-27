from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from .models import UserProfile, UserWord, UserLearningProfile, UserTopicProgress, UserExerciseHistory, ReviewLog
from dictionary.models import Word
from dictionary.serializers import WordSerializer, TopicSerializer

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'password_confirm')
        extra_kwargs = {
            'email': {'required': True},
        }
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password": "Пароли не совпадают"})
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        return User.objects.create_user(**validated_data)

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = UserProfile
        fields = '__all__'

class UserWordSerializer(serializers.ModelSerializer):
    word_detail = WordSerializer(source='word', read_only=True)
    word_id = serializers.IntegerField(write_only=True, required=False)
    
    class Meta:
        model = UserWord
        fields = [
            'id', 'user', 'word', 'word_detail', 'word_id',
            'added_date', 'notes', 'is_learned', 'last_reviewed',
            'review_count', 'ease_factor'
        ]
        read_only_fields = [
            'user', 'added_date', 'last_reviewed', 
            'review_count', 'ease_factor'
        ]
        extra_kwargs = {
            'word': {'read_only': True},
        }
    
    def validate(self, attrs):
        request = self.context.get('request')
        if not request:
            return attrs
            
        if request.method == 'POST':
            user = request.user
            word_id = attrs.get('word_id')
            
            if word_id and UserWord.objects.filter(user=user, word_id=word_id).exists():
                raise serializers.ValidationError({
                    'word_id': 'Это слово уже есть в вашем словаре'
                })
        
        return attrs
    
    def create(self, validated_data):
        request = self.context.get('request')
        if not request or not hasattr(request, 'user'):
            raise serializers.ValidationError("Пользователь не найден")
        
        word_id = validated_data.pop('word_id', None)
        if not word_id:
            raise serializers.ValidationError({"word_id": "Обязательное поле"})
        
        try:
            word = Word.objects.get(id=word_id)
        except Word.DoesNotExist:
            raise serializers.ValidationError({"word_id": "Слово не найдено"})
        
        return UserWord.objects.create(
            user=request.user,
            word=word,
            **validated_data
        )
    
    def update(self, instance, validated_data):
        validated_data.pop('word_id', None)
        
        if 'is_learned' in validated_data:
            is_learned = validated_data['is_learned']
            if is_learned and not instance.is_learned:
                instance.last_reviewed = timezone.now()
            elif not is_learned and instance.is_learned:
                instance.review_count = 0
        
        return super().update(instance, validated_data)

class UserWordReviewSerializer(serializers.Serializer):
    quality = serializers.IntegerField(min_value=0, max_value=5)
    
    def update(self, instance, validated_data):
        quality = validated_data['quality']
        
        if quality < 3:
            instance.review_count = 0
            instance.ease_factor = max(1.3, instance.ease_factor - 0.2)
        else:
            if instance.review_count == 0:
                interval = 1
            elif instance.review_count == 1:
                interval = 6
            else:
                interval = round(instance.review_count * instance.ease_factor)
            
            instance.ease_factor = instance.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
            instance.ease_factor = max(1.3, instance.ease_factor)
            
            instance.last_reviewed = timezone.now()
            instance.review_count += 1
            
            if instance.review_count >= 5 and not instance.is_learned:
                instance.is_learned = True
        
        instance.save()
        return instance
    
class UserLearningProfileSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    
    class Meta:
        model = UserLearningProfile
        fields = [
            'id', 'user', 'fsrs_weights', 'new_cards_per_day', 'max_reviews_per_day',
            'learning_steps', 're_learning_steps', 'desired_retention', 'maximum_interval'
        ]
        read_only_fields = ['user']
    
    def validate_fsrs_weights(self, value):
        """Валидация FSRS весов"""
        try:
            import json
            weights = json.loads(value)
            if not isinstance(weights, list) or len(weights) != 20:
                raise serializers.ValidationError(
                    "FSRS weights должен быть списком из 20 значений"
                )
        except (json.JSONDecodeError, TypeError):
            raise serializers.ValidationError(
                "Неверный формат FSRS weights. Ожидается JSON список."
            )
        return value


class UserTopicProgressSerializer(serializers.ModelSerializer):
    topic_info = TopicSerializer(source='topic', read_only=True)
    user = serializers.StringRelatedField(read_only=True)
    progress_percentage = serializers.SerializerMethodField()
    mastery_label = serializers.SerializerMethodField()
    
    class Meta:
        model = UserTopicProgress
        fields = [
            'id', 'user', 'topic', 'topic_info', 'words_learned', 'total_words',
            'accuracy', 'total_attempts', 'total_correct', 'last_practiced',
            'is_active', 'mastery_level', 'mastery_label', 'progress_percentage'
        ]
        read_only_fields = [
            'user', 'words_learned', 'total_words', 'accuracy',
            'total_attempts', 'total_correct', 'last_practiced'
        ]
    
    def get_progress_percentage(self, obj):
        if obj.total_words > 0:
            return round((obj.words_learned / obj.total_words) * 100, 1)
        return 0
    
    def get_mastery_label(self, obj):
        labels = {
            0: 'Не начато',
            1: 'Начинающий',
            2: 'Осваивает',
            3: 'Средний',
            4: 'Продвинутый',
            5: 'Мастер'
        }
        return labels.get(obj.mastery_level, 'Неизвестно')


class UserExerciseHistorySerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    word_info = WordSerializer(source='word', read_only=True)
    topic_info = serializers.SerializerMethodField()
    exercise_type_display = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source='created_at', read_only=True)
    
    class Meta:
        model = UserExerciseHistory
        fields = [
            'id', 'user', 'exercise_type', 'exercise_type_display',
            'word', 'word_info', 'topic', 'topic_info',
            'is_correct', 'time_spent', 'difficulty', 'user_rating',
            'timestamp', 'created_at'
        ]
        read_only_fields = ['user', 'created_at']
    
    def get_exercise_type_display(self, obj):
        return dict(UserExerciseHistory.EXERCISE_TYPES).get(obj.exercise_type, obj.exercise_type)
    
    def get_topic_info(self, obj):
        if obj.topic:
            return TopicSerializer(obj.topic).data
        return None


class ReviewLogSerializer(serializers.ModelSerializer):
    user_word_info = serializers.SerializerMethodField()
    rating_display = serializers.SerializerMethodField()
    word_info = serializers.SerializerMethodField()
    
    class Meta:
        model = ReviewLog
        fields = [
            'id', 'user_word', 'user_word_info', 'rating', 'rating_display',
            'is_correct', 'response_time', 'exercise_type', 'review_date',
            'scheduled_days', 'word_info'
        ]
        read_only_fields = ['review_date']
    
    def get_user_word_info(self, obj):
        return {
            'id': obj.user_word.id,
            'word_id': obj.user_word.word_id,
            'state': obj.user_word.state,
            'reps': obj.user_word.reps,
            'lapses': obj.user_word.lapses
        }
    
    def get_rating_display(self, obj):
        rating_map = {
            1: 'Again (Забыл)',
            2: 'Hard (С трудом)',
            3: 'Good (Вспомнил)',
            4: 'Easy (Легко)'
        }
        return rating_map.get(obj.rating, str(obj.rating))
    
    def get_word_info(self, obj):
        word = obj.user_word.word
        return {
            'id': word.id,
            'hanzi': word.hanzi,
            'pinyin': word.pinyin_graphic,
            'translation': word.translation.split(';')[0].strip() if ';' in word.translation else word.translation
        }


class UserWordDetailSerializer(serializers.ModelSerializer):
    word_info = WordSerializer(source='word', read_only=True)
    user = serializers.StringRelatedField(read_only=True)
    mastery_score = serializers.FloatField(read_only=True)
    is_learned = serializers.BooleanField(read_only=True)
    next_review_days = serializers.SerializerMethodField()
    review_urgency = serializers.FloatField(read_only=True)
    review_history = serializers.SerializerMethodField()
    
    class Meta:
        model = UserWord
        fields = [
            'id', 'user', 'word', 'word_info', 'added_date', 'notes',
            'due', 'stability', 'difficulty', 'elapsed_days', 'scheduled_days',
            'reps', 'lapses', 'state', 'last_review',
            'total_attempts', 'correct_attempts', 'avg_response_time', 'consecutive_correct',
            'mastery_score', 'is_learned', 'next_review_days', 'review_urgency',
            'review_history'
        ]
        read_only_fields = [
            'user', 'added_date', 'due', 'stability', 'difficulty',
            'elapsed_days', 'scheduled_days', 'reps', 'lapses', 'state',
            'last_review', 'total_attempts', 'correct_attempts',
            'avg_response_time', 'consecutive_correct'
        ]
    
    def get_next_review_days(self, obj):
        if obj.due:
            now = timezone.now()
            if obj.due > now:
                delta = obj.due - now
                return delta.days
        return 0
    
    def get_review_history(self, obj):
        logs = ReviewLog.objects.filter(user_word=obj).order_by('-review_date')[:10]
        return ReviewLogSerializer(logs, many=True).data


class UserWordListSerializer(serializers.ModelSerializer):
    word_info = WordSerializer(source='word', read_only=True)
    mastery_score = serializers.FloatField(read_only=True)
    is_learned = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = UserWord
        fields = [
            'id', 'word', 'word_info', 'state', 'due', 'last_review',
            'reps', 'lapses', 'mastery_score', 'is_learned',
            'total_attempts', 'correct_attempts', 'avg_response_time'
        ]


class UserExerciseStatsSerializer(serializers.Serializer):
    """Сериализатор для статистики упражнений"""
    date = serializers.DateField()
    total_exercises = serializers.IntegerField()
    correct_exercises = serializers.IntegerField()
    accuracy = serializers.FloatField()
    avg_time = serializers.FloatField()
    exercise_types = serializers.DictField()


class UserLearningAnalyticsSerializer(serializers.Serializer):
    """Сериализатор для аналитики обучения"""
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    total_words_studied = serializers.IntegerField()
    new_words_added = serializers.IntegerField()
    total_time_spent = serializers.IntegerField()
    avg_daily_accuracy = serializers.FloatField()
    streak_days = serializers.IntegerField()
    top_topics = serializers.ListField(child=serializers.DictField())
    weak_words = serializers.ListField(child=serializers.DictField())