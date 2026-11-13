from pydantic import Field

from app.domains.common import CamelModel, Text


class SummaryCard(CamelModel):
    id: int
    type: str  # AGENDA / KEEP / PROBLEM / TRY
    title: Text
    content: Text = ""


class SummaryRequest(CamelModel):
    max_length: int = Field(default=1000, ge=100, le=5000)
    cards: list[SummaryCard] = Field(min_length=1, max_length=500)


class SummaryResponse(CamelModel):
    content: str
