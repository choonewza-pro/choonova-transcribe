"""
Core exception hierarchy for ChooNova-Transcribe.
All domain and application exceptions inherit from ChooNovaException.
"""

class ChooNovaException(Exception):
    """Base exception for all application-specific errors."""
    def __init__(self, message: str = "An internal error occurred.", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DomainException(ChooNovaException):
    """Base exception for domain-level business rule violations."""
    def __init__(self, message: str):
        super().__init__(message=message, status_code=400)


class NotFoundException(DomainException):
    """Raised when a requested resource or entity is not found."""
    def __init__(self, resource_name: str, resource_id: str):
        message = f"{resource_name} with id '{resource_id}' was not found."
        super().__init__(message=message)
        self.status_code = 404


class ValidationException(DomainException):
    """Raised when request payload or entity validation fails."""
    def __init__(self, message: str):
        super().__init__(message=message)
        self.status_code = 422


class StorageException(ChooNovaException):
    """Raised when filesystem or disk space operations fail."""
    def __init__(self, message: str):
        super().__init__(message=message, status_code=507)


class QueueFullException(ChooNovaException):
    """Raised when the transcription queue is at capacity."""
    def __init__(self, message: str):
        super().__init__(message=message, status_code=429)


class ASREngineException(ChooNovaException):
    """Raised when an ASR engine (Typhoon or Whisper) fails."""
    def __init__(self, message: str):
        super().__init__(message=message, status_code=500)
