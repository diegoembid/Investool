import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.ai_gateway.gateway import (
    AIDisabled,
    AIGateway,
    BudgetExceeded,
    GatewayError,
    ProviderCallFailed,
    ProviderNotConfigured,
    spent_since,
)
from app.modules.ai_gateway.models import AICall, AICallStatus
from app.modules.ai_gateway.providers.base import ProviderError
from tests.conftest import FakeProvider

HAIKU = "claude-haiku-5-5"


def _call(gw, **kw):
    args = dict(
        provider="anthropic",
        model=HAIKU,
        system="sistema",
        prompt="hola",
        max_output_tokens=500,
        purpose="test",
    )
    args.update(kw)
    return gw.complete(**args)


def _calls(sessions):
    with sessions() as db:
        return list(db.scalars(select(AICall).order_by(AICall.id)))


def test_llamada_correcta_registra_coste_real(sessions, settings, fake_providers):
    gw = AIGateway(sessions, settings, fake_providers)
    r = _call(gw)
    assert r.text == "OK" and not r.cached
    assert r.cost_usd == Decimal("0.000350")  # 1000 in + 500 out con Haiku
    (c,) = _calls(sessions)
    assert c.status == AICallStatus.SUCCEEDED
    assert c.cost_usd == Decimal("0.000350")
    assert c.reserved_usd > 0 and c.price_verified_on is not None


def test_peticion_identica_sale_de_cache_sin_coste(sessions, settings, fake_providers):
    gw = AIGateway(sessions, settings, fake_providers)
    _call(gw)
    r2 = _call(gw)
    assert r2.cached and r2.cost_usd == 0
    assert fake_providers["anthropic"].calls == 1
    assert [c.status for c in _calls(sessions)] == ["succeeded", "cached"]


def test_sin_cache_vuelve_a_llamar(sessions, settings, fake_providers):
    gw = AIGateway(sessions, settings, fake_providers)
    _call(gw, use_cache=False)
    _call(gw, use_cache=False)
    assert fake_providers["anthropic"].calls == 2


def test_tope_del_proveedor_bloquea_sin_llamar(sessions, settings, fake_providers):
    settings.ai_anthropic_monthly_cap_usd = Decimal("0.0001")
    gw = AIGateway(sessions, settings, fake_providers)
    with pytest.raises(BudgetExceeded) as exc:
        _call(gw)
    assert "mensual anthropic" in str(exc.value)
    assert fake_providers["anthropic"].calls == 0
    (c,) = _calls(sessions)
    assert c.status == AICallStatus.BLOCKED and "Tope" in c.error


def test_tope_diario_global_bloquea(sessions, settings, fake_providers):
    settings.ai_global_daily_cap_usd = Decimal("0.0001")
    gw = AIGateway(sessions, settings, fake_providers)
    with pytest.raises(BudgetExceeded, match="diario global"):
        _call(gw)


def test_reservas_abiertas_cuentan_como_gasto(sessions, settings, fake_providers):
    settings.ai_anthropic_monthly_cap_usd = Decimal("1")
    with sessions() as db, db.begin():
        db.add(
            AICall(
                provider="anthropic",
                model=HAIKU,
                purpose="otra",
                status="reserved",
                request_hash="x",
                reserved_usd=Decimal("0.9999"),
            )
        )
    gw = AIGateway(sessions, settings, fake_providers)
    with pytest.raises(BudgetExceeded):
        _call(gw)


def test_reserva_caducada_se_da_por_gastada(sessions, settings, fake_providers):
    old = datetime.now(UTC) - timedelta(hours=2)
    with sessions() as db, db.begin():
        db.add(
            AICall(
                provider="anthropic",
                model=HAIKU,
                purpose="caida",
                status="reserved",
                request_hash="x",
                reserved_usd=Decimal("0.5"),
                created_at=old,
            )
        )
    gw = AIGateway(sessions, settings, fake_providers)
    _call(gw)
    calls = _calls(sessions)
    assert calls[0].status == AICallStatus.ABANDONED
    assert calls[0].cost_usd == Decimal("0.5")
    with sessions() as db:
        assert spent_since(db, old - timedelta(minutes=1)) == Decimal("0.500350")


