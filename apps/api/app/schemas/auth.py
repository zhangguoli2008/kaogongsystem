from datetime import datetime

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    try:
        validate_email(normalized, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError("must be a valid email address") from exc
    return normalized


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128)

    _normalize_email = field_validator("email")(normalize_email)


class RegisterRequest(Credentials):
    pass


class LoginRequest(Credentials):
    pass


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    created_at: datetime
