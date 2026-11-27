"""충돌 감지. 새 카드가 임베딩으로 가까운 후보 카드와 서로 반대되는 주장인지 판정한다."""

import re

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
    "reason 은 팀원 화면에 그대로 보이는 문장이다. 두 카드의 주장을 내용으로 짧게 인용해 무엇이 부딪히는지 "
    "한두 문장으로 쓴다. 두 의견은 내용으로만 가리킨다. '새로 올라온 의견', '비교할 의견', '기준 카드', '후보 카드', "
    "'card_id', 카드 번호 같은 구분 이름은 쓰지 않는다. "
    "예) '회의를 주 1회 하자는 의견과 격주로 하자는 의견은 회의 주기가 달라 함께 채택하기 어렵습니다.' "
    "충돌이 없으면 빈 배열을 준다. "
    + DATA_RULE
)


class _Item(BaseModel):
    card_id: int
    reason: str = ""


class _Out(BaseModel):
    conflicts: list[_Item]


# 프롬프트의 구분 이름이나 내부 표기가 reason 에 새어 나오면 팀원 화면에 그대로 보인다(2026-11-28 운영에서
# "…조율하자는 기준 카드의 실행 과제는…" 이 나옴). 프롬프트로 막고, 그래도 나오면 여기서 걷어 낸다.
_INTERNAL_ID = re.compile(r"\s*\(?`?card_id\s*[=:]?\s*\d+`?\)?")
# "카드 3장" 같은 개수 표현은 건드리지 않도록 '번' 이 붙은 것만 본다.
_NUMBERED_CARD = re.compile(r"\d+\s*번\s*카드|카드\s*\d+\s*번")
# 받침이 같은 말로 바꿔 뒤 조사(과/와, 은/는 …)가 그대로 맞게 한다.
_LABELS = {"새로 올라온 의견": "한쪽 의견", "비교할 의견": "다른 의견", "기준 카드": "카드", "후보 카드": "다른 카드"}
_LABEL = re.compile("|".join(map(re.escape, _LABELS)))
# '카드 12번은' 처럼 받침 있는 말을 '카드' 로 줄이면 조사가 어긋난다. '카드' 뒤 받침용 조사를 고친다.
_CARD_PARTICLE = re.compile(r"카드(과|은|을|이)(?=[\s.,!?)]|$)")
_VOWEL_PARTICLE = {"과": "와", "은": "는", "을": "를", "이": "가"}


def tidy_reason(reason: str) -> str:
    """reason 의 내부 표기를 지운다. 구분 이름은 내용을 가리키는 일반 말로 바꿔 문장이 끊기지 않게 한다."""
    text = _INTERNAL_ID.sub("", reason or "")
    text = _NUMBERED_CARD.sub("카드", text)
    text = _LABEL.sub(lambda m: _LABELS[m.group(0)], text)
    text = _CARD_PARTICLE.sub(lambda m: "카드" + _VOWEL_PARTICLE[m.group(1)], text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _line(card: ConflictCard) -> str:
    body = clip(card.content, _CONTENT_LIMIT)
    return f"card_id={card.id} | {card.title}" + (f" | {body}" if body else "")


async def detect_conflicts(gemini: GeminiClient, request: ConflictDetectRequest) -> ConflictDetectResponse:
    candidates = [c for c in request.candidates if c.id != request.card.id]
    if not candidates:
        return ConflictDetectResponse(conflicts=[])

    prompt = (
        "새로 올라온 의견:\n"
        + data_block(_line(request.card))
        + "\n\n비교할 의견:\n"
        + data_block("\n".join(_line(c) for c in candidates))
        + "\n\n새로 올라온 의견과 부딪히는 의견만 골라라."
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
            reason = clip(tidy_reason(item.reason), _REASON_LIMIT) or "두 카드의 주장이 서로 반대됩니다."
            result.append(ConflictItem(card_id=item.card_id, reason=reason))
    return ConflictDetectResponse(conflicts=result)
