# Railway Live Tencent OCR Safety-Corrected Execution Plan

## Status and scope

This correction supersedes Task 3 through Task 5 of `2026-07-15-railway-live-tencent-ocr.md`. Task 1 and Task 2 are already complete: the approved branch is clean and pushed, all baseline tests passed, the approved image was revalidated, the two secret keys are present in Railway, and production is still healthy on `demo + mock + retries=2`.

The correction does not change the approved product outcome. It strengthens the deployment automation so that:

- the rollback trap exists before the first production variable change;
- activation, the paid smoke, evidence collection, restore, and rollback share one shell lifetime;
- a failed `live/2` restore always attempts `mock/2`;
- rollback uploads the exact verified `apps/api` tree instead of redeploying an ambiguous latest deployment;
- the one allowed smoke cannot be resent by curl configuration, SDK retry, or an accidental restart of the same deployment workflow;
- the outer workflow retains the temporary login state only after `LIVE2_VERIFIED`.

## Pre-paid recovery record

The first activation attempt on 2026-07-15 stopped before smoke registration, question upload, one-shot marker consumption, or any OCR request. Railway CLI 5.26.0 exposed the unique deployment message as `meta.cliMessage`, not `meta.deploymentMessage`; additionally, mode-0400/0500 archive entries remained root-owned after Docker `COPY`, so the UID-10001 runtime could not import `/app/app/main.py`. Activation deployment `90c4862d-4bab-4842-bdd9-8e787b09b35f` and its automatic rollback deployment `f70d067c-9b49-422b-a454-c344482c850d` therefore failed health checks.

Production was recovered with the same pushed commit in deployment `3dd63738-4344-40fe-8ab0-5ed27a3c58f0`, using mode-0444 files and mode-0555 directories. Independent checks proved `demo + mock + retries=2`, healthy API/Web endpoints, zero users for the deterministic smoke email, and zero Tencent OCR tasks. A corrected paid rollout requires a fresh explicit user approval; the failed block must not be rerun automatically.

## Code-level one-shot invariants

Before production activation, the branch must include and test all of these invariants:

1. `scripts/production-smoke.sh` requires `SMOKE_EMAIL`, `SMOKE_IMAGE_SHA256`, and `SMOKE_OCR_ONE_SHOT_GUARD_FILE` for `tencent_question_split`.
2. The smoke consumes `paid-ocr.spent` with `O_CREAT|O_EXCL` immediately before its only `POST /api/v1/ocr`.
3. The marker helper requires an owned mode-0700 directory and creates an owned mode-0600 regular marker.
4. curl receives `--disable` first and `--retry 0`, so `~/.curlrc` cannot introduce retries.
5. the Tencent `ClientProfile` explicitly uses `NoopRetryer`.
6. the application test proves `TENCENTCLOUD_OCR_MAX_RETRIES=0` makes exactly one SDK call and performs no application retry sleep.
7. `SMOKE_EMAIL` is deterministically tied to the full `DEPLOY_SHA`; if a process restart occurs after registration, the unique email stops the repeated workflow before OCR.
8. The rollout fully decodes the approved image, copies the exact approved bytes into its private run directory, and verifies the server-downloaded upload against `SMOKE_IMAGE_SHA256` before consuming the one-shot marker.
9. Every Railway upload comes from one read-only, runtime-readable `git archive` snapshot of `DEPLOY_SHA` (files 0444, directories 0555), and runtime verification is bound to the exact discovered deployment ID.
10. Railway CLI 5.26.0 uploads use detached mode without JSON/CI mode, and deployment discovery matches the unique `meta.cliMessage` field.

Required gate:

~~~bash
cd /Users/zhangguoli/Documents/Code/kaogongsystem/.worktrees/tencent-question-split-ocr/apps/api
uv run pytest -q \
  tests/test_live_ocr_rollout_plan.py \
  tests/test_ocr_one_shot_guard.py \
  tests/test_production_smoke_one_shot.py \
  tests/test_tencent_ocr_provider.py \
  tests/test_ocr_status.py
bash -n ../../scripts/production-smoke.sh
~~~

## Rollout state machine

