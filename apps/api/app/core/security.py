from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

SESSION_COOKIE = "kaogong_session"
ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_session_token(user_id: str, secret: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode({"sub": user_id, "exp": expires}, secret, algorithm=ALGORITHM)
