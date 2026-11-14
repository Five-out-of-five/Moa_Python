from pydantic import Field

from app.domains.common import CamelModel, Text


class ContextCard(CamelModel):
    id: int
    type: str = ""
    title: Text
    content: Text = ""
    # 작성자의 방 표시 이름. 나간 멤버는 "나간 멤버". 예전 Spring 은 보내지 않아 비어 있을 수 있다.
    writer: Text = ""


class ContextTask(CamelModel):
    id: int
    title: Text
    status: str = ""
    # 담당자의 방 표시 이름. 없으면 "담당자 없음", 나간 멤버는 "나간 멤버".
    assignee: Text = ""
    # 마감일(한국 날짜, yyyy-MM-dd). 없으면 None.
    due_date: str | None = None


class ContextVote(CamelModel):
    id: int
    title: Text


class ContextMood(CamelModel):
    mood: str


class AssistantContext(CamelModel):
    # 오늘 한국 날짜(yyyy-MM-dd). 마감 임박·지남을 계산하는 기준이다.
    today: str | None = None
    cards: list[ContextCard] = Field(default_factory=list)
    tasks: list[ContextTask] = Field(default_factory=list)
    votes: list[ContextVote] = Field(default_factory=list)
    moods: list[ContextMood] = Field(default_factory=list)


class AssistantRequest(CamelModel):
    room_id: int
    question: Text = Field(min_length=1, max_length=500)
    context: AssistantContext = Field(default_factory=AssistantContext)
