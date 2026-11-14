"""톤앤매너 검사. 채팅 메시지를 보내기 전에 표현을 다듬을지 판단한다."""

from pydantic import BaseModel

from app.clients.gemini import GeminiClient, GeminiTask
from app.domains.common import DATA_RULE, data_block
from app.domains.tone.schemas import ToneCheckRequest, ToneCheckResponse, ToneMode

_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_change": {"type": "boolean"},
        "suggestion": {"type": "string"},
    },
    "required": ["needs_change", "suggestion"],
}

# 요구사항 70: "공격적이거나 정돈되지 않은 문장이 감지되면 순화된 문장을 제안한다."
# 순화 강도는 '표현만 다듬기'(POLISH) / '정중하게'(POLITE) 다.
_GOALS = {
    ToneMode.POLISH: (
        "표현만 다듬는다. 다음 중 하나라도 있으면 고친다.\n"
        "1) 공격적이거나 무례하거나 상대를 깎아내리는 표현 → 뜻은 그대로 두고 부드럽게\n"
        "2) 정돈되지 않은 문장(뜻이 헷갈리는 비문, 두서없이 이어진 문장, 심한 오타·띄어쓰기) → 읽기 쉽게 정리\n"
        "원래 말투(반말·존댓말)는 바꾸지 않는다. 짧은 말투, 구어체, 이모티콘은 문제로 보지 않는다."
    ),
    ToneMode.POLITE: (
        "정중하게 바꾼다. 다음 중 하나라도 있으면 고친다.\n"
        "1) 존댓말이 아닌 문장 → 정중한 존댓말로\n"
        "2) 공격적이거나 무례한 표현 → 부드럽고 정중하게\n"
        "3) 정돈되지 않은 문장(뜻이 헷갈리는 비문, 두서없이 이어진 문장, 심한 오타·띄어쓰기) → 읽기 쉽게 정리\n"
        "이미 정중한 존댓말이고 정돈된 문장이면 바꾸지 않는다."
    ),
}

_SYSTEM = (
    "너는 팀 협업 서비스의 말투 도우미다. 아이디어 카드와 채팅 메시지를 등록하기 전에 표현을 점검한다. "
    "메시지의 뜻·사실·숫자·이름·링크는 바꾸지 않고 표현만 고친다. 내용을 보태거나 빼지 않는다.\n"
    "기준에 걸리지 않으면 needs_change 를 false, suggestion 을 빈 문자열로 둔다. "
    "문장 부호 하나, 맞춤법 한 글자처럼 사소한 차이만 있으면 고치지 않는다(제안이 너무 잦으면 사용자가 기능을 끈다).\n"
    "고칠 게 있으면 needs_change 를 true, suggestion 에 고친 메시지 전체를 쓴다. 설명은 붙이지 않는다. "
    + DATA_RULE
)


class _Out(BaseModel):
    needs_change: bool
    suggestion: str = ""


async def check_tone(gemini: GeminiClient, request: ToneCheckRequest) -> ToneCheckResponse:
    if request.tone_mode is ToneMode.OFF:
        return ToneCheckResponse(needs_change=False)

    prompt = f"기준: {_GOALS[request.tone_mode]}\n\n메시지:\n{data_block(request.text)}"
    out = await gemini.generate_json(
        GeminiTask.TONE, prompt, _SCHEMA, _Out.model_validate, system=_SYSTEM, temperature=0.2
    )

    suggestion = out.suggestion.strip()
    # "바꾸라"면서 같은 글을 주거나 빈 글을 주면 사용자에게 의미 없는 팝업이 뜬다.
    if not out.needs_change or not suggestion or suggestion == request.text:
        return ToneCheckResponse(needs_change=False)
    return ToneCheckResponse(needs_change=True, suggestion=suggestion)
