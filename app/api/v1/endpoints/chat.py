"""Chat endpoint — submits a query to the LangGraph RAG agent."""

import json
import time

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage, ToolMessage

from app.agent.graph import app_graph
from app.api.dependencies import require_company_user
from app.core.exceptions import AgentError
from app.core.logger import get_logger
from app.db.models import User
from app.schemas.chat import ChatRequest, ChatResponse

logger = get_logger(__name__)
router = APIRouter()


def _extract_graph_payload(messages) -> dict | None:
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.name == "generate_graph":
            try:
                payload = json.loads(msg.content)
                if payload.get("is_graph"):
                    return payload
            except (json.JSONDecodeError, AttributeError):
                continue
    return None


@router.post(
    "/invoke",
    response_model=ChatResponse,
    responses={
        403: {"description": "Forbidden — `super_admin` accounts cannot use chat."},
        502: {"description": "Agent service unavailable — LLM or tool call failed."},
    },
)
async def invoke_agent(
    request: ChatRequest,
    current_user: User = Depends(require_company_user),
):
    """
    Submit a natural-language query to the RAG agent.

    The agent follows a reasoning loop (LangGraph):
    1. Calls `search_documents` to retrieve relevant text from uploaded PDFs.
    2. Optionally calls `generate_graph` if the user requests a chart.
    3. Returns a final text answer and an optional Plotly figure payload.

    **Access:** `admin` and `employee` only. `super_admin` receives **403**.
    """
    logger.info(
        "Chat query received",
        extra={
            "user_id": current_user.id,
            "role": str(current_user.role),
            "company_id": current_user.company_id,
            "query_preview": request.query[:120],
        },
    )

    start = time.monotonic()
    try:
        initial_state = {"messages": [HumanMessage(content=request.query)]}
        final_state = await app_graph.ainvoke(initial_state)
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error(
            "Agent invocation failed",
            extra={
                "user_id": current_user.id,
                "company_id": current_user.company_id,
                "elapsed_s": round(elapsed, 3),
            },
            exc_info=exc,
        )
        raise AgentError("The agent failed to process your request. Please try again.") from exc

    elapsed = time.monotonic() - start
    final_message = final_state["messages"][-1].content
    graph_payload = _extract_graph_payload(final_state["messages"])

    logger.info(
        "Chat response ready",
        extra={
            "user_id": current_user.id,
            "company_id": current_user.company_id,
            "elapsed_s": round(elapsed, 3),
            "has_graph": graph_payload is not None,
            "message_turns": len(final_state["messages"]),
        },
    )
    return ChatResponse(response=final_message, graph=graph_payload)
