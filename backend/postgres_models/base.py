"""SQLAlchemy declarative base for all NMS PostgreSQL models."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata namespace for every PostgreSQL model in the auth stack."""
    pass
