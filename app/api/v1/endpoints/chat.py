"""Chat endpoint — submits a query to the LangGraph RAG agent."""

from fastapi import APIRouter, Depends

from app.api.dependencies import require_company_user
from app.db.models import User
from app.schemas.chat import ChatRequest, ChatResponse
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
    current_user: User = Depends(require_company_user),
):
    """
    Submit a natural-language query to the RAG agent.

    The agent follows a reasoning loop (LangGraph):
    1. Calls `search_documents` to retrieve relevant text from uploaded PDFs.
    2. Returns a final text answer.

    **Access:** `admin` and `employee` only. `super_admin` receives **403**.
    """
    response_text = await chat_service.invoke_agent(query=request.query, current_user=current_user)
    return ChatResponse(response=response_text)
