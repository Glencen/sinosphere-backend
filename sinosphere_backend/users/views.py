from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate
from django.db.models import Avg, Count, Sum, Q, F, ExpressionWrapper, FloatField
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import timedelta, datetime
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import UserProfile, UserWord, UserLearningProfile, UserExerciseHistory, UserTopicProgress, LearningScheduler, ReviewLog
from .serializers import (
    UserSerializer, UserProfileSerializer, UserWordSerializer,
    UserWordReviewSerializer, UserLearningProfileSerializer, UserTopicProgressSerializer,
    UserExerciseHistorySerializer, ReviewLogSerializer,
    UserWordDetailSerializer, UserWordListSerializer,
    UserExerciseStatsSerializer, UserLearningAnalyticsSerializer
)

User = get_user_model()


class RegisterView(APIView):
    """
    Регистрация нового пользователя
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            
            UserProfile.objects.create(user=user)
            
            refresh = RefreshToken.for_user(user)
            
            return Response({
                'user': serializer.data,
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'message': 'Пользователь успешно зарегистрирован'
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    """
    Аутентификация пользователя
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        if not username or not password:
            return Response(
                {'error': 'Необходимо указать имя пользователя и пароль'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user = authenticate(username=username, password=password)
        
        if user:
            refresh = RefreshToken.for_user(user)
            
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user_id': user.id,
                'username': user.username,
                'email': user.email
            })
        
        return Response(
            {'error': 'Неверные учетные данные'},
            status=status.HTTP_401_UNAUTHORIZED
        )


