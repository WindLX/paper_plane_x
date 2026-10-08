# Paper Plane X 0.2.1 — Research workspace improvements

## 中文

- 项目文件采用文件树与单文件内容视图；超长 JSON 等文本软换行，Markdown 代码、宽表格和公式局部滚动，避免挤压右侧栏。
- 项目文本文件增加多文件上传、同名覆盖／跳过、原文件下载和明确删除入口；切换文件或离开编辑时保护未保存内容。
- 任务支持批量取消、重试与删除记录；文献库支持批量项目关联、解除关联和删除论文；项目内支持批量移除关联。跨页保留勾选，逐项报告成功、失败与跳过原因。
- 批量 checkbox 与按钮图标对齐现有 UI，操作条仅在选中后出现在通用表格标题栏，标题栏保持 52px 高度。
- 左侧导航、右侧详情和 PDF 支持拖拽与键盘调整；左右栏宽度持久保存，展开或收起 PDF 保留详情宽度。中间画布至少为 960px，空间不足时横向滚动；右栏保持在屏幕内，长 DOI 等元数据按容器宽度换行。
- 修复项目文件中的论文链接打开详情后无法阅读 PDF 的问题。
- Zotero 增加批量重新处理与解除项目关联，按论文 ID 合并重复请求；批量刷新使用分块 batch-get，单项失败隔离，关闭发起窗口或卸载插件后停止派发后续操作。
- Researcher Skill 优先呈现检索、查询规则、字段矩阵、笔记与全文资源；项目文件操作迁入按需读取的 `advanced-topics.md`。CLI 命令保持现有范围。
- Skill 安装与卸载默认使用通用目录 `~/.agents/skills`；需要其他位置时显式指定 `--target-dir`。
- Backend、CLI、Frontend 和 Zotero 统一为 0.2.1；DSH、Radar 保持独立版本。本轮不处理浏览器最小化问题。

## English

- Browse project files with a file tree and single-file preview/editor. Wrap long JSON and text lines, while code, wide tables, and formulas scroll locally.
- Upload multiple project text files, choose overwrite or skip for existing names, download original bytes, and delete files or empty directories. Protect unsaved edits during navigation.
- Run bulk task cancellation, retry, and record deletion; manage project associations or delete papers from the library; remove selected associations within a project. Keep selection across pages and report each outcome.
- Style selection checkboxes and action icons consistently. Show bulk controls only when rows are selected in the shared table header, preserving its 52px height.
- Resize navigation, details, and PDF panes by dragging or keyboard. Persist sidebar widths and preserve detail width when toggling the PDF. Keep a 960px research canvas with horizontal scrolling when needed, contain the right pane within the viewport, and wrap long DOI and other metadata by container width.
- Fix PDF reading from paper links in project files.
- Reprocess or unlink selected Zotero items in batches, merge duplicate paper IDs, refresh details through chunked batch-get, isolate item failures, and stop further dispatch when the owning window closes or the plugin unloads.
- Prioritize research commands in the Researcher Skill and disclose project-file commands through `advanced-topics.md` only when needed. Preserve the existing CLI command surface.
- Install and uninstall Skills in the generic `~/.agents/skills` directory by default; select other locations explicitly with `--target-dir`.
- Update Backend, CLI, Frontend, and Zotero to 0.2.1. DSH and Radar retain independent versions; browser minimization investigation is deferred.

See [project-file behavior](paper_plane_x_frontend/docs/project-files.md), [domain vocabulary](CONTEXT.md), and [advanced Skill reference](paper_plane_x_cli/skills/ppx-researcher/references/advanced-topics.md).
