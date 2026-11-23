"""Local-only 24/7 worker: drains a file queue using Ollama models. See docs/LOCAL_WORKER.md.

It never calls a hosted model API, never touches version control, never edits tracked files
(outputs go under work/ only) and never reads .env.
"""
