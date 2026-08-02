class ExerciseDomainError(Exception):
    default_message = 'Exercise domain error.'

    def __init__(self, message=None):
        super().__init__(message or self.default_message)


class UnknownExerciseHandlerError(ExerciseDomainError):
    default_message = 'Unknown exercise handler.'


class InvalidExerciseConfigError(ExerciseDomainError):
    default_message = 'Invalid exercise config.'


class InvalidExerciseAnswerError(ExerciseDomainError):
    default_message = 'Invalid exercise answer.'


class ExerciseAttemptAlreadySubmittedError(ExerciseDomainError):
    default_message = 'Exercise attempt has already been submitted.'


class ExerciseAttemptExpiredError(ExerciseDomainError):
    default_message = 'Exercise attempt has expired.'


class ExerciseAttemptAccessDeniedError(ExerciseDomainError):
    default_message = 'Exercise attempt does not belong to this user.'
