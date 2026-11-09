"""Account and authentication use cases."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.constants import (
    AUTH_CURRENT_PASSWORD_INVALID_MESSAGE,
    AUTH_INACTIVE_ACCOUNT_MESSAGE,
    AUTH_INVALID_CREDENTIALS_MESSAGE,
    AUTH_INVALID_REFRESH_TOKEN_MESSAGE,
)
from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_token,
    decode_token,
    hash_password_async,
    verify_password_async,
)
from app.models.entities import RefreshSession, User
from app.models.enums import UserRole
from app.repositories.user_repository import UserRepository

logger = logging.getLogger("taskhub")


class AuthService:
    def __init__(
        self,
        repository: UserRepository,
        *,
        secret: str,
        access_minutes: int,
        refresh_days: int,
    ) -> None:
        self._repository = repository
        self._secret = secret
        self._access_minutes = access_minutes
        self._refresh_days = refresh_days

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        try:
            yield
            await self._repository.commit()
        except BaseException:
            logger.warning("Account transaction failed; rolling back")
            await self._repository.rollback()
            raise

    def _token_pair(self, user: User) -> dict[str, str]:
        access, _, _ = create_token(
            secret=self._secret,
            subject=user.id,
            token_type="access",
            expires_in=timedelta(minutes=self._access_minutes),
        )
        refresh, jti, expires = create_token(
            secret=self._secret,
            subject=user.id,
            token_type="refresh",
            expires_in=timedelta(days=self._refresh_days),
        )
        return {
            "access_token": access,
            "refresh_token": refresh,
            "jti": jti,
            "expires": expires.isoformat(),
        }

    async def register(self, email: str, full_name: str, password: str) -> User:
        async with self._transaction():
            user = User(
                email=email,
                full_name=full_name,
                hashed_password=await hash_password_async(password),
                role=UserRole.MEMBER,
                is_active=True,
            )
            await self._repository.add(user)
        return user

    async def login(self, email: str, password: str) -> dict[str, str]:
        async with self._transaction():
            user = await self._repository.get_by_email_for_update(email.lower())
            password_matches = await verify_password_async(
                password, user.hashed_password if user is not None else None
            )
            if user is None or not user.is_active or not password_matches:
                raise AuthenticationError(AUTH_INVALID_CREDENTIALS_MESSAGE)
            pair = self._token_pair(user)
            claims = decode_token(pair["refresh_token"], self._secret)
            await self._repository.add_refresh(
                RefreshSession(
                    jti=pair["jti"],
                    user_id=user.id,
                    expires_at=datetime.fromtimestamp(int(claims["exp"]), UTC),
                )
            )
            tokens = {
                "access_token": pair["access_token"],
                "refresh_token": pair["refresh_token"],
            }
        return tokens

    async def authenticate_access(self, token: str) -> User:
        try:
            claims = decode_token(token, self._secret)
            if claims["type"] != "access":
                raise ValueError
            user = await self._repository.get(UUID(str(claims["sub"])))
            if user is None or not user.is_active:
                raise ValueError
            return user
        except ValueError:
            raise AuthenticationError(AUTH_INACTIVE_ACCOUNT_MESSAGE) from None

    async def refresh(self, token: str) -> dict[str, str]:
        try:
            claims = decode_token(token, self._secret)
        except ValueError:
            raise AuthenticationError(AUTH_INVALID_REFRESH_TOKEN_MESSAGE) from None
        if claims["type"] != "refresh":
            raise AuthenticationError(AUTH_INVALID_REFRESH_TOKEN_MESSAGE)

        user_id = UUID(str(claims["sub"]))
        async with self._transaction():
            user = await self._repository.get_for_update(user_id)
            session = await self._repository.get_refresh_for_update(str(claims["jti"]))
            now = datetime.now(UTC)
            if (
                session is None
                or session.user_id != user_id
                or session.revoked_at is not None
                or session.expires_at <= now
                or user is None
                or not user.is_active
            ):
                raise AuthenticationError(AUTH_INVALID_REFRESH_TOKEN_MESSAGE)
            session.revoked_at = now
            pair = self._token_pair(user)
            new_claims = decode_token(pair["refresh_token"], self._secret)
            await self._repository.add_refresh(
                RefreshSession(
                    jti=pair["jti"],
                    user_id=user.id,
                    expires_at=datetime.fromtimestamp(int(new_claims["exp"]), UTC),
                )
            )
            tokens = {
                "access_token": pair["access_token"],
                "refresh_token": pair["refresh_token"],
            }
        return tokens

    async def logout(self, token: str) -> None:
        try:
            claims = decode_token(token, self._secret)
        except ValueError:
            raise AuthenticationError(AUTH_INVALID_REFRESH_TOKEN_MESSAGE) from None
        if claims["type"] != "refresh":
            raise AuthenticationError(AUTH_INVALID_REFRESH_TOKEN_MESSAGE)

        async with self._transaction():
            session = await self._repository.get_refresh_for_update(str(claims["jti"]))
            if (
                session is None
                or session.user_id != UUID(str(claims["sub"]))
                or session.revoked_at is not None
            ):
                raise AuthenticationError(AUTH_INVALID_REFRESH_TOKEN_MESSAGE)
            session.revoked_at = datetime.now(UTC)

    async def update_profile(self, user: User, changes: dict[str, str]) -> User:
        async with self._transaction():
            locked_user = await self._repository.get_for_update(user.id)
            if locked_user is None or not locked_user.is_active:
                raise AuthenticationError(AUTH_INACTIVE_ACCOUNT_MESSAGE)
            if changes.keys() - {"email", "full_name"}:
                raise ValueError("Unsupported profile field")
            for key, value in changes.items():
                setattr(locked_user, key, value.lower() if key == "email" else value)
            locked_user.updated_at = datetime.now(UTC)
        return locked_user

    async def change_password(self, user: User, current: str, new: str) -> None:
        async with self._transaction():
            locked_user = await self._repository.get_for_update(user.id)
            if locked_user is None or not locked_user.is_active:
                raise AuthenticationError(AUTH_INACTIVE_ACCOUNT_MESSAGE)
            if not await verify_password_async(current, locked_user.hashed_password):
                raise AuthenticationError(AUTH_CURRENT_PASSWORD_INVALID_MESSAGE)
            locked_user.hashed_password = await hash_password_async(new)
            now = datetime.now(UTC)
            locked_user.updated_at = now
            await self._repository.revoke_user_refresh_sessions(user.id, now)
