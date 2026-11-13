"""엔드포인트 계약. Spring 이 보내는 모양 그대로 보내고, Spring 이 읽는 모양으로 오는지 본다."""

import json

import pytest

from app.clients.gemini import GeminiClient, get_gemini_client
from app.domains.assistant.schemas import AssistantRequest
from app.domains.assistant.service import sse_events
from app.domains.layout.grid import violations
from app.domains.layout.schemas import WidgetPlacement
from app.main import app
from tests.conftest import make_settings
from tests.fakes import FakeApiError, install

ALL = ["MOOD", "PROGRESS", "IDEA_BOARD", "TASK_BOARD", "VOTE", "CATCHUP_BRIEFING", "MEDIATION"]


def test_health_is_public(keyed_client):
    assert keyed_client.get("/health").json()["status"] == "UP"


def test_internal_key_is_checked_when_set(keyed_client):
    assert keyed_client.post("/v1/embeddings", json={"text": "a"}).status_code == 401
    wrong = keyed_client.post("/v1/embeddings", json={"text": "a"}, headers={"X-Internal-Api-Key": "nope"})
    assert wrong.status_code == 401
    ok = keyed_client.post("/v1/embeddings", json={"text": "a"}, headers={"X-Internal-Api-Key": "secret"})
    assert ok.status_code == 200


def test_tone_check(client):
    body = client.post("/v1/tone-checks", json={"text": "이거 왜 이럼", "toneMode": "POLITE"}).json()
    assert set(body) == {"needsChange", "suggestion"}
    assert body["needsChange"] is True


def test_tone_off_skips_ai(client):
    body = client.post("/v1/tone-checks", json={"text": "안녕", "toneMode": "OFF"}).json()
    assert body == {"needsChange": False, "suggestion": None}


def test_summary(client):
    cards = [{"id": i, "type": "KEEP", "title": f"t{i}", "content": "null"} for i in range(3)]
    body = client.post("/v1/summaries", json={"maxLength": 1000, "cards": cards}).json()
    assert body["content"]


def test_embedding(client):
    body = client.post("/v1/embeddings", json={"text": "제목\n내용"}).json()
    assert len(body["embedding"]) == 768
    assert body["model"]


def test_conflict_detect_filters_to_candidates(client):
    request = {
        "card": {"id": 1, "title": "a", "content": "null"},
        "candidates": [{"id": 2, "title": "b", "content": "x"}, {"id": 1, "title": "self", "content": "y"}],
    }
    body = client.post("/v1/conflicts/detect", json=request).json()
    assert [c["cardId"] for c in body["conflicts"]] == [2]
    assert body["conflicts"][0]["reason"]


def test_conflict_without_candidates_skips_ai(client):
    body = client.post("/v1/conflicts/detect", json={"card": {"id": 1, "title": "a"}, "candidates": []}).json()
    assert body == {"conflicts": []}


def test_compromise_respects_column_limits(client):
    request = {"cardType": "TRY", "cardA": {"title": "a", "content": "null"}, "cardB": {"title": "b", "content": "y"}}
    body = client.post("/v1/compromises", json=request).json()
    assert 0 < len(body["title"]) <= 100
    assert len(body["content"]) <= 1000


def test_layout_passes_spring_rules(client):
    body = client.post(
        "/v1/layouts/recommend", json={"purpose": "회고", "widgetTypes": ALL, "gridColumns": 12}
    ).json()
    widgets = [WidgetPlacement.model_validate(w) for w in body["widgets"]]
    assert widgets
    assert violations(widgets, 12) == []
    assert set(body["widgets"][0]) == {"widgetType", "x", "y", "w", "h"}


def test_validation_error_is_400(client):
    response = client.post("/v1/tone-checks", json={})
    assert response.status_code == 400
    assert response.json()["code"] == "AI_INVALID_REQUEST"


def _assistant_body():
    return {
        "roomId": 1,
        "question": "요약해줘",
        "context": {
            "cards": [{"id": 7, "type": "KEEP", "title": "카드7", "content": "null"}],
            "tasks": [{"id": 3, "title": "업무", "status": "TODO"}],
            "votes": [],
            "moods": [{"mood": "GOOD"}],
        },
    }


def _events(text: str) -> list[dict]:
    return [json.loads(line[len("data:"):]) for line in text.splitlines() if line.startswith("data:")]


def test_assistant_stream_sends_deltas_then_references(client):
    with client.stream("POST", "/v1/assistant/stream", json=_assistant_body()) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response.read().decode())
    assert all("delta" in e for e in events[:-1])
    answer = "".join(e["delta"] for e in events[:-1])
    assert "[[" not in answer and not answer.endswith("\n")
    assert events[-1] == {"references": {"cards": [{"id": 7, "title": "카드7"}], "tasks": [], "votes": []}}


@pytest.mark.usefixtures("no_sleep")
def test_assistant_failure_before_stream_is_json_error(monkeypatch):
    install(monkeypatch, {"k1": [FakeApiError(429)]})
    failing = GeminiClient(make_settings(gemini_api_key="k1"))
    app.dependency_overrides[get_gemini_client] = lambda: failing
    from fastapi.testclient import TestClient

    try:
        with TestClient(app) as test_client:
            response = test_client.post("/v1/assistant/stream", json=_assistant_body())
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")


async def test_assistant_failure_mid_stream_breaks_connection():
    async def pieces():
        yield "앞부분"
        raise ConnectionError("lost")

    request = AssistantRequest.model_validate(_assistant_body())
    seen = []
    with pytest.raises(ConnectionError):
        async for event in sse_events(pieces(), request):
            seen.append(event)
    # 근거를 보내지 않고 끊는다. Spring 은 이걸 PARTIAL 로 저장한다.
    assert seen == ['data: {"delta": "앞부분"}\n\n']
