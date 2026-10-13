"""Pasarela única hacia los proveedores de IA.

Cada llamada sigue tres pasos, cada uno en su propia transacción:

1. Reserva: se calcula el coste máximo posible y se comprueba contra todos los topes.
   Si cabe, se registra una reserva; si no, se registra un bloqueo y no se llama.
2. Llamada al proveedor (fuera de cualquier transacción).
3. Cierre: se sustituye la reserva por el coste real informado por el proveedor.

Así el gasto nunca puede superar un tope aunque varias tareas llamen a la vez.
"""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.db import utcnow
from app.modules.ai_gateway import pricing
from app.modules.ai_gateway.models import AICacheEntry, AICall, AICallStatus
from app.modules.ai_gateway.providers.base import (
    CompletionRequest,
    Provider,
    ProviderError,
)

_BUDGET_LOCK_KEY = 815_330_001  # clave fija del bloqueo consultivo de PostgreSQL
STALE_RESERVATION = timedelta(minutes=30)
MAX_OUTPUT_TOKENS_LIMIT = 16_000


def _es(value: Decimal, digits: int) -> str:
    """Número con coma decimal, como se escribe en español."""
    return f"{value:.{digits}f}".replace(".", ",")


class GatewayError(Exception):
    """Error de la pasarela con un mensaje apto para mostrar al usuario."""


class AIDisabled(GatewayError):
    pass


class ProviderNotConfigured(GatewayError):
    pass


class BudgetExceeded(GatewayError):
    def __init__(self, scope: str, cap: Decimal, spent: Decimal, needed: Decimal):
        super().__init__(
            f"Tope de gasto alcanzado ({scope}): gastado {_es(spent, 4)} USD de {_es(cap, 2)} USD; "
            f"esta llamada podría costar hasta {_es(needed, 4)} USD"
        )
        self.scope, self.cap, self.spent, self.needed = scope, cap, spent, needed


class ProviderCallFailed(GatewayError):
    pass


@dataclass(frozen=True)
class GatewayResponse:
    text: str
    call_id: int
    cost_usd: Decimal
    cached: bool
    input_tokens: int
    output_tokens: int


def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def spent_since(db: Session, since: datetime, provider: str | None = None) -> Decimal:
    amount = case(
        (AICall.status == AICallStatus.RESERVED, AICall.reserved_usd), else_=AICall.cost_usd
    )
    stmt = select(func.coalesce(func.sum(amount), 0)).where(
        AICall.created_at >= since, AICall.status.in_(AICallStatus.COUNTED)
    )
    if provider:
        stmt = stmt.where(AICall.provider == provider)
    return Decimal(db.scalar(stmt) or 0)


