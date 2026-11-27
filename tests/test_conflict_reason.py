"""충돌 감지 reason 의 내부 표기 정리. reason 은 팀원 화면에 그대로 보인다."""

import asyncio

import pytest

from app.domains.conflict.schemas import ConflictDetectRequest
from app.domains.conflict.service import detect_conflicts, tidy_reason


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 2026-11-28 운영에서 실제로 나온 문장
        (
            "스탠드업을 없애자는 의견과 운영 방식을 조율하자는 기준 카드의 실행 과제는 방향이 다릅니다.",
            "스탠드업을 없애자는 의견과 운영 방식을 조율하자는 카드의 실행 과제는 방향이 다릅니다.",
        ),
        ("후보 카드는 리뷰를 줄이자고 합니다.", "다른 카드는 리뷰를 줄이자고 합니다."),
        ("새로 올라온 의견과 비교할 의견이 부딪힙니다.", "한쪽 의견과 다른 의견이 부딪힙니다."),
        ("리뷰 강화(card_id=12)와 리뷰 축소 (`card_id=3`)가 반대입니다.", "리뷰 강화와 리뷰 축소가 반대입니다."),
        # 받침 있는 '12번' 을 지우면 조사가 어긋나므로 함께 고친다
        ("3번 카드와 카드 12번은 방향이 다릅니다.", "카드와 카드는 방향이 다릅니다."),
        ("카드 7번과 카드 9번을 비교했습니다.", "카드와 카드를 비교했습니다."),
        # 손대지 않아야 하는 문장
        ("카드 3장이 같은 주제를 다룹니다.", "카드 3장이 같은 주제를 다룹니다."),
        ("주 1회 하자는 의견과 격주로 하자는 의견은 다릅니다.", "주 1회 하자는 의견과 격주로 하자는 의견은 다릅니다."),
    ],
)
def test_tidy_reason(raw, expected):
    assert tidy_reason(raw) == expected


class _FakeGemini:
    """generate_json 이 정해 둔 응답을 돌려준다. 받은 프롬프트를 남긴다."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    async def generate_json(self, task, prompt, schema, parse, **kwargs):
        self.prompts.append(prompt)
        return parse(self.payload)


def test_detect_cleans_reason_and_prompt_has_no_internal_labels():
    gemini = _FakeGemini({"conflicts": [{"card_id": 2, "reason": "기준 카드와 후보 카드(card_id=2)는 반대입니다."}]})
    request = ConflictDetectRequest.model_validate(
        {
            "card": {"id": 1, "title": "리뷰 강화", "content": ""},
            "candidates": [{"id": 2, "title": "리뷰 축소", "content": ""}],
        }
    )

    result = asyncio.run(detect_conflicts(gemini, request))

    assert result.conflicts[0].reason == "카드와 다른 카드는 반대입니다."
    assert "기준 카드" not in gemini.prompts[0]
    assert "후보 카드" not in gemini.prompts[0]
