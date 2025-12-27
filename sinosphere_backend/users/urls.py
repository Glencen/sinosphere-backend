from django.urls import path
from rest_framework_simplejwt.views import TokenVerifyView
from . import views

urlpatterns = [
    # Аутентификация и регистрация
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('token/refresh/', views.TokenRefreshView.as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    
    # Профиль пользователя
    path('profile/', views.UserProfileView.as_view(), name='user-profile'),
    
    # Личный словарь пользователя (старый api)
    path('dictionary/', views.UserWordListView.as_view(), name='user-dictionary'),
    path('dictionary/<int:pk>/', views.UserWordLegacyDetailView.as_view(), name='user-word-legacy-detail'),
    
    # Повторение слов
    path('dictionary/<int:pk>/review/', views.UserWordReviewView.as_view(), name='user-word-review'),
    path('review/', views.WordsForReviewView.as_view(), name='words-for-review'),
    
    # Статистика
    path('stats/', views.UserStatsView.as_view(), name='user-stats'),
    
    # Проверка наличия слова в словаре
    path('check-word/<int:word_id>/', views.CheckWordInDictionaryView.as_view(), name='check-word-in-dictionary'),
    
    # Новые пути для детальной информации
    path('user-words/<int:pk>/detail/', views.UserWordDetailView.as_view(), name='user-word-detail-new'),

    # Профиль обучения
    path('learning-profile/', views.UserLearningProfileView.as_view(), name='learning-profile'),
    
    # Прогресс по темам
    path('topic-progress/', views.UserTopicProgressListView.as_view(), name='topic-progress-list'),
    path('topics/<int:topic_id>/activate/', views.ActivateTopicView.as_view(), name='activate-topic'),
    
    # История упражнений
    path('exercise-history/', views.UserExerciseHistoryListView.as_view(), name='exercise-history'),
    
    # Журнал повторений FSRS
    path('review-logs/', views.ReviewLogListView.as_view(), name='review-logs'),
    
    # Детальная информация о слове пользователя
    path('user-words/<int:pk>/', views.UserWordDetailView.as_view(), name='user-word-detail'),
    
    # Слова для повторения (с FSRS)
    path('words-for-review/', views.WordsForReviewView.as_view(), name='words-for-review-fsrs'),
    
    # Статистика упражнений
    path('exercise-stats/', views.UserExerciseStatsView.as_view(), name='exercise-stats'),
    
    # Аналитика обучения
    path('learning-analytics/', views.UserLearningAnalyticsView.as_view(), name='learning-analytics'),
    
    # Оптимизация FSRS
    path('optimize-fsrs/', views.OptimizeFSRSView.as_view(), name='optimize-fsrs'),
    
    # Сброс прогресса слова
    path('user-words/<int:user_word_id>/reset/', views.ResetWordProgressView.as_view(), name='reset-word-progress'),
    
    # Экспорт данных
    path('export-learning-data/', views.ExportLearningDataView.as_view(), name='export-learning-data'),
]