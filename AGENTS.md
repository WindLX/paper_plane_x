# Paper Plane X 工作区开发指南

## 适用范围与事实源

- 本文件适用于工作区根目录；进入子项目后，必须继续读取该目录中的 `AGENTS.md`，更深目录的规则优先。
- 本仓库是集成与发布工作区：Backend、CLI、DSH、Frontend、Zotero 与 Radar 是独立 Git submodule；不在根目录建立 Python 或 Node.js workspace，也不跨子项目共享虚拟环境、依赖目录或锁文件。
- 修改某个子项目前，先进入其目录，并以该项目的 `pyproject.toml` / `package.json`、锁文件、`justfile`、README 和 `docs/` 为事实源；文档与实现冲突时先核对代码和测试，再同步修正文档。
- 根 `justfile` 只负责跨项目编排。项目内开发优先运行该项目自己的 `just` 命令，不凭记忆拼装替代命令。
- 不在 `AGENTS.md` 中复制功能清单、接口清单或易过时的实现细节；项目机制应记录在 README、`docs/`、API schema 和代码中。

## 工作区与 Git 管理

- `paper_plane_x_backend`、`paper_plane_x_cli`、`paper_plane_x_dsh`、`paper_plane_x_frontend`、`paper_plane_x_zotero`、`paper_plane_x_radar` 都有独立 Git 历史。先在实际发生修改的子项目检查 diff 和验证，再处理顶层 submodule 引用。
- 保持最小修改范围，不覆盖用户已有或其他任务产生的脏改动；发现重叠修改时先说明风险再继续。
- 不手改构建产物、缓存、生成文件、vendored 依赖、锁文件中的非预期部分或运行时数据。依赖变化必须通过对应包管理器产生锁文件更新并说明原因。
- Backend、CLI、Frontend 与 Zotero 的版本号由根目录 `VERSION` 和 `scripts/sync_version.py` 统一协调；DSH 与 Radar 维护独立版本。未经发布任务明确要求，不修改版本或创建发布产物。
- 未经用户明确要求，不创建分支、不提交、不推送、不改写 Git 历史，也不初始化或更新 submodule 指针。
- 不提交 `.env`、密钥、token、私有服务地址、真实论文内容、数据库、日志或其他运行时数据；展示日志、截图和测试夹具前先去除敏感信息。

## 开发工作方式

- 修改前先阅读最近作用域的 `AGENTS.md`，再阅读与任务直接相关的源码、测试和文档；不要仅根据文件名或旧说明推断行为。
- 开始实质修改前说明已发现的约束和准备采取的方案；长任务中持续简短汇报发现、下一步、验证结果和阻塞，不等到结束才汇总。
- 优先解决当前明确需求，不为假想客户端、框架、平台或兼容场景增加抽象。
- 一次性直线逻辑不提取私有 helper；只有公共 API、框架回调、边界隔离、复杂不变量、可复用领域操作或显著改善测试性时才新增函数或抽象。
- 不添加静默 fallback、兼容 shim、宽泛异常捕获、吞异常、monkey patch 或临时 hack，除非任务明确要求相应策略；边界失败应提供可定位的错误信息。
- 防御性处理放在外部输入输出、网络、文件、进程、资源生命周期和持久化边界。由类型、协议或构造过程保证的不变量不重复校验，避免在热路径叠加无意义分支或扫描。
- 优先使用显式类型、属性、枚举、穷举分支和清晰的数据模型；避免字符串驱动控制流、动态属性探测和无类型 duck typing。
- 修改公共 API、CLI 输出、持久化格式、跨项目协议或用户流程时，必须检查所有受影响子项目，并同步类型、调用方、测试和文档；不能只让单侧暂时通过。

## 测试与验证

- 新行为和缺陷修复必须有回归测试；纯文档或无法自动化的改动应说明采用的替代验证。
- 先运行最接近改动的定向测试，再按风险扩大到项目的 lint、类型检查、完整测试和 build；跨项目契约变更至少验证生产方和直接消费方。
- 根目录常用聚合命令为 `just test`、`just lint`、`just build` 和 `just pre-commit`，目前覆盖 Backend、CLI、Frontend、Zotero 与 Radar，不包含 DSH；涉及 DSH 时进入其目录单独运行验证。只有任务确实影响这些项目且依赖已就绪时才运行聚合命令。
- 不得声称未执行的检查已通过。验证失败时报告完整命令、关键失败项、是否由本次改动引入，以及尚未验证的范围。
- 不为了通过测试削弱断言、删除覆盖、跳过检查或改变真实契约；若测试与预期冲突，先查明哪一方过时。

## 语言与文档

- 代码、标识符和面向开发者的技术术语遵循现有项目风格；用户可见文案按项目要求同时维护简体中文和英文。
- Markdown 在没有新段落、列表或语义断点时，不因行宽机械换行；表格、代码块和格式化工具接管的文件除外。
- 文档解释设计动机、边界、操作方式和验证方法，不重复大段源码。核心数学、检索评分、排序或其他非直观算法必须在代码中解释假设与关键步骤，并在对应项目的 `docs/` 中给出推导、限制和验证依据。
- 新增或移动文档后检查相对链接；命令示例必须与当前配置文件和 `justfile` 一致。

## 子项目导航

- 后端服务与 Python Agent 运行时：`paper_plane_x_backend/AGENTS.md`
- HTTP CLI 与外部 Agent Skills：`paper_plane_x_cli/AGENTS.md`
- DeepSeek Harness 插件：`paper_plane_x_dsh/AGENTS.md`
- Vue Web 控制台：`paper_plane_x_frontend/AGENTS.md`
- Zotero 插件：`paper_plane_x_zotero/AGENTS.md`
- Codex 文献雷达与晨报投递：`paper_plane_x_radar/AGENTS.md`
