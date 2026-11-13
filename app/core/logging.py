"""로그 설정. 모든 줄에 추적 ID 를 붙인다."""

import logging

from app.core.context import get_trace_id

_FORMAT = "%(asctime)s %(levelname)-5s [%(trace_id)s] %(name)s - %(message)s"


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(TraceIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # google-genai 가 내부 HTTP 요청마다 INFO 를 찍는다. 키가 URL 에 실리는 경우를 막기 위해서도 낮춘다.
    for noisy in ("httpx", "httpx2", "httpcore", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
