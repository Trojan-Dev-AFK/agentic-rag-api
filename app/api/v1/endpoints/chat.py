"""Chat endpoint — submits a query to the LangGraph RAG agent."""

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from app.agent.graph import app_graph
from app.agent.tools.vector_search import (
    reset_search_company_scope,
    reset_search_query_state,
    set_search_company_scope,
    set_search_query_state,
    warmup_vector_search,
)
from app.api.dependencies import get_current_user, require_company_user
from app.core.exceptions import AgentError
from app.core.logger import get_logger
from app.db.models import User
from app.schemas.chat import ChatRequest, ChatResponse, WarmupResponse

logger = get_logger(__name__)
router = APIRouter()


@router.post(
    "/warmup",
    response_model=WarmupResponse,
    responses={
        502: {"description": "Warmup failed — embedding model could not be loaded."},
    },
)
async def warmup_agent(current_user: User = Depends(get_current_user)):
    """Warm up agent resources so the next chat request avoids embedding-model cold start latency."""
    start = time.monotonic()
    try:
        loaded_now = await asyncio.to_thread(warmup_vector_search)
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error(
            "Agent warmup failed",
            extra={"user_id": current_user.id, "elapsed_s": round(elapsed, 3)},
            exc_info=exc,
        )
        raise AgentError("Agent warmup failed. Please try again.") from exc

    elapsed = time.monotonic() - start
    logger.info(
        "Agent warmup completed",
        extra={
            "user_id": current_user.id,
            "elapsed_s": round(elapsed, 3),
            "embeddings_loaded_now": loaded_now,
        },
    )
    return WarmupResponse(
        message="Agent warmup completed",
        embeddings_loaded_now=loaded_now,
        elapsed_seconds=round(elapsed, 3),
    )


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

    if not current_user.company_id:
        logger.warning(
            "Chat blocked — user has no company scope",
            extra={"user_id": current_user.id, "role": str(current_user.role)},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )

    start = time.monotonic()
    search_scope_token = set_search_company_scope(current_user.company_id)
    search_query_state_token = set_search_query_state()
    try:
        initial_state = {"messages": [HumanMessage(content=request.query)]}
        final_state = await app_graph.ainvoke(initial_state, config={"recursion_limit": 8})
    except GraphRecursionError as exc:
        elapsed = time.monotonic() - start
        logger.error(
            "Agent halted by recursion limit",
            extra={
                "user_id": current_user.id,
                "company_id": current_user.company_id,
                "elapsed_s": round(elapsed, 3),
            },
            exc_info=exc,
        )
        raise AgentError(
            "The agent could not converge on an answer. Please rephrase your question with more specific details."
        ) from exc
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
    finally:
        reset_search_query_state(search_query_state_token)
        reset_search_company_scope(search_scope_token)

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
