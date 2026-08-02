from datetime import timedelta
from django.utils import timezone
from django.db.models import Q, Count, Avg
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import permission_classes, api_view
from django.shortcuts import get_object_or_404
from .models import (
    Lesson, Exercise, UserLessonProgress, DailyGoal,
    MemoryCard
)
from dictionary.models import Topic, Word, WordTag
from users.models import UserWord, UserLearningStats, UserTopicProgress, UserExerciseHistory
from .serializers import (
    LessonSerializer, ExerciseSerializer, UserLessonProgressSerializer,
    DailyGoalSerializer, TopicProgressSerializer, LearningStatsSerializer
)



class TopicListView(APIView):
    """
    Получение списка тем для обучения
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        topics = Topic.objects.filter(is_active=True).order_by('order')
        
        user_progress = UserTopicProgress.objects.filter(
            user=request.user
        ).select_related('topic')
        
        progress_dict = {up.topic_id: up for up in user_progress}
        
        result = []
        for topic in topics:
            progress = progress_dict.get(topic.id)
            if progress:
                serializer = TopicProgressSerializer(progress)
            else:
                progress = UserTopicProgress.objects.create(
                    user=request.user,
                    topic=topic,
                    total_words=self._get_words_count_in_topic(topic)
                )
                serializer = TopicProgressSerializer(progress)
            
            result.append(serializer.data)
        
        return Response(result)
    
    def _get_words_count_in_topic(self, topic):
        """Получить количество слов в теме"""
        tag_ids = topic.tags.values_list('id', flat=True)
        return WordTag.objects.filter(tag_id__in=tag_ids).values('word').distinct().count()


class LessonListView(APIView):
    """
    Получение уроков по теме
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, topic_id):
        lessons = Lesson.objects.filter(
            topic_id=topic_id,
            is_active=True
        ).order_by('order')
        
        serializer = LessonSerializer(lessons, many=True)
        return Response(serializer.data)


class StartLessonView(APIView):
    """
    Начать урок
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, id=lesson_id)
        
        progress, created = UserLessonProgress.objects.get_or_create(
            user=request.user,
            lesson=lesson,
            defaults={'attempts': 1}
        )
        
        if not created:
            progress.attempts += 1
            progress.save()
        
        exercises = lesson.exercises.all()
        exercise_serializer = ExerciseSerializer(
            exercises,
            many=True,
            context={'hide_answer': True}
        )
        
        self._update_learning_stats(request.user, 'lesson_started')
        
        return Response({
            'lesson': LessonSerializer(lesson).data,
            'progress': UserLessonProgressSerializer(progress).data,
            'exercises': exercise_serializer.data
        })
    
    def _update_learning_stats(self, user, action):
        """Обновить статистику обучения"""
        stats, _ = UserLearningStats.objects.get_or_create(user=user)
        stats.update_streak()
        
        if action == 'lesson_started':
            stats.save()


class ReviewScheduleView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        tomorrow = now + timedelta(days=1)
        next_week = now + timedelta(days=7)
        two_weeks = now + timedelta(days=14)

        cards = MemoryCard.objects.filter(user=request.user).select_related('learning_item').order_by('due_at')
        buckets = {
            'overdue': cards.filter(due_at__lte=now),
            'today': cards.filter(due_at__gt=now, due_at__date=now.date()),
            'tomorrow': cards.filter(due_at__gt=now, due_at__lte=tomorrow),
            'week': cards.filter(due_at__gt=tomorrow, due_at__lte=next_week),
            'later': cards.filter(due_at__gt=next_week, due_at__lte=two_weeks),
        }

        def card_payload(card):
            word = card.learning_item
            return {
                'id': card.id,
                'word': word.hanzi,
                'word_id': word.id,
                'pinyin': word.pinyin_graphic,
                'translation': word.translation.split(';')[0].strip(),
                'direction': card.direction,
                'next_review': card.due_at,
                'last_review': card.last_review_at,
            }

        return Response({
            key: [card_payload(card) for card in queryset[:10]]
            for key, queryset in buckets.items()
        })


class LearningStatsView(APIView):
    """
    Получение статистики обучения
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        user_words = UserWord.objects.filter(user=user)
        memory_cards = MemoryCard.objects.filter(user=user)
        
        stats, _ = UserLearningStats.objects.get_or_create(user=user)
        stats_serializer = LearningStatsSerializer(stats)
        
        topic_progress = UserTopicProgress.objects.filter(
            user=user,
            is_active=True
        )
        topic_serializer = TopicProgressSerializer(topic_progress, many=True)
        
        today = timezone.now().date()
        daily_goal = DailyGoal.objects.filter(
            user=user,
            date=today
        ).first()
        
        if daily_goal:
            daily_serializer = DailyGoalSerializer(daily_goal)
        else:
            daily_goal = DailyGoal.objects.create(
                user=user,
                target_xp=100,
                target_words=10,
                target_time=30,
                date=today
            )
            daily_serializer = DailyGoalSerializer(daily_goal)
        
        exercise_stats = UserExerciseHistory.objects.filter(
            user=user,
            created_at__gte=timezone.now() - timedelta(days=30)
        ).values('exercise_type').annotate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True)),
            avg_time=Avg('time_spent')
        )
        
        today_reviews = memory_cards.filter(
            user=user,
            due_at__lte=timezone.now()
        ).count()
        
        total_words = user_words.count()
        
        learned_words_count = memory_cards.filter(
            reviews__isnull=False,
        ).values('learning_item').distinct().count()
        
        return Response({
            'stats': stats_serializer.data,
            'topics': topic_serializer.data,
            'daily_goal': daily_serializer.data,
            'exercise_stats': list(exercise_stats),
            'today_reviews': today_reviews,
            'total_words': total_words,
            'learned_words': learned_words_count
        })


