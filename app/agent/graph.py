"""LangGraph StateGraph definition — agent node, tool node, and compiled graph."""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent.tools.graph_generator import generate_graph
from app.agent.tools.vector_search import search_documents
from app.core.logger import get_logger

logger = get_logger(__name__)


class GraphState(TypedDict):
    """Typed state passed between nodes in the LangGraph reasoning loop."""

    messages: Annotated[list[BaseMessage], add_messages]


tools = [search_documents, generate_graph]
tool_node = ToolNode(tools)

logger.info("Initialising LLM", extra={"model": "llama3.1", "temperature": 0})
llm = ChatOllama(model="llama3.1", temperature=0).bind_tools(tools)
logger.info("LLM initialised")


def call_model(state: GraphState):
    """Invoke the LLM with the current message history and return its response."""
    messages = state["messages"]
    logger.debug("Agent node invoked", extra={"message_count": len(messages)})

    system_instruction = SystemMessage(
        content=(
            "You are an expert financial and healthcare data assistant. "
            "You have two tools available:\n"
            "1. 'search_documents' — use this to look up factual information from uploaded documents.\n"
            "2. 'generate_graph' — use this ONLY when the user explicitly asks for a chart, graph, plot, "
            "or visual breakdown. This tool accepts a single JSON string parameter called 'data_json'.\n\n"
            "CRITICAL RULES:\n"
            "- If the user asks for a chart or graph, you MUST call 'generate_graph'."
            " Do NOT just describe data in text.\n"
            "- First use 'search_documents' to gather the numbers if needed,"
            " then call 'generate_graph' with the data.\n"
            "- Never call 'search_documents' repeatedly with the same query in a loop."
            " If you already called it and have results, produce a final answer.\n"
            "- After calling 'generate_graph', keep your final text response brief (e.g. 'Here is your chart.'). "
            "Do NOT re-list all the data points in your text answer — the chart already shows them."
        )
    )

    try:
        response = llm.invoke([system_instruction] + messages)
    except Exception as exc:
        logger.error("LLM invocation failed", exc_info=exc)
        raise

    logger.debug(
        "Agent node completed",
        extra={"has_tool_calls": bool(getattr(response, "tool_calls", None))},
    )
    return {"messages": [response]}


workflow = StateGraph(GraphState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", tools_condition)
workflow.add_edge("tools", "agent")

app_graph = workflow.compile()
logger.info("LangGraph agent compiled and ready")
