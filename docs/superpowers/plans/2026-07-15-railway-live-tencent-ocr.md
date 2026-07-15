# Railway Live Tencent OCR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Switch the Railway production OCR provider from deterministic mock data to Tencent QuestionSplitOCR, perform exactly one paid OCR request with the approved non-sensitive exam image, restore normal retry settings, and verify the persisted result without a second paid request.

**Architecture:** Keep the existing Web same-origin proxy, FastAPI API, PostgreSQL database, upload volume, and demo AI unchanged. The user enters rotated Tencent credentials directly in Railway Chrome UI; automation changes only non-secret provider settings, deploys the existing API, executes the repository smoke workflow once with server retries disabled, then restores retries and verifies persisted evidence.

**Tech Stack:** Railway CLI 5.26.0, Chrome control, Computer Use fallback, Bash, FastAPI/Python 3.12, SQLAlchemy, PostgreSQL, Next.js, Tencent Cloud Python OCR SDK.

## Global Constraints

- Work only in /Users/zhangguoli/Documents/Code/kaogongsystem/.worktrees/tencent-question-split-ocr on branch codex/tencent-question-split-ocr.
- Keep PROVIDER_MODE=demo for the entire rollout.
- Final OCR_PROVIDER must be tencent_question_split only after a successful real smoke.
- TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY are entered by the user in Railway UI; never read, copy, print, log, write locally, or pass them as command arguments.
- Do not create TENCENTCLOUD_REGION; the application default remains empty.
- Set TENCENTCLOUD_OCR_MAX_RETRIES=0 before the paid request and restore it to 2 afterward.
- Execute scripts/production-smoke.sh exactly once with EXPECTED_OCR_PROVIDER=tencent_question_split.
- Do not retry a failed paid request without a new explicit user approval.
- Use only /Users/zhangguoli/Downloads/17715122101_img_01.png, whose required SHA-256 is 09a5739276b827c01cd2fa4a262688eec529426e864b487077285e8e1f57f788.
- Never use any image from /Users/zhangguoli/.codex/attachments for the paid call.
- On any failed real smoke, restore retries=2, switch OCR_PROVIDER back to mock, redeploy, and verify production health.
- Chrome verification is read-only and must not invoke POST /api/v1/ocr.

---

### Task 1: Establish a clean, reproducible rollout baseline

**Files:**
- Read: docs/superpowers/specs/2026-07-15-railway-live-tencent-ocr-design.md
- Read: scripts/production-smoke.sh
- Read: docs/deployment/railway.md
- Test: /Users/zhangguoli/Downloads/17715122101_img_01.png

**Interfaces:**
- Consumes: The approved design, existing Railway link, current production services, and the user-provided image.
- Produces: A clean DEPLOY_SHA, validated image identity, and verified pre-switch production configuration.

- [ ] **Step 1: Define immutable rollout inputs**

Run:

~~~bash
set -euo pipefail
set +x
umask 077
export WORKTREE=/Users/zhangguoli/Documents/Code/kaogongsystem/.worktrees/tencent-question-split-ocr
export BRANCH=codex/tencent-question-split-ocr
export WEB_URL=https://web-production-3ce0.up.railway.app
export API_URL=https://api-production-f136.up.railway.app
export IMAGE_PATH=/Users/zhangguoli/Downloads/17715122101_img_01.png
export IMAGE_SHA=09a5739276b827c01cd2fa4a262688eec529426e864b487077285e8e1f57f788
export RAILWAY_PROJECT_ID=660e7ed2-ccc8-4ba5-bdf4-115f0ea9f2cb
export RAILWAY_ENVIRONMENT_ID=73f7c38b-8c3a-4915-99b4-f6548f36f955
export RAILWAY_API_SERVICE_ID=07967aca-e492-4ad7-a1b9-734913850f17
cd "$WORKTREE"
export DEPLOY_SHA
DEPLOY_SHA=$(git rev-parse HEAD)
printf 'deploy_sha=%s\n' "$DEPLOY_SHA"
~~~

Expected: one full 40-character Git SHA and no secret values.

- [ ] **Step 2: Prove branch and worktree cleanliness**

Run:

~~~bash
test "$(git branch --show-current)" = "$BRANCH"
test -z "$(git status --porcelain)"
git diff --check
git fetch origin --prune
test "$(git rev-parse origin/$BRANCH)" = "$DEPLOY_SHA"
~~~

