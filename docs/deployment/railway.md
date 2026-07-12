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

第 1～6 节以及后续的 API/Postgres 重启持久性检查必须在**同一个新开的 Bash 会话**中顺序执行；不要关闭终端、另开 shell 或只复制中间一段。退出这个 shell 会自动删除本地临时凭据，因此意外中断后必须从资源门禁重新检查，不能盲目重放创建命令。先进入仓库根目录并启动 Bash，再定义固定 CLI、临时目录和失败清理。不要使用包含空格的标量变量代替命令。

```bash
set +x
set -euo pipefail
umask 077

run_tmp=$(mktemp -d "${TMPDIR:-/tmp}/kaogong-railway-run.XXXXXX")
project_list=""
proxy_secret_file=""
secret_file=""
state_file=""

cleanup_local_artifacts() {
  if [[ -n ${run_tmp:-} && -d ${run_tmp:-} ]]; then
    rm -rf -- "$run_tmp"
  fi
  unset SMOKE_PASSWORD
}

cleanup_on_exit() {
  local exit_code=$?
  trap - EXIT
  cleanup_local_artifacts
  exit "$exit_code"
}

trap cleanup_on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

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
project_list="$run_tmp/projects.json"
railway_cli list --json >"$project_list"
python3 - "$project_list" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
items = payload if isinstance(payload, list) else payload.get("projects", [])
if any(item.get("name") == "kaogong-ai-exam" for item in items):
    raise SystemExit("STOP: project kaogong-ai-exam already exists")
PY
rm -f "$project_list"
project_list=""
```

从用户确认的 workspace 页面复制精确 **ID**，不要使用可能重名的显示名称，也不要猜测：

```bash
: "${RAILWAY_WORKSPACE_ID:?Set the exact user-confirmed Railway workspace ID}"
railway_cli init --name kaogong-ai-exam --workspace "$RAILWAY_WORKSPACE_ID" --json
railway_cli status --environment production --json
```

`init`/`link` 会创建本地 `.railway/` 链接元数据；仓库已忽略该目录。

## 2. 创建并逐步检查资源

先定义三个 fail-closed 门禁。无法识别 CLI JSON、资源数量/名称/端口/挂载路径不精确匹配时都会退出；不要修改脚本来“兼容”意外资源。

