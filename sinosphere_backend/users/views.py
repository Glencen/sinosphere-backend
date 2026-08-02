from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate
from django.conf import settings
from django.db.models import Avg, Count, Sum, Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import timedelta, datetime
from learning.models import ExerciseAttempt, MemoryCard, MemoryReview
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.shortcuts import get_object_or_404
from .models import UserProfile, UserWord, UserLearningProfile, UserExerciseHistory, UserTopicProgress
from .serializers import (
    UserSerializer, UserProfileSerializer, UserWordSerializer,
    UserLearningProfileSerializer, UserTopicProgressSerializer,
    UserExerciseHistorySerializer, MemoryCardReviewQueueSerializer, MemoryReviewSerializer,
    UserWordDetailSerializer, UserWordListSerializer,
    UserExerciseStatsSerializer, UserLearningAnalyticsSerializer
)

User = get_user_model()


def _user_payload(user):
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
    }


def _set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        str(refresh_token),
        max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
        httponly=True,
        secure=settings.JWT_REFRESH_COOKIE_SECURE,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
        path='/api/',
    )
    return response


def _clear_refresh_cookie(response):
    response.delete_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        path='/api/',
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
    )
    return response


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

        sort_by = request.query_params.get('sort_by', 'added_date')
        if sort_by == 'added_date':
            user_words = user_words.order_by('-added_date')
        elif sort_by == 'difficulty':
            user_words = user_words.order_by('-difficulty')
        else:
            user_words = user_words.order_by('-added_date')
        
        serializer = UserWordListSerializer(user_words, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = UserWordSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            user_word = serializer.save()
            return Response(
                UserWordSerializer(user_word).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



class UserStatsView(APIView):
    """
    Статистика пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_words = UserWord.objects.filter(user=request.user)
        
        total_words = user_words.count()
        learned_words = MemoryCard.objects.filter(
            user=request.user,
            reviews__isnull=False,
        ).values('learning_item').distinct().count()
        
        difficulty_stats = {}
        for i in range(1, 7):
            count = user_words.filter(word__difficulty=i).count()
            difficulty_stats[f'HSK{i}'] = count
        
        today_reviews = MemoryCard.objects.filter(
            user=request.user,
            due_at__lte=timezone.now(),
        ).count()
        
        week_ago = timezone.now() - timezone.timedelta(days=7)
        words_last_week = user_words.filter(added_date__gte=week_ago).count()
        
        return Response({
            'total_words': total_words,
            'learned_words': learned_words,
            'learning_progress': f'{(learned_words / total_words * 100):.1f}%' if total_words > 0 else '0%',
            'difficulty_stats': difficulty_stats,
            'words_for_review_today': today_reviews,
            'words_added_last_week': words_last_week,
            'active_learning_items': MemoryCard.objects.filter(user=request.user).values('learning_item').distinct().count(),
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


class MemoryReviewListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        card_id = request.query_params.get('card_id')

        reviews = MemoryReview.objects.filter(
            memory_card__user=request.user
        ).select_related('memory_card__learning_item').order_by('-reviewed_at')

        if card_id:
            reviews = reviews.filter(memory_card_id=card_id)
        if date_from:
            try:
                date = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                reviews = reviews.filter(reviewed_at__gte=date)
            except ValueError:
                pass
        if date_to:
            try:
                date = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                reviews = reviews.filter(reviewed_at__lte=date)
            except ValueError:
                pass

        serializer = MemoryReviewSerializer(reviews[:100], many=True)
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
            partial=True
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        user_word = get_object_or_404(
            UserWord,
            pk=pk,
            user=request.user
        )
        user_word.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WordsForReviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        due_cards = MemoryCard.objects.filter(
            user=request.user,
            due_at__lte=now,
        ).select_related('learning_item').prefetch_related('reviews').order_by('due_at')

        urgent_cards = due_cards.filter(due_at__lte=now - timedelta(hours=6))
        new_words_today = UserWord.objects.filter(
            user=request.user,
            added_date__date=now.date(),
        ).select_related('word')[:10]

        return Response({
            'total_for_review': due_cards.count(),
            'urgent_count': urgent_cards.count(),
            'new_words_today': len(new_words_today),
            'words_for_review': MemoryCardReviewQueueSerializer(due_cards[:50], many=True).data,
            'new_words': UserWordListSerializer(new_words_today, many=True).data,
            'urgent_words': MemoryCardReviewQueueSerializer(urgent_cards[:20], many=True).data,
        })


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
        
        history = ExerciseAttempt.objects.filter(user=request.user, is_correct__isnull=False)
        if start_date:
            history = history.filter(submitted_at__gte=start_date)
        
        total_exercises = history.count()
        correct_exercises = history.filter(is_correct=True).count()
        avg_time = history.aggregate(avg=Avg('duration_ms'))['avg'] or 0
        
        exercise_types_stats = history.values('kind').annotate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True)),
            avg_time=Avg('duration_ms')
        )
        exercise_types_stats = [
            {
                'exercise_type': row['kind'],
                'total': row['total'],
                'correct': row['correct'],
                'avg_time': round((row['avg_time'] or 0) / 1000, 2),
            }
            for row in exercise_types_stats
        ]
        
        daily_stats = []
        for i in range(7):
            date = timezone.now().date() - timedelta(days=i)
            day_history = history.filter(submitted_at__date=date)
            
            day_total = day_history.count()
            day_correct = day_history.filter(is_correct=True).count()
            day_avg_time = day_history.aggregate(avg=Avg('duration_ms'))['avg'] or 0
            
            if day_total > 0:
                daily_stats.append({
                    'date': date,
                    'total': day_total,
                    'correct': day_correct,
                    'accuracy': round(day_correct / day_total * 100, 1),
                    'avg_time': round(day_avg_time / 1000, 2)
                })
        
        topic_stats = history.exclude(session__topic__isnull=True).values(
            'session__topic__name'
        ).annotate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True)),
            avg_time=Avg('duration_ms')
        ).order_by('-total')[:10]
        topic_stats = [
            {
                'topic__name': row['session__topic__name'],
                'total': row['total'],
                'correct': row['correct'],
                'avg_time': round((row['avg_time'] or 0) / 1000, 2),
            }
            for row in topic_stats
        ]
        
        return Response({
            'period': period,
            'total_exercises': total_exercises,
            'correct_exercises': correct_exercises,
            'accuracy': round(correct_exercises / total_exercises * 100, 1) if total_exercises > 0 else 0,
            'avg_response_time': round(avg_time / 1000, 2),
            'exercise_types': exercise_types_stats,
            'daily_stats': daily_stats,
            'topic_stats': topic_stats
        })


class UserLearningAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=30)
        attempts = ExerciseAttempt.objects.filter(
            user=request.user,
            is_correct__isnull=False,
            submitted_at__date__range=[start_date, end_date],
        )

        total_words_studied = MemoryCard.objects.filter(
            user=request.user,
            reviews__reviewed_at__date__range=[start_date, end_date],
        ).values('learning_item').distinct().count()

        total_time_ms = attempts.aggregate(total=Sum('duration_ms'))['total'] or 0

        daily_accuracy = []
        for i in range(30):
            date = end_date - timedelta(days=i)
            day_attempts = attempts.filter(submitted_at__date=date)
            day_total = day_attempts.count()
            day_correct = day_attempts.filter(is_correct=True).count()
            if day_total > 0:
                daily_accuracy.append(day_correct / day_total * 100)

        avg_daily_accuracy = round(sum(daily_accuracy) / len(daily_accuracy), 1) if daily_accuracy else 0

        top_topics = UserTopicProgress.objects.filter(
            user=request.user,
            is_active=True,
        ).select_related('topic').order_by('-mastery_level')[:5]

        weak_links = (
            MemoryCard.objects.filter(user=request.user)
            .annotate(
                attempts_count=Count('attempt_links', filter=Q(attempt_links__is_correct__isnull=False)),
                correct_count=Count('attempt_links', filter=Q(attempt_links__is_correct=True)),
            )
            .filter(attempts_count__gte=3)
            .select_related('learning_item')
        )
        weak_words = []
        for card in weak_links:
            accuracy = (card.correct_count / card.attempts_count * 100) if card.attempts_count else 0
            if accuracy < 50:
                weak_words.append({
                    'word': {
                        'id': card.learning_item.id,
                        'hanzi': card.learning_item.hanzi,
                        'pinyin': card.learning_item.pinyin_graphic,
                    },
                    'direction': card.direction,
                    'accuracy': round(accuracy, 1),
                    'attempts': card.attempts_count,
                    'last_review': card.last_review_at,
                })
        weak_words = sorted(weak_words, key=lambda item: item['accuracy'])[:10]

        from users.models import UserLearningStats
        stats, _ = UserLearningStats.objects.get_or_create(user=request.user)

        analytics = {
            'period_start': start_date,
            'period_end': end_date,
            'total_words_studied': total_words_studied,
            'total_time_spent_minutes': round(total_time_ms / 60000, 1),
            'avg_daily_accuracy': avg_daily_accuracy,
            'streak_days': stats.current_streak,
            'top_topics': [
                {
                    'topic': progress.topic.name,
                    'progress': progress.mastery_level,
                    'words_learned': progress.words_learned,
                    'total_words': progress.total_words,
                }
                for progress in top_topics
            ],
            'weak_words': weak_words,
        }

        serializer = UserLearningAnalyticsSerializer(analytics)
        return Response(serializer.data)


class ExportLearningDataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = {
            'export_date': timezone.now().isoformat(),
            'user': {
                'id': request.user.id,
                'username': request.user.username,
                'email': request.user.email,
            },
            'user_words': [],
            'memory_cards': [],
            'memory_reviews': [],
            'exercise_attempts': [],
            'topic_progress': [],
        }

        user_words = UserWord.objects.filter(user=request.user).select_related('word')
        for uw in user_words:
            data['user_words'].append({
                'word_id': uw.word.id,
                'hanzi': uw.word.hanzi,
                'pinyin': uw.word.pinyin_graphic,
                'translation': uw.word.translation,
                'added_date': uw.added_date.isoformat(),
                'notes': uw.notes,
            })

        cards = MemoryCard.objects.filter(user=request.user).select_related('learning_item')
        for card in cards:
            data['memory_cards'].append({
                'id': card.id,
                'word_id': card.learning_item_id,
                'direction': card.direction,
                'due_at': card.due_at.isoformat() if card.due_at else None,
                'last_review_at': card.last_review_at.isoformat() if card.last_review_at else None,
                'scheduler_version': card.scheduler_version,
                'parameter_set_version': card.parameter_set_version,
            })

        reviews = MemoryReview.objects.filter(memory_card__user=request.user).select_related('memory_card')[:1000]
        for review in reviews:
            data['memory_reviews'].append({
                'memory_card_id': review.memory_card_id,
                'rating': review.rating,
                'reviewed_at': review.reviewed_at.isoformat() if review.reviewed_at else None,
                'duration_ms': review.duration_ms,
                'scheduler_version': review.scheduler_version,
                'parameter_set_version': review.parameter_set_version,
            })

        attempts = ExerciseAttempt.objects.filter(user=request.user, is_correct__isnull=False).order_by('-submitted_at')[:1000]
        for attempt in attempts:
            data['exercise_attempts'].append({
                'attempt_id': attempt.id,
                'session_id': attempt.session_id,
                'kind': attempt.kind,
                'handler_version': attempt.handler_version,
                'is_correct': attempt.is_correct,
                'score': float(attempt.score or 0),
                'duration_ms': attempt.duration_ms,
                'submitted_at': attempt.submitted_at.isoformat() if attempt.submitted_at else None,
            })

        progress_rows = UserTopicProgress.objects.filter(user=request.user).select_related('topic')
        for progress in progress_rows:
            data['topic_progress'].append({
                'topic_id': progress.topic_id,
                'topic': progress.topic.name if progress.topic else None,
                'words_learned': progress.words_learned,
                'total_words': progress.total_words,
                'accuracy': progress.accuracy,
                'mastery_level': progress.mastery_level,
                'is_active': progress.is_active,
            })

        return Response(data)


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            UserProfile.objects.create(user=user)
            refresh = RefreshToken.for_user(user)

            response = Response({
                'user': _user_payload(user),
                'access': str(refresh.access_token),
                'message': 'User registered successfully',
            }, status=status.HTTP_201_CREATED)
            return _set_refresh_cookie(response, refresh)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        if not username or not password:
            return Response(
                {'error': 'Username and password are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(username=username, password=password)

        if user:
            refresh = RefreshToken.for_user(user)
            response = Response({
                'access': str(refresh.access_token),
                'user': _user_payload(user),
            })
            return _set_refresh_cookie(response, refresh)

        return Response(
            {'error': 'Invalid credentials'},
            status=status.HTTP_401_UNAUTHORIZED
        )


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        response = Response({'message': 'Logged out'})
        return _clear_refresh_cookie(response)


class TokenRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)

        if not refresh_token:
            return Response(
                {'error': 'Refresh token is missing'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            refresh = RefreshToken(refresh_token)
            return Response({'access': str(refresh.access_token)})
        except Exception:
            response = Response(
                {'error': 'Invalid refresh token'},
                status=status.HTTP_401_UNAUTHORIZED
            )
            return _clear_refresh_cookie(response)