Expected: exit 0 with no output. If the local commit has not yet been pushed, push it first and repeat this exact check.

- [ ] **Step 3: Revalidate the approved image without changing it**

Run:

~~~bash
test -f "$IMAGE_PATH"
test ! -L "$IMAGE_PATH"
test "$(shasum -a 256 "$IMAGE_PATH" | awk '{print $1}')" = "$IMAGE_SHA"
cd "$WORKTREE/apps/api"
uv run python - "$IMAGE_PATH" <<'PY'
from pathlib import Path
from PIL import Image
import sys

path = Path(sys.argv[1])
with Image.open(path) as image:
    image.verify()
with Image.open(path) as image:
    assert image.format == "PNG"
    assert image.mode == "RGB"
    assert (image.width, image.height) == (2224, 2852)
size = path.stat().st_size
assert size == 482226
assert 4 * ((size + 2) // 3) == 642968
assert 4 * ((size + 2) // 3) <= 10 * 1024 * 1024
print("image_validation=passed")
PY
cd "$WORKTREE"
~~~

Expected: image_validation=passed.

- [ ] **Step 4: Verify current production remains demo AI and mock OCR**

Run:

~~~bash
npx -y @railway/cli@5.26.0 ssh \
  --service api --environment production \
  python - <<'PY'
import json
import os

actual = {
    "provider_mode": os.environ.get("PROVIDER_MODE"),
    "ocr_provider": os.environ.get("OCR_PROVIDER"),
    "ocr_retries": os.environ.get("TENCENTCLOUD_OCR_MAX_RETRIES"),
}
assert actual == {
    "provider_mode": "demo",
    "ocr_provider": "mock",
    "ocr_retries": "2",
}
print(json.dumps(actual, sort_keys=True))
PY
curl --fail --silent --show-error --retry 3 --retry-all-errors \
  --connect-timeout 10 --max-time 30 "$API_URL/ready"
curl --fail --silent --show-error --retry 3 --retry-all-errors \
  --connect-timeout 10 --max-time 30 "$WEB_URL/health"
~~~

Expected: the SSH JSON reports demo, mock, and 2; API returns status=ready/provider_mode=demo; Web returns status=ok.

### Task 2: Hand off secret entry in Railway without exposing values

**Files:**
- Read: /Users/zhangguoli/.codex/plugins/cache/openai-bundled/chrome/26.707.72221/skills/control-chrome/SKILL.md
- Read: /Users/zhangguoli/.codex/plugins/cache/openai-bundled/computer-use/1.0.1000387/skills/computer-use/SKILL.md

**Interfaces:**
- Consumes: The user-held rotated Tencent SecretId and SecretKey.
- Produces: Two secret keys stored only in Railway API production Variables while OCR traffic still uses mock.

- [ ] **Step 1: Connect to the user-requested Chrome surface**

Run through the Node JavaScript tool:

~~~javascript
if (globalThis.agent?.browsers == null) {
  const { setupBrowserRuntime } = await import(
    "/Users/zhangguoli/.codex/plugins/cache/openai-bundled/chrome/26.707.72221/scripts/browser-client.mjs"
  );
  await setupBrowserRuntime({ globals: globalThis });
}
if (globalThis.chrome == null) {
  globalThis.chrome = await agent.browsers.get("extension");
  nodeRepl.write(await chrome.documentation());
}
~~~

Expected: complete Chrome documentation is returned and a persistent chrome binding exists. If setup or Chrome discovery fails, read chrome-troubleshooting before any fallback.

- [ ] **Step 2: Open the Railway API service Variables page**

Use the Chrome binding to navigate to:

~~~text
https://railway.com/project/660e7ed2-ccc8-4ba5-bdf4-115f0ea9f2cb/service/07967aca-e492-4ad7-a1b9-734913850f17?environmentId=73f7c38b-8c3a-4915-99b4-f6548f36f955
~~~

Select the production environment and Variables tab using current visible labels. Do not inspect existing variable values.

Expected: the API service Variables editor is visible.

- [ ] **Step 3: Hand control to the user for secret entry**

Ask the user to create or update exactly these two Railway variables and save them:

~~~text
TENCENTCLOUD_SECRET_ID
TENCENTCLOUD_SECRET_KEY
~~~

The user types both values. The assistant does not click a reveal control, read the fields, copy the values, or include them in screenshots.

Expected: the user explicitly reports that Railway saved both variables.

- [ ] **Step 4: Verify only key presence and keep Provider on mock**

Run:

~~~bash
set +x
npx -y @railway/cli@5.26.0 variable list --json \
  --service api --environment production |
  jq -e '
    has("TENCENTCLOUD_SECRET_ID")
    and has("TENCENTCLOUD_SECRET_KEY")
    and .OCR_PROVIDER == "mock"
    and .PROVIDER_MODE == "demo"
  ' >/dev/null
printf 'railway_secret_keys_present=true\n'
~~~

Expected: railway_secret_keys_present=true and no variable value is printed.

### Task 3: Activate the real Provider with paid retries disabled

**Files:**
- Read: apps/api/railway.json
- Read: apps/api/app/services/ocr_contract.py
- Test: apps/api/tests/test_tencent_ocr_provider.py
- Test: apps/api/tests/test_ocr_status.py

**Interfaces:**
- Consumes: Railway secret key presence from Task 2 and DEPLOY_SHA from Task 1.
- Produces: A healthy API deployment running tencent_question_split with retries=0.

- [ ] **Step 1: Re-run the fixed contract tests**

Run:

~~~bash
cd "$WORKTREE/apps/api"
uv run pytest -q tests/test_tencent_ocr_provider.py tests/test_ocr_status.py
cd "$WORKTREE"
~~~

Expected: all selected tests pass with exit 0.

- [ ] **Step 2: Set only non-secret activation variables**

Run:

~~~bash
npx -y @railway/cli@5.26.0 variable set \
  --service api --environment production --skip-deploys \
  OCR_PROVIDER=tencent_question_split \
  TENCENTCLOUD_OCR_MAX_RETRIES=0
~~~

Expected: exit 0 and no secret output.

- [ ] **Step 3: Upload the exact clean API tree**

Run:

~~~bash
test "$(git rev-parse HEAD)" = "$DEPLOY_SHA"
test -z "$(git status --porcelain)"
npx -y @railway/cli@5.26.0 up apps/api --path-as-root \
  --service api --environment production --yes
~~~

Expected: Railway returns a new API build URL and the upload command exits 0.

- [ ] **Step 4: Wait on deployment state instead of sleeping blindly**

Run:

~~~bash
for attempt in $(seq 1 60); do
  status=$(
    npx -y @railway/cli@5.26.0 status --json |
      jq -r '
        .environments.edges[]
        | select(.node.name == "production")
        | .node.serviceInstances.edges[]
        | select(.node.serviceName == "api")
        | .node.latestDeployment.status
      '
  )
  printf 'api_status=%s\n' "$status"
  case "$status" in
    SUCCESS) break ;;
    FAILED|CRASHED|REMOVED) exit 1 ;;
  esac
  sleep 5
