"""절충안. 충돌한 두 카드의 공통 목표를 살린 새 카드 초안을 만든다."""

from pydantic import BaseModel

from app.clients.gemini import GeminiClient, GeminiTask
from app.core.errors import AiErrorCode, AiException
from app.domains.common import DATA_RULE, clip, data_block
from app.domains.compromise.schemas import CompromiseCard, CompromiseRequest, CompromiseResponse

# compromise_draft.title VARCHAR(100), content VARCHAR(1000)
_TITLE_LIMIT = 100
_CONTENT_LIMIT = 1000

_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
    "required": ["title", "content"],
}

_TYPE_LABELS = {"AGENDA": "안건", "TRY": "시도할 점", "KEEP": "유지할 점", "PROBLEM": "문제점"}

_SYSTEM = (
    "너는 팀의 중재자다. 부딪히는 두 의견에서 각자 지키려는 목표를 찾고, 둘 다 받아들일 수 있는 "
    "현실적인 절충안을 하나 제안한다. 어느 한쪽 편을 들지 않는다. "
    "title 은 40자 이내 한 줄, content 는 무엇을 어떻게 할지 600자 이내로 쓴다. "
    + DATA_RULE
)


class _Out(BaseModel):
    title: str
    content: str


def _card(name: str, card: CompromiseCard) -> str:
    return f"{name}: {card.title}" + (f"\n{clip(card.content, 800)}" if card.content else "")


async def propose(gemini: GeminiClient, request: CompromiseRequest) -> CompromiseResponse:
    label = _TYPE_LABELS.get(request.card_type, request.card_type)
    prompt = (
        f"두 카드는 '{label}' 유형이다. 같은 유형의 새 카드로 쓸 절충안을 만들어라.\n\n"
        + data_block(_card("의견 A", request.card_a) + "\n\n" + _card("의견 B", request.card_b))
    )
    out = await gemini.generate_json(
        GeminiTask.COMPROMISE, prompt, _SCHEMA, _Out.model_validate, system=_SYSTEM, temperature=0.5
    )
    title = clip(out.title.replace("\n", " "), _TITLE_LIMIT)
    if not title:
        # compromise_draft.title 은 NOT NULL 이다.
        raise AiException(AiErrorCode.LLM_RESPONSE_INVALID, "절충안 제목이 비었습니다.")
    return CompromiseResponse(title=title, content=clip(out.content, _CONTENT_LIMIT))
