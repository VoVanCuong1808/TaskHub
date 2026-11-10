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
    TokenType,
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

    async def _issue_tokens(self, user: User) -> dict[str, str]:
        access, _, _ = create_token(
            secret=self._secret,
            subject=user.id,
            token_type=TokenType.ACCESS,
            expires_in=timedelta(minutes=self._access_minutes),
        )
        refresh, jti, expires = create_token(
            secret=self._secret,
            subject=user.id,
            token_type=TokenType.REFRESH,
            expires_in=timedelta(days=self._refresh_days),
        )
        await self._repository.add_refresh(
            RefreshSession(jti=jti, user_id=user.id, expires_at=expires)
        )
        return {"access_token": access, "refresh_token": refresh}

    def _decode_refresh_token(self, token: str) -> dict[str, object]:
        try:
            claims = decode_token(token, self._secret)
        except ValueError:
            raise AuthenticationError(AUTH_INVALID_REFRESH_TOKEN_MESSAGE) from None
        if claims["type"] != TokenType.REFRESH.value:
            raise AuthenticationError(AUTH_INVALID_REFRESH_TOKEN_MESSAGE)
        return claims

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
        normalized_email = email.lower()
        user = await self._repository.get_by_email(normalized_email)
        password_matches = await verify_password_async(
            password, user.hashed_password if user is not None else None
        )
        if user is None or not user.is_active or not password_matches:
            raise AuthenticationError(AUTH_INVALID_CREDENTIALS_MESSAGE)
        verified_password_hash = user.hashed_password
        async with self._transaction():
            locked_user = await self._repository.get_for_update(user.id)
            if (
                locked_user is None
                or not locked_user.is_active
                or locked_user.email != normalized_email
                or locked_user.hashed_password != verified_password_hash
            ):
                raise AuthenticationError(AUTH_INVALID_CREDENTIALS_MESSAGE)
            tokens = await self._issue_tokens(locked_user)
        return tokens

    async def authenticate_access(self, token: str) -> User:
        try:
            claims = decode_token(token, self._secret)
            if claims["type"] != TokenType.ACCESS.value:
                raise ValueError
            user = await self._repository.get(UUID(str(claims["sub"])))
            if user is None or not user.is_active:
                raise ValueError
            return user
        except ValueError:
            raise AuthenticationError(AUTH_INACTIVE_ACCOUNT_MESSAGE) from None

    async def refresh(self, token: str) -> dict[str, str]:
        claims = self._decode_refresh_token(token)

        user_id = UUID(str(claims["sub"]))
        replayed = False
        async with self._transaction():
            user = await self._repository.get_for_update(user_id)
            session = await self._repository.get_refresh_for_update(str(claims["jti"]))
            now = datetime.now(UTC)
            if (
                user is not None
                and session is not None
                and session.user_id == user_id
                and session.revoked_at is not None
                and session.expires_at > now
            ):
                await self._repository.revoke_user_refresh_sessions(user_id, now)
                replayed = True
            elif (
                session is None
                or session.user_id != user_id
                or session.revoked_at is not None
                or session.expires_at <= now
                or user is None
                or not user.is_active
            ):
                raise AuthenticationError(AUTH_INVALID_REFRESH_TOKEN_MESSAGE)
            else:
                session.revoked_at = now
                tokens = await self._issue_tokens(user)
        if replayed:
            raise AuthenticationError(AUTH_INVALID_REFRESH_TOKEN_MESSAGE)
        return tokens

    async def logout(self, token: str) -> None:
        claims = self._decode_refresh_token(token)

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
