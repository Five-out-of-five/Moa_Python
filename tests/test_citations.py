from app.domains.assistant.citations import CitationFilter
from app.domains.assistant.schemas import AssistantContext
from app.domains.assistant.service import build_references


def _run(pieces: list[str]) -> tuple[str, CitationFilter]:
    citations = CitationFilter()
    out = "".join(citations.feed(p) for p in pieces) + citations.flush()
    return out, citations


def test_markers_are_removed_and_collected():
    out, c = _run(["답변입니다.\n[[card:1]] [[task:2]] [[card:1]]"])
    assert out == "답변입니다."
    assert c.cited == {"card": [1], "task": [2], "vote": []}


def test_marker_split_across_chunks():
    out, c = _run(["요약 [", "[ca", "rd:1", "2]", "] 끝"])
    assert out == "요약  끝"
    assert c.cited["card"] == [12]


def test_partial_marker_is_held_until_next_chunk():
    citations = CitationFilter()
    assert citations.feed("본문 [[vo") == "본문"
    # "본문" 뒤 공백은 들고 있다가 다음 글과 함께 나간다.
    assert citations.feed("te:3]] 다음") == "  다음"
    assert citations.cited["vote"] == [3]


def test_unfinished_bracket_is_released_at_end():
    out, _ = _run(["배열 [a", "b"])
    assert out == "배열 [ab"


def test_normal_brackets_pass_through():
    out, _ = _run(["[참고] 목록[0] 입니다"])
    assert out == "[참고] 목록[0] 입니다"


def test_references_keep_only_known_ids():
    context = AssistantContext.model_validate(
        {"cards": [{"id": 1, "title": "카드"}], "tasks": [{"id": 2, "title": "업무"}], "votes": []}
    )
    refs = build_references({"card": [1, 99], "task": [2], "vote": [5]}, context)
    assert refs == {"cards": [{"id": 1, "title": "카드"}], "tasks": [{"id": 2, "title": "업무"}], "votes": []}
