"""Stable model-registration imports for ORM consumers outside the API router."""

from app.models.analysis import Analysis
from app.models.ocr_task import OCRTask
from app.models.question import Question
from app.models.review import ReviewRecord, UserSettings
from app.models.user import User

__all__ = ["Analysis", "OCRTask", "Question", "ReviewRecord", "User", "UserSettings"]
