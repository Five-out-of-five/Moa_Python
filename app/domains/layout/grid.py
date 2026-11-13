"""격자 규칙. Spring DashboardService.validate 와 같아야 한다.

- 종류 중복 없음
- 최소 크기: IDEA_BOARD 6x5, TASK_BOARD 4x4, PROGRESS 2x2, 나머지 3x3
- x >= 0, y >= 0, x + w <= 열 수, h <= 8
- 겹침 없음

AI 는 이 규칙을 자주 어긴다. 어긴 응답을 그대로 넘기면 Spring 이 400 으로 막아 사용자는 추천을
못 받는다. 그래서 여기서 고쳐서 넘긴다.
"""

from app.domains.layout.schemas import WidgetPlacement

MAX_HEIGHT = 8

_MIN_SIZE = {"IDEA_BOARD": (6, 5), "TASK_BOARD": (4, 4), "PROGRESS": (2, 2)}
_DEFAULT_MIN = (3, 3)

# Spring DashboardService.DEFAULT_LAYOUT 과 같다. AI 응답을 하나도 못 살렸을 때 쓴다.
DEFAULT_LAYOUT = [
    WidgetPlacement(widget_type="MOOD", x=0, y=0, w=3, h=4),
    WidgetPlacement(widget_type="IDEA_BOARD", x=3, y=0, w=6, h=7),
    WidgetPlacement(widget_type="CATCHUP_BRIEFING", x=9, y=0, w=3, h=7),
    WidgetPlacement(widget_type="TASK_BOARD", x=3, y=7, w=6, h=4),
]


def min_size(widget_type: str) -> tuple[int, int]:
    return _MIN_SIZE.get(widget_type, _DEFAULT_MIN)


def _overlaps(a: WidgetPlacement, b: WidgetPlacement) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def _first_fit(w: int, h: int, placed: list[WidgetPlacement], columns: int) -> tuple[int, int]:
    """위에서부터, 왼쪽부터 처음 비는 자리. y 는 제한이 없으므로 언젠가는 반드시 찾는다."""
    y = 0
    while True:
        for x in range(columns - w + 1):
            probe = WidgetPlacement(widget_type="", x=x, y=y, w=w, h=h)
            if not any(_overlaps(probe, p) for p in placed):
                return x, y
        y += 1


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def repair(raw: list[WidgetPlacement], allowed: list[str], columns: int) -> list[WidgetPlacement]:
    """규칙을 지키는 배치로 고친다. AI 가 준 순서와 위치를 되도록 살린다."""
    allowed_set = set(allowed)
    placed: list[WidgetPlacement] = []
    seen: set[str] = set()

    for item in raw:
        kind = item.widget_type
        if kind not in allowed_set or kind in seen:
            continue
        min_w, min_h = min_size(kind)
        if min_w > columns:
            continue
        w = _clamp(item.w, min_w, columns)
        h = _clamp(item.h, min_h, MAX_HEIGHT)
        candidate = WidgetPlacement(widget_type=kind, x=_clamp(item.x, 0, columns - w), y=max(0, item.y), w=w, h=h)
        if any(_overlaps(candidate, p) for p in placed):
            x, y = _first_fit(w, h, placed, columns)
            candidate = candidate.model_copy(update={"x": x, "y": y})
        placed.append(candidate)
        seen.add(kind)

    if placed:
        return placed
    fallback = [p for p in DEFAULT_LAYOUT if p.widget_type in allowed_set and p.x + p.w <= columns]
    return fallback


def violations(widgets: list[WidgetPlacement], columns: int) -> list[str]:
    """규칙 위반 목록. 테스트와 로그에서 쓴다. 비어 있으면 Spring 검증을 통과한다."""
    problems = []
    if len({w.widget_type for w in widgets}) != len(widgets):
        problems.append("duplicate type")
    for i, a in enumerate(widgets):
        min_w, min_h = min_size(a.widget_type)
        if a.w < min_w or a.h < min_h:
            problems.append(f"{a.widget_type} too small")
        if a.x < 0 or a.y < 0 or a.x + a.w > columns or a.h > MAX_HEIGHT:
            problems.append(f"{a.widget_type} out of grid")
        for b in widgets[i + 1 :]:
            if _overlaps(a, b):
                problems.append(f"{a.widget_type} overlaps {b.widget_type}")
    return problems
