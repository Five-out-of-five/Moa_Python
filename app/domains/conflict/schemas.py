from pydantic import Field

from app.domains.common import CamelModel, Text


class ConflictCard(CamelModel):
    id: int
    title: Text
    content: Text = ""


class ConflictDetectRequest(CamelModel):
    card: ConflictCard
    candidates: list[ConflictCard] = Field(default_factory=list, max_length=50)


class ConflictItem(CamelModel):
    card_id: int
    reason: str


class ConflictDetectResponse(CamelModel):
    conflicts: list[ConflictItem]
