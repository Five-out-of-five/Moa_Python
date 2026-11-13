from fastapi import APIRouter, Depends

from app.clients.gemini import GeminiClient, get_gemini_client
from app.domains.layout.schemas import LayoutRecommendRequest, LayoutRecommendResponse
from app.domains.layout.service import recommend

router = APIRouter(tags=["layout"])


@router.post("/layouts/recommend", response_model=LayoutRecommendResponse)
async def recommend_layout(
    request: LayoutRecommendRequest, gemini: GeminiClient = Depends(get_gemini_client)
) -> LayoutRecommendResponse:
    return await recommend(gemini, request)