def test_gasto_del_mes_anterior_no_cuenta(sessions, settings, fake_providers):
    settings.ai_anthropic_monthly_cap_usd = Decimal("1")
    last_month = datetime(2026, 9, 30, 23, 59, tzinfo=UTC)
    with sessions() as db, db.begin():
        db.add(
            AICall(
                provider="anthropic",
                model=HAIKU,
                purpose="x",
                status="succeeded",
                request_hash="x",
                cost_usd=Decimal("5"),
                created_at=last_month,
            )
        )
    gw = AIGateway(
        sessions, settings, fake_providers, clock=lambda: datetime(2026, 10, 1, 0, 5, tzinfo=UTC)
    )
    assert _call(gw).text == "OK"


def test_ia_desactivada(sessions, settings, fake_providers):
    settings.ai_enabled = False
    gw = AIGateway(sessions, settings, fake_providers)
    with pytest.raises(AIDisabled):
        _call(gw)
    assert fake_providers["anthropic"].calls == 0
    assert _calls(sessions)[0].status == AICallStatus.BLOCKED


def test_modelo_sin_precio_se_bloquea(sessions, settings, fake_providers):
    gw = AIGateway(sessions, settings, fake_providers)
    with pytest.raises(GatewayError, match="catálogo de precios"):
        _call(gw, model="modelo-sin-precio")
    assert fake_providers["anthropic"].calls == 0


def test_proveedor_sin_clave(sessions, settings):
    gw = AIGateway(sessions, settings, {})
    with pytest.raises(ProviderNotConfigured):
        _call(gw)


def test_error_del_proveedor_libera_la_reserva(sessions, settings):
    providers = {"anthropic": FakeProvider(error=ProviderError("Anthropic respondió 500"))}
    gw = AIGateway(sessions, settings, providers)
    with pytest.raises(ProviderCallFailed):
        _call(gw)
    (c,) = _calls(sessions)
    assert c.status == AICallStatus.FAILED and c.cost_usd == 0
    with sessions() as db:
        assert spent_since(db, datetime(2000, 1, 1, tzinfo=UTC)) == 0


def test_sin_respuesta_del_proveedor_se_asume_el_coste_maximo(sessions, settings):
    err = ProviderError("Sin respuesta de Anthropic (APITimeoutError)", outcome_unknown=True)
    gw = AIGateway(sessions, settings, {"anthropic": FakeProvider(error=err)})
    with pytest.raises(ProviderCallFailed):
        _call(gw)
    (c,) = _calls(sessions)
    assert c.status == AICallStatus.FAILED
    assert c.cost_usd == c.reserved_usd > 0


def test_error_inesperado_tambien_se_cuenta(sessions, settings):
    gw = AIGateway(sessions, settings, {"anthropic": FakeProvider(error=RuntimeError("x"))})
    with pytest.raises(RuntimeError):
        _call(gw)
    (c,) = _calls(sessions)
    assert c.cost_usd == c.reserved_usd > 0


def test_cache_tolera_peticiones_identicas_simultaneas(sessions, settings):
    provider = FakeProvider(delay=0.3)
    gw = AIGateway(sessions, settings, {"anthropic": provider})
    errors: list[Exception] = []

    def worker() -> None:
        try:
            _call(gw)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert all(c.status == AICallStatus.SUCCEEDED for c in _calls(sessions))


def test_max_output_tokens_fuera_de_rango(sessions, settings, fake_providers):
    gw = AIGateway(sessions, settings, fake_providers)
    with pytest.raises(ValueError):
        _call(gw, max_output_tokens=0)


def test_llamadas_simultaneas_no_superan_el_tope(sessions, settings):
    """Con presupuesto para una sola llamada, de ocho simultáneas solo pasa una."""
    provider = FakeProvider(delay=0.3)
    gw = AIGateway(sessions, settings, {"anthropic": provider})
    one_call = None
    from app.modules.ai_gateway import pricing

    one_call = pricing.max_cost_usd(pricing.get_price("anthropic", HAIKU), "sistema" + "p0", 500)
    settings.ai_anthropic_monthly_cap_usd = one_call * Decimal("1.5")

    results: list[str] = []

    def worker(i: int) -> None:
        try:
            _call(gw, prompt=f"p{i}", use_cache=False)
            results.append("ok")
        except BudgetExceeded:
            results.append("bloqueada")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1
    assert provider.calls == 1
