from app.domains.common import CamelModel, Text


class CompromiseCard(CamelModel):
    title: Text
    content: Text = ""


class CompromiseRequest(CamelModel):
    card_type: str  # AGENDA / TRY (compromise_draft.card_type)
    card_a: CompromiseCard
    card_b: CompromiseCard


class CompromiseResponse(CamelModel):
    title: str
    content: str
