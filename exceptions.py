"""
Custom exceptions for the SpeakLoudAudio application.
"""

class ApplicationError(Exception):
    """Base class for all application-specific errors."""
    def __init__(self, message="An application error occurred.", status_code=500):
        super().__init__(message)
        self.status_code = status_code

class ExtractionError(ApplicationError):
    """Raised when article extraction from a URL fails."""
    def __init__(self, message="Failed to extract article content.", status_code=400):
        super().__init__(message, status_code)

class TTSError(ApplicationError):
    """Raised when text-to-speech synthesis fails."""
    def __init__(self, message="Failed to synthesize audio.", status_code=500):
        super().__init__(message, status_code)

class ProcessingError(ApplicationError):
    """Raised for errors during the main article processing pipeline."""
    def __init__(self, message="Article processing failed.", status_code=500):
        super().__init__(message, status_code)

class GCPInitializationError(ApplicationError):
    """Raised when Google Cloud client initialization fails."""
    def __init__(self, message="Failed to initialize Google Cloud services.", status_code=500):
        super().__init__(message, status_code)
