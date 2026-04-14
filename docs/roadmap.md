# Paper Plane X 后端开发路线图

## 项目目标
构建 AI 智能体科研工作流系统，支持文献 PDF 解析、结构化数据提取、事实核查和文献综述生成。

## Phase 1: 基础骨架 (Week 1)

**目标**: 搭建可运行的 FastAPI 项目骨架，支持 Project 管理

| 任务                       | 说明                                                   | 状态     |
| -------------------------- | ------------------------------------------------------ | -------- |
| 1.1 项目结构完善           | 补全 `main.py`, `config.py`，配置 uv + pyproject.toml  | ✅ 已完成 |
| 1.2 数据库连接层           | SQLite 原生连接封装，基础 CRUD 工具函数，FTS5 全文搜索 | ✅ 已完成 |
| 1.3 Project/Paper 数据模型 | Pydantic 模型，完整序列化/反序列化                     | ✅ 已完成 |
| 1.4 Project API            | `POST/GET/PATCH/DELETE /projects` + Paper 查询接口     | ✅ 已完成 |
| 1.5 测试框架               | pytest + fixtures，Project API 测试 (11个测试全部通过) | ✅ 已完成 |

**交付物**: 可通过 API 创建/查看项目的基础服务 ✅

**数据库字段命名**:
- `md_content`: 原始 Markdown 文本
- `images_paths`: 图片文件路径列表（JSON 数组）
- `quick_scan`, `synthesis_data`: 提取的结构化数据
- `fact_check_result`: 事实核查结果
- `extraction_status`, `fact_check_status`: 处理状态

---

## Phase 2: Agent 引擎核心 (Week 1-2)

**目标**: 实现可复用的 BaseAgent 框架，支持结构化输出

| 任务               | 说明                                                                          | 状态     |
| ------------------ | ----------------------------------------------------------------------------- | -------- |
| 2.1 LiteLLM 集成   | LLMClient 封装，支持 OpenAI/Anthropic/VLLM/Ollama，每 Agent 独立配置          | ✅ 已完成 |
| 2.2 消息模型       | OpenAI 兼容的消息格式 (System/User/Assistant/ToolMessage)                     | ✅ 已完成 |
| 2.3 工具基类       | Tool/ToolRegistry，@tool 装饰器                                               | ✅ 已完成 |
| 2.4 Agent 异常     | AgentError/AgentExecutionError/AgentValidationError/ToolExecutionError        | ✅ 已完成 |
| 2.5 BaseAgent 核心 | `core/agent_runtime/base_agent.py`，ReAct 循环，Pydantic 验证重试，Trace 落库 | ✅ 已完成 |
| 2.6 测试覆盖       | Agent/Tool/LLM 测试 (10个测试全部通过)                                        | ✅ 已完成 |

**交付物**: ✅ 可继承 BaseAgent 快速开发新 Agent

**关键设计**:
```python
# 定义输出 Schema
class MyOutput(BaseModel):
    result: str

# 创建 Agent
agent = BaseAgent(
    output_schema=MyOutput,
    system_prompt="You are...",
    tools=[my_tool],
    llm_config=settings.get_agent_llm_config("extraction"),
)

# 运行
result = await agent.run({"input": "data"})
# result: MyOutput - 已验证的结构化输出
```

---

## Phase 3: Data Process Workflow - MVP (Week 2-3)

**目标**: 实现单篇论文的完整处理流程（不包含 HITL）

| 任务                         | 说明                                                            | 状态     |
| ---------------------------- | --------------------------------------------------------------- | -------- |
| 3.1 MinerU 工具              | PDF → Markdown + 图片 解析封装                                  | ✅ 已完成 |
| 3.2 Data Extraction Schema   | `QuickScan`, `SynthesisData` Pydantic 模型                      | ✅ 已完成 |
| 3.3 ExtractionAgent          | 基于架构设计的 Prompt 和输出结构                                | ✅ 已完成 |
| 3.4 FactCheckAgent           | `FactCheckResult` 模型，核查逻辑                                | ✅ 已完成 |
| 3.5 局部闭环                 | 核查失败 → 反馈给 ExtractionAgent 重试                          | ✅ 已完成 |
| 3.6 数据入库                 | SQLite 保存元数据+原始文本，FTS5 索引                           | ✅ 已完成 |
| 3.7 Data-Process API         | `POST /projects/{id}/data-process`（单文件上传+后台队列）       | ✅ 已完成 |
| 3.8 文件落盘与路径追踪       | 原始 PDF 存储至 `data/papers/{paper_id}/` 并写入 `raw_pdf_path` | ✅ 已完成 |
| 3.9 任务队列管理 API         | 队列状态查询、任务取消、失败任务重试、同 ID 重新上传            | ✅ 已完成 |
| 3.10 Data-Process 任务池重构 | 统一为 data-process 专用 task manager                           | ✅ 已完成 |
| 3.11 人工结果回填 API        | 人工更新元数据与处理结果，支持 `HUMAN_*` 与 `FAILED` 状态       | ✅ 已完成 |

