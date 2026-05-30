from typing import TypedDict, List, Optional, Annotated
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_ollama import ChatOllama

# 1. Import your custom tools
from app.agent.tools.vector_search import search_documents
from app.agent.tools.graph_generator import generate_graph


# 2. Define your Graph State
class GraphState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    document_id: Optional[str]


# 3. Setup the tools list and node
tools = [search_documents, generate_graph]
tool_node = ToolNode(tools)

# 4. Initialize ChatOllama with deterministic settings (temperature=0)
llm = ChatOllama(
    model="llama3.1",
    temperature=0
).bind_tools(tools)


# 5. Define your model caller node
def call_model(state: GraphState):
    messages = state["messages"]

    system_instruction = SystemMessage(
        content=(
            "You are an expert financial and healthcare data assistant. "
            "You have two tools available:\n"
            "1. 'search_documents' — use this to look up factual information from uploaded documents.\n"
            "2. 'generate_graph' — use this ONLY when the user explicitly asks for a chart, graph, plot, "
            "or visual breakdown. This tool accepts a single JSON string parameter called 'data_json'.\n\n"
            "CRITICAL RULES:\n"
            "- If the user asks for a chart or graph, you MUST call 'generate_graph'. Do NOT just describe data in text.\n"
            "- First use 'search_documents' to gather the numbers if needed, then call 'generate_graph' with the data.\n"
            "- After calling 'generate_graph', keep your final text response brief (e.g. 'Here is your chart.'). "
            "Do NOT re-list all the data points in your text answer — the chart already shows them."
        )
    )

    # Prepend system rules to conversation
    full_messages = [system_instruction] + messages
    response = llm.invoke(full_messages)
    return {"messages": [response]}


# 6. Construct the State Machine Architecture
workflow = StateGraph(GraphState)

workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", tools_condition)
workflow.add_edge("tools", "agent")

app_graph = workflow.compile()