```bash
assert_services() {
  local snapshot="$run_tmp/services.json"
  railway_cli service list --environment production --json >"$snapshot"
  python3 - "$snapshot" "$@" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
expected = list(sys.argv[2:])
if isinstance(payload, list):
    items = payload
elif isinstance(payload, dict):
    items = payload.get("services", payload.get("serviceInstances"))
    if items is None and isinstance(payload.get("environment"), dict):
        items = payload["environment"].get("serviceInstances")
    if isinstance(items, dict):
        items = items.get("edges")
else:
    items = None
if not isinstance(items, list):
    raise SystemExit("STOP: unrecognized service-list JSON")
nodes = []
for item in items:
    if not isinstance(item, dict):
        raise SystemExit("STOP: malformed service-list item")
    node = item.get("node", item)
    if not isinstance(node, dict):
        raise SystemExit("STOP: malformed service-list node")
    nodes.append(node)
names = [
    node.get("name") if node.get("name") is not None else node.get("serviceName")
    for node in nodes
]
if any(not isinstance(name, str) or not name for name in names):
    raise SystemExit("STOP: service without an exact name")
if len(names) != len(set(names)) or sorted(names) != sorted(expected):
    raise SystemExit(
        f"STOP: expected services {sorted(expected)!r}, found {sorted(names)!r}"
    )
PY
}

service_id() {
  local expected_name=$1
  python3 - "$run_tmp/services.json" "$expected_name" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if isinstance(payload, list):
    items = payload
elif isinstance(payload, dict):
    items = payload.get("services", payload.get("serviceInstances"))
    if items is None and isinstance(payload.get("environment"), dict):
        items = payload["environment"].get("serviceInstances")
    if isinstance(items, dict):
        items = items.get("edges")
else:
    items = None
if not isinstance(items, list):
    raise SystemExit("STOP: unrecognized service-list JSON")
matches = []
for item in items:
    node = item.get("node", item) if isinstance(item, dict) else None
    if not isinstance(node, dict):
        raise SystemExit("STOP: malformed service-list node")
    name = node.get("name", node.get("serviceName"))
    if name == sys.argv[2]:
        matches.append(node.get("id", node.get("serviceId")))
if len(matches) != 1 or not isinstance(matches[0], str) or not matches[0]:
    raise SystemExit("STOP: expected one exact service ID")
print(matches[0])
PY
}

assert_domains() {
  local service=$1
  local expected_count=$2
  local expected_port=$3
  local snapshot="$run_tmp/domains-$service.json"
  railway_cli domain list \
    --service "$service" --environment production --json >"$snapshot"
  python3 - "$snapshot" "$expected_count" "$expected_port" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if not isinstance(payload, dict) or not isinstance(payload.get("domains"), list):
    raise SystemExit("STOP: unrecognized domain-list JSON")
domains = payload["domains"]
if any(not isinstance(domain, dict) for domain in domains):
    raise SystemExit("STOP: malformed domain-list item")
if any(domain.get("type") != "service" for domain in domains):
    raise SystemExit("STOP: unexpected custom or unknown domain type")
ids = [domain.get("id") for domain in domains]
hosts = [domain.get("domain") for domain in domains]
if (
    any(not isinstance(value, str) or not value for value in ids + hosts)
    or len(ids) != len(set(ids))
    or len(hosts) != len(set(hosts))
):
    raise SystemExit("STOP: malformed or duplicate Railway domain")
expected_count = int(sys.argv[2])
expected_port = int(sys.argv[3])
if len(domains) != expected_count:
    raise SystemExit(
        f"STOP: expected {expected_count} Railway domain(s), "
        f"found {len(domains)}"
    )
if expected_count == 1:
    domain = domains[0]
    if domain.get("targetPort") != expected_port:
        raise SystemExit("STOP: Railway domain or target port mismatch")
PY
}

domain_origin() {
  python3 - "$run_tmp/domains-$1.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
domains = payload["domains"]
if len(domains) != 1:
    raise SystemExit("STOP: expected exactly one Railway domain")
print(f"https://{domains[0]['domain']}")
PY
}

assert_api_volume_count() {
  local expected_count=$1
  local snapshot="$run_tmp/api-volumes.json"
  : "${API_SERVICE_ID:?Resolve the exact API service ID first}"
  railway_cli volume --service "$API_SERVICE_ID" \
    --environment production list --json >"$snapshot"
  python3 - "$snapshot" "$expected_count" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if not isinstance(payload, dict) or not isinstance(payload.get("volumes"), list):
    raise SystemExit("STOP: unrecognized volume-list JSON")
items = payload["volumes"]
for item in items:
    if not isinstance(item, dict):
        raise SystemExit("STOP: malformed volume-list item")
ids = [item.get("id") for item in items]
if any(not isinstance(value, str) or not value for value in ids):
    raise SystemExit("STOP: malformed volume identity")
if len(ids) != len(set(ids)):
    raise SystemExit("STOP: duplicate volume identity")
api_volumes = [item for item in items if item.get("serviceName") == "api"]
expected_count = int(sys.argv[2])
if len(api_volumes) != expected_count:
    raise SystemExit(
        f"STOP: expected {expected_count} API volume(s), found {len(api_volumes)}"
    )
if expected_count == 1:
    volume = api_volumes[0]
    if volume.get("mountPath") != "/data/uploads":
        raise SystemExit("STOP: API volume mount path mismatch")
    if volume.get("deletedAt") is not None or volume.get("isPendingDeletion") is True:
        raise SystemExit("STOP: API volume is deleted or pending deletion")
PY
}
```

每次创建前后都断言精确拓扑。这样即使上一次命令已在远端成功但本地连接中断，重放也会在下一次 mutation 前停止。

```bash
assert_services
railway_cli add --database postgres --json >"$run_tmp/add-postgres.json"
assert_services Postgres

assert_services Postgres
railway_cli add --service api --json >"$run_tmp/add-api.json"
assert_services Postgres api

assert_services Postgres api
railway_cli add --service web --json >"$run_tmp/add-web.json"
assert_services Postgres api web
```

服务名称精确匹配后，为 API 和 Web 分别创建一个 Railway 域名。域名创建也有独立的空列表前置门禁。

```bash
assert_services Postgres api web
assert_domains api 0 8000
railway_cli domain \
  --service api --environment production --port 8000 --json \
  >"$run_tmp/create-api-domain.json"
assert_domains api 1 8000

assert_services Postgres api web
assert_domains web 0 3000
railway_cli domain \
  --service web --environment production --port 3000 --json \
  >"$run_tmp/create-web-domain.json"
assert_domains web 1 3000

API_URL=$(domain_origin api)
WEB_URL=$(domain_origin web)
printf 'API origin: %s\nWeb origin: %s\n' "$API_URL" "$WEB_URL"
```

