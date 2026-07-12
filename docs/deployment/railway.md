# Railway 正式环境部署运行手册

本手册用于把当前已审核的源码直接上传到 Railway 的 `production` 环境。目标拓扑固定为一个 `Postgres`、一个 `api`、一个 `web` 和一个挂载到 API `/data/uploads` 的持久卷。生产环境使用演示 AI，不配置 `OPENAI_API_KEY`。

## 安全边界与停止条件

开始前确认：

- 只在仓库根目录执行命令，并使用干净、已提交且已通过完整本地验证的 SHA。
- Railway CLI 固定为 5.26.0；不要使用未固定版本的全局 CLI。
- 不运行 `python -m app.seed`，不复制本地数据库或上传目录。
- 不运行 `railway variable list --json`、`--kv` 或任何会显示变量原值的命令。
- 不启用 shell tracing，不在命令行、日志、截图或 QA 文档中记录 JWT、密码、Cookie、数据库 URL 或 Railway token。
- Railway 要求 OAuth/设备确认时停下，交给用户在可见页面完成。
- Railway 要求付费或升级、发现同名项目/服务/域名/卷、要求选择未知 workspace、迁移失败或 `/ready` 非 200 时立即停止，不猜测、不重复创建。
- 失败后不删除项目、数据库、服务或卷；任何清理都需要用户单独授权。

CLI 5.26.0 不支持真正的 `rollback` 命令；`redeploy` 只会重发最新部署，不能当作回滚。真正回滚见本文末尾的控制台流程。

## 1. 固定 CLI、源码与 workspace

在 Bash 或 Zsh 中定义可执行函数。不要使用包含空格的标量变量代替命令；Zsh 不会按预期拆分它。

```bash
set -euo pipefail
umask 077

railway_cli() {
  npx -y @railway/cli@5.26.0 "$@"
}

railway_cli --version
git diff --check
test -z "$(git status --porcelain)"
DEPLOY_SHA=$(git rev-parse HEAD)
printf 'deploying committed SHA %s\n' "$DEPLOY_SHA"
```

登录会打开浏览器或显示设备确认步骤。只确认自己的 Railway 账户：

```bash
railway_cli login
railway_cli whoami
```

列出现有项目仅用于检查名称，不要把输出复制进仓库或 QA 文档。若已经存在 `kaogong-ai-exam`，立即停止并让用户决定是否复用；不要再次执行 `init`。

```bash
project_list=$(mktemp)
railway_cli list --json >"$project_list"
python3 - "$project_list" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
items = payload if isinstance(payload, list) else payload.get("projects", [])
if any(item.get("name") == "kaogong-ai-exam" for item in items):
    raise SystemExit("STOP: project kaogong-ai-exam already exists")
PY
rm -f "$project_list"
```

从用户确认的 workspace 页面复制精确 ID 或名称，不要猜测：

```bash
: "${RAILWAY_WORKSPACE:?Set the exact user-confirmed Railway workspace ID or name}"
railway_cli init --name kaogong-ai-exam --workspace "$RAILWAY_WORKSPACE" --json
railway_cli status --environment production --json
```

`init`/`link` 会创建本地 `.railway/` 链接元数据；仓库已忽略该目录。

## 2. 创建并逐步检查资源

新项目应没有服务。依次创建后，用服务列表确认名称；任何命令若报告资源已存在，停止而不是重试。

```bash
railway_cli service list --environment production --json

railway_cli add --database postgres --json
railway_cli service list --environment production --json

railway_cli add --service api --json
railway_cli service list --environment production --json

railway_cli add --service web --json
railway_cli service list --environment production --json
```

确认服务恰好为 `Postgres`、`api`、`web` 后，再生成公网域名。先执行 `domain list`；新服务若已经有域名，停止。

```bash
railway_cli domain list --service api --environment production --json
railway_cli domain list --service web --environment production --json

railway_cli domain --service api --environment production --port 8000 --json
railway_cli domain --service web --environment production --port 3000 --json

railway_cli domain list --service api --environment production --json
railway_cli domain list --service web --environment production --json
```