~~~text
BASELINE
  -> ACTIVATING
  -> LIVE0
  -> ATTEMPTED
  -> SMOKE_OK
  -> EVIDENCE_OK
  -> RESTORING
  -> LIVE2_VERIFIED
~~~

Failure transitions:

- failure before `ATTEMPTED`: upload and verify `mock/2`;
- failure after `ATTEMPTED`: first try to upload and verify `live/2`, then upload and verify `mock/2`;
- failed `live/2` restore: always upload and verify `mock/2`;
- failed `mock/2` rollback: report `UNSAFE`, exit non-zero, and do not issue an OCR request;
- HUP, INT, and TERM use the same EXIT finalizer; SIGKILL cannot be trapped and remains an explicit shell limitation;
- a failed or ambiguous paid smoke is never rerun without a new explicit user approval.

## Single-shell corrected rollout

Run this block exactly once from the clean pushed worktree. It outputs no secret, Cookie, image Base64, or credential value.

~~~bash
set -euo pipefail
set +x
umask 077

WORKTREE=/Users/zhangguoli/Documents/Code/kaogongsystem/.worktrees/tencent-question-split-ocr
BRANCH=codex/tencent-question-split-ocr
WEB_URL=https://web-production-3ce0.up.railway.app
API_URL=https://api-production-f136.up.railway.app
IMAGE_PATH=/Users/zhangguoli/Downloads/17715122101_img_01.png
IMAGE_SHA=09a5739276b827c01cd2fa4a262688eec529426e864b487077285e8e1f57f788
railway_cli=(npx -y @railway/cli@5.26.0)

export WEB_URL API_URL
cd "$WORKTREE"
DEPLOY_SHA=$(git rev-parse HEAD)
test "$(git branch --show-current)" = "$BRANCH"
test -z "$(git status --porcelain)"
test "$(git rev-parse "origin/$BRANCH")" = "$DEPLOY_SHA"
test "$(shasum -a 256 "$IMAGE_PATH" | awk '{print $1}')" = "$IMAGE_SHA"

"${railway_cli[@]}" variable list --json \
  --service api --environment production |
  jq -e '
    (.TENCENTCLOUD_SECRET_ID | type == "string" and length > 0)
    and (.TENCENTCLOUD_SECRET_KEY | type == "string" and length > 0)
    and (has("TENCENTCLOUD_REGION") | not)
    and .OCR_PROVIDER == "mock"
    and .PROVIDER_MODE == "demo"
    and .TENCENTCLOUD_OCR_MAX_RETRIES == "2"
  ' >/dev/null

curl --disable --fail --silent --show-error \
  --connect-timeout 5 --max-time 10 "$API_URL/ready" >/dev/null
"${railway_cli[@]}" ssh --service api --environment production \
  python - <<'PY'
import os

actual = {
    "provider_mode": os.environ.get("PROVIDER_MODE"),
    "ocr_provider": os.environ.get("OCR_PROVIDER"),
    "ocr_retries": os.environ.get("TENCENTCLOUD_OCR_MAX_RETRIES"),
}
expected = {
    "provider_mode": "demo",
    "ocr_provider": "mock",
    "ocr_retries": "2",
}
if actual != expected:
    raise SystemExit("baseline runtime configuration mismatch")
PY

LIVE_RUN_DIR=$(mktemp -d /tmp/kaogong-live-tencent.XXXXXX)
chmod 700 "$LIVE_RUN_DIR"
LIVE_PASSWORD_FILE="$LIVE_RUN_DIR/password"
LIVE_STATE_FILE="$LIVE_RUN_DIR/state.json"
LIVE_EVIDENCE_FILE="$LIVE_RUN_DIR/ocr-evidence.json"
LIVE_GUARD_FILE="$LIVE_RUN_DIR/paid-ocr.spent"
APPROVED_IMAGE_FILE="$LIVE_RUN_DIR/approved-question.png"
DEPLOY_SOURCE_DIR="$LIVE_RUN_DIR/source"
DEPLOY_API_DIR="$DEPLOY_SOURCE_DIR/apps/api"
RUN_TOKEN=$(openssl rand -hex 8)
SMOKE_EMAIL="codex-live-tencent-${DEPLOY_SHA}@example.com"

