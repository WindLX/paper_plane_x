# Paper Plane X 后端开发路线图

## 文档目的
本路线图用于同步当前代码真实进度、阶段目标与下一步优先级。
更新时间：2026-04-19（基于仓库代码与测试现状审查）。

## 审查结论（2026-04-19）

1. 核心后端链路已经打通：Project/Paper CRUD、Data Process 异步任务、任务持久化与恢复可用。
2. Librarian 已有可用 MVP：`/projection`、`/matrix`、`/search` 三类能力可用。
3. HITL 与 Survey Writer 仍处于占位阶段：路由前缀已保留，但业务尚未落地。
4. 测试基线总体稳定：本地执行为 154 通过、1 失败；失败位于 `tests/unit/test_tools_librarian.py`，属于文案断言不一致。

---

## Phase 1: 基础骨架（已完成）

目标：搭建可运行 FastAPI 项目骨架，支持 Project 管理。

| 任务                       | 说明                                   | 状态     |
| -------------------------- | -------------------------------------- | -------- |
| 1.1 项目结构完善           | `main.py`、`config.py`、uv + pyproject | ✅ 已完成 |
| 1.2 数据库连接层           | SQLite 原生连接封装、基础 CRUD、FTS5   | ✅ 已完成 |
| 1.3 Project/Paper 数据模型 | Pydantic 模型与序列化                  | ✅ 已完成 |
| 1.4 Project API            | 项目 CRUD + 项目论文关系               | ✅ 已完成 |
| 1.5 测试框架               | pytest + fixtures + API 集测           | ✅ 已完成 |

交付物：可通过 API 创建/维护项目与论文实体。

---

## Phase 2: Agent 引擎核心（已完成）

目标：实现可复用的 Agent Runtime，支持结构化输出与工具调用。

| 任务               | 说明                             | 状态     |
| ------------------ | -------------------------------- | -------- |
| 2.1 LiteLLM 集成   | 统一 LLMClient，多模型后端适配   | ✅ 已完成 |
| 2.2 消息模型       | OpenAI 兼容消息模型              | ✅ 已完成 |
| 2.3 工具系统       | ToolRegistry + `@tool` 装饰器    | ✅ 已完成 |
| 2.4 Agent 异常     | 运行、校验、工具异常分层         | ✅ 已完成 |
| 2.5 BaseAgent 核心 | `api/normal` 双模式 + trace 落库 | ✅ 已完成 |
| 2.6 单元测试       | Agent/Tool/LLM 核心覆盖          | ✅ 已完成 |

交付物：可低成本扩展新 Agent，且 I/O 受 Pydantic 严格约束。

---

## Phase 3: Data Process Workflow（已完成）

目标：实现单篇论文上传到结构化数据入库的完整流程。

| 任务                              | 说明                                       | 状态     |
| --------------------------------- | ------------------------------------------ | -------- |
| 3.1 PDF 解析                      | MinerU：PDF -> Markdown + 图片             | ✅ 已完成 |
| 3.2 Extraction/Analysis/FactCheck | 三智能体串联 + 事实核查闭环                | ✅ 已完成 |
| 3.3 上传即入队                    | `POST /api/v1/papers`                      | ✅ 已完成 |
| 3.4 重跑能力                      | `POST /api/v1/papers/{paper_id}/reprocess` | ✅ 已完成 |
| 3.5 人工回填                      | `PATCH /api/v1/papers/{paper_id}`          | ✅ 已完成 |
| 3.6 任务可观测与控制              | `/data-process/tasks` + cancel/retry       | ✅ 已完成 |
| 3.7 任务持久化                    | SQLite `data_process_tasks`                | ✅ 已完成 |
| 3.8 生命周期接管                  | FastAPI lifespan 启停 worker pool          | ✅ 已完成 |

交付物：上传 PDF -> 异步处理 -> 结果入库的完整后端闭环。

---

## Phase 4: 检索与数据能力增强（进行中）

目标：增强检索可组合性与跨论文对比能力。

| 任务                    | 说明                                        | 状态            |
| ----------------------- | ------------------------------------------- | --------------- |
| 4.1 Librarian 路由      | `/projection`、`/matrix`、`/search`         | ✅ 已完成（MVP） |
| 4.2 项目维度统一搜索    | `POST /api/v1/projects/{project_id}/search` | ✅ 已完成        |
| 4.3 Chroma 向量检索深化 | 扩展索引字段、排序与融合策略                | ⏳ 进行中        |
| 4.4 检索工具原子化      | 面向 Agent 的可组合检索能力                 | ⏳ 进行中        |
| 4.5 CLI 安全治理        | 路径白名单、超时、输出治理                  | ⏳ 规划中        |

当前里程碑：
- 已完成可用检索 MVP 与字段投影能力。
- 下一步聚焦向量检索深化与原子工具编排。

---

## Phase 5: HITL 与 Survey Workflow（待启动）

目标：引入人机协作决策与综述写作链路。

| 任务                        | 说明                                              | 状态   |
| --------------------------- | ------------------------------------------------- | ------ |
| 5.1 HITL 状态机             | `IDLE/RUNNING/WAITING_FOR_HUMAN/COMPLETED/FAILED` | 待开始 |
| 5.2 HITL API 落地           | `/api/v1/hitl/*` 从占位到可用接口                 | 待开始 |
| 5.3 Writer/Reviewer/Planner | Survey 多 Agent 协作流程                          | 待开始 |
| 5.4 导出链路                | 结构化输出到文稿导出                              | 待开始 |

说明：当前 `agents/planner.py`、`agents/reviewer.py`、`agents/writer.py` 为空占位文件。

---

## 当前后端快照

1. 路由分组：`project`、`paper`、`librarian`、`data_process` 已接入；`hitl` 仅路由前缀。
2. 任务系统：支持排队、执行、取消、重试；状态持久化；服务重启后恢复待处理任务。
3. 数据模型：论文状态已拆分为 `extraction_status`、`extraction_fact_check_status`、`analysis_fact_check_status`。
4. 数据库迁移：已具备迁移前自动备份与历史字段兼容迁移。

---

## 开发原则

1. 先跑通再优化：优先端到端可用。
2. 测试驱动：核心流程需有单测/集测支撑。
3. 类型安全：Pydantic + pyright 约束。
4. 可追溯：保留 Agent 交互 trace 与关键状态。
5. 数据库变更纪律：涉及 schema 变更必须包含迁移逻辑与迁移前备份。
