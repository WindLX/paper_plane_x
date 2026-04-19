# paper_plane_x_backend 包说明

该目录是后端核心代码包，按职责分层组织。

## 目录结构

- api/routers
	- FastAPI 路由（project、paper、data_process、hitl）
- services/orchestrators
	- 业务编排入口（project、paper、data_process）
- services
	- 数据访问与任务管理（paper/repository、database、data_process_tasks）
- core/agent_runtime
	- Agent 运行时（BaseAgent、LLMClient、tooling、memory）
- schemas
	- API 与 Agent I/O schema
- tools
	- Agent 可调用工具

## Data Process 主链路

1. `POST /api/v1/papers` 接收上传请求并创建/复用论文。
2. `orchestrators/paper.py` 触发 `orchestrators/data_process.py` 入队任务。
3. `data_process_tasks/task_manager.py` 持久化任务并由 worker 池执行。
4. `paper/` 目录下 `parser.py`、`processor.py`、`repository.py` 分别执行解析、提取编排与数据访问。

关键文件：

- services/orchestrators/paper.py
- services/orchestrators/data_process.py
- services/orchestrators/project.py
- services/data_process_tasks/
- services/paper/
- api/routers/paper.py
- api/routers/data_process.py

## 代码约定

- 不使用 ORM，统一走 SQLite 原生封装。
- 业务错误在服务层收敛，路由层负责 HTTP 映射。
- Agent 输出必须通过 schema 校验。
- 关键流程日志统一采用 `event=` 字段。
