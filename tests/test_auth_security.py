"""Authentication primitives and payload validation tests."""

import asyncio
import threading
import time
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import jwt
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from app.api.v1.auth import (
    _clear_refresh_cookie,
    _set_refresh_cookie,
    require_trusted_origin,
)
from app.core.config import Settings
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)
from app.main import create_app
from app.models.entities import User
from app.models.enums import UserRole
from app.schemas.auth import RegisterRequest
from app.schemas.user import UserUpdate
from app.services.auth_service import AuthService

SECRET = "unit-test-signing-secret-for-auth-tests-at-least-64-bytes-long"


class PasswordTests(unittest.TestCase):
    def test_password_hash_is_salted_and_does_not_truncate_long_passwords(self) -> None:
        password = "  " + "a" * 100 + "tail  "
        first = hash_password(password)
        second = hash_password(password)
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(password, first))
        self.assertFalse(verify_password(password[:-2] + "xx", first))
        self.assertFalse(verify_password(password, None))
        self.assertFalse(verify_password(password, "disabled$legacy"))


class AsyncPasswordTests(unittest.IsolatedAsyncioTestCase):
    async def test_hash_and_verify_run_off_the_event_loop(self) -> None:
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        hash_release = threading.Event()
        hash_started = asyncio.Event()
        verify_release = threading.Event()
        verify_started = asyncio.Event()

        def blocking_hash(password: str) -> str:
            loop.call_soon_threadsafe(hash_started.set)
            if not hash_release.wait(timeout=1):
                raise TimeoutError("event loop did not run while hashing")
            hash_threads.append(threading.get_ident())
            return f"hash:{password}"

        def blocking_verify(password: str, encoded: str | None) -> bool:
            loop.call_soon_threadsafe(verify_started.set)
            if not verify_release.wait(timeout=1):
                raise TimeoutError("event loop did not run while verifying")
            verify_threads.append(threading.get_ident())
            return encoded == f"hash:{password}"

        hash_threads = []
        verify_threads = []
        with patch("app.core.security.hash_password", blocking_hash):
            hashing = asyncio.create_task(hash_password_async("password"))
            await asyncio.wait_for(hash_started.wait(), timeout=0.5)
            hash_release.set()
            encoded = await hashing
        with patch("app.core.security.verify_password", blocking_verify):
            verification = asyncio.create_task(
                verify_password_async("password", encoded)
            )
            await asyncio.wait_for(verify_started.wait(), timeout=0.5)
            verify_release.set()
            verified = await verification
        self.assertTrue(verified)
        self.assertNotEqual(hash_threads[0], loop_thread)
        self.assertNotEqual(verify_threads[0], loop_thread)

    async def test_write_transaction_rolls_back_cancellation(self) -> None:
        class Repository:
            commits = 0
            rollbacks = 0

            async def commit(self) -> None:
                self.commits += 1

            async def rollback(self) -> None:
                self.rollbacks += 1

        repository = Repository()
        service = AuthService(
            repository, secret=SECRET, access_minutes=10, refresh_days=10
        )
        with self.assertRaises(asyncio.CancelledError):
            async with service._transaction():
                raise asyncio.CancelledError
        self.assertEqual(repository.rollbacks, 1)
        self.assertEqual(repository.commits, 0)

    async def test_profile_service_rejects_authority_fields(self) -> None:
        class Repository:
            user = User(
                id=uuid4(),
                email="user@example.com",
                full_name="User",
                hashed_password="hash",
                role=UserRole.MEMBER,
                is_active=True,
            )
            commits = 0
            rollbacks = 0

            async def get_for_update(self, user_id):
                return self.user

            async def commit(self) -> None:
                self.commits += 1

            async def rollback(self) -> None:
                self.rollbacks += 1

        repository = Repository()
        service = AuthService(
            repository, secret=SECRET, access_minutes=10, refresh_days=10
        )
        with self.assertRaises(ValueError):
            await service.update_profile(repository.user, {"role": "admin"})
        self.assertEqual(repository.user.role, UserRole.MEMBER)
        self.assertTrue(repository.user.is_active)
        self.assertEqual(repository.rollbacks, 1)
        self.assertEqual(repository.commits, 0)

    async def test_query_hash_and_token_failures_rollback_write_transactions(
        self,
    ) -> None:
        class Repository:
            user = User(
                id=uuid4(),
                email="user@example.com",
                full_name="User",
                hashed_password="stored-hash",
                role=UserRole.MEMBER,
                is_active=True,
            )
            commits = 0
            rollbacks = 0
            fail_lookup = True

            async def get_by_email_for_update(self, email: str):
                if self.fail_lookup:
                    raise RuntimeError("query failed")
                return self.user

            async def commit(self) -> None:
                self.commits += 1

            async def rollback(self) -> None:
                self.rollbacks += 1

        repository = Repository()
        service = AuthService(
            repository, secret=SECRET, access_minutes=10, refresh_days=10
        )
        with (
            patch(
                "app.services.auth_service.hash_password_async",
                AsyncMock(side_effect=RuntimeError("hash failed")),
            ),
            self.assertRaisesRegex(RuntimeError, "hash failed"),
        ):
            await service.register("new@example.com", "New User", "password")
        with self.assertRaisesRegex(RuntimeError, "query failed"):
            await service.login("user@example.com", "password")

        repository.fail_lookup = False
        with (
            patch(
                "app.services.auth_service.verify_password_async",
                AsyncMock(return_value=True),
            ),
            patch.object(
                service, "_token_pair", side_effect=RuntimeError("token failed")
            ),
            self.assertRaisesRegex(RuntimeError, "token failed"),
        ):
            await service.login("user@example.com", "password")

        self.assertEqual(repository.rollbacks, 3)
        self.assertEqual(repository.commits, 0)


class SettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_cookie_and_origin_configuration_validation(self) -> None:
        with self.assertRaisesRegex(ValidationError, "production requires Secure"):
            Settings(environment="production", refresh_cookie_secure=False)
        with self.assertRaisesRegex(ValidationError, "SameSite=None requires"):
            Settings(refresh_cookie_secure=False, refresh_cookie_samesite="none")
        for origins in (["*"], ["https://example.com/path"], ["ftp://example.com"]):
            with self.subTest(origins=origins), self.assertRaises(ValidationError):
                Settings(frontend_origins=origins)

    async def test_origin_guard_and_cors_are_exact_and_fail_closed(self) -> None:
        settings = Settings(frontend_origins=["https://ui.example.test"])

        def request(origin: str | None):
            headers = [] if origin is None else [(b"origin", origin.encode())]
            return Request(
                {
                    "type": "http",
                    "method": "POST",
                    "scheme": "http",
                    "server": ("api.example.test", 80),
                    "path": "/api/v1/auth/login",
                    "raw_path": b"/api/v1/auth/login",
                    "query_string": b"",
                    "headers": headers,
                }
            )

        for origin in (
            None,
            "null",
            "https://ui.example.test.evil",
            "http://[",
            "https://u@ui.example.test",
        ):
            with (
                self.subTest(origin=origin),
                self.assertRaises(HTTPException) as caught,
            ):
                require_trusted_origin(request(origin), settings)
            self.assertEqual(caught.exception.status_code, 403)
        require_trusted_origin(request("https://ui.example.test"), settings)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(settings)),
            base_url="http://api.example.test",
        ) as client:
            allowed = await client.options(
                "/api/v1/users/me",
                headers={
                    "Origin": "https://ui.example.test",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )
            denied = await client.options(
                "/api/v1/users/me",
                headers={
                    "Origin": "https://evil.example.test",
                    "Access-Control-Request-Method": "GET",
                },
            )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(
            allowed.headers["access-control-allow-origin"], "https://ui.example.test"
        )
        self.assertEqual(allowed.headers["access-control-allow-credentials"], "true")
        self.assertEqual(denied.status_code, 400)

    async def test_cookie_helpers_use_configured_path_and_attributes(self) -> None:
        response = Response()
        settings = Settings(api_v1_prefix="/custom/v2", refresh_cookie_secure=False)
        _set_refresh_cookie(response, "dummy", settings)
        header = response.headers["set-cookie"].lower()
        self.assertIn("path=/custom/v2/auth", header)
        self.assertIn("httponly", header)
        self.assertIn("samesite=lax", header)
        self.assertNotIn("domain=", header)
        _clear_refresh_cookie(response, settings)
        self.assertTrue(
            any(
                "max-age=0" in value.lower()
                for value in response.headers.getlist("set-cookie")
            )
        )
        secure_response = Response()
        _set_refresh_cookie(secure_response, "dummy", Settings())
        self.assertIn("secure", secure_response.headers["set-cookie"].lower())

    async def test_short_or_missing_jwt_secret_fails_before_database_startup(
        self,
    ) -> None:
        for secret in (None, "short"):
            app = create_app(Settings(jwt_secret_key=secret))
            with (
                self.subTest(secret_is_set=secret is not None),
                self.assertRaisesRegex(RuntimeError, "at least 32 bytes"),
            ):
                async with app.router.lifespan_context(app):
                    self.fail("startup should reject the signing key")


class TokenTests(unittest.TestCase):
    def test_expired_wrong_algorithm_and_missing_claims_are_rejected(self) -> None:
        expired, _, _ = create_token(
            secret=SECRET,
            subject=uuid4(),
            token_type="refresh",
            expires_in=timedelta(seconds=-1),
        )
        wrong_algorithm = jwt.encode(
            {
                "sub": str(uuid4()),
                "type": "access",
                "jti": str(uuid4()),
                "iat": 1,
                "exp": 4_000_000_000,
            },
            SECRET,
            algorithm="HS384",
        )
        missing_claims = jwt.encode({"sub": str(uuid4())}, SECRET, algorithm="HS256")
        for token in (expired, wrong_algorithm, missing_claims):
            with self.subTest(token=token[:10]), self.assertRaises(ValueError):
                decode_token(token, SECRET)

    def test_numeric_claims_require_integer_values_and_sane_lifetimes(self) -> None:
        now = int(time.time())
        base = {
            "sub": str(uuid4()),
            "jti": str(uuid4()),
            "type": "access",
            "iat": now,
            "exp": now + 60,
        }
        malformed = (
            {**base, "exp": "4000000000"},
            {**base, "iat": True},
            {**base, "iat": now + 61},
            {**base, "exp": now},
            {**base, "nbf": True},
        )
        for claims in malformed:
            token = jwt.encode(claims, SECRET, algorithm="HS256")
            with self.subTest(claims=claims), self.assertRaises(ValueError):
                decode_token(token, SECRET)

    def test_token_round_trip_validates_type_and_subject(self) -> None:
        user_id = uuid4()
        token, token_id, _ = create_token(
            secret=SECRET,
            subject=user_id,
            token_type="access",
            expires_in=timedelta(minutes=5),
        )
        claims = decode_token(token, SECRET)
        self.assertEqual(claims["sub"], str(user_id))
        self.assertEqual(claims["jti"], token_id)
        self.assertEqual(claims["type"], "access")


class PayloadTests(unittest.TestCase):
    def test_registration_preserves_password_and_rejects_extra_privileges(self) -> None:
        password = "  " + "a" * 12 + "  "
        payload = RegisterRequest(
            email="User@Example.com", full_name="  Test User  ", password=password
        )
        self.assertEqual(payload.password, password)
        self.assertEqual(payload.full_name, "Test User")
        with self.assertRaises(ValidationError):
            RegisterRequest(
                email="user@example.com",
                full_name="Test User",
                password=password,
                role="admin",
            )
        with self.assertRaises(ValidationError):
            RegisterRequest(
                email="user@example.com",
                full_name="bad\x00name",
                password=password,
            )

    def test_profile_cannot_set_authority_fields_or_invalid_email(self) -> None:
        with self.assertRaises(ValidationError):
            UserUpdate(role="admin")
        with self.assertRaises(ValidationError):
            UserUpdate(email="a b@example.com")
        with self.assertRaises(ValidationError):
            UserUpdate(full_name="bad\x00name")
