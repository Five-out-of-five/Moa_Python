from pydantic import Field

from app.domains.common import CamelModel, Text


class LayoutRecommendRequest(CamelModel):
    purpose: Text = Field(min_length=1, max_length=500)
    widget_types: list[str] = Field(min_length=1, max_length=30)
    grid_columns: int = Field(default=12, ge=4, le=24)


class WidgetPlacement(CamelModel):
    widget_type: str
    x: int
    y: int
    w: int
    h: int


class LayoutRecommendResponse(CamelModel):
    widgets: list[WidgetPlacement]
    reason: str
