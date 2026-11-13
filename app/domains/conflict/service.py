"""충돌 감지. 새 카드가 임베딩으로 가까운 후보 카드와 서로 반대되는 주장인지 판정한다."""

from pydantic import BaseModel

from app.clients.gemini import GeminiClient, GeminiTask
from app.domains.common import DATA_RULE, clip, data_block
from app.domains.conflict.schemas import (
    ConflictCard,
    ConflictDetectRequest,
    ConflictDetectResponse,
    ConflictItem,
)

# card_conflict.reason VARCHAR(500)
_REASON_LIMIT = 500
_CONTENT_LIMIT = 500

_SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"card_id": {"type": "integer"}, "reason": {"type": "string"}},
                "required": ["card_id", "reason"],
            },
        }
    },
    "required": ["conflicts"],
}

_SYSTEM = (
    "너는 팀 아이디어 보드에서 서로 부딪히는 의견을 찾는 역할이다. "
    "충돌은 두 카드가 같은 대상에 대해 반대 방향을 주장해서 둘 다 채택하기 어려운 경우만이다. "
    "주제만 비슷하거나, 서로 보완하거나, 같은 말을 다르게 한 것은 충돌이 아니다. 애매하면 충돌로 보지 않는다. "
    "reason 은 무엇과 무엇이 부딪히는지 한두 문장으로 쓴다. 충돌이 없으면 빈 배열을 준다. "
    + DATA_RULE
)


class _Item(BaseModel):
    card_id: int
    reason: str = ""


class _Out(BaseModel):
    conflicts: list[_Item]


def _line(card: ConflictCard) -> str:
    body = clip(card.content, _CONTENT_LIMIT)
    return f"card_id={card.id} | {card.title}" + (f" | {body}" if body else "")


async def detect_conflicts(gemini: GeminiClient, request: ConflictDetectRequest) -> ConflictDetectResponse:
    candidates = [c for c in request.candidates if c.id != request.card.id]
    if not candidates:
        return ConflictDetectResponse(conflicts=[])

    prompt = (
        "기준 카드:\n"
        + data_block(_line(request.card))
        + "\n\n후보 카드:\n"
        + data_block("\n".join(_line(c) for c in candidates))
        + "\n\n기준 카드와 충돌하는 후보 카드만 골라라."
    )
    out = await gemini.generate_json(
        GeminiTask.CONFLICT, prompt, _SCHEMA, _Out.model_validate, system=_SYSTEM, temperature=0.0
    )

    # 후보에 없는 ID(지어낸 ID)와 중복은 버린다. Spring 이 그대로 저장하기 때문이다.
    allowed = {c.id for c in candidates}
    seen: set[int] = set()
    result = []
    for item in out.conflicts:
        if item.card_id in allowed and item.card_id not in seen:
            seen.add(item.card_id)
            reason = clip(item.reason, _REASON_LIMIT) or "두 카드의 주장이 서로 반대됩니다."
            result.append(ConflictItem(card_id=item.card_id, reason=reason))
    return ConflictDetectResponse(conflicts=result)
