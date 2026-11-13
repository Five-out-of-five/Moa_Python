"""추적 ID 미들웨어.

BaseHTTPMiddleware 를 쓰지 않는다. 그 방식은 응답 본문을 한 번 더 감싸서 SSE 스트림이
조각마다 바로 나가지 않는 경우가 있다. 순수 ASGI 로 헤더만 다룬다.
"""

import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import TRACE_HEADER, set_trace_id

_HEADER_KEY = TRACE_HEADER.lower().encode("latin-1")


class TraceIdMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(_HEADER_KEY, b"").decode("latin-1").strip()
        # 밖에서 온 값은 길이와 문자를 제한한다. 로그에 그대로 찍히기 때문이다.
        trace_id = incoming if incoming and len(incoming) <= 64 and incoming.isalnum() else uuid.uuid4().hex[:16]
        set_trace_id(trace_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((_HEADER_KEY, trace_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_header)
