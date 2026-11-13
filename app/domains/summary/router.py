from fastapi import APIRouter, Depends

from app.clients.gemini import GeminiClient, get_gemini_client
from app.domains.summary.schemas import SummaryRequest, SummaryResponse
from app.domains.summary.service import summarize

router = APIRouter(tags=["summary"])


@router.post("/summaries", response_model=SummaryResponse)
async def create_summary(
    request: SummaryRequest, gemini: GeminiClient = Depends(get_gemini_client)
) -> SummaryResponse:
    return await summarize(gemini, request)
