from decimal import Decimal

import pytest

from app.modules.ai_gateway import pricing


def test_coste_basico_haiku():
    p = pricing.get_price("anthropic", "claude-haiku-5-5")
    # 1.000 tokens de entrada a 0,10 + 500 de salida a 0,50 por millón
    assert pricing.cost_usd(p, 1000, 500) == Decimal("0.000350")


def test_contexto_largo_haiku_usa_precios_altos():
    p = pricing.get_price("anthropic", "claude-haiku-5-5")
    assert pricing.cost_usd(p, 100_001, 0) == Decimal("0.050001")  # 100.001 × 0,50 / 1e6
    assert pricing.cost_usd(p, 100_000, 0) == Decimal("0.010000")  # justo en el límite


def test_lectura_y_escritura_de_cache():
    p = pricing.get_price("anthropic", "claude-sonnet-5-5")
    # 1e6 leídos de caché a 0,10 + 1e6 escritos a 2,50
    assert pricing.cost_usd(p, 0, 0, 1_000_000, 1_000_000) == Decimal("2.600000")


def test_modelo_desconocido_no_tiene_precio():
    with pytest.raises(pricing.UnknownModel):
        pricing.get_price("openai", "modelo-inventado")


def test_coste_maximo_usa_tope_de_salida():
    p = pricing.get_price("openai", "gpt-6-luna")
    prompt = "x" * 3000  # cota: 3.050 tokens
    expected = pricing.cost_usd(p, 3050, 2000)
    assert pricing.max_cost_usd(p, prompt, 2000) == expected
    assert expected > pricing.cost_usd(p, 1000, 0)


def test_estimacion_de_tokens_nunca_se_queda_corta():
    # Cada token ocupa al menos un byte: la cota vale para cualquier idioma o contenido.
    assert pricing.estimate_input_tokens("a" * 4000) >= 4000
    assert pricing.estimate_input_tokens("市场" * 15000) >= 30000  # chino: >= 1 token/carácter
    assert pricing.estimate_input_tokens("1234567890," * 30000) >= 330000


def test_reserva_aplica_precio_de_contexto_largo_si_la_cota_lo_supera():
    p = pricing.get_price("anthropic", "claude-haiku-5-5")
    prompt = "9," * 60_000  # 120.000 bytes: podría superar los 100.000 tokens
    assert pricing.max_cost_usd(p, prompt, 100) == pricing.cost_usd(p, 120_050, 100)
    assert pricing.cost_usd(p, 120_050, 100) > pricing.cost_usd(p, 99_000, 100) * 4


def test_todas_las_entradas_tienen_fuente_y_fecha():
    for price in pricing.CATALOG.values():
        assert price.source.startswith("https://")
        assert len(price.verified_on) == 10
        assert price.input > 0 and price.output > 0
