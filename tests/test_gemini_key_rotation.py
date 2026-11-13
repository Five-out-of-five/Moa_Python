"""키 전환·재시도 규칙.

429/401/403 -> 다음 키, 쿨다운
5xx·타임아웃·깨진 응답 -> 같은 키로 재시도
400 등 -> 바로 실패
"""

import json
import logging

import pytest

from app.clients.gemini import GeminiClient, GeminiTask
from app.core.errors import AiErrorCode, AiException
from tests.conftest import make_settings
from tests.fakes import FakeApiError, install

pytestmark = pytest.mark.usefixtures("no_sleep")


def _client(keys: str = "k1,k2,k3", **overrides) -> GeminiClient:
    return GeminiClient(make_settings(gemini_api_key=keys, **overrides))


async def _call(client: GeminiClient):
    return await client.generate_json(GeminiTask.TONE, "p", {"type": "object"}, lambda data: data)


async def test_quota_error_rotates_to_next_key(monkeypatch):
    calls = install(monkeypatch, {"k1": [FakeApiError(429, "RESOURCE_EXHAUSTED")]})
    client = _client()
    assert await _call(client) == {"ok": True}
    assert calls == ["k1", "k2"]


async def test_rotated_key_stays_in_cooldown(monkeypatch):
    calls = install(monkeypatch, {"k1": [FakeApiError(429)]})
    client = _client()
    await _call(client)
    await _call(client)
    # 두 번째 요청은 쿨다운 중인 k1 을 건너뛰고 k2 에서 시작한다.
    assert calls == ["k1", "k2", "k2"]


@pytest.mark.parametrize("status", [401, 403])
async def test_dead_key_rotates(monkeypatch, status):
    calls = install(monkeypatch, {"k1": [FakeApiError(status)]})
    assert await _call(_client()) == {"ok": True}
    assert calls == ["k1", "k2"]


async def test_all_keys_exhausted_fails(monkeypatch):
    install(monkeypatch, {k: [FakeApiError(429)] for k in ("k1", "k2", "k3")})
    with pytest.raises(AiException) as caught:
        await _call(_client())
    assert caught.value.error_code is AiErrorCode.LLM_CALL_FAILED


async def test_server_error_retries_same_key(monkeypatch):
    calls = install(monkeypatch, {"k1": [FakeApiError(503), FakeApiError(500)]})
    assert await _call(_client()) == {"ok": True}
    assert calls == ["k1", "k1", "k1"]


async def test_retries_are_limited(monkeypatch):
    install(monkeypatch, {"k1": [FakeApiError(503)] * 5})
    with pytest.raises(AiException) as caught:
        await _call(_client(gemini_max_retries=2))
    assert caught.value.error_code is AiErrorCode.LLM_CALL_FAILED


async def test_bad_request_fails_without_retry(monkeypatch):
    calls = install(monkeypatch, {"k1": [FakeApiError(400, "INVALID_ARGUMENT")]})
    with pytest.raises(AiException):
        await _call(_client())
    assert calls == ["k1"]


async def test_broken_json_is_retried(monkeypatch):
    calls = install(monkeypatch, {"k1": ["{not json", ""]})
    assert await _call(_client()) == {"ok": True}
    assert calls == ["k1", "k1", "k1"]


async def test_parse_failure_is_retried_then_reported(monkeypatch):
    install(monkeypatch, {"k1": ['{"a": 1}'] * 5})

    def parse(data):
        raise ValueError("missing field")

    with pytest.raises(AiException) as caught:
        await _call_with(_client(), parse)
    assert caught.value.error_code is AiErrorCode.LLM_RESPONSE_INVALID


async def _call_with(client, parse):
    return await client.generate_json(GeminiTask.TONE, "p", {"type": "object"}, parse)


async def test_key_value_is_never_logged(monkeypatch, caplog):
    install(monkeypatch, {"secret-key-1": [FakeApiError(429, "quota")]})
    with caplog.at_level(logging.DEBUG):
        await _call(_client("secret-key-1,secret-key-2"))
    assert "secret-key" not in caplog.text
    assert "1/2" in caplog.text


async def test_embedding_dimension_mismatch_fails(monkeypatch):
    install(monkeypatch, {"k1": [[0.1] * 10]})
    with pytest.raises(AiException) as caught:
        await _client("k1").embed("text")
    assert caught.value.error_code is AiErrorCode.EMBEDDING_FAILED


async def test_embedding_is_normalized(monkeypatch):
    install(monkeypatch, {"k1": [[3.0] * 768]})
    vector = await _client("k1").embed("text")
    assert len(vector) == 768
    assert abs(sum(v * v for v in vector) - 1.0) < 1e-9


async def test_stream_rotates_before_first_chunk(monkeypatch):
    calls = install(monkeypatch, {"k1": [FakeApiError(429)], "k2": [["안녕", "하세요"]]})
    stream = await _client().open_text_stream(GeminiTask.ASSISTANT, "p")
    assert [piece async for piece in stream] == ["안녕", "하세요"]
    assert calls == ["k1", "k2"]


async def test_empty_stream_is_reported(monkeypatch):
    install(monkeypatch, {"k1": [[]] * 5})
    with pytest.raises(AiException) as caught:
        await _client("k1").open_text_stream(GeminiTask.ASSISTANT, "p")
    assert caught.value.error_code is AiErrorCode.LLM_RESPONSE_INVALID


def test_stub_json_matches_schema():
    import asyncio

    client = GeminiClient(make_settings(ai_stub_mode=True, gemini_api_key=""))
    schema = {"type": "object", "properties": {"items": {"type": "array", "items": {
        "type": "object", "properties": {"card_id": {"type": "integer"}}}}}}
    result = asyncio.run(client.generate_json(GeminiTask.CONFLICT, "card_id=4 card_id=9", schema, lambda d: d))
    assert json.dumps(result) == json.dumps({"items": [{"card_id": 4}, {"card_id": 9}]})
