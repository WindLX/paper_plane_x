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
- 论文列表、详情、删除

2. Data Process 异步处理
- 单文件上传入队
- worker 池后台消费
- 失败/取消任务重试
- 同 paper_id 重新上传重试

3. 追溯与审计
- 论文记录关联 raw_pdf_path
- 论文记录关联 final_fact_check_trace_id
- agent_traces 持久化 LLM usage 字段

## API 概览

项目与论文：

- POST /api/v1/projects
- GET /api/v1/projects
- GET /api/v1/projects/{project_id}
- PATCH /api/v1/projects/{project_id}
- DELETE /api/v1/projects/{project_id}
- GET /api/v1/projects/{project_id}/papers
- GET /api/v1/projects/{project_id}/papers/{paper_id}
- DELETE /api/v1/projects/{project_id}/papers/{paper_id}

Data Process：

- POST /api/v1/projects/{project_id}/data-process
- POST /api/v1/projects/{project_id}/data-process/{paper_id}/retry
- GET /api/v1/projects/{project_id}/data-process/tasks
- POST /api/v1/projects/{project_id}/data-process/tasks/{task_id}/cancel
- POST /api/v1/projects/{project_id}/data-process/tasks/{task_id}/retry

## 配置说明

配置优先级（高到低）：

1. 初始化参数
2. 系统环境变量
3. .env
4. TOML 配置文件

默认 TOML 文件：

- config/default.toml

可通过环境变量切换：

- PPX_CONFIG_FILE=./config/example.local.toml

常用环境变量：

- LLM__API_KEY
- DATABASE_URL
- MINERU_BASE_URL
- MINERU_OUTPUT_DIR
- DATA_PROCESS_WORKER_COUNT
- DATA_PROCESS_MAX_RETRIES
- DATA_PROCESS_SHUTDOWN_TIMEOUT

## 开发命令

```bash
# Lint
uv run ruff check .

# Type check
uv run pyright

# Test
uv run pytest -q
```