class RecommendedTopicsView(APIView):
    """
    Получение рекомендуемых тем для изучения
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_progress = UserTopicProgress.objects.filter(user=request.user)
        
        if not user_progress.exists():
            recommended = Topic.objects.filter(
                difficulty_level=1,
                is_active=True
            ).order_by('order')[:3]
            serializer = TopicProgressSerializer(recommended, many=True)
            return Response(serializer.data)
        
        recommendations = []
        
        active_topics = user_progress.filter(
            is_active=True,
            mastery_level__lt=5
        ).order_by('-mastery_level')
        
        for progress in active_topics[:2]:
            recommendations.append(progress)
        
        completed_topics = user_progress.filter(mastery_level__gte=3)
        if completed_topics.exists():
            avg_difficulty = completed_topics.aggregate(
                avg=Avg('topic__difficulty_level')
            )['avg']
            
            new_topics = Topic.objects.filter(
                difficulty_level__lte=avg_difficulty + 1,
                is_active=True
            ).exclude(
                id__in=user_progress.values_list('topic_id', flat=True)
            ).order_by('difficulty_level')[:2]
            
            for topic in new_topics:
                progress, created = UserTopicProgress.objects.get_or_create(
                    user=request.user,
                    topic=topic
                )
                recommendations.append(progress)
        
        serializer = TopicProgressSerializer(recommendations, many=True)
        return Response(serializer.data)


class UpdateDailyGoalView(APIView):
    """
    Обновление дневных целей пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Получение дневной цели (ДОБАВЛЕН GET метод)"""
        today = timezone.now().date()
        daily_goal = DailyGoal.objects.filter(
            user=request.user,
            date=today
        ).first()
        
        if daily_goal:
            serializer = DailyGoalSerializer(daily_goal)
        else:
            daily_goal = DailyGoal.objects.create(
                user=request.user,
                target_xp=100,
                target_words=10,
                target_time=30,
                date=today
            )
            serializer = DailyGoalSerializer(daily_goal)
        
        return Response(serializer.data)
    
    def put(self, request):
        """Обновление дневной цели"""
        today = timezone.now().date()
        goal, created = DailyGoal.objects.get_or_create(
            user=request.user,
            date=today,
            defaults={
                'target_xp': 100,
                'target_words': 10,
                'target_time': 30
            }
        )
        
        serializer = DailyGoalSerializer(goal, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_lesson(request, lesson_id):
    """
    Завершить урок
    """
    lesson = get_object_or_404(Lesson, id=lesson_id)
    progress = get_object_or_404(
        UserLessonProgress,
        user=request.user,
        lesson=lesson
    )
    
    completed_exercises = Exercise.objects.filter(lesson=lesson).count()
    
    progress.completed = True
    progress.completed_at = timezone.now()
    progress.score = 90
    progress.save()
    
    stats, _ = UserLearningStats.objects.get_or_create(user=request.user)
    stats.total_lessons_completed += 1
    stats.xp_points += lesson.xp_reward
    stats.save()
    
    goal, _ = DailyGoal.objects.get_or_create(
        user=request.user,
        date=timezone.now().date(),
        defaults={
            'target_xp': 100,
            'target_words': 10,
            'target_time': 30
        }
    )
    goal.update_progress(xp=lesson.xp_reward)
    
    return Response({
        'success': True,
        'xp_earned': lesson.xp_reward,
        'lesson_completed': True
    })


class LearningDashboardView(APIView):
    """
    Получение всех данных для главной страницы обучения одним запросом
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        user_words = UserWord.objects.filter(user=user)
        memory_cards = MemoryCard.objects.filter(user=user)
        stats, _ = UserLearningStats.objects.get_or_create(user=user)
        
        learned_words_count = memory_cards.filter(
            reviews__isnull=False,
        ).values('learning_item').distinct().count()
        
        stats_data = {
            'total_words': user_words.count(),
            'learned_words': learned_words_count,
            'level': stats.level,
            'current_streak': stats.current_streak,
            'total_lessons_completed': stats.total_lessons_completed,
            'total_exercises_completed': stats.total_exercises_completed,
            'total_time_spent': stats.total_time_spent,
            'xp_points': stats.xp_points
        }
        
        today = timezone.now().date()
        daily_goal = DailyGoal.objects.filter(
            user=user,
            date=today
        ).first()
        
        if not daily_goal:
            daily_goal = DailyGoal.objects.create(
                user=user,
                target_xp=100,
                target_words=10,
                target_time=30,
                date=today
            )
        
        daily_goal_data = {
            'target_xp': daily_goal.target_xp,
            'target_words': daily_goal.target_words,
            'target_time': daily_goal.target_time,
            'current_xp': daily_goal.current_xp,
            'current_words': daily_goal.current_words,
            'current_time': daily_goal.current_time,
            'completed': daily_goal.completed,
            'date': daily_goal.date
        }
        
        words_for_review = memory_cards.filter(
            user=user,
            due_at__lte=timezone.now()
        ).count()
        
        topics = UserTopicProgress.objects.filter(
            user=user,
            is_active=True
        ).order_by('-mastery_level')[:4]
        
        topics_data = []
        for topic in topics:
            topic_obj = topic.topic
            words_learned = topic.words_learned or 0
            total_words = topic.total_words or 1
            
            topics_data.append({
                'id': topic.id,
                'topic_id': topic_obj.id if topic_obj else topic.topic_id,
                'name': topic_obj.name if topic_obj else 'Тема',
                'description': topic_obj.description if topic_obj else '',
                'icon': topic_obj.icon if topic_obj and hasattr(topic_obj, 'icon') else '📚',
                'words_count': total_words,
                'progress_percentage': round((words_learned / total_words * 100), 1),
                'mastery_level': topic.mastery_level or 0,
                'is_active': topic.is_active
            })
        
        return Response({
            'stats': stats_data,
            'daily_goal': daily_goal_data,
            'words_for_review': words_for_review,
            'topics': topics_data,
            'success': True
        })
    


