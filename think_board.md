# Overview:

1) For a complex application which combines REST API and asynchronous workload, separation of concern is the primary goal.
2) If we tightly couple the API routing with LLM prompts or database queries, the codebase will become unmaintainable quickly.
3) The strucure followed in this project isolates the web server, AI agent, background worker, and database.

# Why this specific structure?

1) The agent/ folder is completely decoupled from the api/ folder. This is the most critical architectural decision. The FastAPI endpoints in app/api should know nothing about LangChain, token limits, or prompts. The chat.py endpints simply receives a string, imports the compiled graph from app/agent/graph.py, passes the string to it, and waits for the final state to return. This allows us to test our agent via the CLI without even booting up the web server.
2) State and Nodes are isolated. LangGraph relies heavily on state manipulation. By keeping your state.py (the structure of our memory) separate from our nodes/ (the functions that modify the memory), we make debugging complex agen loops much easier.
3) Prompts are treated like configurations. Hardcoding 50-line LLM instructions inside Python functions makes code unreadable. Moving them to app/agent/prompts/ allows us to version-control and tweak our prompt engineering without touching the core execution logic.
4) Dedicated worker/ directory. Because generating embeddings for a 100-page PDF will block the FastAPI event loop, that logic lives entirely inside app/worker/tasks.py. The API simply accepts the file and hands it off to this directory via Redis.

# Why are we using REST instead of GraphQL:

1) File upload problem:

- REST handles file uploads natively and efficiently using multipart/form-data. FastAPI makes this trivially easy.
- GraphQL is strictly designed for JSON. Handling binary file uploads in pure GraphQL is notoriously clunky, often requiring external libraries (like graphql-upload) or forcing us to build a separate REST endpoint just for the files anyway.

2) Asynchronous Workflows (Agent takes time):

- In REST, we can easily implement a webhook pattern or a polling system. You POST the question, receive a 202 Accepted with a thread_id, and then the client can gracefully poll a GET /v1/chat/{thread_id}/status endpoint.
- While GraphQL has Subscriptions (via WebSockets) for real-time updates, setting up the WebSocket infrastructure adds significant complexity.

3) API Surface Simplicity:

- GraphQL shines when the frontend client needs to dictate exactly what shape of data it wants (e.g. "Give me the user, their last 5 documents, and just the titles of those documents").
- Our application is heavily command-driven rather that query-driven. The API surface is small and action-oriented (e.g. "POST /v1/documents -> Upload a file").

4) Summary:

- Because the core interactions involves binary file uploads (PDFs) and long-running asynchronous AI tasks, a RESTful architecture with explicit state endpoints provided a cleaner, more reliable contract between the client and the server.

# Project Phases:

- Phase 1:
  - The goal is to get the web server running and defining the database schema to handle both standard relational data (document metadata), and vector data (AI embeddings).
  - We are using a pre-built PostgreSQL image that already has the pgvector extension compiled.
- Phase 2:
  - The goal is to create the ingestion pipeline using celery (background worker), and redis (message queue).
  - If we upload a 50-page PDF, it might take 10-20 seconds to chunk it and get the embeddings from OpenAI.
  - If we write this code directly inside our FastAPI /upload endpoint, the user's browser will sit there loading for 20 seconds, and the API might timeout.
  - This is why we are using celery and redis.
    - FastAPI instantly says "Got the file. Putting it in the queue."
    - Redis holds the message in line.
    - Celery (running in a completely separate terminal) picks up the message, does all the heavy PDF chunking and AI math, and updates the database to "COMPLETED" when it finishes.
    - Celery needs "export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES" to be executed in macos (silicon) to safely create background processes.
    - Run celery in single thread in macos locally → "celery -A app.worker.celery_app worker --pool=solo --loglevel=info"
- Phase 3:
  - 
