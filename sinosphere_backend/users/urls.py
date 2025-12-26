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
    
    # Личный словарь пользователя
    path('dictionary/', views.UserWordListView.as_view(), name='user-dictionary'),
    path('dictionary/<int:pk>/', views.UserWordDetailView.as_view(), name='user-word-detail'),
    
    # Повторение слов
    path('dictionary/<int:pk>/review/', views.UserWordReviewView.as_view(), name='user-word-review'),
    path('review/', views.WordsForReviewView.as_view(), name='words-for-review'),
    
    # Статистика
    path('stats/', views.UserStatsView.as_view(), name='user-stats'),
    
    # Проверка наличия слова в словаре
    path('check-word/<int:word_id>/', views.CheckWordInDictionaryView.as_view(), name='check-word-in-dictionary'),
]