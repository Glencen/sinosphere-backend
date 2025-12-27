from rest_framework import serializers
from django.utils import timezone
from .models import Lesson, Exercise, UserLessonProgress, DailyGoal
from dictionary.serializers import WordSerializer, TopicSerializer
from users.models import UserLearningStats, UserTopicProgress

class ExerciseSerializer(serializers.ModelSerializer):
    word_info = WordSerializer(source='word', read_only=True)
    options_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Exercise
        fields = [
            'id', 'lesson', 'exercise_type', 'question', 
            'correct_answer', 'options', 'options_display',
            'word', 'word_info', 'difficulty', 'explanation', 'order'
        ]
        extra_kwargs = {
            'correct_answer': {'write_only': True}
        }
    
    def get_options_display(self, obj):
        if obj.options and isinstance(obj.options, list):
            return obj.options
        return []


class LessonSerializer(serializers.ModelSerializer):
    topic_info = TopicSerializer(source='topic', read_only=True)
    exercises_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Lesson
        fields = [
            'id', 'title', 'description', 'topic', 'topic_info',
            'difficulty', 'order', 'is_active', 'estimated_time',
            'xp_reward', 'exercises_count'
        ]
    
    def get_exercises_count(self, obj):
        return obj.exercises.count()


class UserLessonProgressSerializer(serializers.ModelSerializer):
    lesson_info = LessonSerializer(source='lesson', read_only=True)
    completion_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = UserLessonProgress
        fields = [
            'id', 'user', 'lesson', 'lesson_info', 'completed',
            'score', 'started_at', 'completed_at', 'attempts',
            'completion_percentage'
        ]
        read_only_fields = ['user', 'started_at']
    
    def get_completion_percentage(self, obj):
        if obj.completed:
            return 100
        return 0


class DailyGoalSerializer(serializers.ModelSerializer):
    progress_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = DailyGoal
        fields = [
            'id', 'user', 'target_xp', 'target_words', 'target_time',
            'current_xp', 'current_words', 'current_time', 'date',
            'completed', 'progress_percentage'
        ]
        read_only_fields = ['user', 'date']
    
    def get_progress_percentage(self, obj):
        xp_percent = min(100, (obj.current_xp / obj.target_xp * 100) if obj.target_xp > 0 else 0)
        words_percent = min(100, (obj.current_words / obj.target_words * 100) if obj.target_words > 0 else 0)
        time_percent = min(100, (obj.current_time / obj.target_time * 100) if obj.target_time > 0 else 0)
        
        return {
            'xp': round(xp_percent, 1),
            'words': round(words_percent, 1),
            'time': round(time_percent, 1),
            'overall': round((xp_percent + words_percent + time_percent) / 3, 1)
        }


class TopicProgressSerializer(serializers.ModelSerializer):
    topic_info = TopicSerializer(source='topic', read_only=True)
    progress_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = UserTopicProgress
        fields = [
            'id', 'user', 'topic', 'topic_info', 'words_learned',
            'total_words', 'accuracy', 'last_practiced', 'is_active',
            'mastery_level', 'progress_percentage'
        ]
        read_only_fields = ['user', 'words_learned', 'total_words', 'accuracy']
    
    def get_progress_percentage(self, obj):
        if obj.total_words > 0:
            return round((obj.words_learned / obj.total_words) * 100, 1)
        return 0


class ExerciseSubmissionSerializer(serializers.Serializer):
    exercise_id = serializers.IntegerField(required=False)
    word_id = serializers.IntegerField(required=True)
    answer = serializers.CharField(required=True)
    exercise_type = serializers.CharField(required=True)
    time_spent = serializers.FloatField(default=0)
    
    def validate(self, data):
        from dictionary.models import Word
        try:
            word = Word.objects.get(id=data['word_id'])
        except Word.DoesNotExist:
            raise serializers.ValidationError({"word_id": "Слово не найдено"})
        
        data['word'] = word
        return data


class LearningStatsSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    daily_goals_completed = serializers.SerializerMethodField()
    streak_status = serializers.SerializerMethodField()
    
    class Meta:
        model = UserLearningStats
        fields = [
            'id', 'user', 'total_lessons_completed', 'total_exercises_completed',
            'total_time_spent', 'current_streak', 'longest_streak', 'last_activity_date',
            'xp_points', 'level', 'daily_goals_completed', 'streak_status'
        ]
    
    def get_daily_goals_completed(self, obj):
        seven_days_ago = timezone.now() - timezone.timedelta(days=7)
        daily_goals = DailyGoal.objects.filter(
            user=obj.user,
            date__gte=seven_days_ago,
            completed=True
        )
        return daily_goals.count()
    
    def get_streak_status(self, obj):
        today = timezone.now().date()
        if obj.last_activity_date == today:
            return "active"
        elif obj.last_activity_date == today - timezone.timedelta(days=1):
            return "at_risk"
        else:
            return "broken"


class GeneratedExerciseSerializer(serializers.Serializer):
    type = serializers.CharField()
    question = serializers.CharField()
    word_id = serializers.IntegerField()
    options = serializers.ListField(child=serializers.CharField(), required=False)
    correct_answer = serializers.CharField(required=False)
    hint = serializers.CharField(required=False, allow_blank=True)
    difficulty = serializers.IntegerField(default=1)
    pairs = serializers.ListField(child=serializers.DictField(), required=False)
    instructions = serializers.CharField(required=False)
    
    def to_representation(self, instance):
        data = super().to_representation(instance)
        if 'correct_answer' in data and self.context.get('hide_answer', True):
            del data['correct_answer']
        return data