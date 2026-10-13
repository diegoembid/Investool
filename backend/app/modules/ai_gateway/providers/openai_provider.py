from typing import Any

import openai

from app.modules.ai_gateway.providers.base import (
    CompletionRequest,
    CompletionResult,
    ProviderError,
    timeout_for,
)


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        # Sin reintentos automáticos del SDK: cada intento debe pasar por la pasarela
        # con su propia reserva de presupuesto.
        max_retries: int = 0,
        http_client: Any = None,  # cliente HTTP propio del SDK (solo para pruebas)
    ):
        self._client = openai.OpenAI(
            api_key=api_key, max_retries=max_retries, http_client=http_client
        )

    def complete(self, request: CompletionRequest) -> CompletionResult:
        try:
            resp = self._client.responses.create(
                model=request.model,
                instructions=request.system,
                input=request.prompt,
                max_output_tokens=request.max_output_tokens,
                # No guardar la conversación en los servidores de OpenAI.
                store=False,
                timeout=timeout_for(request.max_output_tokens),
            )
        except openai.APIStatusError as exc:
            raise ProviderError(f"OpenAI respondió {exc.status_code}: {_safe(exc)}") from exc
        except openai.APIConnectionError as exc:  # incluye el tiempo agotado
            raise ProviderError(
                f"Sin respuesta de OpenAI ({type(exc).__name__}); se asume el coste máximo",
                outcome_unknown=True,
            ) from exc
        except openai.APIError as exc:
            raise ProviderError(f"Error de OpenAI: {type(exc).__name__}") from exc

        u = resp.usage
        total_in = (u.input_tokens if u else 0) or 0
        cached = 0
        if u and u.input_tokens_details is not None:
            cached = u.input_tokens_details.cached_tokens or 0
        return CompletionResult(
            text=resp.output_text or "",
            input_tokens=max(total_in - cached, 0),
            output_tokens=(u.output_tokens if u else 0) or 0,
            cache_read_tokens=cached,
            stop_reason=resp.status,
        )


def _safe(exc: openai.APIStatusError) -> str:
    body = exc.body if isinstance(exc.body, dict) else {}
    err = body.get("error", body) if isinstance(body, dict) else {}
    msg = err.get("message") if isinstance(err, dict) else None
    return str(msg or exc.message)[:300]
