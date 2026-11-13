"""테스트 공통 설정.

app.main 은 import 할 때 설정을 읽는다. 로컬 .env(실제 키가 있을 수 있다)보다 앞서도록
환경변수를 먼저 고정한다. 환경변수는 .env 보다 우선한다.
"""

import os

os.environ.update(
    {
        "APP_ENV": "test",
        "GEMINI_API_KEY": "test-key",
        "AI_STUB_MODE": "false",
        "INTERNAL_API_KEY": "",
        "AI_STUB_FAIL_RATE": "0",
        "AI_STUB_DELAY_MS": "0",
    }
)

import asyncio  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.clients import gemini as gemini_module  # noqa: E402
from app.clients.gemini import GeminiClient, get_gemini_client  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402


def make_settings(**overrides) -> Settings:
    """.env 를 읽지 않는 설정."""
    return Settings(_env_file=None, **overrides)


@pytest.fixture
def no_sleep(monkeypatch):
    """재시도 대기를 없앤다. 테스트가 백오프만큼 느려지지 않게."""
    real_sleep = asyncio.sleep

    async def _sleep(seconds, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr(gemini_module.asyncio, "sleep", _sleep)


@pytest.fixture
def stub_client() -> GeminiClient:
    return GeminiClient(make_settings(ai_stub_mode=True, gemini_api_key=""))


@pytest.fixture
def client(stub_client):
    """스텁 Gemini 로 도는 앱."""
    app.dependency_overrides[get_gemini_client] = lambda: stub_client
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def keyed_client(stub_client):
    """INTERNAL_API_KEY 가 설정된 앱."""
    app.dependency_overrides[get_gemini_client] = lambda: stub_client
    app.dependency_overrides[get_settings] = lambda: make_settings(ai_stub_mode=True, internal_api_key="secret")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
