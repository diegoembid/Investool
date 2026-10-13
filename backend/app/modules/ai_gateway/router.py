from datetime import datetime
from decimal import Decimal
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_db, get_sessionmaker
from app.modules.ai_gateway import usage
from app.modules.ai_gateway.gateway import AIGateway, build_providers
from app.modules.ai_gateway.providers.base import Provider
from app.modules.ai_gateway.smoke import run_smoke_test
from app.modules.auth.deps import current_user
from app.modules.auth.models import User

router = APIRouter(prefix="/api/ai", tags=["ai"])


@lru_cache
def _providers() -> dict[str, Provider]:
    return build_providers(get_settings())


def get_providers() -> dict[str, Provider]:
    return _providers()


def get_gateway(
    settings: Settings = Depends(get_settings),
    providers: dict[str, Provider] = Depends(get_providers),
) -> AIGateway:
    return AIGateway(get_sessionmaker(), settings, providers)


class ProviderUsageOut(BaseModel):
    provider: str
    configured: bool
    month_spent_usd: Decimal
    month_cap_usd: Decimal
    calls_by_status: dict[str, int]


class CallOut(BaseModel):
    id: int
    created_at: datetime
    provider: str
    model: str
    purpose: str
    status: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    reserved_usd: Decimal
    latency_ms: int | None
    error: str | None


class UsageOut(BaseModel):
    as_of: datetime
    ai_enabled: bool
    usd_to_eur: Decimal
    today_spent_usd: Decimal
    daily_cap_usd: Decimal
    month_spent_usd: Decimal
    monthly_cap_usd: Decimal
    providers: list[ProviderUsageOut]
    recent_calls: list[CallOut]


class SmokeOut(BaseModel):
    provider: str
    model: str
    ok: bool
    detail: str
    cost_usd: Decimal
    call_id: int | None


@router.get("/usage", response_model=UsageOut)
def get_usage(
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    providers: dict[str, Provider] = Depends(get_providers),
) -> UsageOut:
    s = usage.summarize(db, settings, set(providers))
    return UsageOut(
        as_of=s.as_of,
        ai_enabled=s.ai_enabled,
        usd_to_eur=s.usd_to_eur,
        today_spent_usd=s.today_spent_usd,
        daily_cap_usd=s.daily_cap_usd,
        month_spent_usd=s.month_spent_usd,
        monthly_cap_usd=s.monthly_cap_usd,
        providers=[ProviderUsageOut(**p.__dict__) for p in s.providers],
        recent_calls=[CallOut.model_validate(c, from_attributes=True) for c in s.recent_calls],
    )


@router.post("/smoke-test/{provider}", response_model=SmokeOut)
def smoke_test(
    provider: str,
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
    gateway: AIGateway = Depends(get_gateway),
) -> SmokeOut:
    if provider not in usage.PROVIDERS:
        raise HTTPException(status_code=404, detail="Proveedor desconocido")
    r = run_smoke_test(gateway, settings, provider, user_id=user.id)
    return SmokeOut(**r.__dict__)
