# Paper Plane X

Paper Plane X 是一套面向个人科研工作流的本地优先工具集，核心目标是把“上传论文 -> 解析 -> 结构化提炼 -> 人工校正 -> 项目管理”这一条链路整理得干净、稳定、可追溯。

当前仓库包含三个主要部分：

- `paper_plane_x_backend/`：FastAPI 后端，负责数据处理、任务编排、项目管理、检索接口与数据落库
- `paper_plane_x_frontend/`：Vue 3 控制台，用于管理项目、任务与查看处理结果
- `paper_plane_x_zotero/`：Zotero 插件，用于从文献管理侧发起同步、查看与人工编辑

版本管理、配置约定与跨子项目的共同规则，统一见：

- [PROJECT_CONVENTIONS.md](./PROJECT_CONVENTIONS.md)
- [VERSION](./VERSION)

## 仓库结构

```text
paper_plane_x/
├── VERSION
├── PROJECT_CONVENTIONS.md
├── scripts/
│   └── sync_version.py
├── paper_plane_x_backend/
├── paper_plane_x_frontend/
└── paper_plane_x_zotero/
```

## 推荐阅读顺序

如果你是第一次进入这个仓库，建议按这个顺序看文档：

1. 本文档：了解仓库整体结构与各模块职责
2. [paper_plane_x_backend/README.md](./paper_plane_x_backend/README.md)：后端能力、开发、测试、部署入口
3. [paper_plane_x_backend/docs/README.md](./paper_plane_x_backend/docs/README.md)：后端详细文档索引
4. [paper_plane_x_frontend/README.md](./paper_plane_x_frontend/README.md)：前端控制台开发与构建
5. [paper_plane_x_zotero/README.md](./paper_plane_x_zotero/README.md)：Zotero 插件开发与使用

## 当前开发方式

这个项目有意保持“个人项目友好”的工作流：

- 前后端分别独立运行，不引入仓库根统一编排工具
- 后端通过 `PPX_CONFIG_FILE` 选择配置 profile
- 前端通过 `VITE_API_BASE_URL` 选择目标后端
- 版本号由仓库根 `VERSION` 单一维护

## 常用命令

### 后端

```bash
cd paper_plane_x_backend
uv sync
cp .env.example .env
./scripts/dev_api.sh
```

### 前端

```bash
cd paper_plane_x_frontend
pnpm install
cp .env.example .env
pnpm dev
```

### 版本同步

```bash
python scripts/sync_version.py --set 0.1.1
```

## 文档导航

### 后端

- [Backend README](./paper_plane_x_backend/README.md)
- [Backend Docs Index](./paper_plane_x_backend/docs/README.md)
- [Architecture](./paper_plane_x_backend/docs/architecture.md)
- [Quickstart](./paper_plane_x_backend/docs/workflow_quickstart.md)
- [Testing Guide](./paper_plane_x_backend/tests/README.md)

### 前端

- [Frontend README](./paper_plane_x_frontend/README.md)

### Zotero 插件

- [Zotero README](./paper_plane_x_zotero/README.md)
