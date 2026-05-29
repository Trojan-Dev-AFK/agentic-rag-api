# Defines the TypedDict for agent state
from typing import TypedDict, Sequence, Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # The "add_messages" annotation is critical.
    # It tells LangGraph: "Don't overwrite the messages array on each loop. Append to it."
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # We store the document_id so the agent knows which document the user is asking about
    document_id: str | None
