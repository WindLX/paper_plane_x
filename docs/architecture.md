# AI 智能体科研工作流系统设计方案 (Paper Plane X)

## 1. 项目概述与核心原则
本项目旨在构建一个针对科研 Survey 环节的多 Agent 协作工作流。
**核心原则**：
- **极简工程设计**：弃用 LangGraph/Celery 等重型图计算和任务调度框架，依托 FastAPI lifespan + SQLite 数据库维护系统状态机。
- **强制结构化约束**：所有 Agent 的输入、输出必须严格由 Pydantic Schema 定义与校验。
- **人机协同 (HITL, Human-in-the-loop)**：核心决策节点（如大纲确认、质量审查）支持状态机挂起（Suspend），等待并集成人类反馈后再恢复执行。
- **绝对事实溯源**：所有 AI 生成的内容必须带有精确的文献锚点（如 `[DocID-Section]`），且 LLM 的完整交互轨迹（Trace）必须落库以备回溯。

## 2. 技术栈选择
- **包管理与运行**：`uv` (Python 生态), `pnpm` (Node.js 生态)
- **后端服务**：`FastAPI` (提供 RESTful 控制接口，管理异步任务)，数据库不使用任何 ORM 框架
- **AI 交互引擎**：`LiteLLM` (统一兼容多模型 API 调用), `Pydantic` (Schema 约束与解析)
- **持久化层**：`SQLite` (存储元数据、项目状态机上下文、利用 FTS5 插件实现全文检索), `ChromaDB` (轻量级本地向量库，当前暂列待做)
- **前端交互**：`Vue 3` + `Vite` + `TypeScript`
- **基础工具链**：`MinerU` (PDF 转 Markdown 多模态解析), `Pandoc` (最终产物格式化导出)

---

## 3. 系统分层架构设计
系统采用自顶向下的分层架构设计，确保职责单一和模块解耦。

### 3.1 App 层 (全局控制层)
App 层作为系统的顶层入口，基于 FastAPI 构建 Web 服务器。前端通过 HTTP 请求驱动后端执行各类操作。
- **职责**：维护全局配置（如模型密钥、并发数限制）、依赖注入（Database Session, Clients）、路由分发以及后台任务的生命周期管理。

#### 3.1.1 前后端交互流（RESTFUL API）
当前后端已实现并稳定提供以下核心接口：

- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `GET /api/v1/projects/{id}`
- `PATCH /api/v1/projects/{id}`
- `DELETE /api/v1/projects/{id}`
- `POST /api/v1/papers`
- `GET /api/v1/papers`
- `GET /api/v1/papers/{paper_id}`
- `PATCH /api/v1/papers/{paper_id}`
- `POST /api/v1/papers/{paper_id}/reprocess`
- `DELETE /api/v1/papers/{paper_id}`
- `GET /api/v1/projects/{id}/papers`
- `GET /api/v1/projects/{id}/papers/{paper_id}`
- `POST /api/v1/projects/{id}/papers/{paper_id}`
- `DELETE /api/v1/projects/{id}/papers/{paper_id}`
- `GET /api/v1/projects/{id}/papers/search`
- `GET /api/v1/data-process/tasks`（任务状态总览）
- `POST /api/v1/data-process/tasks/{task_id}/cancel`（终止任务）
- `POST /api/v1/data-process/tasks/{task_id}/retry`（失败/取消任务重试）

接口返回 `202 Accepted` 后，通常在后台 data-process worker 池中完成处理；若上传命中已完成论文（同 SHA256），则直接返回复用结果并跳过入队。上传与重试接口返回 `task_id`，用于查询队列状态、终止任务与失败重试；若命中处理中论文（同 SHA256 且状态为 `PENDING/PROCESSING`），返回 `409 Conflict`。

### 3.2 Project 层 (项目管理层)
Project 是用户管理科研工作流的基本业务单元。系统中的所有行为与产物均归属于特定的 Project。

**Project 核心属性 (落库映射):**
1. `project_id`: 唯一标识 (UUID)
2. `name`: 项目名称
3. `created_at` / `updated_at`: 时间戳
4. `current_data_process_state`: 当前 data-process 任务状态节点
5. `operation_logs`: 项目级别的核心操作流水

