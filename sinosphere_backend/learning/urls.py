from django.urls import path
from . import views

urlpatterns = [
    # Темы
    path('topics/', views.TopicListView.as_view(), name='topic-list'),
    path('topics/recommended/', views.RecommendedTopicsView.as_view(), name='recommended-topics'),
    
    # Уроки
    path('topics/<int:topic_id>/lessons/', views.LessonListView.as_view(), name='topic-lessons'),
    path('lessons/<int:lesson_id>/start/', views.StartLessonView.as_view(), name='start-lesson'),
    path('lessons/<int:lesson_id>/complete/', views.complete_lesson, name='complete-lesson'),
    
    # Упражнения
    path('exercises/generate/', views.GenerateExerciseView.as_view(), name='generate-exercise'),
    path('exercises/submit/', views.SubmitExerciseView.as_view(), name='submit-exercise'),
    path('practice/session/', views.PracticeSessionView.as_view(), name='practice-session'),
    
    # Повторение
    path('review/schedule/', views.ReviewScheduleView.as_view(), name='review-schedule'),
    
    # Статистика
    path('stats/', views.LearningStatsView.as_view(), name='learning-stats'),
    
    # Цели
    path('daily-goal/', views.UpdateDailyGoalView.as_view(), name='update-daily-goal'),
]