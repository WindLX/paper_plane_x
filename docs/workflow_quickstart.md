# Paper Plane X Data Process 快速上手

这份文档用于快速验证后端 Data Process 是否可用：
- 创建项目
- 上传 1 个 PDF
- 观察后台处理状态
- 查看结果与落盘文件

## 1. 前置条件

1. 已在项目根目录，且后端依赖安装完成。
2. 已初始化环境变量（至少确保数据库和 MinerU 相关配置可用）。
3. MinerU 服务可访问（默认 `MINERU_BASE_URL=http://localhost:7860`）。

如果 MinerU 没有启动，上传会成功入队，但后台处理会失败并将状态写为 `FAILED`。

## 2. 启动后端

在一个终端执行：

```bash
cd paper_plane_x_backend
uv sync
uv run uvicorn paper_plane_x_backend.main:app --app-dir src --host 127.0.0.1 --port 8000 --reload --reload-dir src --reload-exclude ".git/" --reload-exclude ".venv/" --reload-exclude "data/logs/" --reload-exclude "data/papers/" --reload-exclude "node_modules/*"
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/health
```

期望返回示例：

```json
{"status":"ok","app_name":"Paper Plane X"}
```

## 3. 创建项目

在另一个终端执行：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"Data Process Smoke Test","description":"upload one pdf"}'
```

返回里会有 `project_id`，保存下来。示例：

```bash
export PROJECT_ID="替换成上一步返回的 project_id"
```

## 4. 上传 PDF 启动 Data Process

准备一个测试 PDF 路径：

```bash
export PDF_PATH="/absolute/path/to/your/test.pdf"
```

调用上传接口：

```bash
curl -s -o /tmp/ppx_start_resp.json -w "%{http_code}\n" -X POST "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/data-process" \
  -F "pdf_file=@${PDF_PATH};type=application/pdf" \
  -F "title=Smoke Test Paper" \
  -F "authors=Alice,Bob" \
  -F "year=2024" \
  -F "venue=ArXiv"

cat /tmp/ppx_start_resp.json
```

期望：
- HTTP 状态码 `202`
- 返回 `resource_id`（即 paper_id）
- 返回 `task_id`
- `status` 为 `QUEUED`

保存 `paper_id`：

```bash
export PAPER_ID="替换成上一步返回的 resource_id"
export TASK_ID="替换成上一步返回的 task_id"
```

可用 jq 快速提取（可选）：

```bash
export PAPER_ID="$(jq -r '.resource_id' /tmp/ppx_start_resp.json)"
export TASK_ID="$(jq -r '.task_id' /tmp/ppx_start_resp.json)"
```

## 5. 查询处理状态

查看单篇详情：

```bash
curl -s "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/papers/${PAPER_ID}"
```

建议重点关注字段：
- `extraction_status`
- `fact_check_status`
- `raw_pdf_path`
- `final_fact_check_trace_id`

状态字段说明：
- `extraction_status`: `PENDING` -> `PROCESSING` -> `COMPLETED` 或 `FAILED`
- `fact_check_status`: `PENDING` -> `PASSED` 或 `FAILED`
- 人工更新后可出现：
  - `extraction_status=HUMAN_COMPLETED`
  - `fact_check_status=HUMAN_PASSED`

也可以循环轮询：

```bash
while true; do
  curl -s "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/papers/${PAPER_ID}" \
    | sed 's/,/\n/g' | grep -E 'extraction_status|fact_check_status|raw_pdf_path'
  sleep 2
done
```

查看任务队列状态：

```bash
curl -s "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/data-process/tasks"
```

返回里可看到：
- `queued/running/completed/failed/canceled` 统计
- 每个任务的 `task_id`, `paper_id`, `status`, `error`, `created_at`

取消任务：

```bash
curl -s -X POST \
  "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/data-process/tasks/${TASK_ID}/cancel"
```

重试失败任务（无需重新上传文件，复用 raw_pdf_path）：

```bash
curl -s -X POST \
  "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/data-process/tasks/${TASK_ID}/retry"
```

同一 paper_id 重新上传并重试：

```bash
curl -s -X POST \
  "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/data-process/${PAPER_ID}/retry" \
  -F "pdf_file=@${PDF_PATH};type=application/pdf"
```

说明：该接口当前仅接收 PDF 文件，不再接收 title/authors/year/venue/doi 元数据。

人工手动更新元数据与处理结果：

```bash
curl -s -X PATCH \
  "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/data-process/${PAPER_ID}/manual-update" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Manual Updated Title",
    "authors": ["Alice", "Bob"],
    "extraction_status": "HUMAN_COMPLETED",
    "quick_scan": {"manual": true},
    "synthesis_data": {"sections": 3},
    "fact_check_status": "HUMAN_PASSED",
    "fact_check_result": {"reviewer": "human"}
  }'
```

手动状态可选值：
- `extraction_status`: `HUMAN_COMPLETED` 或 `FAILED`
- `fact_check_status`: `HUMAN_PASSED` 或 `FAILED`
```

## 6. 成功时你应看到什么

当处理完成：
- `extraction_status` 为 `COMPLETED`
- `fact_check_status` 为 `PASSED`
- `quick_scan` 与 `synthesis_data` 有值
- `raw_pdf_path` 指向原始文件路径（位于 `data/papers/{paper_id}/original.<ext>`）

并且同目录下通常会有 MinerU 产生的 markdown 和图片。

## 7. 常见问题

1. 一直 `PENDING` 或 `PROCESSING`
- 检查后端进程日志是否有 worker 异常。
- 确认 `DATA_PROCESS_WORKER_COUNT` 大于 0。

2. 变成 `FAILED`
- 优先看后端日志栈信息。
- 查看论文详情中的 `fact_check_result` 是否有错误信息。
- 确认 MinerU 服务地址与可达性。

3. 上传成功但没有文件
- 检查 `MINERU_OUTPUT_DIR` 配置（默认 `./data/papers`）。
- 确认运行目录是否是 `paper_plane_x_backend`。

4. 无法终止/删除任务
- 已完成（`COMPLETED`）或已失败（`FAILED`）任务不能再取消。
- 运行中的任务取消后会短暂显示 `CANCELING`，随后变为 `CANCELED`。
- `DELETE /api/v1/projects/{project_id}/papers/{paper_id}` 在 `PENDING/PROCESSING` 状态会返回 409。

5. 服务重启后任务丢失
- 当前任务状态持久化在 SQLite，应用启动会恢复 `QUEUED` 任务并重置 `RUNNING/CANCELING` 为 `QUEUED` 后继续执行。

## 8. 最小验收清单

- 能创建项目。
- 能上传 PDF 并拿到 `paper_id`。
- 详情接口能返回 `raw_pdf_path`。
- 最终状态能进入 `COMPLETED/PASSED`（或有明确失败原因）。