**用户针对 Project 可执行的动作:**
- **CRUD 操作**：新建、删除、重命名、获取列表。
- **产物管理**：查看/导出当前项目的中间产物和最终 Survey 报告。
- **任务驱动**：启动 data-process 任务，或在 HITL 节点提交人类反馈推进处理。

### 3.3 Data Process 任务层
Data Process 由一系列状态机节点组成。节点由各类 Sub-Agent 和 Utility Tools 构成。当 Project 未主动驱动时，状态处于 IDLE。

关键边界约定：
- 当前仅保留 `Data Process` 任务池（任务模型、队列管理、生命周期控制）。
- API 与执行器均围绕 data-process 任务池组织，不再引入通用 workflow 抽象。

当前核心处理链：`Data Process`（数据解析入库）。

#### 3.3.1 Data Process 处理链
该处理链负责将上传的单篇 PDF 转换为高价值、结构化的知识切片，并写入 SQLite（含 FTS5 索引）。
接口层保持“单文件上传”，并发吞吐由后台 worker 池消费任务队列实现。
每次入队会生成 `task_id`，并维护任务状态：`QUEUED/RUNNING/COMPLETED/FAILED/CANCELED`（运行中取消显示为 `CANCELING`）。

当前实现拆分：
- `api/routers/data_process.py`: 仅做 HTTP 入参校验、错误映射、响应组装
- `services/orchestrators/data_process.py`: Data Process 业务编排与领域错误边界
- `services/data_process_tasks/task_manager.py`: Data Process 任务队列、worker lifecycle、cancel/retry 状态流

针对单篇论文，采用**并行双分支处理机制**：

##### 3.3.1.1 阶段一：原始解析 (MinerU Parsing)
调用 `MinerU` 将 PDF 转换为包含版面信息的 Markdown 与图片。
- **Input**: `raw_pdf` (文件流), `meta_json` (论文元数据：Title, Authors, Year 等)
- **Config**: MinerU Client 参数
- **Output**: `raw_md` (全文 Markdown), `images` (提取图片路径列表), 合并后的完整 `PaperMetadata`。

当前实现约束：
- 原始 PDF 落盘到 `data/papers/{paper_id}/original.<ext>`。
- `papers` 表记录 `raw_pdf_path`，与 `images_paths` 一起形成可追溯文件锚点。
- `create_paper` 在计算 `raw_pdf_sha256` 后执行复用分流：
    - 命中 `COMPLETED/HUMAN_COMPLETED`：直接复用既有 `paper_id`，返回 `COMPLETED`，不再入队。
    - 命中 `PENDING/PROCESSING`：拒绝重复提交，返回 `409 Conflict`。
    - 命中 `FAILED`：复用既有 `paper_id` 并重新入队。
    - 未命中：创建新论文记录并入队处理。

##### 3.3.1.2 阶段二：双分支并行提炼 (Parallel Extraction + Analysis)
由 `ExtractionAgent` 与 `AnalysisAgent` 并行处理同一份论文内容。
- **Input**: `raw_md`, `images` (可选)
- **Long Memory**: `System.md` + 各自任务 Prompt（`Extraction.md` / `Analysis.md`）。
- **Short Memory**: 各分支独立维护，核查失败时仅反馈到对应分支进行重试。
- **Output (Pydantic 强制约束)**:
    - Extraction 分支：`QuickScan` + `SynthesisData`
    - Analysis 分支：`AnalysisReport`
- **鲁棒性机制**：内置解析重试逻辑。若 LLM 输出无法被 Pydantic 解析，将自动重试；达最大重试次数则挂起任务通知人类。

##### 3.3.1.3 阶段三：双分支事实核查 (Dual Fact Checking)
由两个独立 `FactCheckAgent` 实例分别核查两条分支结果，严格比对“提取产物”与“原始解析产物”，防止 LLM 幻觉。
- **Input**:
    - Extraction 分支：`raw_md` + `QuickScan` + `SynthesisData`
    - Analysis 分支：`raw_md` + `AnalysisReport`
