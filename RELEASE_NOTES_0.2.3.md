# Paper Plane X 0.2.3 — Project navigation and Zotero linking

## 中文

- 项目概览将热门标签和年份分布前置，紧随数量统计卡片；桌面并排显示，窄屏纵向排列。
- 项目名称右侧恢复项目 ID 的一键复制入口，切换标签页仍可使用。空间充足时显示完整 ID，名称与 ID 合计宽度不足时优先省略 ID，悬停查看和复制始终使用完整值，不额外增加顶部行高。
- Zotero 侧边栏关联项目复用条目区的项目选择弹窗，可按名称、描述或 ID 搜索；保留折叠的手动项目 ID 输入入口。
- 修复 Zotero 手动输入项目 ID 时侧边栏重绘导致折叠、失焦和光标位置丢失的问题。取消选择不修改关联；避免重复启动绑定，侧边栏失效或插件卸载后停止派发绑定请求。
- Backend、CLI、Frontend、Zotero 统一更新至 0.2.3。Backend 和 CLI 本次仅同步发布版本；DSH 与 Radar 保持独立版本。

## English

- Move tags and year statistics immediately after the count cards in the project overview. Display the two sections side by side on desktop and vertically on narrow screens.
- Restore a one-click project ID beside the project name across all tabs. Show the full ID whenever space permits and truncate it first when the combined name and ID do not fit. Hover and copy retain the full value without adding a header row.
- Reuse the item-list project picker in the Zotero sidebar, with search by name, description, or ID. Keep manual project ID entry in a collapsible section.
- Preserve the manual entry section, input focus, and cursor selection during sidebar redraws. Cancellation leaves associations unchanged; prevent duplicate linking and stop dispatching when the sidebar becomes inactive or the plugin unloads.
- Coordinate Backend, CLI, Frontend, and Zotero at 0.2.3. Backend and CLI only receive version updates; DSH and Radar retain independent versions.

See [project page design](paper_plane_x_frontend/design-system/pages/projects.md) and [Zotero usage](paper_plane_x_zotero/README.md).
