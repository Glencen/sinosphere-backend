from django.urls import path
from rest_framework_simplejwt.views import TokenVerifyView
from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('token/refresh/', views.TokenRefreshView.as_view(), name='token-refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token-verify'),

    path('me/profile/', views.UserProfileView.as_view(), name='me-profile'),
    path('me/dictionary/', views.UserWordListView.as_view(), name='me-dictionary'),
    path('me/dictionary/<int:pk>/', views.UserWordDetailView.as_view(), name='me-dictionary-detail'),
    path('me/dictionary/<int:pk>/review/', views.UserWordReviewView.as_view(), name='me-dictionary-review'),
    path('me/dictionary/check/<int:word_id>/', views.CheckWordInDictionaryView.as_view(), name='me-dictionary-check'),

    path('me/review/words/', views.WordsForReviewView.as_view(), name='me-review-words'),
    path('me/review/logs/', views.ReviewLogListView.as_view(), name='me-review-logs'),

    path('me/stats/', views.UserStatsView.as_view(), name='me-stats'),
    path('me/exercise-stats/', views.UserExerciseStatsView.as_view(), name='me-exercise-stats'),
    path('me/learning-analytics/', views.UserLearningAnalyticsView.as_view(), name='me-learning-analytics'),
    path('me/export-learning-data/', views.ExportLearningDataView.as_view(), name='me-export-learning-data'),

    path('me/learning-profile/', views.UserLearningProfileView.as_view(), name='me-learning-profile'),
    path('me/topic-progress/', views.UserTopicProgressListView.as_view(), name='me-topic-progress'),
    path('me/topics/<int:topic_id>/activate/', views.ActivateTopicView.as_view(), name='me-topic-activate'),
    path('me/exercise-history/', views.UserExerciseHistoryListView.as_view(), name='me-exercise-history'),
    path('me/optimize-fsrs/', views.OptimizeFSRSView.as_view(), name='me-optimize-fsrs'),
    path('me/words/<int:user_word_id>/reset/', views.ResetWordProgressView.as_view(), name='me-word-reset'),
]