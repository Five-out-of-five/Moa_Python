from pydantic import Field

from app.domains.common import CamelModel, Text


class ContextCard(CamelModel):
    id: int
    type: str = ""
    title: Text
    content: Text = ""


class ContextTask(CamelModel):
    id: int
    title: Text
    status: str = ""


class ContextVote(CamelModel):
    id: int
    title: Text


class ContextMood(CamelModel):
    mood: str


class AssistantContext(CamelModel):
    cards: list[ContextCard] = Field(default_factory=list)
    tasks: list[ContextTask] = Field(default_factory=list)
    votes: list[ContextVote] = Field(default_factory=list)
    moods: list[ContextMood] = Field(default_factory=list)


class AssistantRequest(CamelModel):
    room_id: int
    question: Text = Field(min_length=1, max_length=500)
    context: AssistantContext = Field(default_factory=AssistantContext)