cleanup_deploy_material() {
  chmod -R u+w "$DEPLOY_SOURCE_DIR" 2>/dev/null || true
  rm -rf -- "$DEPLOY_SOURCE_DIR"
  chmod u+w "$APPROVED_IMAGE_FILE" 2>/dev/null || true
  rm -f -- "$APPROVED_IMAGE_FILE" "$LIVE_RUN_DIR"/deploy-*.log
}

cleanup_run_dir() {
  cleanup_deploy_material
  rm -f -- \
    "$LIVE_PASSWORD_FILE" \
    "$LIVE_STATE_FILE" \
    "$LIVE_EVIDENCE_FILE" \
    "$LIVE_GUARD_FILE"
  rmdir -- "$LIVE_RUN_DIR" 2>/dev/null || true
}

early_finalize() {
  local status=$?
  trap - EXIT
  trap '' HUP INT TERM
  set +e
  cleanup_run_dir
  trap - HUP INT TERM
  exit "$status"
}

trap early_finalize EXIT
trap 'exit 130' HUP INT TERM

printf '%s' "$(openssl rand -hex 24)" >"$LIVE_PASSWORD_FILE"
: >"$LIVE_STATE_FILE"
: >"$LIVE_EVIDENCE_FILE"
chmod 600 "$LIVE_PASSWORD_FILE" "$LIVE_STATE_FILE" "$LIVE_EVIDENCE_FILE"

mkdir "$DEPLOY_SOURCE_DIR"
git archive "$DEPLOY_SHA" | tar -x -C "$DEPLOY_SOURCE_DIR"
test -z "$(find "$DEPLOY_SOURCE_DIR" -type l -print -quit)"
find "$DEPLOY_SOURCE_DIR" -type f -exec chmod 444 {} +
find "$DEPLOY_SOURCE_DIR" -type d -exec chmod 555 {} +
test -f "$DEPLOY_API_DIR/railway.json"

cd "$WORKTREE/apps/api"
uv run python - "$IMAGE_PATH" "$APPROVED_IMAGE_FILE" "$IMAGE_SHA" <<'PY'
from __future__ import annotations

import hashlib
import io
import os
import stat
import sys

from PIL import Image


source_path, destination_path, expected_sha = sys.argv[1:]
source = os.open(source_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
try:
    before = os.fstat(source)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
    ):
        raise SystemExit("approved image source identity is unsafe")
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    while chunk := os.read(source, 1024 * 1024):
        chunks.append(chunk)
        digest.update(chunk)
    after = os.fstat(source)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise SystemExit("approved image source changed during validation")
finally:
    os.close(source)

raw = b"".join(chunks)
if digest.hexdigest() != expected_sha:
    raise SystemExit("approved image digest mismatch")
if len(raw) != 482226:
    raise SystemExit("approved image size mismatch")
with Image.open(io.BytesIO(raw)) as image:
    image.verify()
with Image.open(io.BytesIO(raw)) as image:
    image.load()
    if image.format != "PNG" or image.mode != "RGB":
        raise SystemExit("approved image format or mode mismatch")
    if (image.width, image.height) != (2224, 2852):
        raise SystemExit("approved image dimensions mismatch")

parent, name = os.path.dirname(destination_path), os.path.basename(destination_path)
directory = os.open(
    parent,
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
)
try:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=directory,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("approved image snapshot write was incomplete")
            view = view[written:]
        os.fsync(descriptor)
        saved = os.fstat(descriptor)
        if (
            not stat.S_ISREG(saved.st_mode)
            or saved.st_uid != os.geteuid()
            or saved.st_nlink != 1
            or stat.S_IMODE(saved.st_mode) != 0o600
        ):
            raise SystemExit("approved image snapshot identity is unsafe")
    finally:
        os.close(descriptor)
    os.fsync(directory)
finally:
    os.close(directory)
print("approved_image_snapshot=validated")
PY
cd "$WORKTREE"
chmod 400 "$APPROVED_IMAGE_FILE"