done
test "$status" = "SUCCESS"
~~~

Expected: the last status is SUCCESS.

- [ ] **Step 5: Verify the running process and readiness**

Run:

~~~bash
activation_ready=0
for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error --connect-timeout 5 --max-time 10 \
    "$API_URL/ready" >/dev/null 2>&1 &&
    npx -y @railway/cli@5.26.0 ssh \
      --service api --environment production \
      python - <<'PY' >/dev/null 2>&1
import json
import os

actual = {
    "provider_mode": os.environ.get("PROVIDER_MODE"),
    "ocr_provider": os.environ.get("OCR_PROVIDER"),
    "ocr_retries": os.environ.get("TENCENTCLOUD_OCR_MAX_RETRIES"),
}
expected = {
    "provider_mode": "demo",
    "ocr_provider": "tencent_question_split",
    "ocr_retries": "0",
}
assert actual == expected, actual
print(json.dumps(actual, sort_keys=True))
PY
  then
    activation_ready=1
    break
  fi
  sleep 2
done
test "$activation_ready" = "1"
npx -y @railway/cli@5.26.0 ssh \
  --service api --environment production \
  python - <<'PY'
import json
import os

actual = {
    "provider_mode": os.environ.get("PROVIDER_MODE"),
    "ocr_provider": os.environ.get("OCR_PROVIDER"),
    "ocr_retries": os.environ.get("TENCENTCLOUD_OCR_MAX_RETRIES"),
}
assert actual == {
    "provider_mode": "demo",
    "ocr_provider": "tencent_question_split",
    "ocr_retries": "0",
}
print(json.dumps(actual, sort_keys=True))
PY
curl --fail --silent --show-error --retry 3 --retry-all-errors \
  --connect-timeout 10 --max-time 30 "$API_URL/ready"
