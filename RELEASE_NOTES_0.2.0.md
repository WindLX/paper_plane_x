# Paper Plane X 0.2.0 — MinerU 4 migration

## 中文

- 本地 PDF 解析迁移至 MinerU 4.x V1：校验和上传、异步任务轮询、Markdown 与图片产物下载，默认 standard 质量和全部页面。
- 保留 PPX `/api/v1/parse/pdf`、论文处理流程及 CLI JSON 输出契约；旧 MinerU `/file_parse` 服务需先迁移。
- CLI `ppx pdf parse` 新增 `--timeout`，默认 1800 秒，适应按需部署的首次启动和长论文；同步 bundled PDF skill。
- 提供 systemd 按需启动和闲置超过一小时停止模板，停止前保护传输及后台解析任务。
- 本地 `output_dir` 表示 PPX 的产物目录，不再发送到 MinerU 主机。云端解析器不受此次本地协议迁移影响。

## English

- Migrate local PDF parsing to MinerU 4.x V1 uploads, asynchronous parse jobs, and artifact downloads, using Standard quality and all pages.
- Preserve the PPX public PDF API, paper processing workflow, and CLI JSON output. Upgrade legacy MinerU deployments before running this release.
- Add `ppx pdf parse --timeout` with a 1800-second default and update the bundled PDF skill for cold startup and long documents.
- Include systemd deployment templates for on-demand workers and shutdown after one idle hour, protecting active transfers and parse jobs.
- Treat local `output_dir` as the PPX artifact directory; cloud parsing continues to use its separate protocol.

See [deployment and migration](paper_plane_x_backend/docs/mineru_v4.md).
