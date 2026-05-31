import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage, ToolMessage

from app.agent.graph import app_graph
from app.api.dependencies import require_company_user
from app.db.models import User
from app.schemas.chat import ChatRequest, ChatResponse

# 1. Initialize the router
router = APIRouter()


def _extract_graph_payload(messages) -> Optional[dict]:
    """
    Walk backward through the message history to find a ToolMessage
    from generate_graph that contains a valid Plotly payload.
    """
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.name == "generate_graph":
            try:
                payload = json.loads(msg.content)
                if payload.get("is_graph"):
                    return payload
            except (json.JSONDecodeError, AttributeError):
                continue
    return None


# 3. The Endpoint
@router.post("/invoke", response_model=ChatResponse)
async def invoke_agent(request: ChatRequest, current_user: User = Depends(require_company_user)):
    try:
        # Step A: Format the user's input into LangGraph's expected state dictionary
        initial_state = {
            "messages": [HumanMessage(content=request.query)]
        }

        # Step B: Trigger the graph.
        # We use .ainvoke() because FastAPI is asynchronous and our tool (search_documents) is async.
        final_state = await app_graph.ainvoke(initial_state)

        # Step C: Extract the final text from the Agent's last message
        final_message = final_state["messages"][-1].content

        # Step D: Check if a graph was generated during the agent loop
        graph_payload = _extract_graph_payload(final_state["messages"])

        return ChatResponse(response=final_message, graph=graph_payload)

    except Exception as e:
        # Catch any LLM timeouts or database errors and return a clean 500
        raise HTTPException(status_code=500, detail=f"Agent orchestration failed: {str(e)}")