activation_started=0
paid_attempted=0
smoke_ok=0
evidence_ok=0
deploy_sequence=0
LAST_DEPLOYMENT_ID=""

latest_api_deployment_id() {
  "${railway_cli[@]}" status --json |
    jq -r '
      .environments.edges[]
      | select(.node.name == "production")
      | .node.serviceInstances.edges[]
      | select(.node.serviceName == "api")
      | .node.latestDeployment.id // empty
    '
}

wait_api_config() {
  local expected_provider=$1
  local expected_retries=$2
  local expected_deployment_id=$3
  local attempt
  for attempt in $(seq 1 60); do
    local latest_id=""
    latest_id=$(latest_api_deployment_id 2>/dev/null) || latest_id=""
    if [[ "$latest_id" == "$expected_deployment_id" ]] &&
      curl --disable --fail --silent --show-error \
      --connect-timeout 5 --max-time 10 "$API_URL/ready" >/dev/null 2>&1 &&
      "${railway_cli[@]}" ssh --service api --environment production \
        python - "$expected_provider" "$expected_retries" >/dev/null 2>&1 <<'PY'
import os
import sys

actual = (
    os.environ.get("PROVIDER_MODE"),
    os.environ.get("OCR_PROVIDER"),
    os.environ.get("TENCENTCLOUD_OCR_MAX_RETRIES"),
)
expected = ("demo", sys.argv[1], sys.argv[2])
if actual != expected:
    raise SystemExit("runtime configuration mismatch")
PY
    then
      if ! "${railway_cli[@]}" ssh --service api --environment production \
        python - "$expected_provider" "$expected_retries" <<'PY'
import json
import os
import sys

actual = {
    "provider_mode": os.environ.get("PROVIDER_MODE"),
    "ocr_provider": os.environ.get("OCR_PROVIDER"),
    "ocr_retries": os.environ.get("TENCENTCLOUD_OCR_MAX_RETRIES"),
}
expected = {
    "provider_mode": "demo",
    "ocr_provider": sys.argv[1],
    "ocr_retries": sys.argv[2],
}
if actual != expected:
    raise SystemExit("visible runtime configuration mismatch")
print(json.dumps(actual, sort_keys=True))
PY
      then
        return 1
      fi
      latest_id=$(latest_api_deployment_id 2>/dev/null) || return 1
      [[ "$latest_id" == "$expected_deployment_id" ]] || return 1
      printf 'active_api_deployment_id=%s\n' "$latest_id"
      return 0
    fi
    sleep 2
  done
  return 1
}

deployment_for_message() {
  local message=$1
  "${railway_cli[@]}" deployment list \
    --service api --environment production --limit 100 --json |
    jq -r --arg message "$message" '
      [.[] | select(.meta.cliMessage == $message)]
      | sort_by(.createdAt)
      | last
      | .id // empty
    '
}

deployment_status() {
  local deployment_id=$1
  "${railway_cli[@]}" deployment list \
    --service api --environment production --limit 100 --json |
    jq -r --arg deployment_id "$deployment_id" '
      [.[] | select(.id == $deployment_id)]
      | first
      | .status // empty
    '
}

wait_uploaded_deployment() {
  local message=$1
  local upload_status=$2
  local attempt
  local deployment_id=""
  local status=""
  local previous_status=""

  for attempt in $(seq 1 30); do
    deployment_id=$(deployment_for_message "$message" 2>/dev/null) || deployment_id=""
    [[ -n "$deployment_id" ]] && break
    sleep 2
  done
  if [[ -z "$deployment_id" ]]; then
    printf 'deployment_discovery_failed upload_status=%s\n' "$upload_status" >&2
    return 1
  fi
  LAST_DEPLOYMENT_ID=$deployment_id
  printf 'uploaded_api_deployment_id=%s\n' "$deployment_id"

  for attempt in $(seq 1 120); do
    status=$(deployment_status "$deployment_id" 2>/dev/null) || status=""
    if [[ "$status" != "$previous_status" ]]; then
      printf 'api_deployment_status=%s\n' "$status"
      previous_status=$status
    fi
    case "$status" in
      SUCCESS) return 0 ;;
      FAILED|CRASHED|REMOVED|SKIPPED) return 1 ;;
    esac
    sleep 2
  done
  return 1
}