API 卷必须唯一且挂载到固定路径。CLI 5.26.0 的 `volume list --json` 返回环境中的全部卷，因此门禁按 `serviceName == "api"` 精确筛选，不对 Railway Postgres 模板自己的数据卷作假设。该版本的 `volume --service` 直接消费服务 ID、不会可靠解析服务名称，所以必须先从刚通过门禁的服务快照中提取唯一 API ID；不得把 `api` 名称直接传给卷命令。

```bash
assert_services Postgres api web
API_SERVICE_ID=$(service_id api)
assert_api_volume_count 0
railway_cli volume --service "$API_SERVICE_ID" --environment production \
  add --mount-path /data/uploads --json >"$run_tmp/add-api-volume.json"
assert_api_volume_count 1

railway_cli service link api
railway_cli status --environment production --json
```

## 3. 安全设置变量

变量设置前再次断言完整拓扑，避免引用到拼写相近或意外创建的服务。全部设置使用 `--skip-deploys`，避免半配置状态触发部署。JWT 与 Web→API 私网共享密钥只通过 stdin 传入并丢弃标准输出；共享密钥只生成一次并分别注入两个服务，不能放进命令参数或 shell 输出：

```bash
set +x
set -o pipefail
assert_services Postgres api web
assert_domains api 1 8000
assert_domains web 1 3000
assert_api_volume_count 1
openssl rand -hex 32 |
  railway_cli variable set JWT_SECRET --stdin \
    --service api --environment production --skip-deploys >/dev/null

proxy_secret_file="$run_tmp/internal-proxy-secret"
openssl rand -hex 32 | tr -d '\n' >"$proxy_secret_file"
chmod 600 "$proxy_secret_file"
railway_cli variable set INTERNAL_PROXY_SECRET --stdin \
  --service api --environment production --skip-deploys \
  <"$proxy_secret_file" >/dev/null
railway_cli variable set INTERNAL_PROXY_SECRET --stdin \
  --service web --environment production --skip-deploys \
  <"$proxy_secret_file" >/dev/null
rm -f -- "$proxy_secret_file"
proxy_secret_file=""
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

Web 浏览器端只烘焙同源相对路径；私网地址和共享密钥只存在于服务端运行环境。`RAILWAY_PUBLIC_DOMAIN` 由 Railway 自动提供，代理用它生成可信 forwarded origin。Web 会删除浏览器伪造的共享密钥头并覆写为运行时密钥，API 只在密钥恒定时间比对、Railway 边缘标记和合法 `X-Real-IP` 同时通过时才按真实客户端限流；密钥头永不回传浏览器。

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

先用可见的 `true` 命令完成 Railway 首次 SSH 密钥注册，避免注册提示被后续命令替换捕获。迁移必须精确位于当前唯一 head。随后从 `/proc` 找到实际的 `python -m app.entrypoint` 服务进程并检查其 UID/GID，而不是误把 Railway SSH 子进程当成应用进程。卷写入探针若由 root SSH 启动，会先清空附加组并显式降权到 UID/GID 10001；探针关闭、落盘并自删除后才算通过。

```bash
railway_cli ssh --service api --environment production true

migration_current="$(
  railway_cli ssh --service api --environment production alembic current
)"
test "$migration_current" = "0005_review_records (head)"
printf 'alembic_revision=0005_review_records\n'

railway_cli ssh --service api --environment production python - <<'PY'
import json
import os
import pathlib
import tempfile

target = 10001
matches = []
for proc in pathlib.Path("/proc").iterdir():
    if not proc.name.isdecimal():
        continue
    try:
        argv = [
            part.decode("utf-8", "surrogateescape")
            for part in proc.joinpath("cmdline").read_bytes().split(b"\0")
            if part
        ]
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if argv[1:3] == ["-m", "app.entrypoint"]:
        matches.append(proc)
if len(matches) != 1:
    raise SystemExit(
        f"STOP: expected one app.entrypoint process, found {len(matches)}"
    )

status = {}
for line in matches[0].joinpath("status").read_text(encoding="utf-8").splitlines():
    key, separator, value = line.partition(":")
    if separator:
        status[key] = value.strip()
uids = tuple(int(value) for value in status["Uid"].split())
gids = tuple(int(value) for value in status["Gid"].split())
groups = tuple(int(value) for value in status.get("Groups", "").split())
if uids != (target, target, target, target):
    raise SystemExit("STOP: serving process UID mismatch")
if gids != (target, target, target, target):
    raise SystemExit("STOP: serving process GID mismatch")
if groups:
    raise SystemExit("STOP: serving process has supplementary groups")