~~~

Expected: the SSH JSON reports demo, tencent_question_split, and 0; readiness returns status=ready/provider_mode=demo.

- [ ] **Step 6: Roll back immediately if Task 3 fails**

Run only if any Task 3 activation or readiness step fails:

~~~bash
npx -y @railway/cli@5.26.0 variable set \
  --service api --environment production --skip-deploys \
  OCR_PROVIDER=mock \
  TENCENTCLOUD_OCR_MAX_RETRIES=2
npx -y @railway/cli@5.26.0 redeploy \
  --service api --environment production --yes
~~~

Then wait for the rollback deployment and verify it:

~~~bash
rollback_ready=0
for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error --connect-timeout 5 --max-time 10 \
    "$API_URL/ready" >/dev/null 2>&1 &&
    npx -y @railway/cli@5.26.0 ssh \
      --service api --environment production \
      python - <<'PY' >/dev/null 2>&1
import os

assert os.environ.get("PROVIDER_MODE") == "demo"
assert os.environ.get("OCR_PROVIDER") == "mock"
assert os.environ.get("TENCENTCLOUD_OCR_MAX_RETRIES") == "2"
PY
  then
    rollback_ready=1
    break
  fi
  sleep 2
done
test "$rollback_ready" = "1"
npx -y @railway/cli@5.26.0 ssh \
  --service api --environment production \
  python - <<'PY'
import json
import os

actual = {
    "provider_mode": os.environ.get("PROVIDER_MODE"),
    "ocr_provider": os.environ.get("OCR_PROVIDER"),
    "ocr_retries": os.environ.get("TENCENTCLOUD_OCR_MAX_RETRIES"),
}
assert actual == {
    "provider_mode": "demo",
    "ocr_provider": "mock",
    "ocr_retries": "2",
}
print(json.dumps(actual, sort_keys=True))
PY
curl --fail --silent --show-error --retry 3 --retry-all-errors \
  --connect-timeout 10 --max-time 30 "$API_URL/ready"
~~~

Do not continue to the paid smoke.

Expected: production returns to demo AI, mock OCR, retries=2, and healthy readiness.

### Task 4: Execute exactly one paid smoke and restore normal retries

**Files:**
- Execute: scripts/production-smoke.sh
- Read: apps/api/app/models/ocr_task.py
- Read: apps/api/app/core/database.py
- Test: /Users/zhangguoli/Downloads/17715122101_img_01.png

**Interfaces:**
- Consumes: A healthy live Provider with retries=0 and the approved image.
- Produces: One succeeded Tencent OCR task, persisted question/upload/review data, a secure temporary login state, and a restored retries=2 deployment.

- [ ] **Step 1: Create isolated mode-0600 smoke state**

Run:

~~~bash
set -euo pipefail
set +x
umask 077
export LIVE_RUN_DIR
LIVE_RUN_DIR=$(mktemp -d /tmp/kaogong-live-tencent.XXXXXX)
chmod 700 "$LIVE_RUN_DIR"
export LIVE_PASSWORD_FILE="$LIVE_RUN_DIR/password"
export LIVE_STATE_FILE="$LIVE_RUN_DIR/state.json"
export LIVE_EVIDENCE_FILE="$LIVE_RUN_DIR/ocr-evidence.json"
openssl rand -hex 24 >"$LIVE_PASSWORD_FILE"
chmod 600 "$LIVE_PASSWORD_FILE"
touch "$LIVE_STATE_FILE" "$LIVE_EVIDENCE_FILE"
chmod 600 "$LIVE_STATE_FILE" "$LIVE_EVIDENCE_FILE"
printf 'live_run_dir=%s\n' "$LIVE_RUN_DIR"
~~~

Expected: one path under /tmp; all three files are owned by the current user with mode 0600 and the state/evidence files are empty.

- [ ] **Step 2: Define condition-based deployment verification**

Run in the same shell:

~~~bash
wait_api_config() {
  expected_provider=$1
  expected_retries=$2
  for attempt in $(seq 1 60); do
    if curl --fail --silent --show-error --connect-timeout 5 --max-time 10 \
      "$API_URL/ready" >/dev/null 2>&1 &&
      npx -y @railway/cli@5.26.0 ssh \
        --service api --environment production \
        python - "$expected_provider" "$expected_retries" <<'PY'
import os
import sys

assert os.environ.get("OCR_PROVIDER") == sys.argv[1]
assert os.environ.get("TENCENTCLOUD_OCR_MAX_RETRIES") == sys.argv[2]
assert os.environ.get("PROVIDER_MODE") == "demo"
PY
    then
      return 0
    fi
    sleep 2
  done
  return 1
}
~~~

