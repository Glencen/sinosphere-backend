import random

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from learning.application.sessions import (
    GetCurrentExerciseUseCase,
    GetPracticeSessionSummaryUseCase,
    GetPracticeSessionUseCase,
    StartPracticeSessionUseCase,
    exercise_attempt_result_dto,
    public_attempt_payload,
    session_dto,
    session_progress,
)
from learning.application.use_cases import SubmitExerciseAnswerUseCase
from learning.exercises.exceptions import (
    ExerciseAttemptAccessDeniedError,
    ExerciseAttemptExpiredError,
    InvalidExerciseAnswerError,
    InvalidExerciseConfigError,
    UnknownExerciseHandlerError,
)
from learning.models import ExerciseAttempt, PracticeSession
from learning.serializers import ExerciseAttemptSubmitSerializer, PracticeSessionCreateSerializer


class PracticeSessionCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PracticeSessionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        config = dict(serializer.validated_data)
        rng_seed = config.pop('rng_seed', None)
        rng = random.Random(rng_seed) if rng_seed is not None else random.Random()

        try:
            result = StartPracticeSessionUseCase(rng=rng).execute(user=request.user, config=config)
        except (InvalidExerciseConfigError, UnknownExerciseHandlerError) as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result.dto, status=status.HTTP_201_CREATED)


class PracticeSessionApiDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            session = GetPracticeSessionUseCase().execute(user=request.user, session_id=session_id)
        except PracticeSession.DoesNotExist:
            return Response({'error': 'Practice session not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(session_dto(session))


class PracticeSessionCurrentExerciseView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            session, attempt = GetCurrentExerciseUseCase().execute(user=request.user, session_id=session_id)
        except PracticeSession.DoesNotExist:
            return Response({'error': 'Practice session not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'session_id': session.id,
            'status': session.status,
            'current_exercise': public_attempt_payload(attempt),
            'progress': session_progress(session),
        })


class PracticeSessionSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            summary = GetPracticeSessionSummaryUseCase().execute(user=request.user, session_id=session_id)
        except PracticeSession.DoesNotExist:
            return Response({'error': 'Practice session not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(summary)


class ExerciseAttemptSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, attempt_id):
        serializer = ExerciseAttemptSubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            result = SubmitExerciseAnswerUseCase().execute(
                user=request.user,
                attempt_id=attempt_id,
                answer=data['answer'],
                duration_ms=data.get('duration_ms'),
            )
        except ExerciseAttempt.DoesNotExist:
            return Response({'error': 'Exercise attempt not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ExerciseAttemptAccessDeniedError:
            return Response({'error': 'Exercise attempt not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ExerciseAttemptExpiredError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_410_GONE)
        except (InvalidExerciseAnswerError, InvalidExerciseConfigError, UnknownExerciseHandlerError) as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payload = result.dto
        payload['session_status'] = result.attempt.session.status
        payload['progress'] = session_progress(result.attempt.session)
        return Response(payload)


class ExerciseAttemptResultView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, attempt_id):
        try:
            attempt = ExerciseAttempt.objects.select_related('session').get(id=attempt_id, user=request.user)
        except ExerciseAttempt.DoesNotExist:
            return Response({'error': 'Exercise attempt not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(exercise_attempt_result_dto(attempt))
