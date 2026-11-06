"""Version 1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import tasks

api_router = APIRouter()
api_router.include_router(tasks.router)