def request_hash(provider: str, req: CompletionRequest) -> str:
    payload = json.dumps(
        {
            "provider": provider,
            "model": req.model,
            "system": req.system,
            "prompt": req.prompt,
            "max_output_tokens": req.max_output_tokens,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class AIGateway:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        providers: dict[str, Provider],
        clock: Callable[[], datetime] = utcnow,
    ):
        self._sessions = session_factory
        self._settings = settings
        self._providers = providers
        self._now = clock

    # ------------------------------------------------------------------ API pública
    def complete(
        self,
        *,
        provider: str,
        model: str,
        system: str,
        prompt: str,
        max_output_tokens: int,
        purpose: str,
        user_id: int | None = None,
        use_cache: bool = True,
    ) -> GatewayResponse:
        if not 1 <= max_output_tokens <= MAX_OUTPUT_TOKENS_LIMIT:
            raise ValueError(f"max_output_tokens debe estar entre 1 y {MAX_OUTPUT_TOKENS_LIMIT}")
        req = CompletionRequest(
            model=model, system=system, prompt=prompt, max_output_tokens=max_output_tokens
        )
        rhash = request_hash(provider, req)

        if use_cache:
            cached = self._from_cache(rhash, provider, model, purpose, user_id)
            if cached:
                return cached

        call_id, reserved = self._reserve(provider, req, rhash, purpose, user_id)

        started = time.monotonic()
        try:
            result = self._providers[provider].complete(req)
        except ProviderError as exc:
            charged = reserved if exc.outcome_unknown else Decimal(0)
            self._finish_failed(call_id, str(exc), started, charged)
            raise ProviderCallFailed(str(exc)) from exc
        except Exception as exc:
            # No se sabe si el proveedor cobró: se asume el coste máximo.
            self._finish_failed(
                call_id, f"Error inesperado: {type(exc).__name__}", started, reserved
            )
            raise

        price = pricing.get_price(provider, model)
        cost = pricing.cost_usd(
            price,
            result.input_tokens,
            result.output_tokens,
            result.cache_read_tokens,
            result.cache_write_tokens,
        )
        latency = int((time.monotonic() - started) * 1000)
        with self._sessions() as db, db.begin():
            db.execute(
                update(AICall)
                .where(AICall.id == call_id)
                .values(
                    status=AICallStatus.SUCCEEDED,
                    finished_at=self._now(),
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cache_read_tokens=result.cache_read_tokens,
                    cache_write_tokens=result.cache_write_tokens,
                    cost_usd=cost,
                    latency_ms=latency,
                )
            )
            if use_cache and result.text:
                # Inserción tolerante: dos peticiones idénticas simultáneas no chocan.
                values = dict(
                    request_hash=rhash,
                    user_id=user_id,
                    provider=provider,
                    model=model,
                    response_text=result.text,
                    created_at=self._now(),
                    expires_at=self._now() + timedelta(hours=self._settings.ai_cache_hours),
                )
                db.execute(
                    pg_insert(AICacheEntry)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=[AICacheEntry.request_hash],
                        set_={k: v for k, v in values.items() if k != "request_hash"},
                    )
                )
        return GatewayResponse(
            text=result.text,
            call_id=call_id,
            cost_usd=cost,
            cached=False,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

    # ------------------------------------------------------------------ pasos internos
    def _record_blocked(
        self,
        db: Session,
        provider: str,
        model: str,
        purpose: str,
        rhash: str,
        user_id: int | None,
        reason: str,
    ) -> None:
        db.add(
            AICall(
                user_id=user_id,
                provider=provider,
                model=model,
                purpose=purpose,
                status=AICallStatus.BLOCKED,
                request_hash=rhash,
                created_at=self._now(),
                finished_at=self._now(),
                error=reason,
            )
        )

    def _reserve(
        self,
        provider: str,
        req: CompletionRequest,
        rhash: str,
        purpose: str,
        user_id: int | None,
    ) -> tuple[int, Decimal]:
        s = self._settings
        failure: GatewayError | None = None
        with self._sessions() as db, db.begin():
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _BUDGET_LOCK_KEY})

            now = self._now()
            db.execute(
                update(AICall)
                .where(
                    AICall.status == AICallStatus.RESERVED,
                    AICall.created_at < now - STALE_RESERVATION,
                )
                .values(
                    status=AICallStatus.ABANDONED,
                    cost_usd=AICall.reserved_usd,
                    error="Reserva sin cerrar: se asume el coste máximo",
                )
            )

            if not s.ai_enabled:
                failure = AIDisabled("La IA está desactivada (AI_ENABLED=false)")
            elif provider not in self._providers:
                failure = ProviderNotConfigured(
                    f"El proveedor '{provider}' no está configurado (falta su clave en .env)"
                )
            else:
                try:
                    price = pricing.get_price(provider, req.model)
                except pricing.UnknownModel as exc:
                    failure = GatewayError(str(exc))
                else:
                    needed = pricing.max_cost_usd(
                        price, req.system + req.prompt, req.max_output_tokens
                    )
                    checks = [
                        (
                            "diario global",
                            s.ai_global_daily_cap_usd,
                            spent_since(db, day_start(now)),
                        ),
                        (
                            "mensual global",
                            s.ai_global_monthly_cap_usd,
                            spent_since(db, month_start(now)),
                        ),
                        (
                            f"mensual {provider}",
                            s.provider_monthly_cap(provider),
                            spent_since(db, month_start(now), provider),
                        ),
                    ]
                    for scope, cap, spent in checks:
                        if spent + needed > cap:
                            failure = BudgetExceeded(scope, cap, spent, needed)
                            break

            if failure is not None:
                self._record_blocked(db, provider, req.model, purpose, rhash, user_id, str(failure))
            else:
                call = AICall(
                    user_id=user_id,
                    provider=provider,
                    model=req.model,
                    purpose=purpose,
                    status=AICallStatus.RESERVED,
                    request_hash=rhash,
                    reserved_usd=needed,
                    price_verified_on=price.verified_on,
                    created_at=now,
                )
                db.add(call)
                db.flush()
                call_id = call.id

        if failure is not None:
            raise failure
        return call_id, needed

    def _finish_failed(self, call_id: int, error: str, started: float, charged: Decimal) -> None:
        with self._sessions() as db, db.begin():
            db.execute(
                update(AICall)
                .where(AICall.id == call_id)
                .values(
                    status=AICallStatus.FAILED,
                    finished_at=self._now(),
                    cost_usd=charged,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error=error[:2000],
                )
            )

    def _from_cache(
        self, rhash: str, provider: str, model: str, purpose: str, user_id: int | None
    ) -> GatewayResponse | None:
        with self._sessions() as db, db.begin():
            entry = db.get(AICacheEntry, rhash)
            if entry is None or entry.expires_at <= self._now():
                return None
            call = AICall(
                user_id=user_id,
                provider=provider,
                model=model,
                purpose=purpose,
                status=AICallStatus.CACHED,
                request_hash=rhash,
                created_at=self._now(),
                finished_at=self._now(),
            )
            db.add(call)
            db.flush()
            return GatewayResponse(
                text=entry.response_text,
                call_id=call.id,
                cost_usd=Decimal(0),
                cached=True,
                input_tokens=0,
                output_tokens=0,
            )


def build_providers(settings: Settings) -> dict[str, Provider]:
    """Crea los clientes de los proveedores que tengan clave configurada."""
    from app.modules.ai_gateway.providers.anthropic_provider import AnthropicProvider
    from app.modules.ai_gateway.providers.openai_provider import OpenAIProvider

    providers: dict[str, Provider] = {}
    if settings.anthropic_api_key and settings.anthropic_api_key.get_secret_value():
        providers["anthropic"] = AnthropicProvider(settings.anthropic_api_key.get_secret_value())
    if settings.openai_api_key and settings.openai_api_key.get_secret_value():
        providers["openai"] = OpenAIProvider(settings.openai_api_key.get_secret_value())
    return providers
