from django.urls import path

from learning.api import practice


urlpatterns = [
    path('practice-sessions/', practice.PracticeSessionCreateView.as_view(), name='practice-session-create-api'),
    path('practice-sessions/<int:session_id>/', practice.PracticeSessionApiDetailView.as_view(), name='practice-session-detail-api'),
    path('practice-sessions/<int:session_id>/current-exercise/', practice.PracticeSessionCurrentExerciseView.as_view(), name='practice-session-current-exercise-api'),
    path('practice-sessions/<int:session_id>/summary/', practice.PracticeSessionSummaryView.as_view(), name='practice-session-summary-api'),
    path('exercise-attempts/<int:attempt_id>/submit/', practice.ExerciseAttemptSubmitView.as_view(), name='exercise-attempt-submit-api'),
    path('exercise-attempts/<int:attempt_id>/result/', practice.ExerciseAttemptResultView.as_view(), name='exercise-attempt-result-api'),
]