class LogoutView(APIView):
    """
    Выход пользователя из системы
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            return Response({
                'message': 'Успешный выход из системы. Удалите токены на клиенте.'
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class TokenRefreshView(APIView):
    """
    Обновление access токена с помощью refresh токена
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        refresh_token = request.data.get('refresh')
        
        if not refresh_token:
            return Response(
                {'error': 'Refresh токен не предоставлен'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            refresh = RefreshToken(refresh_token)
            return Response({
                'access': str(refresh.access_token),
            })
        except Exception as e:
            return Response(
                {'error': 'Недействительный refresh токен'},
                status=status.HTTP_401_UNAUTHORIZED
            )

class UserProfileView(APIView):
    """
    Просмотр и обновление профиля пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        serializer = UserProfileSerializer(profile)
        return Response(serializer.data)
    
    def put(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        serializer = UserProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserWordListView(APIView):
    """
    Список слов пользователя с фильтрацией
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_words = UserWord.objects.filter(user=request.user).select_related('word')
        
        state = request.query_params.get('state')
        if state is not None:
            user_words = user_words.filter(state=state)
        
        is_learned = request.query_params.get('is_learned')
        if is_learned is not None:
            if is_learned.lower() == 'true':
                user_words = user_words.filter(reps__gte=3, state=2)
            elif is_learned.lower() == 'false':
                user_words = user_words.filter(Q(reps__lt=3) | ~Q(state=2))
        
        sort_by = request.query_params.get('sort_by', 'due')
        if sort_by == 'added_date':
            user_words = user_words.order_by('-added_date')
        elif sort_by == 'due':
            user_words = user_words.order_by('due')
        elif sort_by == 'mastery':
            user_words = user_words.order_by('-mastery_score')
        elif sort_by == 'difficulty':
            user_words = user_words.order_by('-difficulty')
        
        serializer = UserWordListSerializer(user_words, many=True)
        return Response(serializer.data)


class UserWordLegacyDetailView(APIView):
    """
    Детальное представление, обновление и удаление слова пользователя (старая версия)
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self, pk, user):
        return get_object_or_404(UserWord, pk=pk, user=user)
    
    def get(self, request, pk):
        user_word = self.get_object(pk, request.user)
        serializer = UserWordListSerializer(user_word)
        return Response(serializer.data)
    
    def put(self, request, pk):
        user_word = self.get_object(pk, request.user)
        serializer = UserWordListSerializer(
            user_word, 
            data=request.data,
            context={'request': request},
            partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        user_word = self.get_object(pk, request.user)
        user_word.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserWordReviewView(APIView):
    """
    Обработка повторения слова по системе интервального повторения
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self, pk, user):
        return get_object_or_404(UserWord, pk=pk, user=user)
    
    def post(self, request, pk):
        user_word = self.get_object(pk, request.user)
        serializer = UserWordReviewSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.update(user_word, serializer.validated_data)
            return Response(UserWordSerializer(user_word).data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class WordsForReviewView(APIView):
    """
    Получение слов для повторения на сегодня
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_words = UserWord.objects.filter(user=request.user)
        
        words_for_review = []
        
        for user_word in user_words:
            if not user_word.is_learned:
                if not user_word.last_reviewed:
                    words_for_review.append(user_word)
                else:
                    days_since_review = (timezone.now() - user_word.last_reviewed).days

                    if user_word.review_count == 0:
                        interval = 1
                    elif user_word.review_count == 1:
                        interval = 6
                    else:
                        interval = round(user_word.review_count * user_word.ease_factor)
                    
                    if days_since_review >= interval:
                        words_for_review.append(user_word)
        
        serializer = UserWordSerializer(words_for_review, many=True)
        return Response(serializer.data)


class UserStatsView(APIView):
    """
    Статистика пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_words = UserWord.objects.filter(user=request.user)
        
        total_words = user_words.count()
        learned_words = user_words.filter(is_learned=True).count()
        
        difficulty_stats = {}
        for i in range(1, 7):
            count = user_words.filter(word__difficulty=i).count()
            difficulty_stats[f'HSK{i}'] = count
        
        review_words = UserWord.objects.filter(
            user=request.user,
            is_learned=False
        )
        today_reviews = 0
        for word in review_words:
            if not word.last_reviewed:
                today_reviews += 1
            else:
                days_since_review = (timezone.now() - word.last_reviewed).days
                if word.review_count == 0 and days_since_review >= 1:
                    today_reviews += 1
                elif word.review_count == 1 and days_since_review >= 6:
                    today_reviews += 1
                elif word.review_count > 1:
                    interval = round(word.review_count * word.ease_factor)
                    if days_since_review >= interval:
                        today_reviews += 1
        
        week_ago = timezone.now() - timezone.timedelta(days=7)
        words_last_week = user_words.filter(added_date__gte=week_ago).count()
        
        return Response({
            'total_words': total_words,
            'learned_words': learned_words,
            'learning_progress': f'{(learned_words / total_words * 100):.1f}%' if total_words > 0 else '0%',
            'difficulty_stats': difficulty_stats,
            'words_for_review_today': today_reviews,
            'words_added_last_week': words_last_week,
            'average_ease_factor': user_words.aggregate(Avg('ease_factor'))['ease_factor__avg'] or 0
        })


class CheckWordInDictionaryView(APIView):
    """
    Проверка, есть ли слово в словаре пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, word_id):
        exists = UserWord.objects.filter(
            user=request.user,
            word_id=word_id
        ).exists()
        
        return Response({
            'word_id': word_id,
            'in_dictionary': exists
        })
    
class UserLearningProfileView(APIView):
    """
    Просмотр и обновление профиля обучения пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        profile, created = UserLearningProfile.objects.get_or_create(
            user=request.user,
            defaults={
                'fsrs_weights': '[]',
                'new_cards_per_day': 10,
                'max_reviews_per_day': 100,
                'desired_retention': 0.9,
                'maximum_interval': 36500
            }
        )
        serializer = UserLearningProfileSerializer(profile)
        return Response(serializer.data)
    
    def put(self, request):
        profile, created = UserLearningProfile.objects.get_or_create(
            user=request.user
        )
        serializer = UserLearningProfileSerializer(
            profile, 
            data=request.data, 
            partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserTopicProgressListView(APIView):
    """
    Список прогресса пользователя по темам
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        progress_list = UserTopicProgress.objects.filter(
            user=request.user
        ).select_related('topic').order_by('-last_practiced')
        
        serializer = UserTopicProgressSerializer(progress_list, many=True)
        return Response(serializer.data)


class ActivateTopicView(APIView):
    """
    Активация/деактивация темы для изучения
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, topic_id):
        try:
            from dictionary.models import Topic
            topic = Topic.objects.get(id=topic_id)
        except Topic.DoesNotExist:
            return Response(
                {'error': 'Тема не найдена'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        progress, created = UserTopicProgress.objects.get_or_create(
            user=request.user,
            topic=topic
        )
        
        progress.is_active = request.data.get('is_active', True)
        progress.save()
        
        serializer = UserTopicProgressSerializer(progress)
        return Response(serializer.data)


class UserExerciseHistoryListView(APIView):
    """
    История выполненных упражнений пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        history = UserExerciseHistory.objects.filter(
            user=request.user
        ).select_related('word', 'topic').order_by('-created_at')
        
        exercise_type = request.query_params.get('exercise_type')
        if exercise_type:
            history = history.filter(exercise_type=exercise_type)
        
        is_correct = request.query_params.get('is_correct')
        if is_correct is not None:
            history = history.filter(is_correct=is_correct.lower() == 'true')
        
        date_from = request.query_params.get('date_from')
        if date_from:
            try:
                date = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                history = history.filter(created_at__gte=date)
            except ValueError:
                pass
        
        date_to = request.query_params.get('date_to')
        if date_to:
            try:
                date = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                history = history.filter(created_at__lte=date)
            except ValueError:
                pass
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        start = (page - 1) * page_size
        end = start + page_size
        
        total_count = history.count()
        paginated_history = history[start:end]
        
        serializer = UserExerciseHistorySerializer(paginated_history, many=True)
        
        return Response({
            'total': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size,
            'results': serializer.data
        })


class ReviewLogListView(APIView):
    """
    Просмотр журнала повторений FSRS
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_word_id = request.query_params.get('user_word_id')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        
        logs = ReviewLog.objects.filter(
            user_word__user=request.user
        ).select_related('user_word__word').order_by('-review_date')
        
        if user_word_id:
            logs = logs.filter(user_word_id=user_word_id)
        
        if date_from:
            try:
                date = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                logs = logs.filter(review_date__gte=date)
            except ValueError:
                pass
        
        if date_to:
            try:
                date = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                logs = logs.filter(review_date__lte=date)
            except ValueError:
                pass
        
        serializer = ReviewLogSerializer(logs[:100], many=True)
        return Response(serializer.data)


class UserWordDetailView(APIView):
    """
    Детальная информация о слове пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        user_word = get_object_or_404(
            UserWord, 
            pk=pk, 
            user=request.user
        )
        serializer = UserWordDetailSerializer(user_word)
        return Response(serializer.data)
    
    def put(self, request, pk):
        user_word = get_object_or_404(
            UserWord, 
            pk=pk, 
            user=request.user
        )
        
        serializer = UserWordDetailSerializer(
            user_word, 
            data=request.data, 
            partial=True,
            fields=['notes']
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class WordsForReviewView(APIView):
    """
    Получение слов для повторения на сегодня (с FSRS)
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        now = timezone.now()
        
        words_for_review = UserWord.objects.filter(
            user=request.user,
            due__lte=now,
            state__in=[1, 2, 3]
        ).select_related('word').order_by('due')
        
        new_words_limit = 10
        new_words_today = UserWord.objects.filter(
            user=request.user,
            state=0,
            added_date__date=now.date()
        ).select_related('word')[:new_words_limit]
        
        urgent_words = words_for_review.filter(
            due__lte=now - timedelta(hours=6)
        )
        
        result = {
            'total_for_review': words_for_review.count(),
            'urgent_count': urgent_words.count(),
            'new_words_today': new_words_today.count(),
            'words_for_review': UserWordListSerializer(
                words_for_review[:50],
                many=True
            ).data,
            'new_words': UserWordListSerializer(
                new_words_today,
                many=True
            ).data,
            'urgent_words': UserWordListSerializer(
                urgent_words[:20],
                many=True
            ).data
        }
        
        return Response(result)


class UserExerciseStatsView(APIView):
    """
    Статистика упражнений пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        period = request.query_params.get('period', '7days')
        
        if period == '7days':
            start_date = timezone.now() - timedelta(days=7)
        elif period == '30days':
            start_date = timezone.now() - timedelta(days=30)
        else:
            start_date = None
        
        history = UserExerciseHistory.objects.filter(user=request.user)
        if start_date:
            history = history.filter(created_at__gte=start_date)
        
        total_exercises = history.count()
        correct_exercises = history.filter(is_correct=True).count()
        avg_time = history.aggregate(avg=Avg('time_spent'))['avg'] or 0
        
        exercise_types_stats = history.values('exercise_type').annotate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True)),
            avg_time=Avg('time_spent')
        )
        
        daily_stats = []
        for i in range(7):
            date = timezone.now().date() - timedelta(days=i)
            day_history = history.filter(created_at__date=date)
            
            day_total = day_history.count()
            day_correct = day_history.filter(is_correct=True).count()
            day_avg_time = day_history.aggregate(avg=Avg('time_spent'))['avg'] or 0
            
            if day_total > 0:
                daily_stats.append({
                    'date': date,
                    'total': day_total,
                    'correct': day_correct,
                    'accuracy': round(day_correct / day_total * 100, 1),
                    'avg_time': round(day_avg_time, 2)
                })
        
        topic_stats = history.exclude(topic__isnull=True).values(
            'topic__name'
        ).annotate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True)),
            avg_time=Avg('time_spent')
        ).order_by('-total')[:10]
        
        return Response({
            'period': period,
            'total_exercises': total_exercises,
            'correct_exercises': correct_exercises,
            'accuracy': round(correct_exercises / total_exercises * 100, 1) if total_exercises > 0 else 0,
            'avg_response_time': round(avg_time, 2),
            'exercise_types': list(exercise_types_stats),
            'daily_stats': daily_stats,
            'topic_stats': list(topic_stats)
        })


class UserLearningAnalyticsView(APIView):
    """
    Подробная аналитика обучения пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=30)
        
        total_words_studied = UserWord.objects.filter(
            user=request.user,
            added_date__date__range=[start_date, end_date]
        ).count()
        
        total_time_spent = UserExerciseHistory.objects.filter(
            user=request.user,
            created_at__date__range=[start_date, end_date]
        ).aggregate(total=Sum('time_spent'))['total'] or 0
        
        daily_accuracy = []
        for i in range(30):
            date = end_date - timedelta(days=i)
            day_exercises = UserExerciseHistory.objects.filter(
                user=request.user,
                created_at__date=date
            )
            day_total = day_exercises.count()
            day_correct = day_exercises.filter(is_correct=True).count()
            
            if day_total > 0:
                daily_accuracy.append(day_correct / day_total * 100)
        
        avg_daily_accuracy = round(sum(daily_accuracy) / len(daily_accuracy), 1) if daily_accuracy else 0
        
        top_topics = UserTopicProgress.objects.filter(
            user=request.user,
            is_active=True
        ).select_related('topic').annotate(
            progress_percent=ExpressionWrapper(
                F('words_learned') * 100.0 / F('total_words'),
                output_field=FloatField()
            )
        ).order_by('-progress_percent')[:5]
        
        weak_words = UserWord.objects.filter(
            user=request.user,
            total_attempts__gte=3
        ).annotate(
            accuracy=ExpressionWrapper(
                F('correct_attempts') * 100.0 / F('total_attempts'),
                output_field=FloatField()
            )
        ).filter(
            accuracy__lt=50
        ).select_related('word').order_by('accuracy')[:10]
        
        from users.models import UserLearningStats
        stats, _ = UserLearningStats.objects.get_or_create(user=request.user)
        
        analytics = {
            'period_start': start_date,
            'period_end': end_date,
            'total_words_studied': total_words_studied,
            'total_time_spent_minutes': round(total_time_spent / 60, 1),
            'avg_daily_accuracy': avg_daily_accuracy,
            'streak_days': stats.current_streak,
            'top_topics': [
                {
                    'topic': progress.topic.name,
                    'progress': progress.mastery_level,
                    'words_learned': progress.words_learned,
                    'total_words': progress.total_words
                }
                for progress in top_topics
            ],
            'weak_words': [
                {
                    'word': {
                        'id': uw.word.id,
                        'hanzi': uw.word.hanzi,
                        'pinyin': uw.word.pinyin_graphic
                    },
                    'accuracy': round(uw.accuracy, 1),
                    'attempts': uw.total_attempts,
                    'last_review': uw.last_review
                }
                for uw in weak_words
            ]
        }
        
        serializer = UserLearningAnalyticsSerializer(analytics)
        return Response(serializer.data)


class OptimizeFSRSView(APIView):
    """
    API для запуска оптимизации FSRS параметров для пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            weights = LearningScheduler.optimize_for_user(request.user.id)
            
            if weights:
                return Response({
                    'success': True,
                    'message': 'FSRS параметры оптимизированы',
                    'weights': weights.tolist() if hasattr(weights, 'tolist') else weights
                })
            else:
                return Response({
                    'success': False,
                    'message': 'Недостаточно данных для оптимизации. Нужно минимум 50 повторений.'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Ошибка оптимизации: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ResetWordProgressView(APIView):
    """
    Сброс прогресса по слову
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, user_word_id):
        user_word = get_object_or_404(
            UserWord, 
            id=user_word_id, 
            user=request.user
        )
        
        user_word.due = timezone.now()
        user_word.stability = 0.0
        user_word.difficulty = 8.0
        user_word.elapsed_days = 0
        user_word.scheduled_days = 0
        user_word.reps = 0
        user_word.lapses = 0
        user_word.state = 0
        user_word.total_attempts = 0
        user_word.correct_attempts = 0
        user_word.avg_response_time = 0
        user_word.consecutive_correct = 0
        
        user_word.save()
        
        ReviewLog.objects.filter(user_word=user_word).delete()
        
        serializer = UserWordDetailSerializer(user_word)
        return Response({
            'success': True,
            'message': 'Прогресс по слову сброшен',
            'user_word': serializer.data
        })


class ExportLearningDataView(APIView):
    """
    Экспорт данных обучения пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        data = {
            'export_date': timezone.now().isoformat(),
            'user': {
                'id': request.user.id,
                'username': request.user.username,
                'email': request.user.email
            },
            'user_words': [],
            'review_logs': [],
            'exercise_history': [],
            'topic_progress': []
        }
        
        user_words = UserWord.objects.filter(user=request.user).select_related('word')
        for uw in user_words:
            data['user_words'].append({
                'word_id': uw.word.id,
                'hanzi': uw.word.hanzi,
                'pinyin': uw.word.pinyin_graphic,
                'translation': uw.word.translation,
                'added_date': uw.added_date.isoformat(),
                'due': uw.due.isoformat() if uw.due else None,
                'stability': uw.stability,
                'difficulty': uw.difficulty,
                'reps': uw.reps,
                'lapses': uw.lapses,
                'state': uw.state,
                'last_review': uw.last_review.isoformat() if uw.last_review else None,
                'mastery_score': uw.mastery_score,
                'is_learned': uw.is_learned
            })
        
        history = UserExerciseHistory.objects.filter(
            user=request.user
        ).order_by('-created_at')[:1000]
        
        for h in history:
            data['exercise_history'].append({
                'exercise_type': h.exercise_type,
                'word_id': h.word_id,
                'is_correct': h.is_correct,
                'time_spent': h.time_spent,
                'difficulty': h.difficulty,
                'user_rating': h.user_rating,
                'created_at': h.created_at.isoformat()
            })
        
        return Response(data)