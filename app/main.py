"""모아 AI 서버 진입점. Spring Boot 백엔드만 이 서버를 부른다."""

from fastapi import FastAPI

from app.api import internal_router, public_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import TraceIdMiddleware

settings = get_settings()
setup_logging(settings.log_level)

# 운영에서는 API 문서를 열지 않는다. 내부 서비스라 외부에 노출할 이유가 없다.
_docs = settings.app_env != "prod"
app = FastAPI(
    title="MOA AI",
    version="0.1.0",
    docs_url="/docs" if _docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs else None,
)
app.add_middleware(TraceIdMiddleware)
register_exception_handlers(app)
app.include_router(public_router)
app.include_router(internal_router)
