# Paper Plane X Data Process 快速上手

这份文档用于快速验证后端 Data Process 链路是否可用：
- 创建项目
- 上传 1 个 PDF 并触发异步处理
- 观察任务状态
- 查看结构化结果与落盘文件
- 将论文关联到项目并执行检索

## 1. 前置条件

1. 已在仓库根目录。
2. 后端依赖已安装。
3. 数据库与 MinerU 相关配置可用。
4. MinerU 服务可访问（默认 `MINERU_BASE_URL=http://localhost:7860`）。

说明：如果 MinerU 不可用，上传通常会成功入队，但任务最终会进入 `FAILED`。

## 2. 启动后端

在终端执行：

```bash
cd paper_plane_x_backend
uv sync
uv run uvicorn paper_plane_x_backend.main:app --app-dir src --host 127.0.0.1 --port 8000 --reload --reload-dir src --reload-exclude ".git/" --reload-exclude ".venv/" --reload-exclude "data/logs/" --reload-exclude "data/papers/" --reload-exclude "node_modules/*"
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/health
```

期望返回：

```json
{"status":"ok","app_name":"Paper Plane X"}
```

## 3. 创建项目

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"Data Process Smoke Test","description":"upload one pdf"}'
```

保存返回中的 `project_id`：

```bash
export PROJECT_ID="替换成返回的 project_id"
```

## 4. 上传 PDF 启动 Data Process

```bash
export PDF_PATH="/absolute/path/to/your/test.pdf"
```

```bash
curl -s -o /tmp/ppx_start_resp.json -w "%{http_code}\n" -X POST "http://127.0.0.1:8000/api/v1/papers" \
  -F "pdf_file=@${PDF_PATH};type=application/pdf" \
  -F "title=Smoke Test Paper" \
  -F "authors=Alice,Bob" \
  -F "year=2024" \
  -F "publication=ArXiv"

cat /tmp/ppx_start_resp.json
```

期望：
- HTTP 状态码为 `202`
- 返回 `resource_id`（即 `paper_id`）
- 返回 `task_id`
- 返回 `status=QUEUED`

提取环境变量（可选）：

```bash
export PAPER_ID="$(jq -r '.resource_id' /tmp/ppx_start_resp.json)"
export TASK_ID="$(jq -r '.task_id' /tmp/ppx_start_resp.json)"
```

## 5. 将论文关联到项目

上传接口不会自动绑定到指定项目，需显式关联：

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/papers/${PAPER_ID}"
```

## 6. 查询处理状态

查看论文详情：

```bash
curl -s "http://127.0.0.1:8000/api/v1/papers/${PAPER_ID}"
```

建议重点关注字段：
- `extraction_status`
- `extraction_fact_check_status`
- `analysis_fact_check_status`
- `raw_pdf_path`
- `extraction_final_fact_check_trace_id`
- `analysis_final_fact_check_trace_id`

状态流（常见）：
- `extraction_status`: `PENDING -> PROCESSING -> COMPLETED|FAILED`
- `extraction_fact_check_status`: `PENDING -> PASSED|FAILED|HUMAN_PASSED`
- `analysis_fact_check_status`: `PENDING -> PASSED|FAILED|HUMAN_PASSED`

查询任务队列：

```bash
curl -s "http://127.0.0.1:8000/api/v1/data-process/tasks"
```

返回包含：
- 聚合统计：`queued/running/completed/failed/canceled`
- 任务项：`task_id`、`paper_id`、`status`、`error`、`created_at`

取消任务：

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/data-process/tasks/${TASK_ID}/cancel"
```

重试失败或已取消任务：

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/data-process/tasks/${TASK_ID}/retry"
```

同一论文重传并重跑：

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/papers/${PAPER_ID}/reprocess" \
  -F "pdf_file=@${PDF_PATH};type=application/pdf"
```

说明：`reprocess` 接口当前仅接收 PDF 文件。

## 7. 人工更新结果

```bash
curl -s -X PATCH "http://127.0.0.1:8000/api/v1/papers/${PAPER_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Manual Updated Title",
    "authors": ["Alice", "Bob"],
    "extraction_status": "HUMAN_COMPLETED",
    "quick_scan": {"manual": true},
    "synthesis_data": {"sections": 3},
    "analysis_report": {"manual": true},
    "extraction_fact_check_status": "HUMAN_PASSED",
    "analysis_fact_check_status": "HUMAN_PASSED",
    "extraction_fact_check_result": {"reviewer": "human"},
    "analysis_fact_check_result": {"reviewer": "human"}
  }'
```

## 8. Librarian 验证（可选）

项目内统一搜索：

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/search" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "ignored-by-server",
    "condition_group": {"operator": "and", "conditions": []},
    "limit": 20,
    "offset": 0
  }'
```

按路径取字段：

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/librarian/projection" \
  -H "Content-Type: application/json" \
  -d '{"paper_id":"'"${PAPER_ID}"'","field_path":"quick_scan.quick_summary"}'
```

## 9. 成功验收标准

1. 可以创建项目。
2. 可以上传 PDF，且返回 `paper_id` 与 `task_id`。
3. 论文详情中存在 `raw_pdf_path`（通常位于 `data/papers/{paper_id}/original.<ext>`）。
4. 任务可进入 `COMPLETED`，失败时能看到明确错误原因。
5. 服务重启后，未完成任务可被自动恢复并继续执行。

## 10. 常见问题

1. 一直 `PENDING` 或 `PROCESSING`：检查后端日志与 worker 是否启动，确认 `DATA_PROCESS_WORKER_COUNT > 0`。
2. 任务 `FAILED`：先看后端日志栈，其次看论文详情中的 fact check 结果字段。
3. 文件未落盘：检查 `MINERU_OUTPUT_DIR` 与运行目录是否正确（建议在 `paper_plane_x_backend` 下启动）。
4. 任务无法取消：`COMPLETED/FAILED` 任务不允许取消，运行中任务会先短暂进入 `CANCELING`。
