"""Business logic for invoking the LangGraph chat workflow."""

import time
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import app_graph
from app.agent.tools.vector_search import (
    reset_search_company_scope,
    reset_search_query_state,
    set_search_company_scope,
    set_search_query_state,
)
from app.core.config import settings
from app.core.exceptions import AgentError
from app.core.logger import get_logger
from app.core.runtime_controls import (
    cache_delete_prefix,
    cache_get_json,
    cache_set_json,
    idempotency_get,
    idempotency_set,
    rate_limit_exceeded,
)
from app.db.models import ChatConversation, ChatMessage, User
from app.schemas.chat import ChatConversationResponse, ChatMessageResponse
from app.services.common import sanitize_pagination

logger = get_logger(__name__)

def _conversation_list_cache_key(*, user_id: str, company_id: str) -> str:
    return f"cache:chat:conversations:{company_id}:{user_id}"


def _conversation_messages_cache_key(*, conversation_id: str) -> str:
    return f"cache:chat:messages:{conversation_id}"


def _to_conversation_response(conversation: ChatConversation) -> ChatConversationResponse:
    """Map ORM conversation model to API response object."""
    return ChatConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _to_message_response(message: ChatMessage) -> ChatMessageResponse:
    """Map ORM message model to API response object."""
    return ChatMessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        query=message.user_query,
        response=message.assistant_response,
        created_at=message.created_at,
    )


