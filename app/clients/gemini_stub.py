"""Gemini 더미 클라이언트 (로컬 개발·부하 테스트 전용).

`genai.Client` 의 `aio.models.*` 표면만 흉내낸다. 그래서 GeminiClient 의 키 전환·재시도
경로는 그대로 실행된다.

JSON 응답은 호출자가 넘긴 JSON Schema 를 읽어 그 모양대로 만든다. 프롬프트에 `card_id=12`
같은 식별자가 있으면 배열 항목의 같은 이름 필드에 그 값을 쓴다(`cardId` 와 `card_id` 를 같게 본다).

더미 문자열에는 일부러 "[더미]" 를 넣는다. 스텁을 켠 채 잊으면 화면에서 바로 드러나야 한다.
"""

import asyncio
import hashlib
import json
import math
import random
import re

from app.core.config import Settings

STUB_TEXT = "[더미] AI_STUB_MODE 가 켜져 있어 실제 AI 를 부르지 않았습니다."

_ID_PATTERN = re.compile(r"([a-z][a-z0-9_]*_id)\s*[:=]\s*(\d+)")
_MAX_DEPTH = 12


def _norm(name: str) -> str:
    return name.replace("_", "").lower()


def _id_hints(prompt: str) -> dict[str, list[int]]:
    hints: dict[str, list[int]] = {}
    for name, raw in _ID_PATTERN.findall(prompt):
        values = hints.setdefault(_norm(name), [])
        if int(raw) not in values:
            values.append(int(raw))
    return hints


def _dummy(schema: dict, hints: dict[str, list[int]], *, fixed: dict | None = None, depth: int = 0):
    if depth > _MAX_DEPTH or not isinstance(schema, dict):
        return None
    if schema.get("enum"):
        return schema["enum"][0]

    kind = schema.get("type")
    if kind == "object":
        result = {}
        for name, sub in (schema.get("properties") or {}).items():
            result[name] = fixed[name] if fixed and name in fixed else _dummy(sub, hints, depth=depth + 1)
        return result
    if kind == "array":
        items = schema.get("items") or {}
        for name in (items.get("properties") or {}):
            ids = hints.get(_norm(name))
            if ids:
                return [_dummy(items, hints, fixed={name: v}, depth=depth + 1) for v in ids]
        return [_dummy(items, hints, depth=depth + 1)]
    if kind == "string":
        return STUB_TEXT
    if kind in ("integer", "number"):
        low = schema.get("minimum", 0)
        high = max(low, schema.get("maximum", low + 10))
        value = random.uniform(low, high)
        return int(value) if kind == "integer" else round(value, 2)
    if kind == "boolean":
        return True
    return STUB_TEXT


def _vector(text: str, dimension: int) -> list[float]:
    """같은 텍스트에 같은 벡터. 실행마다 유사도가 흔들리면 결과를 비교할 수 없다."""
    seed = int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")
    rng = random.Random(seed)
    values = [rng.gauss(0.0, 1.0) for _ in range(dimension)]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


class _Obj:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class _StubTransientError(RuntimeError):
    """메시지의 "overloaded" 때문에 RETRY 로 분류된다. 재시도 경로를 실제로 태우기 위함이다."""

    def __init__(self):
        super().__init__("stub injected failure: model is overloaded")


class _StubModels:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def _pause(self) -> None:
        base = self._settings.ai_stub_delay_ms
        jitter = self._settings.ai_stub_jitter_ms
        millis = base + (random.uniform(-jitter, jitter) if jitter else 0.0)
        if millis > 0:
            await asyncio.sleep(millis / 1000.0)

    def _maybe_fail(self) -> None:
        rate = self._settings.ai_stub_fail_rate
        if rate > 0 and random.random() < rate:
            raise _StubTransientError()

    async def embed_content(self, *, model: str, contents, config=None):
        await self._pause()
        self._maybe_fail()
        texts = contents if isinstance(contents, list) else [contents]
        dimension = getattr(config, "output_dimensionality", None) or self._settings.embedding_dimension
        return _Obj(embeddings=[_Obj(values=_vector(str(t), dimension)) for t in texts])

    async def generate_content(self, *, model: str, contents, config=None):
        await self._pause()
        self._maybe_fail()
        schema = getattr(config, "response_json_schema", None)
        if not isinstance(schema, dict):
            return _Obj(text=json.dumps({"stub": STUB_TEXT}, ensure_ascii=False))
        payload = _dummy(schema, _id_hints(str(contents)))
        return _Obj(text=json.dumps(payload, ensure_ascii=False))

    async def generate_content_stream(self, *, model: str, contents, config=None):
        await self._pause()
        self._maybe_fail()
        prompt = str(contents)
        # 근거 표시 흐름도 확인할 수 있게, 프롬프트의 첫 카드를 근거로 붙인다.
        card = re.search(r"card_id=(\d+)", prompt)
        pieces = ["[더미] 이번 회차 ", "내용을 정리한 ", "가짜 답변입니다."]
        if card:
            pieces.append(f"\n[[card:{card.group(1)}]]")

        async def _gen():
            for piece in pieces:
                await asyncio.sleep(0)
                yield _Obj(text=piece)

        return _gen()


class StubGenaiClient:
    """`genai.Client` 대신 들어간다. 쓰이는 표면은 `client.aio.models.*` 뿐이다."""

    def __init__(self, settings: Settings):
        self.aio = _Obj(models=_StubModels(settings))
