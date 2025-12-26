from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate
from django.db.models import Avg
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import UserProfile, UserWord
from .serializers import (
    UserSerializer, 
    UserProfileSerializer, 
    UserWordSerializer,
    UserWordReviewSerializer
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
        user_words = UserWord.objects.filter(user=request.user)
        is_learned = request.query_params.get('is_learned')
        if is_learned is not None:
            if is_learned.lower() == 'true':
                user_words = user_words.filter(is_learned=True)
            elif is_learned.lower() == 'false':
                user_words = user_words.filter(is_learned=False)
        
        added_since = request.query_params.get('added_since')
        if added_since:
            try:
                from datetime import datetime
                date = datetime.fromisoformat(added_since.replace('Z', '+00:00'))
                user_words = user_words.filter(added_date__gte=date)
            except ValueError:
                pass
        
        search = request.query_params.get('search')
        if search:
            user_words = user_words.filter(
                word__hanzi__icontains=search
            ) | user_words.filter(
                word__translation__icontains=search
            )
        
        sort_by = request.query_params.get('sort_by', 'added_date')
        if sort_by == 'added_date':
            user_words = user_words.order_by('-added_date')
        elif sort_by == 'last_reviewed':
            user_words = user_words.order_by('-last_reviewed')
        elif sort_by == 'difficulty':
            user_words = user_words.order_by('word__difficulty')
        
        serializer = UserWordSerializer(user_words, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        serializer = UserWordSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserWordDetailView(APIView):
    """
    Детальное представление, обновление и удаление слова пользователя
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self, pk, user):
        return get_object_or_404(UserWord, pk=pk, user=user)
    
    def get(self, request, pk):
        user_word = self.get_object(pk, request.user)
        serializer = UserWordSerializer(user_word)
        return Response(serializer.data)
    
    def put(self, request, pk):
        user_word = self.get_object(pk, request.user)
        serializer = UserWordSerializer(
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