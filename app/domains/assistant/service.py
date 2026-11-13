"""방 어시스턴트. 방의 카드·업무·투표·기분을 근거로 질문에 답하고 스트림으로 보낸다.

SSE 형식(docs/ai-server.md, Spring PythonAiServerAdapter.stream 이 읽는다):

    data: {"delta": "답변 조각"}
    data: {"references": {"cards": [...], "tasks": [...], "votes": [...]}}

답변 조각을 다 보낸 뒤 근거를 한 번 보내고 연결을 닫는다.
첫 조각 전 실패는 일반 에러(502/504)로 돌려준다(router 가 스트림을 열기 전에 기다린다).
첫 조각 뒤 실패는 연결을 끊는다. Spring 은 그때 받은 데까지 PARTIAL 로 저장한다.
"""

import json
import logging
from collections import Counter
from collections.abc import AsyncIterator

from app.clients.gemini import GeminiClient, GeminiTask
from app.domains.assistant.citations import CitationFilter
from app.domains.assistant.schemas import AssistantContext, AssistantRequest
from app.domains.common import DATA_RULE, clip, data_block

logger = logging.getLogger(__name__)

# 프롬프트가 너무 길어지지 않게 자른다. 최신순으로 온다고 보고 앞에서부터 쓴다.
_MAX_CARDS = 150
_MAX_TASKS = 150
_MAX_VOTES = 50
_CARD_CONTENT_LIMIT = 200

_TYPE_LABELS = {"AGENDA": "안건", "KEEP": "유지", "PROBLEM": "문제", "TRY": "시도"}

_SYSTEM = (
    "너는 팀 협업 방의 AI 어시스턴트다. 아래 방 데이터만 근거로 답한다. 데이터에 없는 내용은 "
    "추측하지 말고 방 데이터로는 알 수 없다고 말한다. 답은 짧고 읽기 쉬운 Markdown 으로 쓴다. "
    "근거로 쓴 항목은 답변 맨 끝 줄에 [[card:ID]] [[task:ID]] [[vote:ID]] 형식으로만 붙인다. "
    "본문에는 ID 를 쓰지 않는다. " + DATA_RULE
)


def _context_text(context: AssistantContext) -> str:
    parts = []
    cards = context.cards[:_MAX_CARDS]
    if cards:
        lines = []
        for c in cards:
            body = clip(c.content, _CARD_CONTENT_LIMIT)
            label = _TYPE_LABELS.get(c.type, c.type)
            lines.append(f"card_id={c.id} [{label}] {c.title}" + (f": {body}" if body else ""))
        parts.append("## 아이디어 카드\n" + "\n".join(lines))
    tasks = context.tasks[:_MAX_TASKS]
    if tasks:
        parts.append("## 업무\n" + "\n".join(f"task_id={t.id} [{t.status}] {t.title}" for t in tasks))
    votes = context.votes[:_MAX_VOTES]
    if votes:
        parts.append("## 진행 중인 투표\n" + "\n".join(f"vote_id={v.id} {v.title}" for v in votes))
    if context.moods:
        counts = Counter(m.mood for m in context.moods)
        parts.append("## 오늘 기분\n" + ", ".join(f"{mood} {n}명" for mood, n in counts.most_common()))
    return "\n\n".join(parts) if parts else "(방에 아직 데이터가 없다)"


def build_references(cited: dict[str, list[int]], context: AssistantContext) -> dict:
    """AI 가 표시한 ID 중 실제 방 데이터에 있는 것만 남긴다. 지어낸 ID 는 버린다."""
    titles = {
        "card": {c.id: c.title for c in context.cards},
        "task": {t.id: t.title for t in context.tasks},
        "vote": {v.id: v.title for v in context.votes},
    }
    return {
        f"{kind}s": [{"id": i, "title": titles[kind][i]} for i in cited[kind] if i in titles[kind]]
        for kind in ("card", "task", "vote")
    }


def _event(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def open_answer(gemini: GeminiClient, request: AssistantRequest) -> AsyncIterator[str]:
    """첫 조각까지 받아 둔 텍스트 스트림. 여기서 실패하면 아직 응답 전이다."""
    prompt = "방 데이터:\n" + data_block(_context_text(request.context)) + "\n\n질문:\n" + data_block(request.question)
    return await gemini.open_text_stream(GeminiTask.ASSISTANT, prompt, system=_SYSTEM, temperature=0.4)


async def sse_events(pieces: AsyncIterator[str], request: AssistantRequest) -> AsyncIterator[str]:
    citations = CitationFilter()
    try:
        async for piece in pieces:
            text = citations.feed(piece)
            if text:
                yield _event({"delta": text})
    except Exception:
        # 다시 던져 연결을 비정상 종료시킨다. 정상 종료로 보이면 Spring 이 잘린 답을 COMPLETED 로 저장한다.
        logger.warning("어시스턴트 스트림이 중간에 끊겼다 (room=%s)", request.room_id, exc_info=True)
        raise
    rest = citations.flush()
    if rest:
        yield _event({"delta": rest})
    yield _event({"references": build_references(citations.cited, request.context)})
