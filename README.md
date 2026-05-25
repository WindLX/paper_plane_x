# Paper Plane X

| 目录                      | 说明                                               | 依赖 |
| ------------------------- | -------------------------------------------------- | ---- |
| `paper_plane_x_backend/`  | FastAPI 后端。PDF 解析、结构化分析、文献检索、对话 | 无   |
| `paper_plane_x_frontend/` | Vue 3 控制台。项目管理、任务监控、Settings         | 后端 |
| `paper_plane_x_zotero/`   | Zotero 7 插件。右键上传、查看/编辑处理结果         | 后端 |

后端通过 HTTP API 对外暴露全部能力。前端和插件均可选。

## 启动

后端必须先启动。

```bash
# 1. 后端
cd paper_plane_x_backend
uv sync && cp .env.example .env && uv run app
```

首次启动后配 LLM Provider，否则 PDF 处理不执行。详见 [后端 README](paper_plane_x_backend/README.md#首次配置)。

```bash
# 2. 前端（可选）
cd paper_plane_x_frontend
pnpm install && cp .env.example .env
# 编辑 .env.development，改 VITE_API_BASE_URL
pnpm dev

# 3. Zotero 插件（可选）
cd paper_plane_x_zotero
npm install && npm run build
# Zotero → Tools → Plugins → Install Plugin From File → .scaffold/build/*.xpi
```

## 版本

版本号由根目录 `VERSION` 单一维护：

```bash
python scripts/sync_version.py --set 0.1.1
```
