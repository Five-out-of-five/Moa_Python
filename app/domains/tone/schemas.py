from enum import StrEnum

from pydantic import Field

from app.domains.common import CamelModel, Text


class ToneMode(StrEnum):
    OFF = "OFF"
    POLISH = "POLISH"  # 뜻은 그대로, 거친 표현만 부드럽게
    POLITE = "POLITE"  # 존댓말로


class ToneCheckRequest(CamelModel):
    text: Text = Field(min_length=1, max_length=5000)
    tone_mode: ToneMode


class ToneCheckResponse(CamelModel):
    needs_change: bool
    # 바꿀 필요가 없으면 null. Spring 이 그대로 프론트에 넘긴다.
    suggestion: str | None = None
