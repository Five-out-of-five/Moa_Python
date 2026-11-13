"""회의 요약. 보드의 아이디어 카드를 주요 의견·합의된 내용·실행 과제 후보로 정리한다(요구사항 67)."""

import logging

from pydantic import BaseModel

from app.clients.gemini import GeminiClient, GeminiTask
from app.core.errors import AiErrorCode, AiException
from app.domains.common import DATA_RULE, clip, data_block
from app.domains.summary.schemas import SummaryRequest, SummaryResponse

logger = logging.getLogger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {"content": {"type": "string"}},
    "required": ["content"],
}

_TYPE_LABELS = {"AGENDA": "안건", "KEEP": "유지할 점", "PROBLEM": "문제점", "TRY": "시도할 점"}

# 카드 하나가 프롬프트를 독점하지 않게 내용 길이를 제한한다.
_CARD_CONTENT_LIMIT = 500

# 요구사항 67: "주요 의견, 합의된 내용, 도출된 실행 과제 후보를 정리한다." 응답은 Markdown 이다(API 134).
_SECTIONS = ("## 주요 의견", "## 합의된 내용", "## 실행 과제 후보")

_SYSTEM = (
    "너는 팀 회고·회의 보드의 요약 담당이다. 카드에 없는 사실을 만들지 않는다.\n"
    "아래 세 제목을 이 순서대로 쓰는 Markdown 으로 정리한다. 제목 아래는 '- ' 로 시작하는 짧은 문장 목록이다.\n"
    "## 주요 의견: 팀이 낸 의견과 문제 제기의 핵심. 같은 뜻의 카드는 하나로 묶는다.\n"
    "## 합의된 내용: 계속 유지하기로 한 것(유지할 점)과, 여러 카드가 같은 방향을 가리켜 사실상 정해진 것만 쓴다. "
    "의견이 갈리거나 한 사람만 낸 것은 합의로 쓰지 않는다. 없으면 '- 아직 합의된 내용이 없습니다.' 한 줄만 쓴다.\n"
    "## 실행 과제 후보: 시도할 점과 문제점에서 나온, 바로 할 수 있는 행동을 '무엇을 한다' 꼴로 쓴다. "
    "카드에 없는 담당자나 기한은 붙이지 않는다. 없으면 '- 도출된 실행 과제가 없습니다.' 한 줄만 쓴다.\n"
    "세 제목 말고 다른 제목이나 머리말·맺음말은 쓰지 않는다. " + DATA_RULE
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
    # 넘치면 뒤를 잘라야 해서 마지막 제목(실행 과제)이 잘린다. 목표를 한도보다 낮게 잡아 여유를 둔다.
    target = request.max_length * 8 // 10
    prompt = (
        f"아래 카드 {len(request.cards)}건을 요약한다. 제목과 기호를 포함해 {target}자 안팎, "
        f"절대 {request.max_length}자를 넘기지 않는다.\n\n" + data_block(_format_cards(request))
    )
    out = await gemini.generate_json(
        GeminiTask.SUMMARY, prompt, _SCHEMA, _Out.model_validate, system=_SYSTEM, temperature=0.3
    )
    content = clip(out.content, request.max_length)
    if not content:
        # 빈 요약을 성공으로 돌려주면 Spring 이 빈 글을 저장한다.
        raise AiException(AiErrorCode.LLM_RESPONSE_INVALID, "요약이 비었습니다.")
    missing = [s for s in _SECTIONS if s not in content]
    if missing:
        # 형식이 조금 어긋나도 내용은 쓸 만하므로 실패로 돌리지 않는다. 자주 보이면 프롬프트를 손본다.
        logger.info("요약에 빠진 제목: %s", ", ".join(missing))
    return SummaryResponse(content=content)
