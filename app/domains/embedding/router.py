"""임베딩. Spring 이 받아 content_embedding 에 저장하고, 가까운 카드를 찾아 충돌 감지에 넘긴다."""

from fastapi import APIRouter, Depends

from app.clients.gemini import GeminiClient, GeminiTask, get_gemini_client
from app.domains.embedding.schemas import EmbeddingRequest, EmbeddingResponse

router = APIRouter(tags=["embedding"])


@router.post("/embeddings", response_model=EmbeddingResponse)
async def create_embedding(
    request: EmbeddingRequest, gemini: GeminiClient = Depends(get_gemini_client)
) -> EmbeddingResponse:
    vector = await gemini.embed(request.text)
    return EmbeddingResponse(embedding=vector, model=gemini.model_for(GeminiTask.EMBEDDING))