if os.geteuid() == 0:
    os.setgroups([])
    os.setgid(target)
    os.setuid(target)
elif (
    os.getuid() != target
    or os.geteuid() != target
    or os.getgid() != target
    or os.getegid() != target
    or os.getgroups()
):
    raise SystemExit("STOP: SSH probe cannot assume application identity")

root = pathlib.Path("/data/uploads")
if not root.is_dir() or not os.access(root, os.W_OK | os.X_OK):
    raise SystemExit("STOP: upload mount is not writable by UID/GID 10001")
descriptor, probe_path = tempfile.mkstemp(prefix=".railway-write-probe-", dir=root)
try:
    with os.fdopen(descriptor, "wb") as probe:
        probe.write(b"ok")
        probe.flush()
        os.fsync(probe.fileno())
finally:
    try:
        os.unlink(probe_path)
    except FileNotFoundError:
        pass
if os.path.lexists(probe_path):
    raise SystemExit("STOP: upload probe did not self-delete")
print(json.dumps({
    "app_uid": uids[1],
    "app_gid": gids[1],
    "probe_uid": os.geteuid(),
    "probe_gid": os.getegid(),
    "mount": "/data/uploads",
    "writable": True,
}, sort_keys=True))
PY

railway_cli ssh --service api --environment production python - <<'PY'
import http.client
import os


def check(host):
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=5)
    try:
        connection.request("GET", "/health", headers={"Host": host})
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


result = {
    "unknown": check("evil.invalid"),
    "healthcheck": check("healthcheck.railway.app"),
    "private": check("api.railway.internal"),
    "public": check(os.environ["RAILWAY_PUBLIC_DOMAIN"]),
}
expected = {"unknown": 400, "healthcheck": 200, "private": 200, "public": 200}
if result != expected:
    raise SystemExit(f"STOP: TrustedHost probe mismatch: {result!r}")
print(result)
PY
```

UID/卷探针输出只能包含 UID/GID、固定挂载路径和布尔结果；Host 探针在容器回环接口验证未知 Host 为 400，healthcheck、私网和 API 公网 Host 为 200，避免 Railway 公网边缘路由掩盖应用中间件结果。任一检查失败都停止部署验收。

## 6. 自动 smoke 与重启前状态

正式 smoke 通过 Web 同源代理执行，密码和状态文件都放在本会话的受限临时目录内。shell 的 EXIT/信号 trap 会在失败或意外退出时删除它们：

```bash
secret_file="$run_tmp/smoke-password"
: >"$secret_file"
chmod 600 "$secret_file"
openssl rand -hex 24 | tr -d '\n' >"$secret_file"
state_file="$run_tmp/smoke-state"
: >"$state_file"
chmod 600 "$state_file"

SMOKE_PASSWORD=$(<"$secret_file") \
WEB_URL="$WEB_URL" API_URL="$API_URL" SMOKE_STATE_FILE="$state_file" \
  bash scripts/production-smoke.sh
```

不要退出当前 shell。保留这两个临时文件仅用于后续 API/Postgres 重启持久性与 Chrome 验收；不要打印密码或 Cookie。`state_file` 只允许包含 smoke 邮箱、上传 UUID 和题目 UUID。

### 6.1 逐服务重启与持久性复验

先定义两个 fail-closed 辅助函数。`wait_api_ready` 必须看到精确的演示模式 readiness；`verify_persistence` 每次都重新登录，并验证账号、题目、分析、复习记录与原始上传文件的逐字节内容。密码只从 mode-600 文件读取，不出现在进程参数中：

```bash
wait_api_ready() {
  local ready_file="$run_tmp/restart-ready.json"
  local ready=0
  local attempt
  for attempt in $(seq 1 60); do
    if curl --fail --silent --show-error --connect-timeout 5 --max-time 10 \
      "$API_URL/ready" >"$ready_file" 2>/dev/null &&
      python3 - "$ready_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload != {"status": "ready", "provider_mode": "demo"}:
    raise SystemExit(1)
PY
    then
      ready=1
      break
    fi
    sleep 2
  done
  if [[ "$ready" != 1 ]]; then
    echo 'STOP: API did not return exact production readiness after restart' >&2
    return 1
  fi
}

