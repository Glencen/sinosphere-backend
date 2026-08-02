from django.urls import path

from learning.practice import views as practice_views


urlpatterns = [
    path('practice-sessions/', practice_views.PracticeSessionCreateView.as_view(), name='practice-session-create-api'),
    path('practice-sessions/<int:session_id>/', practice_views.PracticeSessionApiDetailView.as_view(), name='practice-session-detail-api'),
    path('practice-sessions/<int:session_id>/current-exercise/', practice_views.PracticeSessionCurrentExerciseView.as_view(), name='practice-session-current-exercise-api'),
    path('practice-sessions/<int:session_id>/summary/', practice_views.PracticeSessionSummaryView.as_view(), name='practice-session-summary-api'),
    path('exercise-attempts/<int:attempt_id>/submit/', practice_views.ExerciseAttemptSubmitView.as_view(), name='exercise-attempt-submit-api'),
    path('exercise-attempts/<int:attempt_id>/result/', practice_views.ExerciseAttemptResultView.as_view(), name='exercise-attempt-result-api'),
]
