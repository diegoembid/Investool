"""Catálogo de precios de los modelos de IA (USD por millón de tokens).

Reglas:
- Un modelo que no esté en este catálogo NO se puede llamar: sin precio no hay forma
  de controlar el gasto.
- Cada entrada indica la fecha y la página oficial donde se comprobó el precio.
- Cuando dos páginas oficiales del mismo proveedor no coinciden, se usa el precio más alto.
"""

from dataclasses import dataclass
from decimal import ROUND_UP, Decimal

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    provider: str
    model: str
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal  # escritura en caché (Anthropic, 5 minutos); 0 si no aplica
    verified_on: str
    source: str
    # Tramo de contexto largo: por encima de este número de tokens de entrada se aplican
    # los precios "long_*" a toda la petición.
    long_context_threshold: int | None = None
    long_input: Decimal | None = None
    long_output: Decimal | None = None
    long_cache_read: Decimal | None = None
    long_cache_write: Decimal | None = None


_ANTHROPIC_SRC = "https://platform.claude.com/docs/en/about-claude/pricing"
_OPENAI_SRC = "https://developers.openai.com/api/docs/pricing"
D = Decimal

CATALOG: dict[tuple[str, str], Price] = {
    (p.provider, p.model): p
    for p in [
        Price(
            "anthropic",
            "claude-opus-5-5",
            D("4"),
            D("20"),
            D("0.20"),
            D("5"),
            "2026-10-13",
            _ANTHROPIC_SRC,
        ),
        Price(
            "anthropic",
            "claude-sonnet-5-5",
            D("2"),
            D("10"),
            D("0.10"),
            D("2.50"),
            "2026-10-13",
            _ANTHROPIC_SRC,
        ),
        Price(
            "anthropic",
            "claude-haiku-5-5",
            D("0.10"),
            D("0.50"),
            D("0.01"),
            D("0.125"),
            "2026-10-13",
            _ANTHROPIC_SRC,
            long_context_threshold=100_000,
            long_input=D("0.50"),
            long_output=D("2.50"),
            long_cache_read=D("0.05"),
            long_cache_write=D("0.625"),
        ),
        Price(
            "openai", "gpt-6.1-sol", D("2"), D("10"), D("0.10"), D("0"), "2026-10-13", _OPENAI_SRC
        ),
        Price(
            "openai",
            "gpt-6-luna",
            D("0.10"),
            D("0.50"),
            D("0.01"),
            D("0"),
            "2026-10-13",
            _OPENAI_SRC,
        ),
        # Las dos páginas oficiales de OpenAI no coinciden (4/20 frente a 5/30);
        # se toma el precio más alto.
        Price(
            "openai",
            "gpt-5.6-sol",
            D("5"),
            D("30"),
            D("0.50"),
            D("0"),
            "2026-10-13",
            "https://openai.com/api/pricing/",
        ),
    ]
}


class UnknownModel(Exception):
    def __init__(self, provider: str, model: str):
        super().__init__(f"El modelo {provider}/{model} no está en el catálogo de precios")
        self.provider = provider
        self.model = model


def get_price(provider: str, model: str) -> Price:
    try:
        return CATALOG[(provider, model)]
    except KeyError:
        raise UnknownModel(provider, model) from None


def cost_usd(
    price: Price,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    """Coste de una llamada.

    `input_tokens` son los tokens de entrada NO servidos desde caché ni escritos en ella.
    """
    total_prompt = input_tokens + cache_read_tokens + cache_write_tokens
    long = price.long_context_threshold is not None and total_prompt > price.long_context_threshold
    p_in = price.long_input if long and price.long_input is not None else price.input
    p_out = price.long_output if long and price.long_output is not None else price.output
    p_cr = price.long_cache_read if long and price.long_cache_read is not None else price.cache_read
    p_cw = (
        price.long_cache_write if long and price.long_cache_write is not None else price.cache_write
    )
    total = (
        D(input_tokens) * p_in
        + D(output_tokens) * p_out
        + D(cache_read_tokens) * p_cr
        + D(cache_write_tokens) * p_cw
    )
    # Redondeo siempre hacia arriba: mejor sobrestimar que quedarse corto con los topes.
    return (total / MILLION).quantize(D("0.000001"), rounding=ROUND_UP)


def estimate_input_tokens(text: str) -> int:
    """Cota superior de tokens de entrada.

    Cada token ocupa al menos un byte de texto UTF-8, así que el número de bytes nunca
    se queda corto, sea cual sea el idioma o el contenido (cifras, tablas, chino...).
    Sobrestima mucho el texto normal (unos 4 bytes por token), pero la reserva se sustituye
    por el coste real al terminar la llamada.
    """
    return len(text.encode("utf-8")) + 50


def max_cost_usd(price: Price, prompt_text: str, max_output_tokens: int) -> Decimal:
    """Coste máximo previsible de una llamada, usado para reservar presupuesto."""
    return cost_usd(price, estimate_input_tokens(prompt_text), max_output_tokens)
