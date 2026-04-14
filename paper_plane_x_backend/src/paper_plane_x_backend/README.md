# paper_plane_x_backend 包说明

该目录是后端核心代码包，按职责分层组织。

## 目录结构

- api
	- FastAPI 路由与依赖注入
- services
	- 业务编排与任务执行
- core/agent_runtime
	- BaseAgent、LLMClient、memory、tooling
- agents
	- Extraction/FactCheck 等 Agent 封装
- models
	- Pydantic 数据模型
- schemas
	- API 与 Agent I/O schema
- tools
	- Agent 可调用工具

## Data Process 主链路

1. API 接收上传请求
2. orchestrator 落盘与业务校验
3. task_manager 入队并由 worker 执行
4. paper_service 执行解析、提取、核查、回写

关键文件：

- services/data_process_orchestrator.py
- services/data_process_task_manager.py
- services/paper_service.py
- api/routers/data_process.py

## 代码约定

- 不使用 ORM，统一走 SQLite 原生封装。
- 业务错误在服务层收敛，路由层负责 HTTP 映射。
- Agent 输出必须通过 schema 校验。
- 关键流程日志统一采用 event= 字段。