**交付物**: ✅ 上传 PDF → 提取结构化数据 → 事实核查 → 入库的完整流程

**核心实现**:
- `ExtractionAgent` + `FactCheckAgent` - 双 Agent 协作提取和核查
- `PaperService` - 封装完整 data-process 处理链，支持反馈闭环重试
- `POST /projects/{id}/data-process` - 上传即入队，后台 worker 池处理
- `GET /projects/{id}/papers` - 论文列表和详情查询
- MinerU 配置支持 `MINERU_BASE_URL`、`MINERU_OUTPUT_DIR`
- 应用生命周期统一启动/关闭 data-process worker 池

---

## Phase 4: Data Process 增强 (Week 3-4)

**目标**: 批量处理、向量检索与稳定性增强（不包含 HITL）

| 任务               | 说明                                             | 状态       |
| ------------------ | ------------------------------------------------ | ---------- |
| 4.1 ChromaDB 集成  | `SynthesisData` 段落向量化存储                   | 待开始     |
| 4.2 Librarian 工具 | 关键词检索 (FTS5) + 语义检索 (Chroma)            | 待开始     |
| 4.3 批量处理       | 多 worker 并发消费上传任务（接口仍为单文件上传） | ✅ 部分完成 |
| 4.4 任务状态持久化 | 任务状态落 SQLite，支持服务重启后任务恢复        | ✅ 已完成   |

**交付物**: 支持并发后台处理与可恢复执行的生产级 data-process 系统

---

## 当前实现快照 (2026-04)

- Data Process 入口：`POST /api/v1/projects/{id}/data-process` 与 `POST /api/v1/projects/{id}/data-process/{paper_id}/retry`。
- 人工更新入口：`PATCH /api/v1/projects/{id}/data-process/{paper_id}/manual-update`。
- 上传策略：接口单文件上传，原始 PDF 保存到 `data/papers/{paper_id}/original.<ext>`。
- 重传策略：同 ID 重传接口仅接收 PDF，不再覆盖元数据。
- 后台执行：应用启动时创建 worker 池，任务状态持久化到 SQLite，支持重启后恢复待执行任务。
- 架构边界：仅保留 `data-process` 专用任务池（`services/data_process_task_manager.py`）与编排层（`services/data_process_orchestrator.py`）。
- 任务可观测与控制：新增 `/data-process/tasks` 列表、`/data-process/tasks/{task_id}/cancel` 终止、`/data-process/tasks/{task_id}/retry` 失败重试。
- 数据模型：`papers` 表新增 `raw_pdf_path` 与 `final_fact_check_trace_id` 字段；`images_paths` 与切图共存于 `data/papers/{paper_id}/`。
- 状态枚举：`extraction_status` 支持 `HUMAN_COMPLETED`；`fact_check_status` 支持 `HUMAN_PASSED`。
- Trace 可观测：`agent_traces` 增加 `llm_model`、`prompt_tokens`、`completion_tokens`、`total_tokens`、`usage_payload` 字段。
- 稳定性：当前后端测试全通过（91 例）。

---

## Phase 5: HITL 与 Survey Process (Week 5+)

**目标**: 引入人机协作能力并实现文献综述撰写工作流

| 任务              | 说明                                              | 状态                   |
| ----------------- | ------------------------------------------------- | ---------------------- |
| 5.1 HITL 状态机   | `IDLE/RUNNING/WAITING_FOR_HUMAN/COMPLETED/FAILED` | 待开始                 |
| 5.2 HITL 基础框架 | `AskHuman` 工具，状态挂起/恢复机制                | 待开始                 |
| 5.3 HITL API      | `POST /hitl/{project_id}/feedback` 提交人类反馈   | ⏳ 路由预留，业务待实现 |
| 5.4 Survey Writer | 综述生成、审校与导出流程                          | 待开始                 |

*(待设计)*

---

## 开发原则

1. **先跑通再优化**: 优先实现端到端流程，再优化细节
2. **测试驱动**: 每个功能点都应有对应的单元测试
3. **类型安全**: 所有数据模型使用 Pydantic，启用 strict 模式
4. **No ORM**: 直接使用 SQLite SQL，保持对数据模型的完全控制
