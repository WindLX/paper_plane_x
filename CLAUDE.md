# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Paper Plane X is an AI Agent-powered research survey workflow system. It uses a multi-agent collaborative approach to help researchers process academic papers and generate literature reviews.

Core principles:
- Minimalist engineering: no LangGraph/Celery, use FastAPI lifespan + SQLite state persistence
- Strict structured constraints: all Agent I/O validated by Pydantic schemas
- Human-in-the-loop (HITL): core decision nodes should support suspend/resume with human feedback
- Absolute fact traceability: persist precise anchors and full LLM interaction traces

## Tech Stack

- Backend: FastAPI, uv, LiteLLM, Pydantic, SQLite (FTS5), ChromaDB
- Frontend: Vue 3 + Vite + TypeScript
- Tools: MinerU (PDF parsing)

## Common Commands

### Backend (paper_plane_x_backend/)

```bash
cd paper_plane_x_backend

# Install dependencies
uv sync

# Run development server
uv run uvicorn paper_plane_x_backend.main:app --app-dir src --host 127.0.0.1 --port 8000 --reload

# Run tests
uv run pytest

# Run single test
uv run pytest tests/unit/test_file.py::test_function -v

# Type checking
uv run pyright

# Linting
uv run ruff check .
uv run ruff check --fix .
```

### Frontend (paper_plane_x_frontend/)

```bash
cd paper_plane_x_frontend

# Install dependencies
pnpm install

# Development server
pnpm dev

# Type checking
pnpm vue-tsc

# Build
pnpm build
```

## Development Status

See docs/roadmap.md for detailed phase breakdown.

| Phase   | Description                                                            | Status      |
| ------- | ---------------------------------------------------------------------- | ----------- |
| Phase 1 | Project skeleton, SQLite + FTS5, Project/Paper CRUD API                | Complete    |
| Phase 2 | Agent Engine Core (BaseAgent, LLMClient, Tools)                        | Complete    |
| Phase 3 | Data Process workflow (Extraction/Analysis/FactCheck, queue workers)   | Complete    |
| Phase 4 | Librarian MVP, task persistence/recovery, vector retrieval enhancement | In Progress |
| Phase 5 | HITL framework and Survey writing workflow                             | Pending     |

## Architecture

### Layer Structure

App Layer (FastAPI)
-> Project/Paper API Layer
-> Data-Process Orchestration Layer
-> Core Components (Agents, Tools, Database)

### Key Source Locations

paper_plane_x_backend/src/paper_plane_x_backend/
- main.py: FastAPI entry, lifespan startup/shutdown of worker pool
- config.py: multi-layer config (constructor > env > .env > TOML)
- api/routers/: project, paper, librarian, data_process, hitl
- core/agent_runtime/: BaseAgent, LLMClient, memory, tooling, exceptions
- agents/: data_processor implemented; planner/reviewer/writer are placeholders
- tools/: tool registry and @tool decorator
- services/: database, orchestrators, paper services, data_process_tasks, mineru
- models/core.py: Pydantic domain models
- schemas/: API and agent I/O schemas

## Agent Engine

BaseAgent supports two modes:
- api mode: single structured generation with schema validation
- normal mode: free text + tool-calling loop

Typical usage:

```python
class MyOutput(BaseModel):
    result: str

agent = BaseAgent(
    output_schema=MyOutput,
    mode="api",
    system_prompt="You are...",
    tools=[my_tool],
    llm_config=settings.get_agent_llm_config("extraction"),
)

agent.memory.append_user_message({"input": "data"})
result = await agent.run()
```

Per-agent LLM config is loaded by settings.get_agent_llm_config(agent_name).

## Database Layer

Storage strategy:
- SQLite: metadata, state, logs, queue state
- FTS5: full-text search on selected paper fields
- No ORM: direct SQL with explicit schema control

