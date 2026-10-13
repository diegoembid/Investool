from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow

MONEY = Numeric(14, 6)


class AICallStatus:
    RESERVED = "reserved"  # presupuesto reservado, llamada en curso
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # el proveedor devolvió error (coste 0 salvo que informe uso)
    BLOCKED = "blocked"  # rechazada antes de llamar (tope, modelo desconocido, IA apagada)
    CACHED = "cached"  # respondida desde caché, sin coste
    ABANDONED = "abandoned"  # reserva sin cerrar (caída del proceso): se asume el coste reservado

    COUNTED = (RESERVED, SUCCEEDED, FAILED, ABANDONED)


class AICall(Base):
    """Registro de cada intento de llamada a un modelo de IA."""

    __tablename__ = "ai_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    finished_at: Mapped[datetime | None]
    provider: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved_usd: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    cost_usd: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    price_verified_on: Mapped[str | None] = mapped_column(String(10))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class AICacheEntry(Base):
    """Respuestas reutilizables para peticiones idénticas."""

    __tablename__ = "ai_cache"

    request_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    response_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(index=True)
