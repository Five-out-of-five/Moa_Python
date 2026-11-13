"""라우터 묶음.

- 공개: GET /health (Spring 이 15초마다 연결 확인)
- 내부: /v1/** (INTERNAL_API_KEY 가 설정돼 있으면 X-Internal-Api-Key 검사)
"""

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.security import verify_internal_caller
from app.domains.assistant.router import router as assistant_router
from app.domains.compromise.router import router as compromise_router
from app.domains.conflict.router import router as conflict_router
from app.domains.embedding.router import router as embedding_router
from app.domains.layout.router import router as layout_router
from app.domains.summary.router import router as summary_router
from app.domains.tone.router import router as tone_router

public_router = APIRouter()


@public_router.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "UP", "stub": get_settings().ai_stub_mode}


internal_router = APIRouter(prefix="/v1", dependencies=[Depends(verify_internal_caller)])
for router in (
    tone_router,
    summary_router,
    embedding_router,
    conflict_router,
    compromise_router,
    layout_router,
    assistant_router,
):
    internal_router.include_router(router)
