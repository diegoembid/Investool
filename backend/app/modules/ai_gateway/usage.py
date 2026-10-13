"""Resumen de consumo y gasto de IA para el panel de costes."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import utcnow
from app.modules.ai_gateway.gateway import day_start, month_start, spent_since
from app.modules.ai_gateway.models import AICall

PROVIDERS = ("anthropic", "openai")


@dataclass
class ProviderUsage:
    provider: str
    configured: bool
    month_spent_usd: Decimal
    month_cap_usd: Decimal
    calls_by_status: dict[str, int]


@dataclass
class UsageSummary:
    as_of: datetime
    ai_enabled: bool
    usd_to_eur: Decimal
    today_spent_usd: Decimal
    daily_cap_usd: Decimal
    month_spent_usd: Decimal
    monthly_cap_usd: Decimal
    providers: list[ProviderUsage] = field(default_factory=list)
    recent_calls: list[AICall] = field(default_factory=list)


def summarize(db: Session, settings: Settings, configured: set[str]) -> UsageSummary:
    now = utcnow()
    m0 = month_start(now)
    summary = UsageSummary(
        as_of=now,
        ai_enabled=settings.ai_enabled,
        usd_to_eur=settings.usd_to_eur,
        today_spent_usd=spent_since(db, day_start(now)),
        daily_cap_usd=settings.ai_global_daily_cap_usd,
        month_spent_usd=spent_since(db, m0),
        monthly_cap_usd=settings.ai_global_monthly_cap_usd,
    )
    for p in PROVIDERS:
        rows = db.execute(
            select(AICall.status, func.count(AICall.id))
            .where(AICall.provider == p, AICall.created_at >= m0)
            .group_by(AICall.status)
        ).all()
        summary.providers.append(
            ProviderUsage(
                provider=p,
                configured=p in configured,
                month_spent_usd=spent_since(db, m0, p),
                month_cap_usd=settings.provider_monthly_cap(p),
                calls_by_status={status: n for status, n in rows},
            )
        )
    summary.recent_calls = list(
        db.scalars(select(AICall).order_by(AICall.created_at.desc(), AICall.id.desc()).limit(25))
    )
    return summary
