"""Prueba mínima de cada proveedor: una llamada de coste ínfimo que queda registrada."""

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import Settings
from app.modules.ai_gateway.gateway import AIGateway, GatewayError

SMOKE_SYSTEM = "Eres una prueba de conexión. Responde exactamente con la palabra OK."
SMOKE_PROMPT = "Prueba de conexión."
SMOKE_MAX_TOKENS = 16


@dataclass
class SmokeResult:
    provider: str
    model: str
    ok: bool
    detail: str
    cost_usd: Decimal = Decimal(0)
    call_id: int | None = None


def smoke_models(settings: Settings) -> dict[str, str]:
    return {
        "anthropic": settings.ai_anthropic_smoke_model,
        "openai": settings.ai_openai_smoke_model,
    }


def run_smoke_test(
    gateway: AIGateway, settings: Settings, provider: str, user_id: int | None = None
) -> SmokeResult:
    model = smoke_models(settings).get(provider)
    if model is None:
        return SmokeResult(provider, "-", False, f"Proveedor desconocido: {provider}")
    try:
        r = gateway.complete(
            provider=provider,
            model=model,
            system=SMOKE_SYSTEM,
            prompt=SMOKE_PROMPT,
            max_output_tokens=SMOKE_MAX_TOKENS,
            purpose="smoke_test",
            user_id=user_id,
            use_cache=False,
        )
    except GatewayError as exc:
        return SmokeResult(provider, model, False, str(exc))
    answer = r.text.strip()[:60] or "(respuesta vacía)"
    return SmokeResult(
        provider, model, True, f"Respuesta: {answer}", cost_usd=r.cost_usd, call_id=r.call_id
    )
