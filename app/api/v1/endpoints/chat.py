"""Chat endpoint — submits a query to the LangGraph RAG agent."""

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_company_user
from app.api.v1.endpoints.common import build_list_service_kwargs
from app.db.models import User
from app.db.session import get_db
from app.schemas.chat import ChatConversationResponse, ChatMessageResponse, ChatRequest, ChatResponse
from app.services import chat_service

router = APIRouter()


@router.post(
    "/invoke",
    response_model=ChatResponse,
    responses={
        403: {"description": "Forbidden — `super_admin` accounts cannot use chat."},
        429: {"description": "Too many chat requests."},
        502: {"description": "Agent service unavailable — LLM or tool call failed."},
    },
)
async def invoke_agent(
    request: ChatRequest,
    idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_company_user),
):
    """
    Submit a natural-language query to the RAG agent.

    The agent follows a reasoning loop (LangGraph):
    1. Calls `search_documents` to retrieve relevant text from uploaded PDFs.
    2. Returns a final text answer.

    **Access:** `admin` and `employee` only. `super_admin` receives **403**.
    """
    response_text, conversation_id = await chat_service.invoke_agent(
        query=request.query,
        conversation_id=request.conversation_id,
        idempotency_key=idempotency_key,
        db=db,
        current_user=current_user,
    )
    return ChatResponse(response=response_text, conversation_id=conversation_id)


@router.post(
    "/stream",
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "example": 'event: token\\ndata: {"text":"Hello"}\\n\\nevent: done\\ndata: {"conversation_id":"...","cached":false}\\n\\n'
                }
            },
            "description": "Server-sent event stream of incremental chat tokens and completion metadata.",
        },
        403: {"description": "Forbidden — `super_admin` accounts cannot use chat."},
        429: {"description": "Too many chat requests."},
    },
)
async def stream_agent(
    request: ChatRequest,
    idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_company_user),
):
    """Stream the chat response as SSE token events, then emit a final done event."""
    event_stream = await chat_service.create_streaming_response(
        query=request.query,
        conversation_id=request.conversation_id,
        idempotency_key=idempotency_key,
        db=db,
        current_user=current_user,
    )
    return StreamingResponse(
        event_stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=list[ChatConversationResponse])
async def list_conversations(
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_company_user),
):
    """List persisted chat conversations for the current authenticated user."""
    return await chat_service.list_conversations(
        **build_list_service_kwargs(
            db=db,
            current_user=current_user,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[ChatMessageResponse])
async def get_conversation_messages(
    conversation_id: str,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_company_user),
):
    """Get persisted messages for one conversation owned by the current user."""
    return await chat_service.get_conversation_messages(
        **build_list_service_kwargs(
            db=db,
            current_user=current_user,
            limit=limit,
            offset=offset,
            conversation_id=conversation_id,
        ),
    )
