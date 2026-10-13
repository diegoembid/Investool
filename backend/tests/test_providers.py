"""Los adaptadores se prueban con los SDK oficiales contra respuestas simuladas con el formato
real de cada API. Un transporte simulado sustituye a la red: no sale ninguna petición real
ni se gasta dinero."""

import json

import httpx
import httpx2  # el SDK de Anthropic usa su propio cliente HTTP
import pytest

from app.modules.ai_gateway.providers.anthropic_provider import AnthropicProvider
from app.modules.ai_gateway.providers.base import CompletionRequest, ProviderError
from app.modules.ai_gateway.providers.openai_provider import OpenAIProvider

REQ = CompletionRequest(model="m", system="s", prompt="p", max_output_tokens=16)


class Recorder:
    def __init__(self, status: int, body: dict):
        self.status, self.body = status, body
        self.requests: list[httpx.Request] = []

    def client(self, lib=httpx):
        def handler(request):
            self.requests.append(request)
            return lib.Response(self.status, json=self.body)

        return lib.Client(transport=lib.MockTransport(handler))


def _anthropic(rec: Recorder, key: str = "sk-ant-prueba") -> AnthropicProvider:
    return AnthropicProvider(key, max_retries=0, http_client=rec.client(httpx2))


def _openai(rec: Recorder) -> OpenAIProvider:
    return OpenAIProvider("sk-prueba", max_retries=0, http_client=rec.client())


def test_anthropic_lee_texto_y_uso():
    rec = Recorder(
        200,
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "m",
            "content": [{"type": "text", "text": "OK"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 12,
                "output_tokens": 2,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 50,
            },
        },
    )
    r = _anthropic(rec).complete(REQ)
    assert (r.text, r.input_tokens, r.output_tokens) == ("OK", 12, 2)
    assert (r.cache_read_tokens, r.cache_write_tokens) == (100, 50)
    sent = rec.requests[-1]
    assert sent.url.path.endswith("/messages")
    assert sent.headers["x-api-key"] == "sk-ant-prueba"
    body = json.loads(sent.content)
    assert body["max_tokens"] == 16 and body["system"] == "s"
    assert body["messages"] == [{"role": "user", "content": "p"}]


def test_anthropic_error_sin_filtrar_la_clave():
    rec = Recorder(
        401,
        {
            "type": "error",
            "error": {"type": "authentication_error", "message": "invalid x-api-key"},
        },
    )
    with pytest.raises(ProviderError) as exc:
        _anthropic(rec, key="sk-ant-secreta").complete(REQ)
    assert "401" in str(exc.value) and "invalid x-api-key" in str(exc.value)
    assert "sk-ant-secreta" not in str(exc.value)


def test_openai_lee_texto_y_separa_tokens_en_cache():
    rec = Recorder(
        200,
        {
            "id": "resp_1",
            "object": "response",
            "created_at": 1760000000,
            "status": "completed",
            "model": "m",
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "output": [
                {
                    "type": "message",
                    "id": "msg_1",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "OK", "annotations": []}],
                }
            ],
            "usage": {
                "input_tokens": 120,
                "output_tokens": 3,
                "total_tokens": 123,
                "input_tokens_details": {"cached_tokens": 100},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        },
    )
    r = _openai(rec).complete(REQ)
    assert r.text == "OK"
    assert (r.input_tokens, r.cache_read_tokens, r.output_tokens) == (20, 100, 3)
    sent = rec.requests[-1]
    assert sent.url.path.endswith("/responses")
    body = json.loads(sent.content)
    assert body["store"] is False and body["max_output_tokens"] == 16
    assert body["instructions"] == "s" and body["input"] == "p"


def test_openai_modelo_inexistente():
    rec = Recorder(
        404, {"error": {"message": "The model `m` does not exist", "type": "invalid_request_error"}}
    )
    with pytest.raises(ProviderError, match="404.*does not exist"):
        _openai(rec).complete(REQ)
