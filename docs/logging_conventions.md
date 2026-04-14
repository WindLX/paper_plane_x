# Logging Conventions

本文定义 Paper Plane X 后端日志分级与字段约定，用于统一检索、告警和问题定位。

最近审阅时间：2026-04-14。

## 1. 目标

- 日志可检索：统一使用 `event=` 事件名。
- 日志可关联：关键上下文字段固定命名（如 `project_id`、`paper_id`、`task_id`）。
- 日志可分级：同类问题在固定级别输出。
- 日志可演进：新增模块遵循同一命名规范。

## 2. 分级约定

- `DEBUG`
  - 低成本调试信息。
  - 例如：步骤开始、入参键、计数器状态。
  - 不用于业务结果和异常结论。

- `INFO`
  - 关键业务里程碑与正常状态变化。
  - 例如：任务入队、任务完成、应用启动。

- `WARNING`
  - 可预期但需要关注的异常路径。
  - 例如：资源不存在、请求被业务规则阻断、可恢复失败。

- `ERROR`
  - 明确失败且无需异常堆栈时。
  - 例如：二次失败（如失败状态回写又失败）。

- `EXCEPTION`
  - 需要保留堆栈的失败路径。
  - 例如：流程执行失败、外部依赖抛错。

## 3. 字段约定

### 3.1 通用字段

- `event`
  - 必填。
  - 事件名采用小写蛇形风格，推荐包含模块前缀。
  - 示例：`event=paper.processing_completed`。

- `error`
  - 失败类日志建议提供错误对象字符串化值。

### 3.2 业务上下文字段（按需）

- `project_id`
- `paper_id`
- `task_id`
- `trace_id`
- `agent`
- `mode`
- `step`
- `max_steps`
- `status`

### 3.3 计数和性能字段（按需）

- 计数字段统一使用 `*_count` 后缀。
  - 例如：`tool_call_count`、`referenced_image_count`。

- 时间字段统一显式单位。
  - 例如：`timeout_seconds`、`duration_ms`。

## 4. 事件命名规范

- 格式：`<domain>.<action>` 或 `<domain>.<action>_<qualifier>`
- 示例：
  - `agent.run_started`
  - `task_manager.task_failed`
  - `task_manager.tasks_recovered`
  - `data_process.retry_upload_queued`
  - `data_process.manual_update_request_received`
  - `mineru.parse_http_error`

## 5. 推荐写法

```python
logger.info(
    "event=task_manager.task_submitted task_id=%s project_id=%s paper_id=%s",
    task_id,
    project_id,
    paper_id,
)

logger.exception(
    "event=agent.run_failed agent=%s mode=%s project_id=%s step=%s max_steps=%s",
    agent_name,
    mode,
    project_id,
    step,
    max_steps,
)
```

## 6. 禁止项

- 禁止无 `event=` 的自由文本日志。
- 禁止在日志模板中拼接 f-string 产生不稳定结构。
- 禁止输出敏感字段（密钥、令牌、完整用户隐私内容）。

## 7. 落地范围

本轮已对齐以下后端模块日志：

- `core/agent_runtime/*`
- `services/data_process_*`
- `services/paper_service.py`
- `services/mineru.py`
- `api/routers/project.py`
- `api/routers/data_process.py`
- `api/dependencies.py`
- `agents/data_processor.py`
- `main.py`
- `services/database.py`
