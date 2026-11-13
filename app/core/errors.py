"""에러 코드와 예외 처리.

Spring 은 2xx 가 아니면 본문을 읽지 않고 실패로 처리한다(AI_UNAVAILABLE 또는 건너뜀).
그래서 본문은 로그·디버깅용으로 짧게 둔다: {"code", "message", "traceId"}.
"""

import logging
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.context import get_trace_id

logger = logging.getLogger(__name__)


class AiErrorCode(Enum):
    """(HTTP 상태, 코드, 기본 메시지)"""

    SERVER_ERROR = (500, "AI_SERVER_ERROR", "AI 서버 내부 오류가 발생했습니다.")
    INVALID_REQUEST = (400, "AI_INVALID_REQUEST", "잘못된 요청입니다.")
    UNAUTHORIZED = (401, "AI_UNAUTHORIZED", "내부 호출 인증에 실패했습니다.")

    LLM_CALL_FAILED = (502, "AI_LLM_CALL_FAILED", "LLM 호출에 실패했습니다.")
    LLM_TIMEOUT = (504, "AI_LLM_TIMEOUT", "LLM 응답이 지연되었습니다.")
    LLM_RESPONSE_INVALID = (502, "AI_LLM_RESPONSE_INVALID", "LLM 응답 형식이 올바르지 않습니다.")
    EMBEDDING_FAILED = (502, "AI_EMBEDDING_FAILED", "임베딩 생성에 실패했습니다.")

    @property
    def status(self) -> int:
        return self.value[0]

    @property
    def code(self) -> str:
        return self.value[1]

    @property
    def message(self) -> str:
        return self.value[2]


class AiException(Exception):
    def __init__(self, error_code: AiErrorCode, message: str | None = None):
        self.error_code = error_code
        self.message = message or error_code.message
        super().__init__(self.message)


def error_response(code: AiErrorCode, message: str | None = None) -> JSONResponse:
    body = {"code": code.code, "message": message or code.message, "traceId": get_trace_id()}
    return JSONResponse(status_code=code.status, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AiException)
    async def handle_ai_exception(_: Request, exc: AiException) -> JSONResponse:
        logger.warning("[AiException] %s - %s", exc.error_code.code, exc.message)
        return error_response(exc.error_code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 값 자체(사용자 글)는 로그에 남기지 않고 위치와 이유만 남긴다.
        details = ", ".join(
            f"{'.'.join(str(p) for p in err['loc'][1:])}: {err['msg']}" for err in exc.errors()
        )
        logger.warning("[ValidationError] %s", details)
        return error_response(AiErrorCode.INVALID_REQUEST, details or None)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("[UnexpectedError] %s", type(exc).__name__)
        return error_response(AiErrorCode.SERVER_ERROR)
