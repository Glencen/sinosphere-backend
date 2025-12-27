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
from .models import Lesson, Exercise, UserLessonProgress, DailyGoal
from dictionary.models import Topic, Word, WordTag
from users.models import UserWord, UserLearningStats, UserTopicProgress, UserExerciseHistory
from .serializers import (
    LessonSerializer, ExerciseSerializer, UserLessonProgressSerializer,
    DailyGoalSerializer, TopicProgressSerializer, LearningStatsSerializer,
    ExerciseSubmissionSerializer, GeneratedExerciseSerializer
)
from .exercise_generator import ExerciseGenerator
from .fsrs_optimizer import FSRSOptimizer


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


class GenerateExerciseView(APIView):
    """
    Генерация случайного упражнения
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        topic_id = request.query_params.get('topic_id')
        exercise_type = request.query_params.get('type')
        
        generator = ExerciseGenerator(request.user, topic_id)
        exercise = generator.get_next_exercise(exercise_type)
        
        if not exercise:
            return Response(
                {'error': 'Нет доступных упражнений'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if 'word_id' in exercise:
            word = Word.objects.get(id=exercise['word_id'])
            generator.auto_add_word_to_dictionary(word)
        
        serializer = GeneratedExerciseSerializer(
            exercise,
            context={'hide_answer': True}
        )
        
        return Response(serializer.data)


class SubmitExerciseView(APIView):
    """
    Отправка ответа на упражнение
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = ExerciseSubmissionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        user = request.user
        
        check_result = self._check_answer(
            data['exercise_type'],
            data['answer'],
            data['word_id'],
            data.get('exercise_data')
        )
        
        if check_result.get('error'):
            return Response(
                {'error': check_result['error']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        is_correct = check_result['is_correct']
        word_id = data['word_id']
        exercise_type = data['exercise_type']
        response_time = data.get('time_spent', 0)
        
        try:
            word = Word.objects.get(id=word_id)
        except Word.DoesNotExist:
            return Response(
                {'error': 'Слово не найдено'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        user_word, created = UserWord.objects.get_or_create(
            user=user,
            word=word,
            defaults={
                'due': timezone.now(),
                'state': 0,
                'difficulty': 8.0,
            }
        )
        
        rating = user_word.update_review(is_correct, response_time, exercise_type)
        
        UserExerciseHistory.objects.create(
            user=user,
            exercise_type=exercise_type,
            word=word,
            is_correct=is_correct,
            time_spent=response_time,
            difficulty=word.difficulty,
            user_rating=rating
        )
        
        self._update_daily_goal(user, response_time, xp=15 if is_correct else 5)
        
        self._update_learning_stats(user, is_correct, response_time)
        
        self._update_topic_progress(user, word, is_correct)
        
        return Response({
            'is_correct': is_correct,
            'correct_answer': check_result.get('correct_answer'),
            'explanation': check_result.get('explanation'),
            'rating': rating,
            'next_review': user_word.due,
            'mastery_score': user_word.mastery_score,
            'xp_earned': 15 if is_correct else 5,
            'is_learned': user_word.is_learned,
            'consecutive_correct': user_word.consecutive_correct
        })
    
    def _check_answer(self, exercise_type, user_answer, word_id, exercise_data=None):
        """Проверить правильность ответа"""
        try:
            word = Word.objects.get(id=word_id)
        except Word.DoesNotExist:
            return {'error': 'Слово не найдено'}
        
        result = {
            'is_correct': False,
            'correct_answer': '',
            'explanation': ''
        }
        
        if exercise_type == 'translation_ru':
            user_answer_clean = user_answer.strip().lower()
            
            translations = [t.strip().lower() for t in word.translation.split(';')]
            
            if user_answer_clean in translations:
                result['is_correct'] = True
                result['correct_answer'] = translations[0]
            else:
                result['is_correct'] = False
                result['correct_answer'] = translations[0]
                result['explanation'] = f"Правильный перевод: {translations[0]}"
        
        elif exercise_type == 'translation_cn':
            user_answer_clean = user_answer.strip()
            correct_answer = word.hanzi
            
            if user_answer_clean == correct_answer:
                result['is_correct'] = True
                result['correct_answer'] = correct_answer
            else:
                result['is_correct'] = False
                result['correct_answer'] = correct_answer
                result['explanation'] = f"Правильный ответ: {correct_answer} ({word.pinyin_graphic})"
        
        elif exercise_type == 'multiple_choice':
            try:
                selected_index = int(user_answer)
                if exercise_data and 'correct_index' in exercise_data:
                    result['is_correct'] = (selected_index == exercise_data['correct_index'])
                    if exercise_data.get('options'):
                        result['correct_answer'] = exercise_data['options'][exercise_data['correct_index']]
            except (ValueError, KeyError, IndexError):
                result['is_correct'] = False
        
        elif exercise_type == 'matching':
            if isinstance(user_answer, list) and exercise_data:
                # user_answer: список пар [индекс_китайского, индекс_перевода]
                # exercise_data['correct_pairs']: список правильных пар
                correct_pairs = exercise_data.get('correct_pairs', [])
                user_pairs = user_answer
                
                if sorted(correct_pairs) == sorted(user_pairs):
                    result['is_correct'] = True
                else:
                    result['is_correct'] = False
                    result['explanation'] = "Не все пары сопоставлены правильно"
        
        return result
    
    def _update_topic_progress(self, user, word, is_correct):
        """Обновить прогресс по теме"""
        topics = Topic.objects.filter(
            tags__tagged_words__word=word
        ).distinct()
        
        for topic in topics:
            progress, created = UserTopicProgress.objects.get_or_create(
                user=user,
                topic=topic,
                defaults={'total_words': topic.tags.count()}
            )
            
            if created:
                progress.accuracy = 100 if is_correct else 0
            else:
                total_attempts = getattr(progress, 'total_attempts', 0) + 1
                total_correct = getattr(progress, 'total_correct', 0)
                
                if is_correct:
                    total_correct += 1
                
                progress.accuracy = (total_correct / total_attempts * 100) if total_attempts > 0 else 0
                progress.total_attempts = total_attempts
                progress.total_correct = total_correct
            
            progress.last_practiced = timezone.now()
            
            if progress.accuracy >= 90:
                progress.mastery_level = 5
            elif progress.accuracy >= 75:
                progress.mastery_level = 4
            elif progress.accuracy >= 60:
                progress.mastery_level = 3
            elif progress.accuracy >= 40:
                progress.mastery_level = 2
            elif progress.accuracy > 0:
                progress.mastery_level = 1
            else:
                progress.mastery_level = 0
            
            progress.save()


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
                    'next_review': word.next_review,
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
        stats, _ = UserLearningStats.objects.get_or_create(user=request.user)
        stats_serializer = LearningStatsSerializer(stats)
        
        topic_progress = UserTopicProgress.objects.filter(
            user=request.user,
            is_active=True
        )
        topic_serializer = TopicProgressSerializer(topic_progress, many=True)
        
        today = timezone.now().date()
        daily_goal = DailyGoal.objects.filter(
            user=request.user,
            date=today
        ).first()
        
        if daily_goal:
            daily_serializer = DailyGoalSerializer(daily_goal)
        else:
            daily_serializer = DailyGoalSerializer({
                'target_xp': 100,
                'target_words': 10,
                'target_time': 30,
                'current_xp': 0,
                'current_words': 0,
                'current_time': 0,
                'completed': False
            })
        
        exercise_stats = UserExerciseHistory.objects.filter(
            user=request.user,
            created_at__gte=timezone.now() - timedelta(days=30)
        ).values('exercise_type').annotate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True)),
            avg_time=Avg('time_spent')
        )
        
        today_reviews = UserWord.objects.filter(
            user=request.user,
            next_review__lte=timezone.now()
        ).count()
        
        return Response({
            'stats': stats_serializer.data,
            'topics': topic_serializer.data,
            'daily_goal': daily_serializer.data,
            'exercise_stats': list(exercise_stats),
            'today_reviews': today_reviews,
            'total_words': UserWord.objects.filter(user=request.user).count(),
            'learned_words': UserWord.objects.filter(user=request.user, is_learned=True).count()
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
    
    def put(self, request):
        goal, created = DailyGoal.objects.get_or_create(
            user=request.user,
            date=timezone.now().date()
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


class PracticeSessionView(APIView):
    """
    Сессия практики с набором упражнений
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        topic_id = request.data.get('topic_id')
        session_type = request.data.get('type', 'mixed')
        count = int(request.data.get('count', 10))
        
        generator = ExerciseGenerator(request.user, topic_id)
        exercises = []
        
        for _ in range(count):
            if session_type == 'review':
                exercise_type = random.choice(['translation_ru', 'multiple_choice'])
            elif session_type == 'new':
                exercise_type = random.choice(['translation_cn', 'matching'])
            else:
                exercise_type = None
            
            exercise = generator.get_next_exercise(exercise_type)
            if exercise:
                if 'word_id' in exercise and session_type != 'review':
                    word = Word.objects.get(id=exercise['word_id'])
                    generator.auto_add_word_to_dictionary(word)
                
                exercises.append(exercise)
        
        serializer = GeneratedExerciseSerializer(
            exercises,
            many=True,
            context={'hide_answer': True}
        )
        
        session_id = f"session_{request.user.id}_{int(timezone.now().timestamp())}"
        
        return Response({
            'session_id': session_id,
            'exercises': serializer.data,
            'count': len(exercises),
            'type': session_type
        })