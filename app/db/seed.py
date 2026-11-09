"""Create stable development records required by task creation."""

import hashlib
import secrets
from uuid import UUID

from sqlalchemy import text

from app.models.entities import (
    Project,
    ProjectStatus,
    User,
    UserRole,
    Workspace,
    WorkspaceMember,
)
from app.models.enums import WorkspaceRole

DEFAULT_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
DEFAULT_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000003")
DISABLED_PASSWORD_ITERATIONS = 600_000


def disabled_password_hash() -> str:
    salt = secrets.token_bytes(16)
    material = secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", material, salt, DISABLED_PASSWORD_ITERATIONS)
    return (
        f"disabled$pbkdf2_sha256${DISABLED_PASSWORD_ITERATIONS}"
        f"${salt.hex()}${digest.hex()}"
    )


async def seed_default_data(session_factory) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(text("SELECT pg_advisory_xact_lock(721347102)"))
        if await session.get(User, DEFAULT_USER_ID) is None:
            session.add(
                User(
                    id=DEFAULT_USER_ID,
                    email="system@taskhub.local",
                    full_name="TaskHub System",
                    hashed_password=disabled_password_hash(),
                    role=UserRole.ADMIN,
                )
            )
            await session.flush()
        if await session.get(Workspace, DEFAULT_WORKSPACE_ID) is None:
            session.add(
                Workspace(
                    id=DEFAULT_WORKSPACE_ID,
                    name="Default",
                    owner_id=DEFAULT_USER_ID,
                )
            )
            await session.flush()
        if (
            await session.get(WorkspaceMember, (DEFAULT_WORKSPACE_ID, DEFAULT_USER_ID))
            is None
        ):
            session.add(
                WorkspaceMember(
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    user_id=DEFAULT_USER_ID,
                    role=WorkspaceRole.OWNER,
                )
            )
        if await session.get(Project, DEFAULT_PROJECT_ID) is None:
            session.add(
                Project(
                    id=DEFAULT_PROJECT_ID,
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    name="Default",
                    status=ProjectStatus.ACTIVE,
                )
            )
