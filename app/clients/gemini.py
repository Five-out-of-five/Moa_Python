"""Gemini 클라이언트.

키는 여러 개를 쉼표로 받는다(`GEMINI_API_KEY`). 한 키가 429(한도)·401/403(죽은 키)을 내면
그 키를 쿨다운에 넣고 다음 키로 이어서 부른다. 타임아웃·5xx 같은 일시 오류는 키를 바꿔도
나아지지 않으므로 같은 키로 잠깐 쉬었다 다시 시도한다.

Spring 은 응답을 30초까지 기다린다. 그래서 키 전환·재시도를 합친 전체 시간을
`gemini_deadline_seconds`(기본 25초) 안에 끝낸다.

키 값은 절대 로그에 남기지 않는다. 몇 번째 키인지만 남긴다.
"""

import asyncio
import json
import logging
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from enum import Enum
from typing import Any

from google import genai
from google.genai import types

from app.clients.gemini_stub import StubGenaiClient
from app.core.config import Settings, get_settings
from app.core.errors import AiErrorCode, AiException

logger = logging.getLogger(__name__)


class GeminiTask(Enum):
    """용도. 용도마다 모델을 설정에서 따로 고른다."""

    TONE = "tone"
    SUMMARY = "summary"
    CONFLICT = "conflict"
    COMPROMISE = "compromise"
    LAYOUT = "layout"
    ASSISTANT = "assistant"
    EMBEDDING = "embedding"


class _Action(Enum):
    ROTATE = "rotate"  # 이 키로는 안 된다 -> 쿨다운, 다음 키
    RETRY = "retry"  # 일시적이다 -> 같은 키로 잠깐 뒤에
    FAIL = "fail"  # 요청이 틀렸거나 회복 불가 -> 그대로 실패


# SDK 버전마다 예외 속성명과 메시지가 달라서 상태코드와 메시지를 함께 본다.
_ROTATE_MARKERS = (
    "resource_exhausted",
    "quota",
    "rate limit",
    "too many requests",
    "api key not valid",
    "api_key_invalid",
    "permission_denied",
)
_RETRY_MARKERS = ("unavailable", "overloaded", "deadline", "timed out", "internal error")


def _status_of(exc: BaseException) -> int | None:
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def _brief(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc).replace(chr(10), ' ')[:200]}"


def _classify(exc: BaseException) -> _Action:
    if isinstance(exc, AiException):
        # 빈 응답·깨진 JSON 은 다시 부르면 나을 수 있다. 그 밖의 우리 예외는 다시 해도 같다.
        return _Action.RETRY if exc.error_code is AiErrorCode.LLM_RESPONSE_INVALID else _Action.FAIL

    status = _status_of(exc)
    text = str(exc).lower()
    if status in (401, 403, 429) or any(m in text for m in _ROTATE_MARKERS):
        return _Action.ROTATE
    if isinstance(exc, TimeoutError | ConnectionError):
        return _Action.RETRY
    if status in (500, 502, 503, 504) or any(m in text for m in _RETRY_MARKERS):
        return _Action.RETRY
    return _Action.FAIL


