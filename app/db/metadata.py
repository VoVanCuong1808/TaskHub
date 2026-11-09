"""SQLAlchemy metadata with all mapped tables registered."""

from app.db.base import Base
from app.models import entities

__all__ = ["Base", "entities"]
