"""대시보드 AI 구성. 방의 목적에 맞는 위젯 배치를 추천한다."""

import logging

from pydantic import BaseModel

from app.clients.gemini import GeminiClient, GeminiTask
from app.domains.common import DATA_RULE, clip, data_block
from app.domains.layout.grid import MAX_HEIGHT, min_size, repair, violations
from app.domains.layout.schemas import LayoutRecommendRequest, LayoutRecommendResponse, WidgetPlacement

logger = logging.getLogger(__name__)

_REASON_LIMIT = 300

_DESCRIPTIONS = {
    "MOOD": "오늘 팀원들의 기분 체크",
    "PROGRESS": "업무 진행률 요약",
    "IDEA_BOARD": "아이디어 카드 보드(안건·유지·문제·시도). 회의·회고의 중심",
    "TASK_BOARD": "업무 칸반 보드",
    "VOTE": "진행 중인 투표",
    "CATCHUP_BRIEFING": "자리를 비운 사이 바뀐 내용 브리핑",
    "MEDIATION": "서로 부딪히는 의견 중재",
}

_SYSTEM = (
    "너는 팀 협업 대시보드 배치 도우미다. 방의 목적에 꼭 필요한 위젯만 골라 배치한다. "
    "목적과 관계없는 위젯은 넣지 않는다. 중요한 위젯일수록 왼쪽 위에 크게 둔다. "
    "reason 은 왜 이렇게 배치했는지 두 문장 이내로 쓴다. " + DATA_RULE
)


class _Item(BaseModel):
    widget_type: str
    x: int
    y: int
    w: int
    h: int


class _Out(BaseModel):
    widgets: list[_Item]
    reason: str = ""


def _schema(types: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "widgets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "widget_type": {"type": "string", "enum": types},
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "w": {"type": "integer"},
                        "h": {"type": "integer"},
                    },
                    "required": ["widget_type", "x", "y", "w", "h"],
                },
            },
            "reason": {"type": "string"},
        },
        "required": ["widgets", "reason"],
    }


def _rules(request: LayoutRecommendRequest) -> str:
    lines = []
    for kind in request.widget_types:
        min_w, min_h = min_size(kind)
        lines.append(f"- {kind}: {_DESCRIPTIONS.get(kind, kind)} (최소 {min_w}x{min_h})")
    return (
        f"격자는 가로 {request.grid_columns}칸이다. 좌표 x·y 는 0부터, x + w <= {request.grid_columns}, "
        f"h <= {MAX_HEIGHT}. 위젯끼리 겹치지 않는다. 같은 위젯은 한 번만 쓴다.\n쓸 수 있는 위젯:\n" + "\n".join(lines)
    )


async def recommend(gemini: GeminiClient, request: LayoutRecommendRequest) -> LayoutRecommendResponse:
    types = list(dict.fromkeys(request.widget_types))
    prompt = _rules(request) + "\n\n방의 목적:\n" + data_block(request.purpose)
    out = await gemini.generate_json(
        GeminiTask.LAYOUT, prompt, _schema(types), _Out.model_validate, system=_SYSTEM, temperature=0.3
    )

    raw = [WidgetPlacement(**item.model_dump()) for item in out.widgets]
    widgets = repair(raw, types, request.grid_columns)
    if raw != widgets:
        # 얼마나 자주 고치는지 보려고 남긴다. 너무 잦으면 프롬프트를 손본다.
        logger.info("레이아웃 보정: %s", violations(raw, request.grid_columns) or "일부 위젯 제외")
    reason = clip(out.reason, _REASON_LIMIT) or "방의 목적에 맞춰 위젯을 배치했습니다."
    return LayoutRecommendResponse(widgets=widgets, reason=reason)
