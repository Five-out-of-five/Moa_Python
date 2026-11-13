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

_GOALS = {
    ToneMode.POLISH: (
        "공격적이거나 무례하거나 상대를 깎아내리는 표현이 있으면 뜻은 그대로 두고 부드럽게 바꾼다. "
        "반말·짧은 말투 자체는 문제로 보지 않는다."
    ),
    ToneMode.POLITE: (
        "존댓말이 아니거나 무례한 표현이 있으면 정중한 존댓말로 바꾼다. 이미 정중한 존댓말이면 바꾸지 않는다."
    ),
}

_SYSTEM = (
    "너는 팀 협업 채팅의 말투 도우미다. 메시지의 뜻·사실·숫자·이름은 바꾸지 않고 표현만 고친다. "
    "고칠 게 없으면 needs_change 를 false, suggestion 을 빈 문자열로 둔다. "
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