记下两个公开域名并在当前 shell 中设置为不带尾斜杠的 HTTPS origin；它们不是秘密，但不要把其他账户/项目输出写入仓库。

```bash
API_URL='https://REPLACE_WITH_API_PUBLIC_DOMAIN'
WEB_URL='https://REPLACE_WITH_WEB_PUBLIC_DOMAIN'
```

API 卷必须唯一且挂载到固定路径。先检查空列表，再创建并复查。父命令上的服务/环境选择器是 CLI 5.26.0 的明确语法。

```bash
railway_cli volume --service api --environment production list --json
railway_cli volume --service api --environment production \
  add --mount-path /data/uploads --json
railway_cli volume --service api --environment production list --json

railway_cli service link api
railway_cli status --environment production --json
```

## 3. 安全设置变量

变量设置全部使用 `--skip-deploys`，避免半配置状态触发部署。JWT 只通过 stdin 传入并丢弃标准输出：

```bash
set +x
set -o pipefail
openssl rand -hex 32 |
  railway_cli variable set JWT_SECRET --stdin \
    --service api --environment production --skip-deploys >/dev/null
```

设置 API 的非秘密值与 Railway 引用变量：

```bash
railway_cli variable set \
  --service api --environment production --skip-deploys \
  APP_ENV=production \
  'DATABASE_URL=${{Postgres.DATABASE_URL}}' \
  COOKIE_SECURE=true \
  'ALLOWED_ORIGINS=["https://${{web.RAILWAY_PUBLIC_DOMAIN}}"]' \
  'ALLOWED_HOSTS=["${{api.RAILWAY_PUBLIC_DOMAIN}}","api.railway.internal","healthcheck.railway.app"]' \
  PROVIDER_MODE=demo \
  UPLOAD_DIR=/data/uploads \
  MAX_UPLOAD_BYTES=10485760 \
  PORT=8000 \
  RAILWAY_RUN_UID=0 >/dev/null
```

Web 浏览器端只烘焙同源相对路径；私网地址只存在于服务端运行环境。`RAILWAY_PUBLIC_DOMAIN` 由 Railway 自动提供，代理用它生成可信 forwarded origin。

```bash
railway_cli variable set \
  --service web --environment production --skip-deploys \
  NEXT_PUBLIC_API_URL=/api/v1 \
  'API_INTERNAL_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000' \
  PORT=3000 >/dev/null
```

不要运行变量列表命令来“确认”键名，因为 CLI 会同时返回原值。新项目只应存在本节显式设置的键；`OPENAI_API_KEY` 不得设置。API 的 fail-closed 启动校验和后续 `/ready` 是运行时证据。

## 4. 从干净 SHA 依次部署

变量设置后再次确认工作树和 SHA 未变化：

```bash
git diff --check
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = "$DEPLOY_SHA"
```

先上传 API。不要使用 detached 模式；观察构建、Pre-Deploy 迁移和健康检查直到命令结束：

```bash
railway_cli up apps/api --path-as-root \
  --service api --environment production \
  --message "deploy api ${DEPLOY_SHA}"

railway_cli status --environment production --json
railway_cli deployment list --service api --environment production --limit 1 --json
railway_cli logs --service api --environment production --latest --build --lines 100
railway_cli logs --service api --environment production --latest --deployment --lines 100
railway_cli logs --service api --environment production --latest --lines 100
```

日志只在终端做有界检查，不保存或粘贴原文。若出现 secret、localhost 生产 URL、traceback、迁移错误、重复 crash 或付费提示，立即停止。等待公开 readiness：

```bash
for attempt in $(seq 1 60); do
  curl --fail --silent --show-error --proto '=https' "$API_URL/ready" >/dev/null && break
  sleep 2
done
curl --fail --silent --show-error --proto '=https' "$API_URL/ready" |
  grep -q '"status":"ready"'
```

只有 API readiness 成功后才上传 Web：

