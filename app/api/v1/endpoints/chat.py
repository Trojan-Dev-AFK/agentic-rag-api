"""Chat endpoint — submits a query to the LangGraph RAG agent."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_company_user
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
        502: {"description": "Agent service unavailable — LLM or tool call failed."},
    },
)
async def invoke_agent(
    request: ChatRequest,
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
        db=db,
        current_user=current_user,
    )
    return ChatResponse(response=response_text, conversation_id=conversation_id)


@router.get("/conversations", response_model=list[ChatConversationResponse])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_company_user),
):
    """List persisted chat conversations for the current authenticated user."""
    return await chat_service.list_conversations(db=db, current_user=current_user)


@router.get("/conversations/{conversation_id}/messages", response_model=list[ChatMessageResponse])
async def get_conversation_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_company_user),
):
    """Get persisted messages for one conversation owned by the current user."""
    return await chat_service.get_conversation_messages(
        conversation_id=conversation_id,
        db=db,
        current_user=current_user,
    )
