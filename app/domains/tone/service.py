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
        "원래 말투는 반드시 그대로 둔다. 원문이 존댓말(~요, ~습니다)이면 제안도 존댓말, 반말이면 반말이다. "
        "짧은 말투, 구어체, 이모티콘은 문제로 보지 않는다."
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
    "너는 팀 협업 서비스의 말투 도우미다. 아이디어 카드와 채팅 메시지를 등록하기 전에 표현을 점검한다.\n"
    "지킬 것:\n"
    "- 메시지가 요청하는 일(무엇을 해 달라는지), 사실·숫자·이름·링크는 그대로 둔다. 내용을 보태거나 빼지 않는다.\n"
    "- 공격적·무례한 표현(비난, 깎아내림, 명령조, 비꼼)이 있으면 어조 자체를 바꾼다. "
    "띄어쓰기나 맞춤법만 고치거나 끝에 '줘'만 붙이고 공격적인 어조를 남기면 다듬은 것이 아니다.\n"
    "- 사람을 탓하는 말('너 맨날', '또', '제대로 좀')은 빼고, 바라는 행동을 부탁하는 말로 바꾼다.\n"
    "- 비꼼(겉으로는 칭찬이지만 비꼬는 말, 빈정거리는 '^^')은 그대로 두지 말고 빼서 "
    "바라는 행동을 부탁하는 말로 바꾼다.\n"
    "- 문장 부호 하나, 맞춤법 한 글자처럼 사소한 차이만 있으면 고치지 않는다"
    "(제안이 너무 잦으면 사용자가 기능을 끈다).\n"
    "기준에 걸리지 않으면 needs_change 를 false, suggestion 을 빈 문자열로 둔다. "
    "고칠 게 있으면 needs_change 를 true, suggestion 에 고친 메시지 전체를 쓴다. 설명은 붙이지 않는다.\n"
    "예) 표현만 다듬기: '이거 왜 이렇게 했음? 다시 해와' → '이거 왜 이렇게 했는지 궁금해. 다시 해 줄 수 있어?'\n"
    "예) 표현만 다듬기: '이건좀아닌듯 다시생각해보셈' → '이건 좀 아닌 것 같아. 다시 생각해 보면 좋겠어.'\n"
    "예) 표현만 다듬기: '너 또 늦었잖아 제대로 좀 해' → '이번엔 일정 맞춰 주면 좋겠어.'\n"
    "예) 표현만 다듬기(존댓말 유지): '대체 언제 하실 거예요? 몇 번을 말해요' → "
    "'언제쯤 가능하실까요? 다시 한번 확인 부탁드려요.'\n"
    "예) 표현만 다듬기(비꼼, 존댓말 유지): '와 자료 정말 꼼꼼하시네요^^ 또 빈칸이네' → "
    "'자료에 빈 곳이 있어서요. 채워 주시면 좋겠어요.'\n"
    "예) 정중하게: '빨리 고쳐' → '빠르게 수정해 주시면 감사하겠습니다.'\n"
    + DATA_RULE
    # 공통 규칙의 '한국어로 쓴다'는 AI 가 직접 답할 때의 규칙이다. 여기서는 사용자 글을 다듬으므로 원문 언어를 지킨다.
    + " 단, suggestion 은 원문과 같은 언어로 쓴다. 영어 메시지는 영어로 다듬고 번역하지 않는다."
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
