import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import Settings
from app.models.user import User

logger = logging.getLogger(__name__)

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

TOKEN_PURPOSE_ACCESS = "access"
TOKEN_PURPOSE_PASSWORD_SETUP = "password_setup"


class InvalidTokenError(Exception):
    pass


def hash_password(raw_password: str) -> str:
    return _pwd_context.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(raw_password, password_hash)


def create_access_token(user: User, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "purpose": TOKEN_PURPOSE_ACCESS,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc


def create_password_setup_token(user: User, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "purpose": TOKEN_PURPOSE_PASSWORD_SETUP,
        "iat": now,
        "exp": now + timedelta(minutes=settings.password_setup_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_password_setup_token(token: str, settings: Settings) -> int:
    payload = decode_token(token, settings)
    if payload.get("purpose") != TOKEN_PURPOSE_PASSWORD_SETUP:
        raise InvalidTokenError("token purpose mismatch")
    return int(payload["sub"])
