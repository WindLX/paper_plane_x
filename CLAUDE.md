# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Paper Plane X is an AI Agent-powered research survey workflow system. It uses a multi-agent collaborative approach to help researchers process academic papers and generate literature reviews.

**Core Principles**:
- Minimalist engineering: No LangGraph/Celery, use FastAPI background tasks + SQLite for state management
- Strict structured constraints: All Agent I/O validated by Pydantic schemas
- Human-in-the-loop (HITL): Core decision nodes support suspend/resume with human feedback
- Absolute fact traceability: All AI-generated content must have precise document anchors, full LLM interaction traces persisted

## Tech Stack

- **Backend**: FastAPI, uv (package management), LiteLLM, Pydantic, SQLite (with FTS5), ChromaDB
- **Frontend**: Vue 3 + Vite + TypeScript + TailwindCSS
- **Tools**: MinerU (PDF parsing), Pandoc (document export)

## Common Commands

### Backend (paper_plane_x_backend/)

```bash
# Navigate to backend
cd paper_plane_x_backend

# Run development server
uv run fastapi dev src/paper_plane_x_backend/main.py

# Run tests
uv run pytest

# Run single test
uv run pytest tests/test_file.py::test_function -v

# Type checking
uv run pyright

# Linting
uv run ruff check .
uv run ruff check --fix .

# Add dependency
uv add <package>
uv add --dev <package>

# Sync dependencies
uv sync
```

### Frontend (paper_plane_x_frontend/)

```bash
# Navigate to frontend
cd paper_plane_x_frontend

# Install dependencies
pnpm install

# Development server
pnpm dev

# Build
pnpm build

# Preview production build
pnpm preview

# Type checking
pnpm vue-tsc
```

## Development Status

See `docs/roadmap.md` for detailed phase breakdown.

| Phase   | Description                                                  | Status        |
| ------- | ------------------------------------------------------------ | ------------- |
| Phase 1 | Project skeleton, SQLite + FTS5, Project CRUD API            | ✅ Complete    |
| Phase 2 | Agent Engine Core (BaseAgent, LLMClient, Tools)              | ✅ Complete    |
| Phase 3 | Data Process Workflow (Extraction, FactCheck, queue workers) | ✅ Complete    |
| Phase 4 | ChromaDB, Librarian, HITL Framework                          | ⏳ In Progress |
| Phase 5 | Survey Writing Workflow                                      | ⏳ Pending     |

## Architecture

### Layer Structure

```
App Layer (FastAPI)
    ↓
Project Layer (Project management)
    ↓
Data-Process Orchestration Layer
    ↓
Core Components (Agents, Tools, Database)
```

### Project Structure

```
paper_plane_x_backend/src/paper_plane_x_backend/
├── main.py              # FastAPI app entry
├── config.py            # Global configuration, LLM per-agent config
├── api/                 # REST routers
│   ├── dependencies.py  # FastAPI dependencies (DB session, etc.)
│   ├── routers/
│   │   ├── project.py   # Project + Paper CRUD (complete)
│   │   ├── data_process.py  # Data-process API router (thin router)
│   │   └── hitl.py      # Human-in-the-loop endpoints (Phase 4)
│   └── __init__.py
├── core/                # Agent runtime core
│   └── agent_runtime/
│       ├── base_agent.py # BaseAgent - ReAct loop, structured output
│       ├── llm_client.py # LLMClient (LiteLLM wrapper)
│       ├── memory.py     # Short/long memory manager
│       ├── tooling.py    # Tool registry and schema adapter
│       └── exceptions.py # Agent error hierarchy
├── agents/              # Agent wrappers
│   ├── data_processor.py # ExtractionAgent, FactCheckAgent (complete)
│   ├── planner.py       # (empty - Phase 5)
│   ├── writer.py        # (empty - Phase 5)
│   └── reviewer.py      # (empty - Phase 5)
├── tools/               # Agent-executable tools
│   ├── base.py          # Tool, ToolRegistry, @tool decorator
│   └── librarian.py     # (empty - Phase 4)
├── services/            # Business logic services
│   ├── __init__.py
│   ├── database.py       # SQLite wrapper, FTS5, CRUD operations
│   ├── data_process_orchestrator.py  # Data-process orchestration service
│   ├── data_process_task_manager.py  # Queue/worker/task lifecycle manager
│   └── paper_service.py # Paper processing service
├── utils/               # External utility wrappers
│   ├── mineru.py        # PDF parsing via MinerU API
│   └── pandoc.py        # Document export
├── models/              # Database models (Pydantic)
│   └── core.py          # Project, Paper, AgentTrace
├── schemas/             # I/O schemas (Pydantic)
│   ├── api.py           # API request/response schemas
│   ├── messages.py      # OpenAI-compatible message types
│   ├── agent_io/        # Agent I/O schemas
│   │   ├── base.py      # Citation, CitedText
│   │   └── data_processor.py  # QuickScan, SynthesisData, ExtractionAgentOutput
│   └── state.py         # State machine schemas (future)
```