- **Long Memory**: 设定的核查指令（重点关注数据捏造和结论篡改）。
- **Short Memory**: 无。每次核查均为独立评估。
- **Output (Pydantic)**: `FactCheckResult` (包含 `is_passed` 布尔值，以及 `correction_suggestions` 具体错误指引)。
- **流程控制**：任一分支 `is_passed == False`，仅对对应分支执行局部修正闭环；最终若仍未通过，论文状态进入 `HUMAN_COMPLETED` 等待人工处理。

##### 3.3.1.4 阶段四：数据入库 (Knowledge Ingestion)
将验证无误的最终结构化数据持久化：
- **SQLite 存储**：论文元数据、结构化提取字段（JSON 存入）、事实核查记录、原始 Markdown 文本（建立 FTS5 索引供关键词精准检索）。
- **ChromaDB 存储（待做）**：规划接入 `review_summary` 级别向量索引，并在下一阶段升级为 `SynthesisData` 多粒度索引（`research_gap`、`methodology`、`key_results`、`review_summary`）。

##### 3.3.1.5 数据处理流伪代码示例
```python
# 伪代码：反映“上传入队 + 后台消费 + 双分支并行闭环”
async def upload_endpoint(project_id, pdf_file, metadata):
    paper = create_pending_record(project_id, metadata)
    pdf_path = save_to_data_dir(paper.paper_id, pdf_file)  # data/papers/{paper_id}/original.ext
    set_raw_pdf_path(paper.paper_id, str(pdf_path))
    enqueue(paper.paper_id, pdf_path)
    return {"paper_id": paper.paper_id, "status": "PENDING"}


async def worker_process_task(paper_id, pdf_path):
    raw_md, image_paths = await mineru.parse_pdf(pdf_path)

    extraction_result, extraction_fc, extraction_retry = run_extraction_loop(
        raw_md, image_paths, max_retries=MAX_RETRY_COUNT
    )
    analysis_result, analysis_fc, analysis_retry = run_analysis_loop(
        raw_md, image_paths, max_retries=MAX_RETRY_COUNT
    )

    if extraction_fc.is_passed and analysis_fc.is_passed:
        update_status(paper_id, "COMPLETED")
    else:
        update_status(paper_id, "HUMAN_COMPLETED")

    save_results_to_sqlite(
        paper_id,
        raw_md,
        image_paths,
        extraction_result,
        analysis_result,
        extraction_fc,
        analysis_fc,
        extraction_retry,
        analysis_retry,
    )
```

#### 3.3.2 Survey 工作流
*(TODO: 待设计)*

---

### 3.4 基础底层组件 (Core Components)

#### 3.4.1 Agent 引擎设计 (`src/core/agent_runtime/base_agent.py`)
系统中的所有 Agent（如 Planner, Writer, Reviewer）均继承自统一的 BaseAgent。Agent 的心智模型包含：
1. **Brain**: 核心 LLM 实例（基于 LiteLLM），可选纯文本模型或 VLM 多模态模型。
2. **Long Memory (System Prompt)**: 静态记忆，定义 Agent 的 Role（角色）、Task（任务目标）、Tools（工具使用规范）和 Output Schema。
3. **Short Memory (Context)**: 动态记忆，存储当前会话的上下文、历史调用轨迹及报错信息，形态为标准的 Message List。
4. **Tools**: Agent 被授权使用的函数库集合。
5. **Output Parser**: 依托 Pydantic BaseModel 强约束返回结构。

