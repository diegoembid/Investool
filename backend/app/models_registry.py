"""Importa todos los modelos para que SQLAlchemy y Alembic los conozcan."""

from app.modules.ai_gateway.models import AICacheEntry, AICall  # noqa: F401
from app.modules.auth.models import AuthSession, LoginAttempt, User  # noqa: F401
