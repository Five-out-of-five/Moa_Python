from pydantic import Field

from app.domains.common import CamelModel


class EmbeddingRequest(CamelModel):
    # 카드 제목 100자 + 내용 1000자 + 줄바꿈. 넉넉히 둔다.
    text: str = Field(min_length=1, max_length=5000)


class EmbeddingResponse(CamelModel):
    embedding: list[float]
    model: str
