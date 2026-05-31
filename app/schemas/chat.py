"""Request / response schemas for the agent chat endpoint."""

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Natural-language query sent to the RAG agent."""

    query: str = Field(
        description="The question or instruction for the agent. "
        "The agent will search uploaded documents and optionally generate a chart.",
        min_length=1,
    )

    model_config = ConfigDict(json_schema_extra={"example": {"query": "What was the total revenue for Q3 2025?"}})


class ChatResponse(BaseModel):
    """Agent response containing a text answer and an optional Plotly chart."""

    response: str = Field(description="Agent's text answer.")
    graph: dict | None = Field(
        default=None,
        description=(
            "Plotly figure payload when the agent called `generate_graph`, otherwise `null`. "
            "Contains `is_graph: true`, `chart_type`, and a `payload` object with `data` and `layout` keys "
            "compatible with the Plotly.js `Plotly.newPlot()` API."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "response": "Total Q3 2025 revenue was $4.2 million across all regions.",
                "graph": None,
            }
        }
    )
