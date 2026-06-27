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
from app.core.exceptions import AgentError
from app.core.logger import get_logger
from app.db.models import ChatConversation, ChatMessage, User
from app.schemas.chat import ChatConversationResponse, ChatMessageResponse

logger = get_logger(__name__)


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
) -> tuple[str, str]:
    """Run the graph workflow, persist user/assistant turns, and return answer plus conversation ID."""
    logger.info(
        "Chat query received",
        extra={
            "user_id": current_user.id,
            "role": str(current_user.role),
            "company_id": current_user.company_id,
            "conversation_id": conversation_id,
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
    return final_message, conversation.id


async def list_conversations(*, db: AsyncSession, current_user: User) -> list[ChatConversationResponse]:
    """List all conversations owned by the current user, newest first."""
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )

    result = await db.execute(
        select(ChatConversation)
        .where(
            ChatConversation.user_id == current_user.id,
            ChatConversation.company_id == current_user.company_id,
        )
        .order_by(ChatConversation.updated_at.desc())
    )
    conversations = result.scalars().all()
    return [_to_conversation_response(item) for item in conversations]


async def get_conversation_messages(
    *,
    conversation_id: str,
    db: AsyncSession,
    current_user: User,
) -> list[ChatMessageResponse]:
    """Return persisted messages for one user-scoped conversation."""
    conversation = await _get_scoped_conversation(
        conversation_id=conversation_id,
        current_user=current_user,
        db=db,
    )

    result = await db.execute(
        select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()
    return [_to_message_response(item) for item in messages]
