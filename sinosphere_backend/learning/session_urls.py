from django.urls import path

from . import views

urlpatterns = [
    path('practice-sessions/', views.PracticeSessionCreateView.as_view(), name='practice-session-create-api'),
    path('practice-sessions/<int:session_id>/', views.PracticeSessionApiDetailView.as_view(), name='practice-session-detail-api'),
    path('practice-sessions/<int:session_id>/current-exercise/', views.PracticeSessionCurrentExerciseView.as_view(), name='practice-session-current-exercise-api'),
    path('practice-sessions/<int:session_id>/summary/', views.PracticeSessionSummaryView.as_view(), name='practice-session-summary-api'),
    path('exercise-attempts/<int:attempt_id>/submit/', views.ExerciseAttemptSubmitView.as_view(), name='exercise-attempt-submit-api'),
]