### Key Components

#### Agent Engine (`src/core/agent_runtime/base_agent.py`)

```python
class BaseAgent:
    """Agent base class supporting two modes:
    - 'api' mode: Forced structured output via Pydantic schema
    - 'normal' mode: Free text with tool calling loop (ReAct)
    """
```

**Components**:
- **Brain**: LLMClient (LiteLLM wrapper)
- **Long Memory**: System prompt
- **Short Memory**: Message list (OpenAI-compatible)
- **Tools**: ToolRegistry with `@tool` decorator
- **Output Parser**: Pydantic validation with retry logic

**Usage**:
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

result = await agent.run({"input": "data"})  # Returns validated MyOutput
```

#### LLM Client (`src/core/agent_runtime/llm_client.py`)

```python
class LLMClient:
    """LiteLLM wrapper with three modes:
    - generate(): Plain text generation
    - generate_with_tools(): Tool calling
    - generate_structured(): Forced JSON schema output
    """
```

Per-agent LLM config via `settings.get_agent_llm_config(agent_name)`.

#### Database Layer (`src/services/database.py`)

- **SQLite**: Metadata, state context, operation logs
- **FTS5**: Full-text search on papers (title, md_content, quick_scan, synthesis_data)
- **No ORM**: Direct SQL with Pydantic models

**Key Tables**:
- `projects`: Project metadata, data-process state
- `papers`: Parsed paper data with extraction status + `raw_pdf_path` + `final_fact_check_trace_id`
- `agent_traces`: Complete LLM interaction history + usage fields (`llm_model`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `usage_payload`)
- `workflow_history`: State transition log
- `papers_fts`: FTS5 virtual table for full-text search

#### Data-Process Runtime (Phase 3 - Complete)

Data Process 任务层已完成框架化拆分：
- API 层：`api/routers/data_process.py` 仅负责请求校验和错误映射
- 编排层：`services/data_process_orchestrator.py` 负责业务校验、重试策略与错误边界
- 任务层：`services/data_process_task_manager.py` 负责队列、worker、取消/失败状态流

Data Process 为当前首个任务池实现：

```
Single PDF Upload API
    ↓
Create pending paper record
    ↓
Save original PDF to data/papers/{paper_id}/original.<ext>
    ↓
Enqueue task to in-memory queue
    ↓
Worker pool consumes task (parse → extract → fact-check)
    ↓
SQLite update + FTS5 sync
```

**Data Schemas** (`schemas/agent_io/data_processor.py`):
- `QuickScan`: Tags, verdict, reason, quick_summary
- `SynthesisData`: ResearchGap, Methodology, KeyResults, review_summary
- `CitedText`: All fields require `citations` with exact quotes from source

#### Tool System (`src/tools/base.py`)

```python
@tool()
async def search_papers(query: str, limit: int = 10) -> list[dict]:
    """Search papers by keyword"""
    ...

