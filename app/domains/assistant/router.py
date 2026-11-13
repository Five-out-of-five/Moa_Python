from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.clients.gemini import GeminiClient, get_gemini_client
from app.domains.assistant.schemas import AssistantRequest
from app.domains.assistant.service import open_answer, sse_events

router = APIRouter(tags=["assistant"])


@router.post("/assistant/stream")
async def assistant_stream(
    request: AssistantRequest, gemini: GeminiClient = Depends(get_gemini_client)
) -> StreamingResponse:
    # 첫 조각을 받을 때까지 여기서 기다린다. 실패하면 예외 처리기가 일반 JSON 에러로 돌려준다.
    pieces = await open_answer(gemini, request)
    return StreamingResponse(
        sse_events(pieces, request),
        media_type="text/event-stream",
        # 중간 프록시가 모았다가 한 번에 보내지 않게 한다.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
