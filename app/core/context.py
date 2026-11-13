"""요청 단위 추적 ID. 로그에 함께 찍어 한 요청의 흐름을 묶는다."""

from contextvars import ContextVar

TRACE_HEADER = "X-Trace-Id"

_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")


def get_trace_id() -> str:
    return _trace_id.get()


def set_trace_id(value: str) -> None:
    _trace_id.set(value)
