from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CompletionRequest:
    model: str
    system: str
    prompt: str
    max_output_tokens: int


@dataclass(frozen=True)
class CompletionResult:
    text: str
    # Tokens de entrada facturados a precio normal (sin contar lectura/escritura de caché).
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    stop_reason: str | None = None


class ProviderError(Exception):
    """Error del proveedor, con un mensaje seguro de mostrar (sin claves).

    `outcome_unknown` indica que no se sabe si el proveedor llegó a procesar (y cobrar)
    la petición: tiempo agotado o conexión cortada. En ese caso se asume el coste máximo.
    """

    def __init__(self, message: str, outcome_unknown: bool = False):
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


def timeout_for(max_output_tokens: int) -> float:
    """Tiempo máximo de espera según la salida pedida (unos 40 tokens/s como mínimo)."""
    return min(600.0, 60.0 + max_output_tokens / 40)


class Provider(Protocol):
    name: str

    def complete(self, request: CompletionRequest) -> CompletionResult: ...
