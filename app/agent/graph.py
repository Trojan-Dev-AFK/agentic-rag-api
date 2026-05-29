# Compiles the LangGraph state machine

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage

from app.agent.state import AgentState
from app.agent.tools.vector_search import search_documents

# 1. Define the tools available to the agent
tools = [search_documents]

# 2. Initialize the completely FREE, local open-source LLM
# Llama 3.1 (8B) has native tool-calling capabilities.
llm = ChatOllama(model="llama3.1", temperature=0)
llm_with_tools = llm.bind_tools(tools)


# 3. Define the Agent Node Logic
def call_model(state: AgentState):
    messages = state["messages"]

    # Inject the system prompt if this is the start of the conversation
    if not any(isinstance(m, SystemMessage) for m in messages):
        sys_msg = SystemMessage(
            content="You are an expert data analysis assistant. Use your search tool to find factual information from the user's documents. Always base your answers on the retrieved data. Do not make up information."
        )
        messages = [sys_msg] + messages

    # Call the local Llama 3.1 model
    response = llm_with_tools.invoke(messages)

    # Return the new message to be appended to the state
    return {"messages": [response]}


# 4. Build the State Machine (The Graph)
workflow = StateGraph(AgentState)

# Add our two nodes
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(tools))

# The graph always starts at the agent
workflow.set_entry_point("agent")

# 5. Add Conditional Routing
# tools_condition automatically checks if Llama 3.1 requested a tool.
# If yes -> route to "tools". If no -> route to END.
workflow.add_conditional_edges(
    "agent",
    tools_condition,
    {"tools": "tools", "__end__": END}
)

# After the tool runs, ALWAYS force it to go back to the agent to read the results
workflow.add_edge("tools", "agent")

# Compile the graph into a runnable application
app_graph = workflow.compile()
