"""답변 속 근거 표시를 걷어 내고 모은다.

AI 에게 근거로 쓴 항목을 `[[card:12]]` `[[task:3]]` `[[vote:5]]` 로 붙이게 한다. 이 표시는 화면에
보이면 안 되므로 스트림에서 지우고, 모은 ID 로 마지막에 references 를 만든다.

작은 모델은 방 데이터에 적힌 `card_id=3` 같은 내부 표기를 본문에 그대로 옮기기도 한다
(2026-11-15 Flash-Lite 실측). 이것도 같은 방식으로 지우고 근거로 모은다.

스트림 조각 경계에서 표시가 잘릴 수 있다(`[[ca` + `rd:12]]`, `card_` + `id=3`). 그래서 표시의
앞부분일 수 있는 꼬리는 다음 조각이 올 때까지 내보내지 않고 들고 있는다.
"""

import re

_MARK = re.compile(r"\[\[(card|task|vote):(\d+)\]\]")
# 본문에 새어 나온 내부 표기. 감싼 괄호·백틱과 앞 공백까지 함께 지운다: " (`card_id=3`)" → ""
_RAW_ID = re.compile(r" ?\(?`?(card|task|vote)_id=(\d+)`?\)?")
# 표시의 앞부분일 수 있는 꼬리: "[", "[[car", "[[card:12]", "`card_", "task_id=1" ...
_PARTIAL_TAIL = re.compile(
    r"(\[(\[([a-z]{0,4}(:\d*\]?)?)?)?"
    r"|\(?`?(c(a(r(d(_(i(d(=\d*)?)?)?)?)?)?)?|t(a(s(k(_(i(d(=\d*)?)?)?)?)?)?)?|v(o(t(e(_(i(d(=\d*)?)?)?)?)?)?)?))$"
)

KINDS = ("card", "task", "vote")


class CitationFilter:
    def __init__(self) -> None:
        self._buffer = ""
        self.cited: dict[str, list[int]] = {kind: [] for kind in KINDS}

    def _collect(self, match: re.Match) -> str:
        ids = self.cited[match.group(1)]
        value = int(match.group(2))
        if value not in ids:
            ids.append(value)
        return ""

    def _strip(self, text: str) -> str:
        return _RAW_ID.sub(self._collect, _MARK.sub(self._collect, text))

    def feed(self, text: str) -> str:
        """조각을 넣고, 지금 내보내도 되는 글을 받는다."""
        self._buffer = self._strip(self._buffer + text)
        tail = _PARTIAL_TAIL.search(self._buffer)
        cut = tail.start() if tail else len(self._buffer)
        # 끝의 공백·줄바꿈도 들고 있는다. 근거 표시 앞 줄바꿈이 답변 끝에 남지 않게 하기 위함이다.
        ready = self._buffer[:cut]
        cut = len(ready.rstrip())
        ready, self._buffer = self._buffer[:cut], self._buffer[cut:]
        return ready

    def flush(self) -> str:
        """스트림이 끝났을 때 남은 글. 끝내 표시가 되지 못한 꼬리는 원문 그대로 내보낸다."""
        rest = self._strip(self._buffer).rstrip()
        self._buffer = ""
        return rest
