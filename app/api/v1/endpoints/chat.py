from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any
from langchain_core.messages import HumanMessage

from app.agent.graph import app_graph

# 1. Initialize the router
router = APIRouter()

# 2. Define strict Pydantic schemas for request and response
class ChatRequest(BaseModel):
    query: str
    document_id: Optional[str] = None  # Optional: Let the user filter by a specific PDF

class ChatResponse(BaseModel):
    response: str

# 3. The Endpoint
@router.post("/invoke", response_model=ChatResponse)
async def invoke_agent(request: ChatRequest):
    try:
        # Step A: Format the user's input into LangGraph's expected state dictionary
        initial_state = {
            "messages": [HumanMessage(content=request.query)],
            "document_id": request.document_id
        }

        # Step B: Trigger the graph.
        # We use .ainvoke() because FastAPI is asynchronous and our tool (search_documents) is async.
        final_state = await app_graph.ainvoke(initial_state)

        # Step C: Extract the final string from the Agent's last message
        final_message = final_state["messages"][-1].content

        return ChatResponse(response=final_message)

    except Exception as e:
        # Catch any LLM timeouts or database errors and return a clean 500
        raise HTTPException(status_code=500, detail=f"Agent orchestration failed: {str(e)}")
