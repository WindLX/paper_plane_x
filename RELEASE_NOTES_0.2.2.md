# Paper Plane X 0.2.2 — Project workbench

## 中文

- 项目默认进入概览，固定提供概览、文献、文件、活动导航和可分享的深链接。概览展示当前处理状态、需要关注的论文、显式生成的研究摘要、最近记录、热门标签和年份统计；卡片与跳转提示统一样式。
- 项目活动持久保存，支持类别、结果、日期、关键词筛选与分页。任务完成后更新同一条活动；解除项目关联或删除任务记录后保留历史。活动页复用共享表格，类别和结果带图标，日期支持月份与年份跳转，每页可选择 10/20/50/100 条。
- 项目文件支持 PNG、JPEG、WebP、GIF 和静态自包含 SVG；校验实际内容，保留原字节下载。Markdown 按文件目录解析项目内配图，DOCX/PDF/HTML 转换包含图片；缺失、越界或外链资源明确阻止转换。
- ZIP 导出改为可恢复查看的后台作业，提供真实文件计数、下载进度、取消和再次下载。成品保留 24 小时；后端重启不自动续跑未完成作业。原同步 API 保留。
- 文件树默认展开，宽度可拖拽、键盘调整和双击复位；合并面包屑与操作栏，移除重复标题和无用侧栏按钮。修复菜单事件、PDF 获取焦点打断拖拽和窄屏空状态不可见的问题。
- Agent 配置使用单次总 Token 预算，默认 240000，后端自动计算输入及剩余输出空间；不再要求用户配置旧 `max_tokens` 或 tokenizer model。调整预算表单对齐。
- 逐记录与逐流式 chunk 日志使用 VERBOSE；高频读取和 MinerU 轮询使用 DEBUG，关键业务结果与异常保留可见等级。
- CLI 保持现有命令，上传支持图片原字节；更新按需读取的高级 Skill 参考和操作说明。
- Backend、CLI、Frontend、Zotero 统一更新至 0.2.2；DSH 与 Radar 保持独立版本。Zotero 本次仅同步发布版本。

## English

- Open projects on an overview with fixed Overview, Papers, Files, and Activity navigation and shareable deep links. Present current processing status, attention items, explicitly generated research summaries, recent records, tags, and year statistics with consistent cards and navigation cues.
- Persist project activities across paper unlinking and task-record deletion. Update one activity per processing run and filter by category, result, date, and keyword. Reuse the table shell, add category/result icons, support month/year navigation, and select 10/20/50/100 rows per page.
- Upload PNG, JPEG, WebP, GIF, and static self-contained SVG project images with content validation and original-byte downloads. Resolve local Markdown image paths and include images in DOCX/PDF/HTML exports; report missing, external, or escaping resources before conversion.
- Track background ZIP export jobs with real file counts, transfer progress, cancellation, and repeat downloads. Retain results for 24 hours, fail interrupted jobs on restart, and preserve the synchronous API.
- Expand directories by default, resize the file tree by pointer or keyboard, merge breadcrumbs and file actions, and remove duplicate headers. Fix menu events, PDF focus interrupting resize gestures, and off-screen empty states on narrow tables.
- Configure a total token budget per request, defaulting to 240000. Calculate input usage and remaining output room in the backend without requiring legacy `max_tokens` or a tokenizer-model setting. Align the budget form.
- Move per-record and per-stream-chunk diagnostics to VERBOSE and frequent reads and MinerU polling to DEBUG; retain meaningful business results and failures at visible levels.
- Preserve CLI commands, send uploaded image bytes unchanged, and update the progressively disclosed advanced Skill reference.
- Coordinate Backend, CLI, Frontend, and Zotero at 0.2.2. DSH and Radar keep independent versions; Zotero only receives the version update in this release.

See [workbench behavior](docs/project-workbench.md), [project files](paper_plane_x_frontend/docs/project-files.md), [activity history ADR](docs/adr/0001-project-activity-history.md), and [logging conventions](paper_plane_x_backend/docs/logging_conventions.md).
