"""Current account profile endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.deps import AuthServiceDep, get_current_user
from app.models.entities import User
from app.schemas.user import ChangePasswordRequest, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserRead,
    responses={401: {"description": "Not authenticated"}},
)
async def get_me(user: Annotated[User, Depends(get_current_user)]) -> UserRead:
    return UserRead.model_validate(user)


@router.patch(
    "/me",
    response_model=UserRead,
    responses={
        401: {"description": "Not authenticated"},
        409: {"description": "Email already exists"},
    },
)
async def update_me(
    payload: UserUpdate,
    user: Annotated[User, Depends(get_current_user)],
    service: AuthServiceDep,
) -> UserRead:
    updated = await service.update_profile(user, payload.model_dump(exclude_unset=True))
    return UserRead.model_validate(updated)


@router.post(
    "/me/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"description": "Invalid current password"}},
)
async def change_password(
    payload: ChangePasswordRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: AuthServiceDep,
):
    await service.change_password(user, payload.current_password, payload.new_password)
