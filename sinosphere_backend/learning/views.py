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
            difficulty=word.difficulty
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
            user_answer_clean = str(user_answer).strip().lower()
            
            translations = [t.strip().lower() for t in word.translation.split(';')]
            
            if user_answer_clean in translations:
                result['is_correct'] = True
                result['correct_answer'] = translations[0]
            else:
                result['is_correct'] = False
                result['correct_answer'] = translations[0]
                result['explanation'] = f"Правильный перевод: {translations[0]}"
        
        elif exercise_type == 'translation_cn':
            user_answer_clean = str(user_answer).strip()
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
                pairs = exercise_data.get('pairs') or []
                expected_translations = [
                    str(pair.get('translation', '')).strip().lower()
                    for pair in pairs
                ]
                submitted_translations = [
                    str(answer).strip().lower()
                    for answer in user_answer
                ]

                if expected_translations and submitted_translations == expected_translations:
                    result['is_correct'] = True
                else:
                    result['is_correct'] = False
                    result['explanation'] = "Не все пары сопоставлены правильно"
        
        return result
    
    def _update_topic_progress(self, user, word, is_correct):
        """Обновить прогресс по теме"""
        from users.models import UserTopicProgress
        from django.utils import timezone
        from dictionary.models import Topic, WordTag
        
        topics = Topic.objects.filter(
            tags__tagged_words__word=word
        ).distinct()
        
        for topic in topics:
            progress, created = UserTopicProgress.objects.get_or_create(
                user=user,
                topic=topic,
                defaults={
                    'total_words': self._get_words_count_in_topic(topic),
                    'is_active': True,
                    'last_practiced': timezone.now()
                }
            )
            
            if not created:
                total_attempts = getattr(progress, 'total_attempts', 0) + 1
                total_correct = getattr(progress, 'total_correct', 0)
                
                if is_correct:
                    total_correct += 1
                
                progress.total_attempts = total_attempts
                progress.total_correct = total_correct
                progress.accuracy = (total_correct / total_attempts * 100) if total_attempts > 0 else 0
                progress.last_practiced = timezone.now()
                
                progress.words_learned = self._get_learned_words_count_in_topic(user, topic)
                
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
    
    def _get_words_count_in_topic(self, topic):
        """Получить количество слов в теме"""
        tag_ids = topic.tags.values_list('id', flat=True)
        from dictionary.models import WordTag
        return WordTag.objects.filter(tag_id__in=tag_ids).values('word').distinct().count()

    def _get_learned_words_count_in_topic(self, user, topic):
        """Получить количество изученных слов в теме"""
        from users.models import UserWord
        tag_ids = topic.tags.values_list('id', flat=True)
        
        user_words = UserWord.objects.filter(
            user=user,
            word__word_tags__tag_id__in=tag_ids
        ).distinct()
        
        learned_count = 0
        for user_word in user_words:
            if user_word.is_learned:
                learned_count += 1
        
        return learned_count

    def _update_daily_goal(self, user, response_time, xp=0, words=0):
        """Обновить прогресс дневной цели"""
        from .models import DailyGoal
        from django.utils import timezone
        
        today = timezone.now().date()
        
        try:
            daily_goal = DailyGoal.objects.get(user=user, date=today)
        except DailyGoal.DoesNotExist:
            daily_goal = DailyGoal.objects.create(
                user=user,
                date=today,
                target_xp=100,
                target_words=10,
                target_time=30
            )
        
        time_minutes = response_time / 60.0 if response_time else 0
        
        daily_goal.update_progress(xp=xp, words=words, time_minutes=time_minutes)
    
    def _update_learning_stats(self, user, is_correct, response_time):
        """Обновить статистику обучения"""
        from users.models import UserLearningStats
        
        stats, created = UserLearningStats.objects.get_or_create(user=user)
        stats.update_streak()
        
        stats.total_exercises_completed += 1
        stats.total_time_spent += int(response_time)
        xp_to_add = 15 if is_correct else 5
        stats.xp_points += xp_to_add
        
        self._update_user_level(stats)
        
        stats.save()
    
    def _update_user_level(self, stats):
        """Обновить уровень пользователя на основе XP"""
        required_xp = stats.level * 100
        
        while stats.xp_points >= required_xp:
            stats.level += 1
            stats.xp_points -= required_xp
            required_xp = stats.level * 100

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
