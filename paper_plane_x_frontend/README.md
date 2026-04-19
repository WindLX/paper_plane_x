# Paper Plane X Frontend

前端基于 Vue 3 + TypeScript + Vite，用于承接后端 Data Process 工作流与后续 HITL 交互。

## 开发启动

```bash
cd paper_plane_x_frontend
pnpm install
pnpm dev
```

默认开发地址：

- http://127.0.0.1:5173

## 构建与检查

```bash
pnpm vue-tsc
pnpm build
pnpm preview
```

## 当前状态

- 前端仍处于基础壳阶段。
- 后续将围绕以下功能建设：
	- Project 列表与详情
	- PDF 上传与任务状态轮询
	- 任务取消与重试操作
	- HITL 反馈入口

## 对接后端

推荐后端地址：

- http://127.0.0.1:8000

主要接口分组：

- /api/v1/projects
- /api/v1/papers
- /api/v1/projects/{project_id}/papers
- /api/v1/data-process/tasks