```bash
railway_cli up apps/web --path-as-root \
  --service web --environment production \
  --message "deploy web ${DEPLOY_SHA}"

railway_cli status --environment production --json
railway_cli deployment list --service web --environment production --limit 1 --json
railway_cli logs --service web --environment production --latest --build --lines 100
railway_cli logs --service web --environment production --latest --deployment --lines 100
railway_cli logs --service web --environment production --latest --lines 100

curl --fail --silent --show-error --proto '=https' "$WEB_URL/health" |
  grep -q '"status":"ok"'
```

## 5. 迁移、运行用户和卷检查

迁移必须位于当前唯一 head，卷探针必须自删除，服务进程必须已经降权到 UID/GID 10001：

```bash
railway_cli ssh --service api --environment production alembic current

railway_cli ssh --service api --environment production python -c \
  'import os, pathlib, tempfile; root=pathlib.Path("/data/uploads"); assert os.geteuid()==10001 and os.getegid()==10001; probe=tempfile.NamedTemporaryFile(dir=root, delete=True); probe.write(b"ok"); probe.flush(); print({"uid":os.geteuid(),"gid":os.getegid(),"mount":"/data/uploads","writable":True})'

railway_cli ssh --service api --environment production python -c \
  'import http.client, os; check=lambda host: (lambda c: (c.request("GET","/health",headers={"Host":host}), c.getresponse())[1].status)(http.client.HTTPConnection("127.0.0.1",8000,timeout=5)); result={"unknown":check("evil.invalid"),"healthcheck":check("healthcheck.railway.app"),"private":check("api.railway.internal"),"public":check(os.environ["RAILWAY_PUBLIC_DOMAIN"])}; assert result=={"unknown":400,"healthcheck":200,"private":200,"public":200}; print(result)'
```

`alembic current` 必须包含 `0005_review_records`。探针输出只能包含 UID/GID、固定挂载路径和布尔结果；Host 探针在容器回环接口验证未知 Host 为 400，healthcheck、私网和 API 公网 Host 为 200，避免 Railway 公网边缘路由掩盖应用中间件结果。任一检查失败都停止部署验收。

## 6. 自动 smoke 与重启前状态

正式 smoke 通过 Web 同源代理执行，密码保存在 Git 之外的 0600 临时文件：

```bash
secret_file=$(mktemp)
chmod 600 "$secret_file"
openssl rand -hex 24 >"$secret_file"
state_file=$(mktemp)
chmod 600 "$state_file"

SMOKE_PASSWORD=$(<"$secret_file") \
WEB_URL="$WEB_URL" API_URL="$API_URL" SMOKE_STATE_FILE="$state_file" \
  bash scripts/production-smoke.sh
```

保留这两个临时文件仅用于后续 API/Postgres 重启持久性与 Chrome 验收；不要打印密码或 Cookie。`state_file` 只允许包含 smoke 邮箱、上传 UUID 和题目 UUID。

## 7. 回滚与失败处理

Railway CLI 5.26.0 没有历史版本 rollback 命令。需要回滚应用代码时：

1. 打开 Railway 控制台对应服务的 Deployments。
2. 选择部署前已确认成功的历史部署。
3. 从该部署的操作菜单选择 **Rollback**；该操作恢复镜像与自定义变量。
4. 先回滚 API 并等待 `/ready`，再按需回滚 Web。
5. 重新执行迁移版本、卷写入和 production smoke 检查。

不要用 `railway redeploy` 冒充回滚；它只重发最新版本。不要运行 `railway down`、Alembic downgrade、数据库/卷删除或 seed。失败资源也不在本任务中删除，除非用户随后明确授权。

## 8. 可审计信息

最终 QA 文档只记录公开 Web/API URL、Git SHA、Alembic revision、非秘密变量键名清单、部署状态、UID/卷布尔结果和 smoke 邮箱。不要记录：

- JWT、数据库 URL、Railway token、登录密码、Cookie 或请求体；
- `whoami`、项目列表、变量列表或原始日志全文；
- 任何 `railway.internal` 地址或变量原值。

相关官方文档：[CLI uploads](https://docs.railway.com/cli/up)、[variables](https://docs.railway.com/cli/variable)、[volumes](https://docs.railway.com/cli/volume)、[deployments](https://docs.railway.com/cli/deployment)、[deployment actions](https://docs.railway.com/deployments/deployment-actions)。
