"""생각 수준 설정이 Gemini 호출 설정으로 넘어가는지."""

import pytest
from pydantic import ValidationError

from app.clients import gemini as gemini_module
from app.clients.gemini import GeminiClient, GeminiTask
from tests.conftest import make_settings


class _Obj:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def _capture(monkeypatch) -> list:
    """genai.Client 대역. 받은 config 를 모은다."""
    configs: list = []

    class _Models:
        async def generate_content(self, *, model, contents, config=None):
            configs.append(config)
            return _Obj(text='{"ok": true}')

        async def generate_content_stream(self, *, model, contents, config=None):
            configs.append(config)

            async def _gen():
                yield _Obj(text="hi")

            return _gen()

    monkeypatch.setattr(gemini_module.genai, "Client", lambda api_key: _Obj(aio=_Obj(models=_Models())))
    return configs


def _level(config) -> str | None:
    thinking = config.thinking_config
    return None if thinking is None else thinking.thinking_level.value


async def test_default_thinking_level_is_low(monkeypatch):
    configs = _capture(monkeypatch)
    client = GeminiClient(make_settings(gemini_api_key="k1"))

    await client.generate_json(GeminiTask.SUMMARY, "p", {"type": "object"}, lambda d: d)
    stream = await client.open_text_stream(GeminiTask.ASSISTANT, "p")
    [piece async for piece in stream]

    assert [_level(c) for c in configs] == ["LOW", "LOW"]


async def test_thinking_level_per_task(monkeypatch):
    configs = _capture(monkeypatch)
    client = GeminiClient(make_settings(gemini_api_key="k1", gemini_thinking_layout="medium", gemini_thinking_tone=""))

    await client.generate_json(GeminiTask.LAYOUT, "p", {"type": "object"}, lambda d: d)
    await client.generate_json(GeminiTask.TONE, "p", {"type": "object"}, lambda d: d)

    # 빈 값은 설정을 보내지 않아 모델 기본값을 쓴다.
    assert [_level(c) for c in configs] == ["MEDIUM", None]


def test_thinking_level_accepts_upper_case_and_rejects_unknown():
    assert make_settings(gemini_api_key="k1", gemini_thinking_summary=" HIGH ").gemini_thinking_summary == "high"
    with pytest.raises(ValidationError):
        make_settings(gemini_api_key="k1", gemini_thinking_summary="max")