up_config() {
  local provider=$1
  local retries=$2
  local message
  local upload_log
  local upload_status
  deploy_sequence=$((deploy_sequence + 1))
  message="codex-${RUN_TOKEN}-${deploy_sequence}-${provider}-${retries}-${DEPLOY_SHA:0:12}"
  upload_log="$LIVE_RUN_DIR/deploy-${deploy_sequence}.log"
  "${railway_cli[@]}" variable set \
    --service api --environment production --skip-deploys \
    OCR_PROVIDER="$provider" \
    TENCENTCLOUD_OCR_MAX_RETRIES="$retries" >/dev/null || return 1
  if "${railway_cli[@]}" up "$DEPLOY_API_DIR" --path-as-root \
    --service api --environment production \
    --yes --detach --message "$message" >"$upload_log"; then
    upload_status=0
  else
    upload_status=$?
  fi
  wait_uploaded_deployment "$message" "$upload_status" || return 1
  wait_api_config "$provider" "$retries" "$LAST_DEPLOYMENT_ID"
}

finish_rollout() {
  local original_status=$?
  local restore_status=1
  local rollback_status=1
  local final_status=$original_status
  local outcome=NO_CHANGE
  local retain_run_dir=0
  trap - EXIT
  trap '' HUP INT TERM
  set +e

  if (( activation_started == 0 )); then
    outcome=NO_CHANGE
  elif (( paid_attempted == 1 )); then
    up_config tencent_question_split 2
    restore_status=$?
    if ((
      original_status == 0 &&
      smoke_ok == 1 &&
      evidence_ok == 1 &&
      restore_status == 0
    )); then
      outcome=LIVE2_VERIFIED
      retain_run_dir=1
      final_status=0
    else
      up_config mock 2
      rollback_status=$?
      if (( rollback_status == 0 )); then
        outcome=MOCK2_VERIFIED
      else
        outcome=UNSAFE
      fi
      final_status=1
    fi
  else
    up_config mock 2
    rollback_status=$?
    if (( rollback_status == 0 )); then
      outcome=MOCK2_VERIFIED
    else
      outcome=UNSAFE
    fi
    final_status=1
  fi

  cleanup_deploy_material
  if (( retain_run_dir == 0 )); then
    rm -f -- "$LIVE_PASSWORD_FILE" "$LIVE_EVIDENCE_FILE"
    if [[ -e "$LIVE_GUARD_FILE" ]]; then
      printf 'failed_guard_dir=%s\n' "$LIVE_RUN_DIR"
    else
      rm -f -- "$LIVE_STATE_FILE"
      rmdir -- "$LIVE_RUN_DIR" 2>/dev/null || true
    fi
  else
    printf 'live_run_dir=%s\n' "$LIVE_RUN_DIR"
    printf 'smoke_email=%s\n' "$SMOKE_EMAIL"
  fi
  printf 'rollout_outcome=%s\n' "$outcome"
  trap - HUP INT TERM
  exit "$final_status"
}

trap finish_rollout EXIT
trap 'exit 130' HUP INT TERM

activation_started=1
up_config tencent_question_split 0

paid_attempted=1
(
  set +a
  unset SMOKE_PASSWORD
  SMOKE_PASSWORD=$(<"$LIVE_PASSWORD_FILE")
  export EXPECTED_OCR_PROVIDER=tencent_question_split
  export SMOKE_IMAGE_PATH="$APPROVED_IMAGE_FILE"
  export SMOKE_IMAGE_SHA256="$IMAGE_SHA"
  export SMOKE_STATE_FILE="$LIVE_STATE_FILE"
  export SMOKE_EMAIL
  export SMOKE_OCR_ONE_SHOT_GUARD_FILE="$LIVE_GUARD_FILE"
  cd "$DEPLOY_SOURCE_DIR"
  source scripts/production-smoke.sh
)
smoke_ok=1

upload_id=$(python3 - "$LIVE_STATE_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    print(json.load(source)["upload_id"])
PY
)

