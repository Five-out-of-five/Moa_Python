from fastapi import APIRouter, Depends

from app.clients.gemini import GeminiClient, get_gemini_client
from app.domains.conflict.schemas import ConflictDetectRequest, ConflictDetectResponse
from app.domains.conflict.service import detect_conflicts

router = APIRouter(tags=["conflict"])


@router.post("/conflicts/detect", response_model=ConflictDetectResponse)
async def detect(
    request: ConflictDetectRequest, gemini: GeminiClient = Depends(get_gemini_client)
) -> ConflictDetectResponse:
    return await detect_conflicts(gemini, request)