**Agent 核心调度逻辑 (ReAct/Tool-Call 循环):**
Agent 内部实现了一套防死循环的自主运转机制，自动处理工具调用和格式校验。
```python
# 伪代码：安全的 Agent 执行引擎
class BaseAgent(Generic[OutputType]):
    def __init__(self, config: Config, output_schema: Type[OutputType]):
        self.brain = LiteLLM(...)
        self.tools = [...] # 可用工具注册
        self.output_schema = output_schema
        self.long_memory = self._build_system_prompt()

    async def run(self, inputs: dict) -> OutputType:
        short_memory = [self.long_memory, self._format_user_prompt(inputs)]
        
        for step in range(MAX_AGENT_STEPS): # 防死循环限制
            response = await self.brain.generate(messages=short_memory, tools=self.tools)
            short_memory.append(response.message)
            
            # 场景 1：模型决定调用工具
            if response.is_tool_call:
                for tool_call in response.tool_calls:
                    try:
                        tool_result = await self.execute_tool(tool_call)
                    except Exception as e:
                        tool_result = f"Tool Execution Error: {str(e)}"
                    # 将工具执行结果追加到短期记忆，供 LLM 决策
                    short_memory.append(ToolResultMessage(tool_result))
                continue # 继续下一次 LLM 思考
            
            # 场景 2：模型输出最终结果，尝试进行 Pydantic 校验
            try:
                final_output = self.output_schema.model_validate_json(response.content)
                self.save_trace(short_memory) # 记录完整 Trace 备查
                return final_output
            except ValidationError as e:
                # 校验失败，将报错信息告诉 LLM 让其自我纠正
                error_msg = f"Output parsing failed: {e}. Please strictly follow the JSON schema."
                short_memory.append(UserMessage(error_msg))
                continue
                
        raise AgentExecutionError("Exceeded maximum processing steps or recurrent JSON errors.")
```

**IO 协议规范化**：所有 Agent 和 Tool 的交互数据均被封装为派生自 pydantic.BaseModel 的类。通过 LiteLLM 的 Structured Outputs 功能，强制底层 LLM 完全按照预定义的 JSON Schema 生成数据，从源头消灭传统正则解析带来的工程不稳定性。

#### 3.4.2 独立工具模块 (Utils)
不与 Agent 直接发生交互，在 Workflow 外部或者特定节点作为独立函数调用的工程工具。
- **`MinerU`**: PDF 解析引擎，将版面转为 Markdown/图片，支撑数据预处理阶段。
- **`Pandoc`**: 格式转换流水线，用于在最后阶段将内部的 Markdown 综合报告转储为 PDF 或 Word (`.docx`) 格式。

#### 3.4.3 智能体工具集 (Tools)
挂载在 Agent 实例上，允许 LLM 在思考过程中主动发起调用的功能函数。
- **[`Librarian`](./librarian.md)**: 文献检索工具合集，当前提供项目级 FTS5 检索与 Layer1 点路径能力；下一阶段规划补齐向量检索并拆分为原子能力（FTS 检索、向量检索、融合重排、上下文扩展、证据追踪），供 Agent 自由组合。
- **`Text CLI Tools`** *(Phase 4 规划中)*: 为 Agent 提供受限 `rg/awk/sed` 文本处理能力，用于检索后整理与汇总；执行边界采用白名单目录、可写受限临时目录、超时和输出截断。
- **`AskHuman`** *(TODO)*: 人机交互工具。当 Agent 遇到不确定边界、或者完成关键里程碑（如大纲生成完毕）时调用此工具。它会向系统抛出中断信号（Suspend），将状态机置于 `WAITING_FOR_HUMAN`，并在前端弹窗请求指导。

#### 3.4.4 数据库层 (Database)
当前数据层采用 `sqlite3` 原生封装（无 ORM），并实现以下结构：

- `projects`: 项目元数据、状态上下文与操作日志
- `papers`: 论文元数据与处理产物（含 `md_content`、`raw_pdf_path`、`images_paths`、`analysis_report`、分支化核查字段 `extraction_fact_check_*` 与 `analysis_fact_check_*`，以及 `extraction_final_fact_check_trace_id` / `analysis_final_fact_check_trace_id`）
- `paper_projects`: 论文与项目的关联关系（多对多）
- `agent_traces`: Agent 交互轨迹与 LLM 用量信息（`trace_id`、`agent_name`、`llm_model`、`prompt_tokens`、`completion_tokens`、`total_tokens`、`usage_payload`）
- `data_process_tasks`: data-process 任务状态持久化
- `papers_fts`: 基于 FTS5 的全文索引（由触发器与 `papers` 同步）

当前策略：默认按最新 schema 初始化，不再维护历史字段兼容迁移。



