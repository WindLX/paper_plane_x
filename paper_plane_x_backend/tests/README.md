# 测试目录说明

当前测试按职责分层：

- `tests/unit/`：纯单元测试（不依赖 HTTP 路由行为）
  - `test_agent_runtime.py` / `test_agent_runtime_extended.py`：Agent runtime、LLM client、memory/tooling
  - `test_data_process_task_manager.py`：任务池生命周期、取消与关闭行为
  - `test_paper_repository.py`：PaperRepository 的数据访问与状态重置逻辑
  - `test_paper_parser.py`：PaperParser 的输入准备与图片编码逻辑
  - `test_paper_processor.py`：PaperProcessor 的处理流水线与失败回滚逻辑
  - `test_database_service.py`：SQLite schema 初始化与迁移兜底
  - `test_orchestrators_data_process.py`：编排器业务分支与重试路径
  - `test_data_process_router_lifecycle.py`：worker 池生命周期委托
  - `test_models_core.py`：核心模型序列化/反序列化与枚举解析
  - `test_config_settings.py`：配置合并与 agent 级覆盖逻辑
- `tests/integration/`：API 与业务编排集成测试
  - `test_project_api.py`：Project 路由、Paper 顶层路由与 Project-Paper 关联
  - `test_data_process_api.py`：data-process 路由与编排
  - `test_app_health.py`：应用健康检查端点
- `tests/conftest.py`：共享 fixture（临时运行目录、测试 DB、TestClient）

## 覆盖重点

- Data-process worker 池在 shutdown 时的可中断性：`test_data_process_task_manager.py`
- Data-process 运行中任务取消竞态与清理路径：`test_data_process_task_manager.py`
- Data-process 提交/重试/取消/重试失败任务等关键流程：`test_data_process_api.py`
- Data-process 已取消任务重试链路：`test_data_process_api.py`
- Agent 结构化输出、工具循环、trace 落库与 LLMClient 请求构造：unit agent tests
- Database schema 新字段与旧表清理：`test_database_service.py`
- Orchestrator 对重试失败任务的边界处理：`test_orchestrators_data_process.py`
- 核心模型 JSON/枚举转换：`test_models_core.py`
- Settings agent 配置覆盖合并：`test_config_settings.py`

## 当前回归状态

- 后端当前回归结果：103 passed
- 推荐本地执行顺序：
  1. `uv run ruff check .`
  2. `uv run pyright`
  3. `uv run pytest -q`

## 约定

- 新增测试时优先判断应放入 `unit` 还是 `integration`。
- 文件名使用 `test_*`，类/函数命名反映行为，不反映实现细节。
- 修复 bug 时，优先补最小可复现测试，再改实现。