Expected: the function is defined without output.

- [ ] **Step 3: Define mandatory restore and rollback behavior**

Run in the same shell:

~~~bash
paid_smoke_succeeded=0

restore_live_settings() {
  original_status=$?
  trap - EXIT HUP INT TERM
  set +e

  npx -y @railway/cli@5.26.0 variable set \
    --service api --environment production --skip-deploys \
    TENCENTCLOUD_OCR_MAX_RETRIES=2 >/dev/null
  restore_set_status=$?

  if [ "$restore_set_status" -eq 0 ]; then
    npx -y @railway/cli@5.26.0 redeploy \
      --service api --environment production --yes
    restore_deploy_status=$?
  else
    restore_deploy_status=1
  fi

  if [ "$restore_deploy_status" -eq 0 ]; then
    wait_api_config tencent_question_split 2
    restore_verify_status=$?
  else
    restore_verify_status=1
  fi

  if [ "$paid_smoke_succeeded" -ne 1 ] || [ "$original_status" -ne 0 ]; then
    npx -y @railway/cli@5.26.0 variable set \
      --service api --environment production --skip-deploys \
      OCR_PROVIDER=mock \
      TENCENTCLOUD_OCR_MAX_RETRIES=2 >/dev/null
    rollback_set_status=$?
    if [ "$rollback_set_status" -eq 0 ]; then
      npx -y @railway/cli@5.26.0 redeploy \
        --service api --environment production --yes
      rollback_deploy_status=$?
    else
      rollback_deploy_status=1
    fi
    if [ "$rollback_deploy_status" -eq 0 ]; then
      wait_api_config mock 2
      rollback_verify_status=$?
    else
      rollback_verify_status=1
    fi
  else
    rollback_verify_status=0
  fi

  set -e
  if [ "$restore_verify_status" -ne 0 ] || [ "$rollback_verify_status" -ne 0 ]; then
    printf 'STOP: failed to restore a verified safe OCR configuration\n' >&2
    exit 1
  fi
  exit "$original_status"
}

trap restore_live_settings EXIT
trap 'exit 130' HUP INT TERM
~~~

Expected: restore_live_settings is installed as the EXIT/signal handler.

- [ ] **Step 4: Reconfirm retries=0 immediately before the paid request**

Run:

~~~bash
wait_api_config tencent_question_split 0
~~~

Expected: exit 0. Any failure triggers the restore trap and no smoke command is run.

- [ ] **Step 5: Execute the one allowed real smoke**

Run exactly once:

~~~bash
SMOKE_PASSWORD=$(<"$LIVE_PASSWORD_FILE") \
EXPECTED_OCR_PROVIDER=tencent_question_split \
SMOKE_IMAGE_PATH="$IMAGE_PATH" \
WEB_URL="$WEB_URL" \
API_URL="$API_URL" \
SMOKE_STATE_FILE="$LIVE_STATE_FILE" \
  bash scripts/production-smoke.sh
~~~

Expected: production smoke passed; state points to LIVE_STATE_FILE. Do not rerun this command for any failure.

- [ ] **Step 6: Extract redacted evidence from the persisted OCR task**

Run:

~~~bash
upload_id=$(
  python3 - "$LIVE_STATE_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    print(json.load(source)["upload_id"])
PY
)

npx -y @railway/cli@5.26.0 ssh \
  --service api --environment production \
  python - "$upload_id" >"$LIVE_EVIDENCE_FILE" <<'PY'
import asyncio
import json
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import create_session_factory
from app.models.ocr_task import OCRTask


