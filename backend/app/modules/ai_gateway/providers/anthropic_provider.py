from typing import Any

import anthropic

from app.modules.ai_gateway.providers.base import (
    CompletionRequest,
    CompletionResult,
    ProviderError,
    timeout_for,
)


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        # Sin reintentos automáticos del SDK: cada intento debe pasar por la pasarela
        # con su propia reserva de presupuesto.
        max_retries: int = 0,
        http_client: Any = None,  # cliente HTTP propio del SDK (solo para pruebas)
    ):
        self._client = anthropic.Anthropic(
            api_key=api_key, max_retries=max_retries, http_client=http_client
        )

    def complete(self, request: CompletionRequest) -> CompletionResult:
        try:
            msg = self._client.messages.create(
                model=request.model,
                max_tokens=request.max_output_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.prompt}],
                timeout=timeout_for(request.max_output_tokens),
            )
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic respondió {exc.status_code}: {_safe(exc)}") from exc
        except anthropic.APIConnectionError as exc:  # incluye el tiempo agotado
            raise ProviderError(
                f"Sin respuesta de Anthropic ({type(exc).__name__}); se asume el coste máximo",
                outcome_unknown=True,
            ) from exc
        except anthropic.APIError as exc:
            raise ProviderError(f"Error de Anthropic: {type(exc).__name__}") from exc

        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        u = msg.usage
        return CompletionResult(
            text=text,
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
            stop_reason=msg.stop_reason,
        )


def _safe(exc: anthropic.APIStatusError) -> str:
    body = exc.body if isinstance(exc.body, dict) else {}
    err = body.get("error", {}) if isinstance(body.get("error"), dict) else {}
    return str(err.get("message") or exc.message)[:300]