verify_persistence() {
  local values_file="$run_tmp/restart-state-values"
  local cookie_jar="$run_tmp/restart-cookies"
  local login_body="$run_tmp/restart-login.json"
  local question_body="$run_tmp/restart-question.json"
  local reviews_body="$run_tmp/restart-reviews.json"
  local image_body="$run_tmp/restart-image"
  local image_headers="$run_tmp/restart-image.headers"
  local smoke_image_path=${SMOKE_IMAGE_PATH:-docs/design/ai-exam-diagnosis-dashboard-selected.png}
  local login_status question_status reviews_status image_status
  local email question_id upload_id

  python3 - "$state_file" "$values_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if set(payload) != {"email", "question_id", "upload_id"}:
    raise SystemExit("STOP: unexpected smoke-state shape")
values = [payload["email"], payload["question_id"], payload["upload_id"]]
if any(not isinstance(value, str) or not value or "\n" in value for value in values):
    raise SystemExit("STOP: malformed smoke-state value")
with open(sys.argv[2], "w", encoding="utf-8") as target:
    target.write("\n".join(values) + "\n")
PY
  {
    IFS= read -r email
    IFS= read -r question_id
    IFS= read -r upload_id
  } <"$values_file"

  python3 - "$login_body" "$email" "$secret_file" <<'PY'
import json
import sys

output, email, password_path = sys.argv[1:]
with open(password_path, encoding="utf-8") as source:
    password = source.read()
with open(output, "w", encoding="utf-8") as target:
    json.dump({"email": email, "password": password}, target)
PY

  login_status=$(curl --silent --show-error --connect-timeout 10 --max-time 60 \
    --cookie-jar "$cookie_jar" \
    --header 'Content-Type: application/json' --data-binary @"$login_body" \
    --output /dev/null --write-out '%{http_code}' \
    "$WEB_URL/api/v1/auth/login")
  test "$login_status" = 200

  question_status=$(curl --silent --show-error --connect-timeout 10 --max-time 60 \
    --cookie "$cookie_jar" \
    --output "$question_body" --write-out '%{http_code}' \
    "$WEB_URL/api/v1/questions/$question_id")
  test "$question_status" = 200
  python3 - "$question_body" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
assert payload["analysis_status"] == "已完成"
assert payload["mastery_status"] == "复习中"
assert payload["current_analysis"]["is_demo"] is True
PY

  reviews_status=$(curl --silent --show-error --connect-timeout 10 --max-time 60 \
    --cookie "$cookie_jar" \
    --output "$reviews_body" --write-out '%{http_code}' \
    "$WEB_URL/api/v1/reviews/questions/$question_id")
  test "$reviews_status" = 200
  python3 - "$reviews_body" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
assert payload["total"] == 1
assert len(payload["items"]) == 1
assert payload["items"][0]["result_status"] == "复习中"
PY

  test -f "$smoke_image_path"
  image_status=$(curl --silent --show-error --connect-timeout 10 --max-time 60 \
    --cookie "$cookie_jar" \
    --dump-header "$image_headers" --output "$image_body" \
    --write-out '%{http_code}' "$WEB_URL/api/v1/uploads/$upload_id")
  test "$image_status" = 200
  grep -Eqi '^content-type:[[:space:]]*image/(png|jpeg|webp)' "$image_headers"
  cmp -s "$smoke_image_path" "$image_body"

  rm -f -- "$values_file" "$cookie_jar" "$login_body" "$question_body" \
    "$reviews_body" "$image_body" "$image_headers"
}
```

严格按 API→验证→Postgres→验证的顺序执行。不得连续发出两个重启命令，也不得在中间 readiness 或持久性检查失败后继续：

```bash
railway_cli service restart \
  --service api --environment production --yes --json \
  >"$run_tmp/restart-api.json"
wait_api_ready
verify_persistence

railway_cli service restart \
  --service Postgres --environment production --yes --json \
  >"$run_tmp/restart-postgres.json"
wait_api_ready
verify_persistence
```

两轮复验都通过后，继续使用同一账号做 Chrome 验收；仍不要提前删除本地临时凭据。

只有重启持久性和 Chrome 验收都结束后，才在同一 shell 执行以下最终清理；这会删除密码、smoke 状态和所有 CLI JSON 快照，并解除 trap：

```bash
cleanup_local_artifacts
trap - EXIT HUP INT TERM
run_tmp=""
proxy_secret_file=""
secret_file=""
state_file=""
printf 'local Railway QA credentials removed\n'
```

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

相关官方文档：[CLI uploads](https://docs.railway.com/cli/up)、[variables](https://docs.railway.com/cli/variable)、[volumes](https://docs.railway.com/cli/volume)、[deployments](https://docs.railway.com/cli/deployment)、[deployment actions](https://docs.railway.com/deployments/deployment-actions)、[public-network request headers](https://docs.railway.com/networking/public-networking/specs-and-limits)。
