"""Chat endpoint — submits a query to the LangGraph RAG agent."""

import asyncio
import json
import re
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

GRAPH_INTENT_PATTERN = re.compile(
    r"\b(chart|graph|plot|visual(?:ization)?|bar\s+chart|line\s+chart|pie\s+chart|scatter(?:\s+plot)?)\b",
    re.IGNORECASE,
)
MONTH_TO_INDEX = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


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


def _query_requests_graph(query: str) -> bool:
    return bool(GRAPH_INTENT_PATTERN.search(query))


def _collect_search_evidence(messages) -> str:
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.name == "search_documents" and isinstance(msg.content, str):
            parts.append(msg.content)
    return "\n".join(parts)


def _extract_graph_axes(graph_payload: dict) -> tuple[list[str], list[float]]:
    payload = graph_payload.get("payload", {})
    traces = payload.get("data", [])
    labels: list[str] = []
    values: list[float] = []

    for trace in traces:
        trace_type = str(trace.get("type", "")).lower()
        if trace_type == "pie":
            trace_labels = trace.get("labels", [])
            trace_values = trace.get("values", [])
        else:
            trace_labels = trace.get("x", [])
            trace_values = trace.get("y", [])

        if isinstance(trace_labels, list):
            labels.extend([str(item).strip() for item in trace_labels if str(item).strip()])
        if isinstance(trace_values, list):
            for item in trace_values:
                try:
                    values.append(float(item))
                except (TypeError, ValueError):
                    continue

    return labels, values


def _number_candidates(value: float) -> set[str]:
    rounded_int = int(round(value))
    rounded_two = round(value, 2)
    candidates = {
        str(value),
        str(rounded_int),
        str(rounded_two),
        f"{rounded_int:,}",
        f"{rounded_two:,.2f}",
    }
    return {candidate.lower() for candidate in candidates}


def _query_requires_full_months(query: str) -> bool:
    has_monthly_phrase = bool(re.search(r"\b(per\s+month|monthly|month\s+by\s+month)\b", query, re.IGNORECASE))
    has_year = bool(re.search(r"\b(19|20)\d{2}\b", query))
    return has_monthly_phrase and has_year


def _validate_graph_grounding(query: str, graph_payload: dict, search_evidence: str) -> tuple[bool, str | None]:
    if not search_evidence.strip():
        return False, "no search evidence available"

    labels, values = _extract_graph_axes(graph_payload)
    if not labels or not values:
        return False, "graph payload is missing labels or values"

    evidence_lc = search_evidence.lower()
    for label in labels:
        label_lc = label.lower()
        if label_lc not in evidence_lc:
            return False, f"label '{label}' not found in retrieved evidence"

    for value in values:
        if not any(candidate in evidence_lc for candidate in _number_candidates(value)):
            return False, f"value '{value}' not found in retrieved evidence"

    if _query_requires_full_months(query):
        month_indices = {MONTH_TO_INDEX[label.lower()] for label in labels if label.lower() in MONTH_TO_INDEX}
        if len(month_indices) != 12:
            return False, "monthly yearly request requires 12 month data points"

    return True, None


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

        graph_requested = _query_requests_graph(request.query)
        graph_payload = _extract_graph_payload(final_state["messages"])
        graph_source = "native" if graph_payload is not None else None

        if graph_requested and graph_payload is None:
            logger.warning(
                "Graph requested but missing from initial response — retrying once with forced graph instruction",
                extra={
                    "user_id": current_user.id,
                    "company_id": current_user.company_id,
                },
            )
            force_graph_message = HumanMessage(
                content=(
                    "The user explicitly requested a chart/graph. "
                    "You must call `generate_graph` in this turn and then respond briefly."
                )
            )
            retry_state = {"messages": final_state["messages"] + [force_graph_message]}
            try:
                final_state = await app_graph.ainvoke(retry_state, config={"recursion_limit": 8})
                graph_payload = _extract_graph_payload(final_state["messages"])
                if graph_payload is not None:
                    graph_source = "forced_retry"
            except GraphRecursionError as exc:
                logger.warning(
                    "Forced graph retry hit recursion limit",
                    extra={
                        "user_id": current_user.id,
                        "company_id": current_user.company_id,
                    },
                    exc_info=exc,
                )
            except Exception as exc:
                logger.warning(
                    "Forced graph retry failed",
                    extra={
                        "user_id": current_user.id,
                        "company_id": current_user.company_id,
                    },
                    exc_info=exc,
                )

        if graph_requested and graph_payload is None:
            logger.warning(
                "Graph still missing after first retry — forcing a tool-call-only retry",
                extra={
                    "user_id": current_user.id,
                    "company_id": current_user.company_id,
                },
            )
            force_tool_call_only = HumanMessage(
                content=(
                    "You failed to call the tool in the previous turn. "
                    "In this turn, you MUST emit a real tool call to `generate_graph` only. "
                    "Do not output JSON text that looks like a tool call. "
                    "Do not output prose before calling the tool."
                )
            )
            retry_state = {"messages": final_state["messages"] + [force_tool_call_only]}
            try:
                final_state = await app_graph.ainvoke(retry_state, config={"recursion_limit": 8})
                graph_payload = _extract_graph_payload(final_state["messages"])
                if graph_payload is not None:
                    graph_source = "forced_retry"
            except GraphRecursionError as exc:
                logger.warning(
                    "Tool-call-only retry hit recursion limit",
                    extra={
                        "user_id": current_user.id,
                        "company_id": current_user.company_id,
                    },
                    exc_info=exc,
                )
            except Exception as exc:
                logger.warning(
                    "Tool-call-only retry failed",
                    extra={
                        "user_id": current_user.id,
                        "company_id": current_user.company_id,
                    },
                    exc_info=exc,
                )

        elapsed = time.monotonic() - start
        final_message = final_state["messages"][-1].content

        if graph_requested and graph_payload is None:
            logger.error(
                "Graph requested but no native generate_graph tool call was produced",
                extra={
                    "user_id": current_user.id,
                    "company_id": current_user.company_id,
                    "message_turns": len(final_state["messages"]),
                },
            )
            raise AgentError(
                "Chart generation failed because the model did not produce a native graph tool call. "
                "Please retry your request."
            )

        if graph_requested and graph_payload is not None:
            search_evidence = _collect_search_evidence(final_state["messages"])
            is_grounded, reason = _validate_graph_grounding(request.query, graph_payload, search_evidence)
            if not is_grounded:
                logger.error(
                    "Graph rejected — data not grounded in search evidence",
                    extra={
                        "user_id": current_user.id,
                        "company_id": current_user.company_id,
                        "reason": reason,
                    },
                )
                raise AgentError(
                    "Chart generation failed validation because the plotted data was not fully grounded in "
                    "retrieved documents. Please upload complete monthly revenue figures and retry."
                )
            graph_source = f"{graph_source}_grounded" if graph_source else "grounded"

        logger.info(
            "Chat response ready",
            extra={
                "user_id": current_user.id,
                "company_id": current_user.company_id,
                "elapsed_s": round(elapsed, 3),
                "has_graph": graph_payload is not None,
                "graph_requested": graph_requested,
                "graph_source": graph_source,
                "message_turns": len(final_state["messages"]),
            },
        )
        return ChatResponse(response=final_message, graph=graph_payload)
    finally:
        reset_search_query_state(search_query_state_token)
        reset_search_company_scope(search_scope_token)
