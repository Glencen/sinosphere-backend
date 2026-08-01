import json

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers

from .models import (
    ReviewLog,
    UserExerciseHistory,
    UserLearningProfile,
    UserProfile,
    UserTopicProgress,
    UserWord,
)
from dictionary.models import Word
from dictionary.serializers import TopicSerializer, WordSerializer


User = get_user_model()

def _word_payload(word):
    if not word:
        return None
    return {
        'id': word.id,
        'hanzi': word.hanzi,
        'pinyin': word.pinyin_graphic,
        'pinyin_graphic': word.pinyin_graphic,
        'pinyin_numeric': word.pinyin_numeric,
        'translation': word.translation,
        'difficulty': word.difficulty,
    }

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'password_confirm')
        extra_kwargs = {'email': {'required': True}}

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password': 'Passwords do not match'})
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
    word = serializers.SerializerMethodField()
    word_id = serializers.IntegerField(write_only=True, required=False)
    mastery_score = serializers.FloatField(read_only=True)
    is_learned = serializers.BooleanField(read_only=True)
    review_urgency = serializers.SerializerMethodField()

    class Meta:
        model = UserWord
        fields = [
            'id', 'user', 'word', 'word_id', 'added_date', 'notes',
            'due', 'stability', 'difficulty', 'elapsed_days', 'scheduled_days',
            'reps', 'lapses', 'state', 'last_review', 'total_attempts',
            'correct_attempts', 'avg_response_time', 'consecutive_correct',
            'mastery_score', 'is_learned', 'review_urgency',
        ]
        read_only_fields = [
            'user', 'word', 'added_date', 'due', 'stability', 'difficulty',
            'elapsed_days', 'scheduled_days', 'reps', 'lapses', 'state',
            'last_review', 'total_attempts', 'correct_attempts',
            'avg_response_time', 'consecutive_correct', 'mastery_score',
            'is_learned', 'review_urgency',
        ]

    def get_word(self, obj):
        return _word_payload(obj.word)



    def get_review_urgency(self, obj):
        return obj.get_review_urgency()

    def validate(self, attrs):
        request = self.context.get('request')
        if request and request.method == 'POST':
            word_id = attrs.get('word_id')
            if word_id and UserWord.objects.filter(user=request.user, word_id=word_id).exists():
                raise serializers.ValidationError({
                    'word_id': 'This word is already in your dictionary'
                })
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        if not request or not hasattr(request, 'user'):
            raise serializers.ValidationError('User is required')

        word_id = validated_data.pop('word_id', None)
        if not word_id:
            raise serializers.ValidationError({'word_id': 'This field is required'})

        try:
            word = Word.objects.get(id=word_id)
        except Word.DoesNotExist as exc:
            raise serializers.ValidationError({'word_id': 'Word not found'}) from exc

        return UserWord.objects.create(user=request.user, word=word, **validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('word_id', None)
        return super().update(instance, validated_data)


class UserWordReviewSerializer(serializers.Serializer):
    quality = serializers.IntegerField(min_value=0, max_value=5)
    time_spent = serializers.FloatField(default=0)
    exercise_type = serializers.CharField(default='manual_review')

    def update(self, instance, validated_data):
        # Legacy endpoint compatibility: quality 0-2 is a failed review, 3-5 is successful.
        is_correct = validated_data['quality'] >= 3
        instance.update_review(
            is_correct=is_correct,
            response_time=validated_data.get('time_spent', 0),
            exercise_type=validated_data.get('exercise_type', 'manual_review'),
        )
        return instance


class UserLearningProfileSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = UserLearningProfile
        fields = [
            'id', 'user', 'fsrs_weights', 'new_cards_per_day', 'max_reviews_per_day',
            'learning_steps', 're_learning_steps', 'desired_retention', 'maximum_interval',
        ]
        read_only_fields = ['user']

    def validate_fsrs_weights(self, value):
        try:
            weights = json.loads(value)
        except (json.JSONDecodeError, TypeError) as exc:
            raise serializers.ValidationError('FSRS weights must be a JSON list') from exc

        if not isinstance(weights, list) or len(weights) != 20:
            raise serializers.ValidationError('FSRS weights must be a list of 20 numbers')
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
            'is_active', 'mastery_level', 'mastery_label', 'progress_percentage',
        ]
        read_only_fields = [
            'user', 'words_learned', 'total_words', 'accuracy',
            'total_attempts', 'total_correct', 'last_practiced',
        ]

    def get_progress_percentage(self, obj):
        if obj.total_words > 0:
            return round((obj.words_learned / obj.total_words) * 100, 1)
        return 0

    def get_mastery_label(self, obj):
        labels = {
            0: 'Not started',
            1: 'Beginner',
            2: 'Learning',
            3: 'Intermediate',
            4: 'Advanced',
            5: 'Mastered',
        }
        return labels.get(obj.mastery_level, 'Unknown')


class UserExerciseHistorySerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    word = serializers.SerializerMethodField()
    topic_info = serializers.SerializerMethodField()
    exercise_type_display = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = UserExerciseHistory
        fields = [
            'id', 'user', 'exercise_type', 'exercise_type_display',
            'word', 'topic', 'topic_info', 'is_correct',
            'time_spent', 'difficulty', 'timestamp', 'created_at',
        ]
        read_only_fields = ['user', 'created_at']

    def get_word(self, obj):
        return _word_payload(obj.word)


    def get_exercise_type_display(self, obj):
        return dict(UserExerciseHistory.EXERCISE_TYPES).get(obj.exercise_type, obj.exercise_type)

    def get_topic_info(self, obj):
        if obj.topic:
            return TopicSerializer(obj.topic).data
        return None


class ReviewLogSerializer(serializers.ModelSerializer):
    user_word_info = serializers.SerializerMethodField()
    rating_display = serializers.SerializerMethodField()

    class Meta:
        model = ReviewLog
        fields = [
            'id', 'user_word', 'user_word_info', 'rating', 'rating_display',
            'is_correct', 'response_time', 'exercise_type', 'review_date',
            'scheduled_days', 'word',
        ]
        read_only_fields = ['review_date']

    def get_user_word_info(self, obj):
        return {
            'id': obj.user_word.id,
            'word_id': obj.user_word.word_id,
            'state': obj.user_word.state,
            'reps': obj.user_word.reps,
            'lapses': obj.user_word.lapses,
        }

    def get_rating_display(self, obj):
        rating_map = {
            1: 'Again',
            2: 'Hard',
            3: 'Good',
            4: 'Easy',
        }
        return rating_map.get(obj.rating, str(obj.rating))



class UserWordDetailSerializer(serializers.ModelSerializer):
    word = serializers.SerializerMethodField()
    user = serializers.StringRelatedField(read_only=True)
    mastery_score = serializers.FloatField(read_only=True)
    is_learned = serializers.BooleanField(read_only=True)
    next_review_days = serializers.SerializerMethodField()
    review_urgency = serializers.SerializerMethodField()
    review_history = serializers.SerializerMethodField()

    class Meta:
        model = UserWord
        fields = [
            'id', 'user', 'word', 'added_date', 'notes',
            'due', 'stability', 'difficulty', 'elapsed_days', 'scheduled_days',
            'reps', 'lapses', 'state', 'last_review', 'total_attempts',
            'correct_attempts', 'avg_response_time', 'consecutive_correct',
            'mastery_score', 'is_learned', 'next_review_days',
            'review_urgency', 'review_history',
        ]
        read_only_fields = [
            'user', 'word', 'added_date', 'due', 'stability', 'difficulty',
            'elapsed_days', 'scheduled_days', 'reps', 'lapses', 'state',
            'last_review', 'total_attempts', 'correct_attempts',
            'avg_response_time', 'consecutive_correct', 'mastery_score',
            'is_learned', 'next_review_days', 'review_urgency',
            'review_history',
        ]

    def get_word(self, obj):
        return _word_payload(obj.word)



    def get_next_review_days(self, obj):
        if obj.due and obj.due > timezone.now():
            return (obj.due - timezone.now()).days
        return 0

    def get_review_urgency(self, obj):
        return obj.get_review_urgency()

    def get_review_history(self, obj):
        logs = ReviewLog.objects.filter(user_word=obj).order_by('-review_date')[:10]
        return ReviewLogSerializer(logs, many=True).data


class UserWordListSerializer(serializers.ModelSerializer):
    word = serializers.SerializerMethodField()
    mastery_score = serializers.FloatField(read_only=True)
    is_learned = serializers.BooleanField(read_only=True)
    review_urgency = serializers.SerializerMethodField()
    next_review = serializers.DateTimeField(source='due', read_only=True)

    class Meta:
        model = UserWord
        fields = [
            'id', 'word', 'state', 'due', 'next_review',
            'last_review', 'reps', 'lapses', 'mastery_score', 'is_learned',
            'total_attempts', 'correct_attempts', 'avg_response_time',
            'review_urgency',
        ]

    def get_word(self, obj):
        return _word_payload(obj.word)



    def get_review_urgency(self, obj):
        return obj.get_review_urgency()


class UserExerciseStatsSerializer(serializers.Serializer):
    date = serializers.DateField()
    total_exercises = serializers.IntegerField()
    correct_exercises = serializers.IntegerField()
    accuracy = serializers.FloatField()
    avg_time = serializers.FloatField()
    exercise_types = serializers.DictField()


class UserLearningAnalyticsSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    total_words_studied = serializers.IntegerField()
    total_time_spent_minutes = serializers.FloatField()
    avg_daily_accuracy = serializers.FloatField()
    streak_days = serializers.IntegerField()
    top_topics = serializers.ListField(child=serializers.DictField())
    weak_words = serializers.ListField(child=serializers.DictField())


