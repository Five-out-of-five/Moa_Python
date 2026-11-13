"""genai.Client 대역. 키마다 정해 둔 결과(문자열 또는 예외)를 순서대로 돌려준다."""


class FakeApiError(Exception):
    """google-genai APIError 처럼 code 속성을 가진 예외."""

    def __init__(self, code: int, message: str = ""):
        super().__init__(message or f"error {code}")
        self.code = code


class _Obj:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class FakeModels:
    def __init__(self, key: str, script: dict, calls: list):
        self._key = key
        self._script = script
        self._calls = calls

    def _next(self):
        self._calls.append(self._key)
        queue = self._script.get(self._key) or []
        outcome = queue.pop(0) if queue else '{"ok": true}'
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def generate_content(self, **kwargs):
        return _Obj(text=self._next())

    async def embed_content(self, **kwargs):
        outcome = self._next()
        return _Obj(embeddings=[_Obj(values=outcome)])

    async def generate_content_stream(self, **kwargs):
        outcome = self._next()

        async def _gen():
            for piece in outcome:
                if isinstance(piece, BaseException):
                    raise piece
                yield _Obj(text=piece)

        return _gen()


def install(monkeypatch, script: dict) -> list:
    """`genai.Client(api_key=...)` 를 대역으로 바꾼다. 호출된 키 순서를 담는 목록을 준다."""
    from app.clients import gemini as gemini_module

    calls: list = []

    def _factory(api_key: str):
        return _Obj(aio=_Obj(models=FakeModels(api_key, script, calls)))

    monkeypatch.setattr(gemini_module.genai, "Client", _factory)
    return calls
