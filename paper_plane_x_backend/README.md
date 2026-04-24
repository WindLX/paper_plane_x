# Paper Plane X Backend

Paper Plane X 后端负责 Data Process 主链路：上传 PDF、后台解析提取、事实核查、结构化落库和任务状态管理。

## 快速启动

```bash
cd paper_plane_x_backend
uv sync
uv run fastapi dev src/paper_plane_x_backend/main.py
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/health
```

## 核心能力

1. 项目与论文管理
- 项目 CRUD
- 论文实体 CRUD（顶层 `/papers`）
- Project-Paper 关联管理（`link/unlink`）

2. Data Process 异步处理
- 单文件上传入队
- worker 池后台消费
- 失败/取消任务重试
- 同 paper_id 重新上传重试

3. 追溯与审计
- 论文记录关联 raw_pdf_path
- 论文记录关联 extraction / analysis / fact-check 分支的全量 trace_id 数组
- agent_traces 持久化 `trace_id/agent_name` 与 LLM usage 字段

4. 并行双 Loop 处理
- ExtractionAgent 与 AnalysisAgent 并行执行
- 两条分支各自经过 FactCheckAgent 闭环重试
- 落库字段区分 extraction / analysis 两套核查状态与结果
- 任一分支核查失败时，论文状态进入 `HUMAN_COMPLETED` 等待人工处理

5. API 模式输出容错
- `BaseAgent(api)` 在结构化校验前会先尝试直接 `json.loads`。
- 若失败，会继续从 markdown code fence（含 `json` 标记）与普通文本中提取 JSON object 候选。
- 当存在多个候选时，按 JSON 字符串长度从大到小依次做 schema 校验，命中即返回。
- 仅接受 JSON object 作为根类型；array/标量会被拒绝并进入原有重试逻辑。
- 容错只放宽输入清洗，不放宽最终 Pydantic schema 校验。

6. 检索与 Agent 工具（Phase 4 规划）
- Librarian 原子化检索能力（FTS 检索、融合重排、上下文扩展、证据追踪）
- 为 Agent 提供受限 `rg/awk/sed` 文本处理工具（可写受限 + 安全治理）

## API 概览

项目与论文：

- POST /api/v1/projects
- GET /api/v1/projects
- GET /api/v1/projects/{project_id}
- PATCH /api/v1/projects/{project_id}
- DELETE /api/v1/projects/{project_id}
- POST /api/v1/papers
- GET /api/v1/papers
- GET /api/v1/papers/{paper_id}
- PATCH /api/v1/papers/{paper_id}
- POST /api/v1/papers/{paper_id}/reprocess
- DELETE /api/v1/papers/{paper_id}
- GET /api/v1/projects/{project_id}/papers
- GET /api/v1/projects/{project_id}/papers/{paper_id}
- POST /api/v1/projects/{project_id}/papers/{paper_id}
- DELETE /api/v1/projects/{project_id}/papers/{paper_id}
- GET /api/v1/projects/{project_id}/papers/search

Data Process：

- GET /api/v1/data-process/tasks
- POST /api/v1/data-process/tasks/{task_id}/cancel
- POST /api/v1/data-process/tasks/{task_id}/retry

## 配置说明

配置优先级（高到低）：

1. 初始化参数
2. 系统环境变量
3. .env
4. TOML 配置文件

默认 TOML 文件：

- config/default.toml

可通过环境变量切换：

- PPX_CONFIG_FILE=/absolute/path/to/custom.toml

常用环境变量：

- PPX_LLM__API_KEY
- PPX_DATABASE_URL
- PPX_MINERU_BASE_URL
- PPX_MINERU_OUTPUT_DIR
- PPX_DATA_PROCESS_WORKER_COUNT
- PPX_DATA_PROCESS_MAX_RETRIES
- PPX_DATA_PROCESS_SHUTDOWN_TIMEOUT

## 开发命令

```bash
# Lint
uv run ruff check .

# Type check
uv run pyright

# Test
uv run pytest -q
```