async def _get_scoped_conversation(
    *,
    conversation_id: str,
    current_user: User,
    db: AsyncSession,
) -> ChatConversation:
    """Return a conversation only when it belongs to the authenticated user and company."""
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
            ChatConversation.company_id == current_user.company_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        logger.warning(
            "Conversation access denied or not found",
            extra={
                "conversation_id": conversation_id,
                "user_id": current_user.id,
                "company_id": current_user.company_id,
            },
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


def _build_history_messages(history_rows: list[ChatMessage]) -> list[HumanMessage | AIMessage]:
    """Convert persisted chat messages into LangChain message objects."""
    messages: list[HumanMessage | AIMessage] = []
    for row in history_rows:
        messages.append(HumanMessage(content=row.user_query))
        messages.append(AIMessage(content=row.assistant_response))
    return messages


async def invoke_agent(
    *,
    query: str,
    current_user: User,
    db: AsyncSession,
    conversation_id: str | None,
    idempotency_key: str | None,
) -> tuple[str, str]:
    """Run the graph workflow, persist user/assistant turns, and return answer plus conversation ID."""
    logger.info(
        "Chat query received",
        extra={
            "user_id": current_user.id,
            "role": str(current_user.role),
            "company_id": current_user.company_id,
            "conversation_id": conversation_id,
            "idempotency_key": bool(idempotency_key),
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

    chat_limit_key = f"rl:chat:{current_user.id}"
    if await rate_limit_exceeded(
        key=chat_limit_key,
        limit=settings.CHAT_RATE_LIMIT_REQUESTS,
        window_seconds=settings.CHAT_RATE_LIMIT_WINDOW_SECONDS,
    ):
        logger.warning("Chat invoke throttled by rate limiter", extra={"user_id": current_user.id})
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many chat requests")

    idem_cache_key: str | None = None
    normalized_idem = (idempotency_key or "").strip()
    if normalized_idem:
        idem_cache_key = f"idem:chat:{current_user.id}:{normalized_idem}"
        cached = await idempotency_get(key=idem_cache_key)
        if cached:
            return cached

    if conversation_id:
        conversation = await _get_scoped_conversation(
            conversation_id=conversation_id,
            current_user=current_user,
            db=db,
        )
    else:
        conversation = ChatConversation(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            company_id=current_user.company_id,
            title=query[:120],
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)

    history_result = await db.execute(
        select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.created_at.asc())
    )
    history_rows = history_result.scalars().all()
    history_messages = _build_history_messages(history_rows)

    start = time.monotonic()
    search_scope_token = set_search_company_scope(current_user.company_id)
    search_query_state_token = set_search_query_state()
    try:
        initial_state = {"messages": [*history_messages, HumanMessage(content=query)]}
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

    db.add(
        ChatMessage(
            conversation_id=conversation.id,
            user_query=query,
            assistant_response=final_message,
        )
    )
    conversation.updated_at = datetime.now(UTC)
    await db.commit()

    await cache_delete_prefix(
        prefix=_conversation_list_cache_key(user_id=current_user.id, company_id=current_user.company_id)
    )
    await cache_delete_prefix(prefix=_conversation_messages_cache_key(conversation_id=conversation.id))

    logger.info(
        "Chat response ready",
        extra={
            "user_id": current_user.id,
            "company_id": current_user.company_id,
            "conversation_id": conversation.id,
            "elapsed_s": round(elapsed, 3),
            "message_turns": len(final_state["messages"]),
        },
    )

    if idem_cache_key:
        await idempotency_set(
            key=idem_cache_key,
            response=final_message,
            conversation_id=conversation.id,
            ttl_seconds=settings.CHAT_IDEMPOTENCY_TTL_SECONDS,
        )

    return final_message, conversation.id


async def list_conversations(
    *,
    db: AsyncSession,
    current_user: User,
    limit: int | None = None,
    offset: int | None = None,
) -> list[ChatConversationResponse]:
    """List all conversations owned by the current user, newest first."""
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )

    safe_limit, safe_offset = sanitize_pagination(limit=limit, offset=offset)
    cache_key = f"{_conversation_list_cache_key(user_id=current_user.id, company_id=current_user.company_id)}:{safe_limit}:{safe_offset}"
    cached = await cache_get_json(key=cache_key)
    if isinstance(cached, list):
        try:
            return [ChatConversationResponse(**item) for item in cached if isinstance(item, dict)]
        except Exception as exc:
            logger.warning(
                "Conversation list cache payload invalid — bypassing cache",
                extra={"key": cache_key, "user_id": current_user.id},
                exc_info=exc,
            )

    result = await db.execute(
        select(ChatConversation)
        .where(
            ChatConversation.user_id == current_user.id,
            ChatConversation.company_id == current_user.company_id,
        )
        .order_by(ChatConversation.updated_at.desc())
        .offset(safe_offset)
        .limit(safe_limit)
    )
    conversations = result.scalars().all()
    response_rows = [_to_conversation_response(item) for item in conversations]
    await cache_set_json(
        key=cache_key,
        payload=[item.model_dump(mode="json") for item in response_rows],
        ttl_seconds=settings.CHAT_HISTORY_CACHE_TTL_SECONDS,
    )
    return response_rows


async def get_conversation_messages(
    *,
    conversation_id: str,
    db: AsyncSession,
    current_user: User,
    limit: int | None = None,
    offset: int | None = None,
) -> list[ChatMessageResponse]:
    """Return persisted messages for one user-scoped conversation."""
    conversation = await _get_scoped_conversation(conversation_id=conversation_id, current_user=current_user, db=db)

    safe_limit, safe_offset = sanitize_pagination(limit=limit, offset=offset)
    cache_key = f"{_conversation_messages_cache_key(conversation_id=conversation.id)}:{safe_limit}:{safe_offset}"
    cached = await cache_get_json(key=cache_key)
    if isinstance(cached, list):
        try:
            return [ChatMessageResponse(**item) for item in cached if isinstance(item, dict)]
        except Exception as exc:
            logger.warning(
                "Conversation messages cache payload invalid — bypassing cache",
                extra={"key": cache_key, "conversation_id": conversation.id},
                exc_info=exc,
            )

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation.id)
        .order_by(ChatMessage.created_at.asc())
        .offset(safe_offset)
        .limit(safe_limit)
    )
    messages = result.scalars().all()
    response_rows = [_to_message_response(item) for item in messages]
    await cache_set_json(
        key=cache_key,
        payload=[item.model_dump(mode="json") for item in response_rows],
        ttl_seconds=settings.CHAT_HISTORY_CACHE_TTL_SECONDS,
    )
    return response_rows
