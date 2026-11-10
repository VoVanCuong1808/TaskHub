"""Password hashing and compact HMAC JWT helpers."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from enum import Enum
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

_password_hash = PasswordHash.recommended()
_dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$lt3yCOTLraGL+nKPUmubbw$oLPUxLENnJFdwQw7bOCej8ly01YrSLydIEt5opx/MOw"
TOKEN_ALGORITHM = "HS256"


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        if encoded is None or encoded.startswith("disabled$"):
            _password_hash.verify(password, _dummy_hash)
            return False
        return _password_hash.verify(password, encoded)
    except (UnknownHashError, ValueError, TypeError):
        return False


async def verify_password_async(password: str, encoded: str | None) -> bool:
    return await asyncio.to_thread(verify_password, password, encoded)


def create_token(
    *,
    secret: str,
    subject: UUID,
    token_type: TokenType | str,
    expires_in: timedelta,
    jti: str | None = None,
) -> tuple[str, str, datetime]:
    token_type = TokenType(token_type)
    issued = datetime.now(UTC)
    expires = issued + expires_in
    token_id = jti or str(uuid4())
    token = jwt.encode(
        {
            "sub": str(subject),
            "type": token_type.value,
            "jti": token_id,
            "iat": issued,
            "exp": expires,
        },
        secret,
        algorithm=TOKEN_ALGORITHM,
        headers={"typ": "JWT"},
    )
    return token, token_id, expires


def decode_token(token: str, secret: str) -> dict[str, object]:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[TOKEN_ALGORITHM],
            options={"require": ["sub", "jti", "iat", "exp", "type"]},
        )
        issued = payload.get("iat")
        expires = payload.get("exp")
        now = int(time.time())
        if type(issued) is not int or type(expires) is not int:
            raise ValueError("invalid token")
        if "nbf" in payload and type(payload["nbf"]) is not int:
            raise ValueError("invalid token")
        if issued < 0 or expires <= issued or issued > now + 60:
            raise ValueError("invalid token")
        if payload.get("type") not in {token_type.value for token_type in TokenType}:
            raise ValueError("invalid token")
        if type(payload.get("sub")) is not str or type(payload.get("jti")) is not str:
            raise ValueError("invalid token")
        UUID(payload["sub"])
        UUID(payload["jti"])
        return payload
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError):
        raise ValueError("invalid token") from None