class GeminiClient:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        keys = self._settings.gemini_api_keys

        if self._settings.ai_stub_mode:
            # 클라이언트 자리만 바꿔 끼운다. 키 전환·재시도 경로는 그대로 탄다.
            self._clients: list[Any] = [StubGenaiClient(self._settings) for _ in (keys or ["stub"])]
            logger.warning("AI_STUB_MODE 가 켜져 있습니다. Gemini 를 부르지 않고 [더미] 응답을 줍니다.")
        else:
            self._clients = [genai.Client(api_key=key) for key in keys]

        self._key_count = len(self._clients)
        # 단일 이벤트 루프에서만 갱신하므로 락이 필요 없다. await 를 끼고 갱신하지 않는다.
        self._cooldown_until = [0.0] * self._key_count
        self._index = 0
        logger.info("Gemini 키 %d개 로드 (한도 초과 시 다음 키로 넘어감)", self._key_count)

    @property
    def key_count(self) -> int:
        return self._key_count

    def model_for(self, task: GeminiTask) -> str:
        s = self._settings
        return {
            GeminiTask.TONE: s.gemini_model_tone,
            GeminiTask.SUMMARY: s.gemini_model_summary,
            GeminiTask.CONFLICT: s.gemini_model_conflict,
            GeminiTask.COMPROMISE: s.gemini_model_compromise,
            GeminiTask.LAYOUT: s.gemini_model_layout,
            GeminiTask.ASSISTANT: s.gemini_model_assistant,
            GeminiTask.EMBEDDING: s.gemini_model_embedding,
        }[task]

    # ------------------------------------------------------------------
    # 키 선택
    # ------------------------------------------------------------------

    def _pick(self) -> int:
        now = time.monotonic()
        for offset in range(self._key_count):
            index = (self._index + offset) % self._key_count
            if self._cooldown_until[index] <= now:
                self._index = index
                return index
        # 전부 쿨다운이면 가장 먼저 풀리는 키로 한 번 시도한다. 한도가 일찍 풀릴 수도 있다.
        index = min(range(self._key_count), key=lambda i: self._cooldown_until[i])
        self._index = index
        return index

    def _disable(self, index: int, exc: BaseException) -> None:
        seconds = self._settings.gemini_key_cooldown_seconds
        self._cooldown_until[index] = time.monotonic() + seconds
        self._index = (index + 1) % self._key_count
        logger.warning("Gemini 키 %d/%d 를 %d초간 제외: %s", index + 1, self._key_count, seconds, _brief(exc))

    async def _invoke(self, call: Callable[[Any], Awaitable[Any]], fallback: AiErrorCode) -> Any:
        """`call(client)` 이 성공할 때까지 키를 돌려 가며 부른다. 전체 시간은 마감 안으로 제한한다."""
        deadline = time.monotonic() + self._settings.gemini_deadline_seconds
        retries_left = self._settings.gemini_max_retries
        rotations_left = self._key_count
        attempts = 0
        last_exc: BaseException | None = None

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                last_exc = last_exc or TimeoutError()
                break
            index = self._pick()
            attempts += 1
            try:
                async with asyncio.timeout(remaining):
                    return await call(self._clients[index])
            except Exception as exc:
                last_exc = exc
                action = _classify(exc)

                if action is _Action.FAIL:
                    if isinstance(exc, AiException):
                        raise
                    logger.warning("Gemini 호출 실패(재시도 안 함): %s", _brief(exc))
                    raise AiException(fallback) from exc

                if action is _Action.ROTATE:
                    self._disable(index, exc)
                    rotations_left -= 1
                    if rotations_left <= 0:
                        break
                    continue

                if retries_left <= 0:
                    break
                retries_left -= 1
                backoff = min(4.0, 0.5 * 2 ** (self._settings.gemini_max_retries - retries_left - 1))
                if deadline - time.monotonic() <= backoff:
                    break
                logger.warning("Gemini 일시 오류, %.1f초 뒤 재시도: %s", backoff, _brief(exc))
                await asyncio.sleep(backoff)

        if isinstance(last_exc, TimeoutError):
            code = AiErrorCode.LLM_TIMEOUT
        elif isinstance(last_exc, AiException):
            # 호출은 됐는데 응답이 계속 이상했다. 호출 실패로 덮으면 원인이 뒤바뀐다.
            code = last_exc.error_code
        else:
            code = fallback
        raise AiException(code, f"Gemini 호출 실패 (키 {self._key_count}개, 시도 {attempts}회)") from last_exc

    # ------------------------------------------------------------------
    # 호출
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float]:
        """텍스트 하나를 단위 벡터로 바꾼다. 차원은 settings.embedding_dimension."""
        model = self.model_for(GeminiTask.EMBEDDING)
        expected = self._settings.embedding_dimension

        async def _call(client: Any) -> list[float]:
            response = await client.aio.models.embed_content(
                model=model,
                contents=[text],
                config=types.EmbedContentConfig(
                    output_dimensionality=expected,
                    task_type="SEMANTIC_SIMILARITY",
                ),
            )
            embeddings = response.embeddings or []
            if not embeddings or not embeddings[0].values:
                raise AiException(AiErrorCode.LLM_RESPONSE_INVALID, "임베딩 응답이 비었습니다.")
            vector = list(embeddings[0].values)
            if len(vector) != expected:
                # 모델을 바꾸고 DB 컬럼을 안 바꾼 상황. 저장 시점에 터지면 원인을 찾기 어렵다.
                raise AiException(AiErrorCode.EMBEDDING_FAILED, f"임베딩 차원이 설정과 다릅니다. (기대 {expected})")
            # 축소한 차원은 단위 벡터가 아니다. 코사인 거리를 쓰므로 길이를 1로 맞춘다.
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            return [v / norm for v in vector]

        return await self._invoke(_call, AiErrorCode.EMBEDDING_FAILED)

    async def generate_json[T](
        self,
        task: GeminiTask,
        prompt: str,
        schema: dict,
        parse: Callable[[Any], T],
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> T:
        """JSON Schema 에 맞는 응답을 받아 `parse` 로 바꾼다.

        파싱을 호출 안에서 하는 이유: 깨진 JSON·빈 값은 다시 부르면 나을 수 있어서 재시도 대상이다.
        `parse` 가 ValueError(pydantic ValidationError 포함)를 내면 응답 형식 오류로 본다.
        """
        model = self.model_for(task)

        async def _call(client: Any) -> T:
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    temperature=temperature,
                ),
            )
            if not response.text:
                raise AiException(AiErrorCode.LLM_RESPONSE_INVALID)
            try:
                return parse(json.loads(response.text))
            except ValueError as exc:
                raise AiException(AiErrorCode.LLM_RESPONSE_INVALID, f"응답 형식 오류: {_brief(exc)}") from exc

        return await self._invoke(_call, AiErrorCode.LLM_CALL_FAILED)

    async def open_text_stream(
        self,
        task: GeminiTask,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """텍스트 스트림을 연다.

        첫 조각을 받을 때까지는 키 전환·재시도를 한다. 그래서 여기서 실패하면 아직 응답을 보내기
        전이라 일반 에러(502/504)로 돌려줄 수 있다. 첫 조각 이후의 실패는 스트림을 끊는다.
        """
        model = self.model_for(task)
        config = types.GenerateContentConfig(system_instruction=system, temperature=temperature)

        async def _open(client: Any) -> tuple[str, AsyncIterator[Any]]:
            stream = await client.aio.models.generate_content_stream(model=model, contents=prompt, config=config)
            iterator = aiter(stream)
            while True:
                try:
                    chunk = await anext(iterator)
                except StopAsyncIteration:
                    raise AiException(AiErrorCode.LLM_RESPONSE_INVALID, "스트림이 비었습니다.") from None
                if chunk.text:
                    return chunk.text, iterator

        first, iterator = await self._invoke(_open, AiErrorCode.LLM_CALL_FAILED)
        return self._rest_of_stream(first, iterator)

    async def _rest_of_stream(self, first: str, iterator: AsyncIterator[Any]) -> AsyncIterator[str]:
        yield first
        # 조각 사이 대기도 Spring 읽기 타임아웃(30초)보다 짧아야 한다.
        gap = self._settings.gemini_deadline_seconds
        while True:
            try:
                async with asyncio.timeout(gap):
                    chunk = await anext(iterator)
            except StopAsyncIteration:
                return
            if chunk.text:
                yield chunk.text


_client: GeminiClient | None = None


def get_gemini_client() -> GeminiClient:
    """프로세스당 하나. 키 쿨다운 상태를 이 인스턴스가 들고 있다."""
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client


def reset_gemini_client() -> None:
    """테스트용. 설정을 바꾼 뒤 새 클라이언트를 만들게 한다."""
    global _client
    _client = None
