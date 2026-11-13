from fastapi import APIRouter, Depends

from app.clients.gemini import GeminiClient, get_gemini_client
from app.domains.tone.schemas import ToneCheckRequest, ToneCheckResponse
from app.domains.tone.service import check_tone

router = APIRouter(tags=["tone"])


@router.post("/tone-checks", response_model=ToneCheckResponse)
async def tone_check(
    request: ToneCheckRequest, gemini: GeminiClient = Depends(get_gemini_client)
) -> ToneCheckResponse:
    return await check_tone(gemini, request)
