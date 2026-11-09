"""Registration and browser-safe token lifecycle endpoints."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.core.deps import AuthServiceDep, SettingsDep
from app.core.exceptions import AuthenticationError
from app.schemas.auth import AccessToken, LoginRequest, RegisterRequest
from app.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "refresh_token"


def _origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def require_trusted_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin is None or origin == "null":
        raise HTTPException(status_code=403, detail="Untrusted Origin")
    try:
        parsed = urlsplit(origin)
        _port = parsed.port
    except ValueError:
        raise HTTPException(status_code=403, detail="Untrusted Origin") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or origin != f"{parsed.scheme}://{parsed.netloc}"
        or origin not in {_origin(request), *settings.frontend_origins}
    ):
        raise HTTPException(status_code=403, detail="Untrusted Origin")


def origin_guard(request: Request, settings: SettingsDep) -> None:
    require_trusted_origin(request, settings)


OriginGuard = Annotated[None, Depends(origin_guard)]


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.refresh_token_days * 86400,
        path=f"{settings.api_v1_prefix.rstrip('/')}/auth",
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE,
        path=f"{settings.api_v1_prefix.rstrip('/')}/auth",
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


def _access_response(pair: dict[str, str], response: Response) -> AccessToken:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return AccessToken(access_token=pair["access_token"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Email already exists"}},
)
async def register(payload: RegisterRequest, service: AuthServiceDep) -> UserRead:
    user = await service.register(
        payload.email.lower(), payload.full_name, payload.password
    )
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=AccessToken,
    responses={
        401: {"description": "Invalid credentials"},
        403: {"description": "Untrusted Origin"},
    },
)
async def login(
    _origin: OriginGuard,
    payload: LoginRequest,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> AccessToken:
    pair = await service.login(payload.email.lower(), payload.password)
    _set_refresh_cookie(response, pair["refresh_token"], settings)
    return _access_response(pair, response)


@router.post(
    "/refresh",
    response_model=AccessToken,
    responses={
        401: {"description": "Invalid refresh token"},
        403: {"description": "Untrusted Origin"},
    },
)
async def refresh(
    _origin: OriginGuard,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> AccessToken:
    if not refresh_token:
        raise AuthenticationError("Invalid refresh token")
    pair = await service.refresh(refresh_token)
    _set_refresh_cookie(response, pair["refresh_token"], settings)
    return _access_response(pair, response)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"description": "Invalid refresh token"},
        403: {"description": "Untrusted Origin"},
    },
)
async def logout(
    _origin: OriginGuard,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> Response:
    try:
        if not refresh_token:
            raise AuthenticationError("Invalid refresh token")
        await service.logout(refresh_token)
    except AuthenticationError as exc:
        response = JSONResponse(status_code=401, content={"detail": str(exc)})
    else:
        response.status_code = status.HTTP_204_NO_CONTENT
    _clear_refresh_cookie(response, settings)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response
