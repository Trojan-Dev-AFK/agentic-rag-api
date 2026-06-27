"""Request / response schemas for the agent chat endpoint."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import FormattedDatetime


class ChatRequest(BaseModel):
    """Natural-language query sent to the RAG agent."""

    query: str = Field(
        description="The question or instruction for the agent. The agent will search uploaded documents.",
        min_length=1,
    )
    conversation_id: str | None = Field(
        default=None,
        description=(
            "Existing conversation UUID to continue. " "If omitted, a new conversation is created automatically."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "What was the total revenue for Q3 2025?",
                "conversation_id": "7bd56ad4-3885-4f9b-bd12-118584989f09",
            }
        }
    )


class ChatResponse(BaseModel):
    """Agent response containing a text answer."""

    response: str = Field(description="Agent's text answer.")
    conversation_id: str = Field(description="Conversation UUID where this Q/A turn was persisted.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "response": "Total Q3 2025 revenue was $4.2 million across all regions.",
                "conversation_id": "7bd56ad4-3885-4f9b-bd12-118584989f09",
            }
        }
    )


class ChatConversationResponse(BaseModel):
    """Conversation metadata for history listing."""

    id: str = Field(description="Conversation UUID.")
    title: str | None = Field(default=None, description="Optional conversation title derived from the first query.")
    created_at: FormattedDatetime = Field(
        description="Conversation creation time formatted as `DD:MM:YYYY HH:MM:SS.mmm` (UTC)."
    )
    updated_at: FormattedDatetime = Field(
        description="Latest activity time formatted as `DD:MM:YYYY HH:MM:SS.mmm` (UTC)."
    )


class ChatMessageResponse(BaseModel):
    """A single persisted Q/A turn in a conversation."""

    id: str = Field(description="Message UUID.")
    conversation_id: str = Field(description="Parent conversation UUID.")
    query: str = Field(description="Original user question for this turn.")
    response: str = Field(description="Assistant response for this turn.")
    created_at: FormattedDatetime = Field(
        description="Message creation time formatted as `DD:MM:YYYY HH:MM:SS.mmm` (UTC)."
    )
