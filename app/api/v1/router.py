"""Version 1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import auth, tasks, users, workspaces

api_router = APIRouter()
api_router.include_router(tasks.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(workspaces.router)
