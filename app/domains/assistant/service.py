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
from datetime import date, datetime, timedelta, timezone

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
# 한국은 서머타임이 없어 고정 +9시간이면 된다(윈도우·slim 이미지에는 시간대 데이터가 없을 수 있다).
_KST = timezone(timedelta(hours=9))

_TYPE_LABELS = {"AGENDA": "안건", "KEEP": "유지", "PROBLEM": "문제", "TRY": "시도"}
# 영어 상태값을 넘기면 답변에 TODO·TIRED 같은 값이 그대로 보인다. 화면에 쓰는 말로 바꿔 넘긴다.
_TASK_STATUS_LABELS = {"TODO": "할 일", "IN_PROGRESS": "진행 중", "REVIEW": "검토 중", "DONE": "완료"}
_MOOD_LABELS = {"VERY_GOOD": "아주 좋음", "GOOD": "좋음", "NORMAL": "보통", "TIRED": "피곤함", "EXHAUSTED": "지침"}

_SYSTEM = (
    "너는 팀 협업 방의 AI 어시스턴트다. "
    "아래 방 데이터(아이디어 카드, 업무, 진행 중인 투표, 오늘 기분)를 근거로 답한다.\n"
    "답하는 방법:\n"
    "- 우선순위·추천·판단을 물으면 피하지 말고 방 데이터를 엮어 판단한다. 예를 들어 문제 카드와 관련된 시도 카드, "
    "업무 진행 상태, 팀원 기분을 함께 보고 '~로 보아 ~가 먼저로 보입니다'처럼 근거를 밝혀 답한다. "
    "이런 판단 답에만 끝에 '최종 결정은 팀이 해요' 한 문장을 붙인다. "
    "개수·목록·사람·날짜처럼 사실을 묻는 답에는 붙이지 않는다.\n"
    "- 방 데이터에 전혀 없는 사실(매출, 외부 정보, 다른 방 이야기 등)은 "
    "'방 데이터로는 알 수 없다'고 말하고 지어내지 않는다.\n"
    "- 방 데이터가 '(방에 아직 데이터가 없다)'이면 어떤 질문이든 "
    "'아직 방에 카드·업무·투표·기분 데이터가 없어 답할 수 없어요. 데이터가 쌓인 뒤 다시 물어봐 주세요.'라고 안내한다.\n"
    "- 일반 지식·용어 설명, 서비스 사용법, 잡담처럼 방 데이터와 관계없는 질문에만 "
    "'이 방의 카드·업무·투표·기분 데이터로만 답할 수 있어요'라고 짧게 안내하고, "
    "대신 물어볼 만한 질문 예시를 하나 든다. 인사에는 짧게 인사하고 같은 안내를 한다. "
    "방 데이터로 답한 질문에는 이 안내를 붙이지 않는다.\n"
    "- 사람: 카드 작성자는 '작성', 업무 담당자는 '담당'에 적힌 이름만 쓴다. 이름을 추측하지 않는다. "
    "'담당자 없음', '나간 멤버'는 그대로 쓴다. 투표·기분은 누가 했는지 데이터에 없으므로 모른다고 한다.\n"
    "- 날짜: 마감까지 남은 날·지난 날은 업무 옆에 적힌 값을 그대로 쓰고 직접 계산하지 않는다. "
    "'마감 임박'은 남은 날이 3일 이하인 미완료 업무다.\n"
    "- 개수: 제목 옆 '총 N장/건'과 유형별 개수를 그대로 쓴다.\n"
    "- 질문이 영어여도 답은 항상 한국어로 쓴다. 답은 짧고 읽기 쉬운 Markdown 으로 쓴다. "
    "영어 상태값, card_id·task_id·vote_id 같은 내부 표기와 번호는 본문에 쓰지 않고 카드·업무 제목으로 가리킨다.\n"
    "- 답에 실제로 쓴 카드·업무·투표만 답변 맨 끝 줄에 [[card:ID]] [[task:ID]] [[vote:ID]] 형식으로 붙인다.\n"
    + DATA_RULE
)


def _today(context: AssistantContext) -> date:
    """Spring 이 보낸 오늘(한국 날짜). 없으면(예전 Spring) 한국 시간으로 직접 구한다."""
    if context.today:
        try:
            return date.fromisoformat(context.today)
        except ValueError:
            logger.warning("today 형식 오류: %s", context.today)
    return datetime.now(_KST).date()


def _due_text(due: str | None, status: str, today: date) -> str:
    """마감일을 사람이 읽는 말로 바꾼다. AI 에게 날짜 계산을 맡기면 자주 틀린다."""
    if not due:
        return "마감일 없음"
    try:
        days = (date.fromisoformat(due) - today).days
    except ValueError:
        return f"마감 {due}"
    if status == "DONE":
        return f"마감 {due}"
    if days < 0:
        return f"마감 {due}, {-days}일 지남"
    if days == 0:
        return f"마감 {due}, 오늘 마감"
    return f"마감 {due}, {days}일 남음"


def _context_text(context: AssistantContext) -> str:
    today = _today(context)
    parts = [f"## 오늘\n{today.isoformat()}"]
    cards = context.cards[:_MAX_CARDS]
    if cards:
        # 개수 질문은 AI 가 직접 세면 틀리기 쉬워 미리 센 값을 함께 준다.
        by_type = Counter(_TYPE_LABELS.get(c.type, c.type) for c in context.cards)
        summary = ", ".join(f"{label} {n}장" for label, n in by_type.most_common())
        lines = []
        for c in cards:
            body = clip(c.content, _CARD_CONTENT_LIMIT)
            label = _TYPE_LABELS.get(c.type, c.type)
            writer = f" (작성: {c.writer})" if c.writer else ""
            lines.append(f"card_id={c.id} [{label}] {c.title}" + (f": {body}" if body else "") + writer)
        parts.append(f"## 아이디어 카드 (총 {len(context.cards)}장: {summary})\n" + "\n".join(lines))
    tasks = context.tasks[:_MAX_TASKS]
    if tasks:
        by_status = Counter(_TASK_STATUS_LABELS.get(t.status, t.status) for t in context.tasks)
        summary = ", ".join(f"{label} {n}건" for label, n in by_status.most_common())
        lines = []
        for t in tasks:
            status = _TASK_STATUS_LABELS.get(t.status, t.status)
            assignee = f" / 담당: {t.assignee}" if t.assignee else ""
            lines.append(f"task_id={t.id} [{status}] {t.title}{assignee} / {_due_text(t.due_date, t.status, today)}")
        parts.append(f"## 업무 (총 {len(context.tasks)}건: {summary})\n" + "\n".join(lines))
    votes = context.votes[:_MAX_VOTES]
    if votes:
        parts.append(
            f"## 진행 중인 투표 (총 {len(context.votes)}건)\n" + "\n".join(f"vote_id={v.id} {v.title}" for v in votes)
        )
    if context.moods:
        counts = Counter(_MOOD_LABELS.get(m.mood, m.mood) for m in context.moods)
        parts.append("## 오늘 기분\n" + ", ".join(f"{mood} {n}명" for mood, n in counts.most_common()))
    if len(parts) == 1:
        parts.append("(방에 아직 데이터가 없다)")
    return "\n\n".join(parts)


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