Key tables:
- projects: project metadata
- papers: paper metadata + parsed content + processing states + structured outputs
- paper_projects: many-to-many relation between project and paper
- agent_traces: full LLM interaction history and token usage
- data_process_tasks: persistent queue states
- papers_fts: FTS5 index table

Current paper state fields:
- extraction_status
- extraction_fact_check_status
- analysis_fact_check_status
- extraction_final_fact_check_trace_id
- analysis_final_fact_check_trace_id

## Data-Process Runtime

Module split:
- API layer: api/routers/data_process.py
- Orchestration layer: services/orchestrators/data_process.py
- Task runtime layer: services/data_process_tasks/task_manager.py

Worker pool lifecycle:
- Startup in FastAPI lifespan via start_worker_pool()
- Shutdown via stop_worker_pool()

Runtime capabilities:
- Queue status query
- Task cancellation
- Retry for failed/canceled tasks
- SQLite-backed task persistence with startup recovery

## Librarian

Current API-level capabilities:
- POST /api/v1/librarian/projection
- POST /api/v1/librarian/matrix
- POST /api/v1/librarian/search
- POST /api/v1/projects/{project_id}/search

Status:
- MVP available for projection, matrix comparison, and unified condition search
- Further retrieval fusion/vector enhancement is still in progress

## Configuration System

Priority (high to low):
1. Constructor arguments
2. Environment variables
3. .env file
4. TOML config (config/default.toml, override by PPX_CONFIG_FILE)

Common settings:
- DATABASE_URL, DATA_DIR
- LLM and AGENT_LLM.*
- MINERU_BASE_URL, MINERU_OUTPUT_DIR
- DATA_PROCESS_WORKER_COUNT, DATA_PROCESS_MAX_RETRIES, DATA_PROCESS_SHUTDOWN_TIMEOUT
- LOG_LEVEL, LOG_TO_FILE, LOG_APP_ONLY, LOG_FILE_PATH

Prompt files are loaded via settings.load_prompt(group, filename) from prompts/.

## Logging

- Console + rotating file handler (default: data/logs/backend.log)
- LOG_APP_ONLY=true narrows logs to paper_plane_x_backend namespace

## Testing Strategy

- Unit tests: agent runtime, services, models, config, tools
- Integration tests: key API and workflow paths
- No DB mocking for core flows, prefer real SQLite test database

Test layout:
- tests/unit/
- tests/integration/
- tests/conftest.py

## API Endpoints

Health:
- GET /health

Projects:
- POST /api/v1/projects
- GET /api/v1/projects
- GET /api/v1/projects/{project_id}
- PATCH /api/v1/projects/{project_id}
- DELETE /api/v1/projects/{project_id}

Project-Paper relation:
- GET /api/v1/projects/{project_id}/papers
- POST /api/v1/projects/{project_id}/papers/{paper_id}
- DELETE /api/v1/projects/{project_id}/papers/{paper_id}
- POST /api/v1/projects/{project_id}/search

Papers:
- POST /api/v1/papers
- GET /api/v1/papers
- GET /api/v1/papers/{paper_id}
- PATCH /api/v1/papers/{paper_id}
- POST /api/v1/papers/{paper_id}/reprocess
- DELETE /api/v1/papers/{paper_id}

Data Process tasks:
- GET /api/v1/data-process/tasks
- POST /api/v1/data-process/tasks/{task_id}/cancel
- POST /api/v1/data-process/tasks/{task_id}/retry

Librarian:
- POST /api/v1/librarian/projection
- POST /api/v1/librarian/matrix
- POST /api/v1/librarian/search

HITL:
- Prefix only: /api/v1/hitl (business endpoints pending)

## Notes on DB Schema Changes

Database is now in active use. For any schema change, must implement both:
1. Migration logic (add columns / rename compatibility / legacy copy)
2. Automatic pre-migration backup (recommended before init_tables migration step, timestamped under data/backups)

For legacy field renames, prefer copy-then-compatibility strategy to avoid runtime breakage on existing production databases.