async def main() -> None:
    upload_id = sys.argv[1]
    session_factory = create_session_factory(get_settings().database_url)
    async with session_factory() as session:
        task = (
            await session.execute(
                select(OCRTask)
                .where(OCRTask.source_file_id == upload_id)
                .order_by(OCRTask.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
    result = task.normalized_result_json or {}
    questions = result.get("questions") or []
    first = questions[0] if questions else {}
    evidence = {
        "provider": task.provider,
        "api_name": task.api_name,
        "status": task.status,
        "provider_request_id_present": bool(task.provider_request_id),
        "provider_request_id": task.provider_request_id,
        "question_count": task.question_count,
        "first_question_text": (first.get("question_text") or "")[:160],
    }
    assert evidence["provider"] == "tencent_question_split"
    assert evidence["api_name"] == "QuestionSplitOCR"
    assert evidence["status"] == "succeeded"
    assert evidence["provider_request_id_present"] is True
    assert evidence["question_count"] >= 1
    assert evidence["first_question_text"]
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


asyncio.run(main())
PY

chmod 600 "$LIVE_EVIDENCE_FILE"
python3 -m json.tool "$LIVE_EVIDENCE_FILE"
~~~

Expected: succeeded tencent_question_split evidence, a non-empty RequestId, question_count at least 1, and a non-empty first question text. No Base64 or secret appears.

- [ ] **Step 7: Mark success and let the trap restore retries=2**

Run:

~~~bash
paid_smoke_succeeded=1
exit 0
~~~

Expected: the EXIT trap redeploys API, verifies tencent_question_split with retries=2, and exits 0.

### Task 5: Verify the persisted real result in Chrome without another OCR call

**Files:**
- Read: LIVE_STATE_FILE from Task 4
- Read: LIVE_PASSWORD_FILE from Task 4
- Read: LIVE_EVIDENCE_FILE from Task 4

**Interfaces:**
- Consumes: The persisted smoke account, question ID, generated password, and successful real OCR evidence.
- Produces: A read-only Chrome acceptance result and proof that no second OCR task was created.

- [ ] **Step 1: Read only the non-secret login identity and saved question ID**

Run:

~~~bash
python3 - "$LIVE_STATE_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    data = json.load(source)
print(json.dumps(
    {"email": data["email"], "question_id": data["question_id"]},
    sort_keys=True,
))
PY
~~~

Expected: one smoke email and one UUID. Do not print LIVE_PASSWORD_FILE.

- [ ] **Step 2: Use Chrome documentation to log in to the existing smoke account**

Reuse the chrome binding from Task 2. Open WEB_URL/login, fill the email from LIVE_STATE_FILE and the password read inside the trusted automation process from LIVE_PASSWORD_FILE, then submit login.

Expected: Chrome reaches the authenticated application shell. No OCR endpoint is called.

- [ ] **Step 3: Verify the live Provider label without starting recognition**

Open WEB_URL/questions/new and select the image-recognition mode without choosing a file or clicking the recognition button.

Expected: the page displays 腾讯云真实 OCR and does not display 演示 OCR（不会调用腾讯云）.

- [ ] **Step 4: Verify the persisted question detail**

Open WEB_URL/questions/{question_id}, substituting the UUID read in Step 1.

Expected: the detail page shows the saved first-question text, answer options, source image/visual metadata, completed demo AI diagnosis, and the demo AI marker.

- [ ] **Step 5: Prove Chrome did not create another OCR task**

Run:

~~~bash
upload_id=$(
  python3 - "$LIVE_STATE_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    print(json.load(source)["upload_id"])
PY
)

npx -y @railway/cli@5.26.0 ssh \
  --service api --environment production \
  python - "$upload_id" <<'PY'
import asyncio
import json
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import create_session_factory
from app.models.ocr_task import OCRTask


async def main() -> None:
    upload_id = sys.argv[1]
    session_factory = create_session_factory(get_settings().database_url)
    async with session_factory() as session:
        tasks = (
            await session.execute(
                select(OCRTask)
                .where(OCRTask.source_file_id == upload_id)
                .order_by(OCRTask.created_at.asc())
            )
        ).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].status == "succeeded"
    print(json.dumps({"ocr_task_count": 1, "status": "succeeded"}))


asyncio.run(main())
PY
~~~

Expected: ocr_task_count=1 and status=succeeded.

### Task 6: Run final production and repository verification

**Files:**
- Verify: apps/api
- Verify: apps/web
- Verify: docs/superpowers/specs/2026-07-15-railway-live-tencent-ocr-design.md
- Verify: docs/superpowers/plans/2026-07-15-railway-live-tencent-ocr.md

**Interfaces:**
- Consumes: Successful live deployment, real OCR evidence, and Chrome read-only evidence.
- Produces: A clean pushed branch and a final evidence-backed completion report.

- [ ] **Step 1: Verify final runtime configuration**

Run:

~~~bash
npx -y @railway/cli@5.26.0 ssh \
  --service api --environment production \
  python - <<'PY'
import json
import os

actual = {
    "provider_mode": os.environ.get("PROVIDER_MODE"),
    "ocr_provider": os.environ.get("OCR_PROVIDER"),
    "ocr_retries": os.environ.get("TENCENTCLOUD_OCR_MAX_RETRIES"),
}
assert actual == {
    "provider_mode": "demo",
    "ocr_provider": "tencent_question_split",
    "ocr_retries": "2",
}
print(json.dumps(actual, sort_keys=True))
PY
npx -y @railway/cli@5.26.0 ssh \
  --service api --environment production \
  alembic current
~~~

Expected: demo AI, live Tencent OCR, retries=2, and 0006_question_split_ocr (head).

- [ ] **Step 2: Verify Railway deployments and public health**

Run:

~~~bash
npx -y @railway/cli@5.26.0 status --json |
  jq '[
    .environments.edges[]
    | select(.node.name == "production")
    | .node.serviceInstances.edges[]
    | {
        service: .node.serviceName,
        deployment: .node.latestDeployment.id,
        status: .node.latestDeployment.status
      }
  ] | sort_by(.service)'
curl --fail --silent --show-error --retry 3 --retry-all-errors \
  --connect-timeout 10 --max-time 30 "$API_URL/health"
curl --fail --silent --show-error --retry 3 --retry-all-errors \
  --connect-timeout 10 --max-time 30 "$API_URL/ready"
curl --fail --silent --show-error --retry 3 --retry-all-errors \
  --connect-timeout 10 --max-time 30 "$WEB_URL/health"
~~~

Expected: Postgres, api, and web are SUCCESS; health/readiness remain demo AI and healthy.

- [ ] **Step 3: Run fresh backend verification**

Run:

~~~bash
cd "$WORKTREE/apps/api"
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run pytest -q
~~~

Expected: lock check, Ruff, strict mypy, and all non-opt-in tests pass; the real Tencent E2E remains skipped because the paid request was already completed through production smoke.

- [ ] **Step 4: Run fresh frontend verification**

Run:

~~~bash
cd "$WORKTREE/apps/web"
npm test -- --run
npm run lint
npx tsc --noEmit
npm run build
~~~

Expected: all Vitest tests, ESLint, TypeScript, and the Next.js production build pass.

- [ ] **Step 5: Run final repository and secret scans**

Run:

~~~bash
cd "$WORKTREE"
git diff --check
test -z "$(git status --porcelain)"
printf 'tracked_env='
git ls-files | rg '(^|/)\.env$' | wc -l | tr -d ' '
printf 'akid_files='
rg -Il --hidden --glob '!**/.git/**' 'AKID[A-Za-z0-9]{16,}' . | wc -l | tr -d ' '
printf 'openai_key_files='
rg -Il --hidden --glob '!**/.git/**' 'sk-[A-Za-z0-9_-]{20,}' . | wc -l | tr -d ' '
printf 'private_key_files='
rg -Il --hidden --glob '!**/.git/**' -- \
  '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' . |
  wc -l | tr -d ' '
printf 'long_base64_files='
rg -Il --hidden --glob '!**/.git/**' \
  '[A-Za-z0-9+/]{500,}={0,2}' . |
  wc -l | tr -d ' '
~~~

Expected: clean worktree and every scan count is 0.

- [ ] **Step 6: Push documentation commits and verify remote equality**

Run:

~~~bash
cd "$WORKTREE"
git push origin "$BRANCH"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/$BRANCH)"
gh pr view 2 --repo zhangguoli2008/kaogongsystem \
  --json state,isDraft,headRefOid,url
~~~

Expected: push succeeds, local and remote SHAs match, and Draft PR #2 remains open at https://github.com/zhangguoli2008/kaogongsystem/pull/2.

- [ ] **Step 7: Remove only the exact temporary smoke directory after reporting**

After the user has received the evidence report, run:

~~~bash
test -n "$LIVE_RUN_DIR"
case "$LIVE_RUN_DIR" in
  /tmp/kaogong-live-tencent.*) rm -rf -- "$LIVE_RUN_DIR" ;;
  *) printf 'refusing unsafe cleanup path\n' >&2; exit 1 ;;
esac
~~~

Expected: only the generated live smoke directory is removed; no workspace or user file is changed.
