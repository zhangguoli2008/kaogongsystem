"""Stable model-registration imports for ORM consumers outside the API router."""

from app.models.analysis import Analysis
from app.models.question import Question

__all__ = ["Analysis", "Question"]
