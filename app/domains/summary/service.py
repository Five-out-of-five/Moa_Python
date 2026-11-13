"""회차 요약. 보드의 아이디어 카드를 유형별로 묶어 정리한다."""

from pydantic import BaseModel

from app.clients.gemini import GeminiClient, GeminiTask
from app.core.errors import AiErrorCode, AiException
from app.domains.common import DATA_RULE, clip, data_block
from app.domains.summary.schemas import SummaryRequest, SummaryResponse

_SCHEMA = {
    "type": "object",
    "properties": {"content": {"type": "string"}},
    "required": ["content"],
}

_TYPE_LABELS = {"AGENDA": "안건", "KEEP": "유지할 점", "PROBLEM": "문제점", "TRY": "시도할 점"}

# 카드 하나가 프롬프트를 독점하지 않게 내용 길이를 제한한다.
_CARD_CONTENT_LIMIT = 500

_SYSTEM = (
    "너는 팀 회고·회의 보드의 요약 담당이다. 카드에 없는 사실을 만들지 않는다. "
    "같은 뜻의 카드는 하나로 묶고, 유형(안건·유지할 점·문제점·시도할 점)별로 핵심만 짧은 문장으로 정리한다. "
    "카드가 없는 유형은 쓰지 않는다. 결정되지 않은 것을 결정된 것처럼 쓰지 않는다. "
    + DATA_RULE
)


class _Out(BaseModel):
    content: str


def _format_cards(request: SummaryRequest) -> str:
    lines = []
    for card in request.cards:
        label = _TYPE_LABELS.get(card.type, card.type)
        body = clip(card.content, _CARD_CONTENT_LIMIT)
        lines.append(f"- [{label}] {card.title}" + (f": {body}" if body else ""))
    return "\n".join(lines)


async def summarize(gemini: GeminiClient, request: SummaryRequest) -> SummaryResponse:
    prompt = (
        f"아래 카드 {len(request.cards)}건을 {request.max_length}자 이내로 요약한다. "
        "줄바꿈으로 유형을 나눈다.\n\n" + data_block(_format_cards(request))
    )
    out = await gemini.generate_json(
        GeminiTask.SUMMARY, prompt, _SCHEMA, _Out.model_validate, system=_SYSTEM, temperature=0.3
    )
    content = clip(out.content, request.max_length)
    if not content:
        # 빈 요약을 성공으로 돌려주면 Spring 이 빈 글을 저장한다.
        raise AiException(AiErrorCode.LLM_RESPONSE_INVALID, "요약이 비었습니다.")
    return SummaryResponse(content=content)
