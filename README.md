# AI 公考错题诊断系统

这是一个可本地运行的前后端分离 Web 应用，把错题录入、OCR 修正、AI 诊断、每日复习和学习统计连成完整闭环。默认不需要外部 API 密钥：系统会进入明确标注的演示模式，并使用确定性 OCR/分析结果。

## 最快启动

需要 Docker Desktop，或已安装 Docker Engine 与 Compose v2 插件。先检查环境：

```bash
docker --version
docker compose version
cp .env.example .env
bash scripts/dev-preflight.sh
```

如果 `docker compose version` 不存在：

- macOS / Windows：安装并启动 [Docker Desktop](https://docs.docker.com/desktop/)，其中已包含 Compose。
- Linux：按照 [Docker Compose 插件安装说明](https://docs.docker.com/compose/install/linux/) 安装；Debian/Ubuntu 通常可运行 `sudo apt-get update && sudo apt-get install docker-compose-plugin`。

启动数据库、API 和 Web：

```bash
docker compose up --build -d
docker compose exec api python -m app.seed
bash scripts/smoke.sh
```

打开 <http://localhost:3000>。演示账号：

- 邮箱：`demo@example.com`
- 密码：`demo-pass-123`

种子命令可以重复运行；它会补齐固定演示样例，不会重复增加演示用户、题目、分析或复习记录。

## 服务与数据

| 服务 | 本地地址 | 说明 |
|---|---|---|
| Web | <http://localhost:3000> | Next.js 用户界面 |
| API | <http://localhost:8000> | FastAPI；健康检查为 `/health` |
| PostgreSQL | `localhost:5432` | 仅供本地开发连接 |

这些端口默认只绑定宿主机回环地址 `127.0.0.1`，不会直接暴露给局域网。PostgreSQL 数据存放在 Compose 命名卷 `postgres_data`，上传图片存放在命名卷 `uploads`。`docker compose down` 只停止并移除本项目容器和网络，不删除数据卷。只有确定要清空本项目全部本地数据时，才使用 `docker compose down -v`。

## 常用命令

```bash
make dev       # 前台构建并启动全部服务
make seed      # 写入或修复幂等演示数据
make smoke     # 验证健康检查、登录页、演示登录与 Dashboard API
make prod-smoke  # 验证已部署 Railway 正式环境的完整 API 闭环
make migrate   # 手动执行 Alembic 迁移
make test      # 后端测试 + 前端测试、lint、生产构建
make down      # 停止本项目服务并保留数据卷
```

API 容器每次启动都会在 Uvicorn 之前执行 `alembic upgrade head`，所以日常启动不需要额外迁移步骤。需要单独确认迁移时可以运行：

```bash
docker compose exec api alembic current
docker compose exec api alembic upgrade head
```

## AI Provider 模式

`.env` 中的 `PROVIDER_MODE` 支持三种值：

- `auto`（默认）：配置 `OPENAI_API_KEY` 时使用真实 Provider，否则使用演示 Provider。
- `demo`：始终使用确定性演示 OCR 与分析，不产生外部调用。
- `live`：强制使用真实 Provider；缺少 `OPENAI_API_KEY` 时 API 会拒绝启动并给出明确错误。

启用真实 OpenAI Provider：

```dotenv
PROVIDER_MODE=live
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-5.5
```

保存后用 `docker compose up --build -d` 重建/重启服务。不要把 `.env` 或真实密钥提交到版本库；仓库只提交不含密钥的 `.env.example`。

## 试卷切题 OCR

OCR 与 AI Provider 独立。默认 `OCR_PROVIDER=mock`，会返回明确标注为演示数据的多题结果，不调用外部服务。正式 OCR 使用腾讯云 `QuestionSplitOCR`，支持 PNG、JPG/JPEG、BMP、PDF 指定页、多题题干与选项、Figure、Table、坐标和受控裁剪图。识别只产生可编辑草稿，不会自动保存答案、解析或触发 AI。

后端 `.env` 仅需写入轮换后的子账号凭证：

```dotenv
OCR_PROVIDER=tencent_question_split
TENCENTCLOUD_SECRET_ID=
TENCENTCLOUD_SECRET_KEY=
TENCENTCLOUD_REGION=
OCR_PROCESSING_LEASE_SECONDS=180
MAX_UPLOAD_BYTES=10485760
UPLOAD_MAX_CONCURRENCY=2
UPLOAD_QUEUE_TIMEOUT_SECONDS=5
UPLOAD_RATE_LIMIT_PER_MINUTE=10
UPLOAD_RATE_LIMIT_PER_HOUR=100
```

`OCR_PROCESSING_LEASE_SECONDS` 默认 180 秒，且必须至少为“排队超时 + 单次请求超时 ×（重试次数 + 1）+ 30 秒”，避免没有 heartbeat 时误回收仍在正常裁剪或提交的 worker。API 进程意外退出后，超过租约仍为 `processing` 的任务可由新请求原子回收；未过期任务继续返回 409，避免重复计费。完整的开通、最小权限、配置边界、测试、计费和排障说明见 [QuestionSplitOCR 接入与运维文档](docs/tencent-question-split-ocr.md)。真实密钥绝不能写入 Web 环境变量、源码或 Git。

上传大小按 Base64 编码后 1–10 MiB 配置。API 的 ASGI 入口会在 multipart 解析和鉴权前同时检查 `Content-Length` 与实际流式字节数；标准配置最多接收 7.5 MiB 原文件加 64 KiB multipart 封装，并用共享入口 Semaphore 把未登录请求也限制在 `UPLOAD_MAX_CONCURRENCY` 内。文件读取有界，图片/PDF 检查、SHA-256 和写盘在线程池中执行；请求取消时会等实际 worker 结束并清理未提交文件后才释放处理 Semaphore。排队超过 `UPLOAD_QUEUE_TIMEOUT_SECONDS` 或同一用户超过 10 次/分钟、100 次/小时会返回中文 429。当前 Railway 拓扑保持一个 API 副本，因此进程级并发与双窗口限流就是部署全局边界。

## 在宿主机运行测试

需要 Python 3.12、[uv](https://docs.astral.sh/uv/) 和 Node.js 24：

```bash
cd apps/api
uv sync
uv run pytest -q

cd ../web
npm ci
npm test -- --run
npm run lint
npx tsc --noEmit
npm run build
```

也可以从仓库根目录直接运行 `make test`。

## 本地主机名与 Cookie

前后端默认统一使用 `localhost`。请始终通过 `http://localhost:3000` 打开 Web，不要改用 `127.0.0.1:3000`；Cookie 按主机名隔离，混用会表现为登录后仍被判定为未登录。API CORS 默认也只允许 `http://localhost:3000`。

生产环境应至少完成以下配置：使用高强度随机 `JWT_SECRET`、启用 HTTPS、设置 `COOKIE_SECURE=true`、限制数据库端口暴露，并将允许来源调整为真实 Web 域名。

## Railway 正式环境

Railway 的创建、变量注入、CLI 直传、检查与回滚步骤见 [Railway 部署运行手册](docs/deployment/railway.md)。正式环境的浏览器请求始终使用 Web 同源 `/api/v1`，由 Next.js 在服务端通过 Railway 私网代理到 API；不要把 API 私网地址配置到浏览器端。建议先以演示 AI + Mock OCR 完成部署验收，再注入轮换后的腾讯子账号密钥并切换真实 OCR。

完成部署后，在仓库根目录提供 `WEB_URL` 与 `API_URL` 即可运行 `make prod-smoke`。正式环境不得运行 `python -m app.seed`，也不得复制本地数据库或上传目录。

## 排错

- `Development preflight` 报端口占用：停止占用 `3000`、`8000` 或 `5432` 的进程/容器后重试。
- API 因 `PROVIDER_MODE=live requires OPENAI_API_KEY` 停止：补充密钥，或改为 `auto` / `demo`。
- 修改了 `NEXT_PUBLIC_API_URL`：这是浏览器端构建变量，需要重新构建 Web 镜像。
- 查看日志：`docker compose logs -f api web db`。
- 查看状态：`docker compose ps`。
