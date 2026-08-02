import random
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
    PracticeSession, ExerciseAttempt
)
from dictionary.models import Topic, Word, WordTag
from users.models import UserWord, UserLearningStats, UserTopicProgress, UserExerciseHistory
from .serializers import (
    LessonSerializer, ExerciseSerializer, UserLessonProgressSerializer,
    DailyGoalSerializer, TopicProgressSerializer, LearningStatsSerializer,
    PracticeSessionCreateSerializer, ExerciseAttemptSubmitSerializer
)
from .fsrs_optimizer import FSRSOptimizer
from .application.use_cases import SubmitExerciseAnswerUseCase
from .application.sessions import (
    GetCurrentExerciseUseCase, GetPracticeSessionUseCase,
    GetPracticeSessionSummaryUseCase, StartPracticeSessionUseCase,
    exercise_attempt_result_dto, public_attempt_payload, session_dto, session_progress
)
from .exercises.exceptions import ExerciseAttemptAccessDeniedError, ExerciseAttemptExpiredError, InvalidExerciseAnswerError, InvalidExerciseConfigError, UnknownExerciseHandlerError



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
    """
    Получение расписания повторений
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_words = UserWord.objects.filter(user=request.user)
        
        fsrs = FSRSOptimizer()
        schedule = fsrs.get_review_schedule(user_words)
        
        schedule_serialized = {}
        for key, words in schedule.items():
            schedule_serialized[key] = [
                {
                    'id': word.id,
                    'word': word.word.hanzi,
                    'pinyin': word.word.pinyin_graphic,
                    'translation': word.word.translation.split(';')[0].strip(),
                    'next_review': word.due,
                    'stability': word.stability,
                    'difficulty': word.difficulty,
                    'reps': word.reps,
                    'state': word.state
                }
                for word in words[:10]
            ]
        
        return Response(schedule_serialized)


class LearningStatsView(APIView):
    """
    Получение статистики обучения
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        user_words = UserWord.objects.filter(user=user)
        
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
        
        today_reviews = UserWord.objects.filter(
            user=user,
            due__lte=timezone.now()
        ).count()
        
        total_words = user_words.count()
        
        learned_words_count = 0
        for user_word in user_words:
            if user_word.is_learned:
                learned_words_count += 1
        
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
        stats, _ = UserLearningStats.objects.get_or_create(user=user)
        
        learned_words_count = 0
        for user_word in user_words:
            if user_word.is_learned:
                learned_words_count += 1
        
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
        
        words_for_review = UserWord.objects.filter(
            user=user,
            due__lte=timezone.now()
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
    
    def _get_learned_words_count(self, user):
        """
        Определяем количество изученных слов.
        """
        user_words = UserWord.objects.filter(user=user)
        learned_words_count = 0
        
        for user_word in user_words:
            if user_word.is_learned:
                learned_words_count += 1
        
        return learned_words_count


class PracticeSessionCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PracticeSessionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        config = dict(serializer.validated_data)
        rng_seed = config.pop('rng_seed', None)
        rng = random.Random(rng_seed) if rng_seed is not None else random.Random()

        try:
            result = StartPracticeSessionUseCase(rng=rng).execute(user=request.user, config=config)
        except (InvalidExerciseConfigError, UnknownExerciseHandlerError) as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result.dto, status=status.HTTP_201_CREATED)


class PracticeSessionApiDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            session = GetPracticeSessionUseCase().execute(user=request.user, session_id=session_id)
        except PracticeSession.DoesNotExist:
            return Response({'error': 'Practice session not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(session_dto(session))


class PracticeSessionCurrentExerciseView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            session, attempt = GetCurrentExerciseUseCase().execute(user=request.user, session_id=session_id)
        except PracticeSession.DoesNotExist:
            return Response({'error': 'Practice session not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'session_id': session.id,
            'status': session.status,
            'current_exercise': public_attempt_payload(attempt),
            'progress': session_progress(session),
        })


class PracticeSessionSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            summary = GetPracticeSessionSummaryUseCase().execute(user=request.user, session_id=session_id)
        except PracticeSession.DoesNotExist:
            return Response({'error': 'Practice session not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(summary)


class ExerciseAttemptSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, attempt_id):
        serializer = ExerciseAttemptSubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            result = SubmitExerciseAnswerUseCase().execute(
                user=request.user,
                attempt_id=attempt_id,
                answer=data['answer'],
                duration_ms=data.get('duration_ms'),
            )
        except ExerciseAttempt.DoesNotExist:
            return Response({'error': 'Exercise attempt not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ExerciseAttemptAccessDeniedError:
            return Response({'error': 'Exercise attempt not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ExerciseAttemptExpiredError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_410_GONE)
        except (InvalidExerciseAnswerError, InvalidExerciseConfigError, UnknownExerciseHandlerError) as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payload = result.dto
        payload['session_status'] = result.attempt.session.status
        payload['progress'] = session_progress(result.attempt.session)
        return Response(payload)


class ExerciseAttemptResultView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, attempt_id):
        try:
            attempt = ExerciseAttempt.objects.select_related('session').get(id=attempt_id, user=request.user)
        except ExerciseAttempt.DoesNotExist:
            return Response({'error': 'Exercise attempt not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(exercise_attempt_result_dto(attempt))