"${railway_cli[@]}" ssh --service api --environment production \
  python - "$SMOKE_EMAIL" "$upload_id" >"$LIVE_EVIDENCE_FILE" <<'PY'
import asyncio
import json
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import create_session_factory
from app.models.ocr_task import OCRTask
from app.models.user import User


async def main() -> None:
    email, upload_id = sys.argv[1:]
    session_factory = create_session_factory(get_settings().database_url)
    async with session_factory() as session:
        tasks = (
            await session.execute(
                select(OCRTask)
                .join(User, OCRTask.user_id == User.id)
                .where(
                    User.email == email,
                    OCRTask.provider == "tencent_question_split",
                )
                .order_by(OCRTask.created_at.asc())
            )
        ).scalars().all()
    if len(tasks) != 1:
        raise SystemExit(f"expected exactly one Tencent OCR task, found {len(tasks)}")
    task = tasks[0]
    result = task.normalized_result_json or {}
    questions = result.get("questions") or []
    first = questions[0] if questions else {}
    evidence = {
        "ocr_task_count": len(tasks),
        "source_file_matches": task.source_file_id == upload_id,
        "provider": task.provider,
        "api_name": task.api_name,
        "status": task.status,
        "provider_request_id_present": bool(task.provider_request_id),
        "provider_request_id": task.provider_request_id,
        "question_count": task.question_count,
        "first_question_text": (first.get("question_text") or "")[:160],
    }
    if evidence["source_file_matches"] is not True:
        raise SystemExit("OCR task source file mismatch")
    if evidence["api_name"] != "QuestionSplitOCR":
        raise SystemExit("OCR task API name mismatch")
    if evidence["status"] != "succeeded":
        raise SystemExit("OCR task did not succeed")
    if evidence["provider_request_id_present"] is not True:
        raise SystemExit("OCR provider request ID is missing")
    if evidence["question_count"] < 1 or not evidence["first_question_text"]:
        raise SystemExit("OCR task returned no usable question")
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


asyncio.run(main())
PY
chmod 600 "$LIVE_EVIDENCE_FILE"
python3 -m json.tool "$LIVE_EVIDENCE_FILE"
evidence_ok=1
exit 0
~~~

Expected final lines on success:

~~~text
live_run_dir=/tmp/kaogong-live-tencent.<random>
smoke_email=codex-live-tencent-<full-DEPLOY_SHA>@example.com
rollout_outcome=LIVE2_VERIFIED
~~~

Do not execute the block a second time if it exits non-zero or returns an ambiguous transport result.

## Read-only Chrome acceptance and cleanup

After `LIVE2_VERIFIED`, reconstruct these paths from the returned `live_run_dir` without printing the password:

~~~bash
LIVE_PASSWORD_FILE="$live_run_dir/password"
LIVE_STATE_FILE="$live_run_dir/state.json"
LIVE_EVIDENCE_FILE="$live_run_dir/ocr-evidence.json"
LIVE_GUARD_FILE="$live_run_dir/paid-ocr.spent"
~~~

Chrome may read the email, question ID, and password inside the trusted automation process. It must only log in, open `/questions/new` without selecting a file, and open the saved `/questions/{question_id}` detail. It must not call `/ocr`.

After Chrome acceptance, query all Tencent OCR tasks for the deterministic smoke email again and require exactly one succeeded task. Then delete only the four known mode-0600 files and remove the exact mode-0700 run directory. Do not delete the Railway Tencent credentials.

## Final verification

Task 6 of the original plan then applies. In addition, the final proof chain must state:

- one atomic `paid-ocr.spent` marker was consumed;
- the fully decoded approved image snapshot and the server-downloaded upload both matched the fixed SHA-256 digest before the marker was consumed;
- the smoke contains one OCR POST and curl retry was disabled;
- the Web proxy contains one upstream fetch;
- the SDK retryer is `NoopRetryer`;
- runtime application retries were 0 during the smoke;
- activation, restore, and runtime checks were tied to exact deployment IDs uploaded from the same `DEPLOY_SHA` snapshot;
- exactly one Tencent OCRTask exists for the deployment-bound smoke email;
- final runtime is `demo + tencent_question_split + retries=2`.
