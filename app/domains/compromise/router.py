from fastapi import APIRouter, Depends

from app.clients.gemini import GeminiClient, get_gemini_client
from app.domains.compromise.schemas import CompromiseRequest, CompromiseResponse
from app.domains.compromise.service import propose

router = APIRouter(tags=["compromise"])


@router.post("/compromises", response_model=CompromiseResponse)
async def create_compromise(
    request: CompromiseRequest, gemini: GeminiClient = Depends(get_gemini_client)
) -> CompromiseResponse:
    return await propose(gemini, request)
