"""레이아웃 보정. 결과는 언제나 Spring DashboardService.validate 를 통과해야 한다."""

import random

from app.domains.layout.grid import DEFAULT_LAYOUT, repair, violations
from app.domains.layout.schemas import WidgetPlacement

ALL = ["MOOD", "PROGRESS", "IDEA_BOARD", "TASK_BOARD", "VOTE", "CATCHUP_BRIEFING", "MEDIATION"]


def _w(kind, x, y, w, h):
    return WidgetPlacement(widget_type=kind, x=x, y=y, w=w, h=h)


def test_valid_layout_is_kept():
    raw = [_w("IDEA_BOARD", 0, 0, 6, 5), _w("TASK_BOARD", 6, 0, 6, 5)]
    assert repair(raw, ALL, 12) == raw


def test_default_layout_is_valid():
    assert violations(DEFAULT_LAYOUT, 12) == []


def test_too_small_and_out_of_grid_are_fixed():
    raw = [_w("IDEA_BOARD", 10, -2, 2, 2), _w("MOOD", 0, 0, 1, 20)]
    fixed = repair(raw, ALL, 12)
    assert violations(fixed, 12) == []
    assert fixed[0] == _w("IDEA_BOARD", 6, 0, 6, 5)


def test_overlap_is_moved():
    raw = [_w("IDEA_BOARD", 0, 0, 6, 5), _w("VOTE", 2, 2, 3, 3)]
    fixed = repair(raw, ALL, 12)
    assert violations(fixed, 12) == []
    assert fixed[1] == _w("VOTE", 6, 0, 3, 3)


def test_duplicates_and_unknown_types_are_dropped():
    raw = [_w("MOOD", 0, 0, 3, 3), _w("MOOD", 3, 0, 3, 3), _w("CHAT", 6, 0, 3, 3)]
    assert [w.widget_type for w in repair(raw, ALL, 12)] == ["MOOD"]


def test_nothing_usable_falls_back_to_default():
    assert repair([_w("CHAT", 0, 0, 3, 3)], ALL, 12) == DEFAULT_LAYOUT


def test_random_inputs_always_pass_spring_rules():
    rng = random.Random(7)
    for _ in range(500):
        raw = [
            _w(rng.choice([*ALL, "X"]), *(rng.randint(-5, 15) for _ in range(4)))
            for _ in range(rng.randint(0, 10))
        ]
        assert violations(repair(raw, ALL, 12), 12) == []


def test_missing_base_widgets_are_added():
    fixed = repair([_w("PROGRESS", 0, 0, 4, 4), _w("VOTE", 4, 0, 3, 3)], ALL, 12)
    kinds = [w.widget_type for w in fixed]
    assert "TASK_BOARD" in kinds and "IDEA_BOARD" in kinds
    assert violations(fixed, 12) == []


def test_reason_uses_korean_widget_names():
    from app.domains.layout.service import _korean_reason

    assert _korean_reason("TASK_BOARD 위젯과 MOOD 위젯을 배치") == "업무 보드 위젯과 상태값 위젯을 배치"