# Tools auto-convert to OpenAI function schema
agent = BaseAgent(tools=[search_papers])
```

## State Machine Design

Workflow states (`models/core.py`):
- `IDLE`: Not started
- `RUNNING`: In progress
- `WAITING_FOR_HUMAN`: Suspended at HITL checkpoint
- `COMPLETED`: Successfully finished
- `FAILED`: Error state

State transitions persisted to SQLite with full context for resume capability.

## Testing Strategy

- **Unit tests**: Agent logic, tool functions, validation
- **Integration tests**: Full workflow with mocked LLM
- **No database mocking**: Use test SQLite instance

**Test Layout**:
- `tests/unit/`: unit tests for agent runtime, services, models, config
- `tests/integration/`: API and workflow integration tests
- `tests/conftest.py`: Shared fixtures (client, test DB)

**Run Tests**:
```bash
uv run pytest -v
```

## Agent Development Pattern

1. **Define output schema** in `schemas/agent_io/`:
```python
class MyAgentOutput(BaseModel):
    field1: str
    field2: list[str]
```

2. **Create agent** inheriting from `BaseAgent`:
```python
class MyAgent:
    def __init__(self, config: Config):
        self.agent = BaseAgent(
            output_schema=MyAgentOutput,
            mode="api",
            llm_config=settings.get_agent_llm_config("my_agent"),
        )

    async def run(self, input_data: dict) -> MyAgentOutput:
        return await self.agent.run(input_data)
```

3. **Agent handles automatically**:
   - Tool calling loop
   - Output validation with retry
   - Trace logging to `agent_traces` table
   - Error handling (AgentValidationError, AgentExecutionError)

## Configuration

Environment variables (`.env`):
```bash
# Application
APP_NAME="Paper Plane X"
DEBUG=true
LOG_LEVEL=INFO

# Server
HOST=127.0.0.1
PORT=8000

# Database
DATABASE_URL=sqlite:///./data/app.db
DATA_DIR=./data

# LLM Global Default
LLM__MODEL=gpt-4o
LLM__API_KEY=sk-...
LLM__BASE_URL=  # For VLLM: http://localhost:8000/v1
LLM__TEMPERATURE=0.7
LLM__MAX_TOKENS=4096

# Per-Agent LLM Config (optional, overrides global)
LLM__EXTRACTION__MODEL=gpt-4o-mini
LLM__FACT_CHECK__TEMPERATURE=0.1

# MinerU (PDF parsing)
MINERU_BASE_URL=http://localhost:8000
MINERU_OUTPUT_DIR=./data/papers

# Data Process Task Pool
DATA_PROCESS_MAX_RETRIES=3
DATA_PROCESS_WORKER_COUNT=2
```

## HITL (Human-in-the-Loop)

When agents need human input:
- Agent calls `AskHuman` tool with question/context
- Workflow state saved to `WAITING_FOR_HUMAN`
- Frontend polls/pushes for human response
- Human submits feedback via API
- Workflow resumes with injected feedback

*(Implementation pending Phase 4)*

## API Endpoints

Current implemented endpoints:

```
GET  /health                    # Health check

# Projects
POST   /api/v1/projects                         # Create project
GET    /api/v1/projects                         # List projects (paginated)
GET    /api/v1/projects/{id}                    # Get project
PATCH  /api/v1/projects/{id}                    # Update project
DELETE /api/v1/projects/{id}                    # Delete project

# Papers
GET    /api/v1/projects/{id}/papers             # List project papers
GET    /api/v1/projects/{id}/papers/{paper_id}  # Get paper detail
DELETE /api/v1/projects/{id}/papers/{paper_id}  # Delete paper (blocked when processing)

# Data Process (Phase 3 - Complete)
POST /api/v1/projects/{id}/data-process      # Async data processing
POST /api/v1/projects/{id}/data-process/{paper_id}/retry  # Re-upload and retry same paper ID
GET  /api/v1/projects/{id}/data-process/tasks             # Task queue status
POST /api/v1/projects/{id}/data-process/tasks/{task_id}/cancel         # Cancel queued/running task
POST /api/v1/projects/{id}/data-process/tasks/{task_id}/retry          # Retry failed/canceled task

# HITL (Phase 4)
POST /api/v1/hitl/{project_id}/feedback               # Submit human feedback
```
