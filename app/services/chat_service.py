"""Business logic for invoking the LangGraph chat workflow."""

import time

from fastapi import HTTPException, status
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from app.agent.graph import app_graph
from app.agent.tools.vector_search import (
    reset_search_company_scope,
    reset_search_query_state,
    set_search_company_scope,
    set_search_query_state,
)
from app.core.exceptions import AgentError
from app.core.logger import get_logger
from app.db.models import User

logger = get_logger(__name__)


async def invoke_agent(*, query: str, current_user: User) -> str:
    """Run the graph workflow for a company-scoped user query and return final text answer."""
    logger.info(
        "Chat query received",
        extra={
            "user_id": current_user.id,
            "role": str(current_user.role),
            "company_id": current_user.company_id,
            "query_preview": query[:120],
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
        initial_state = {"messages": [HumanMessage(content=query)]}
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
    if not isinstance(final_message, str):
        final_message = str(final_message)

    logger.info(
        "Chat response ready",
        extra={
            "user_id": current_user.id,
            "company_id": current_user.company_id,
            "elapsed_s": round(elapsed, 3),
            "message_turns": len(final_state["messages"]),
        },
    )
    return final_message
