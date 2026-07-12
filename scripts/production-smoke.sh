#!/usr/bin/env bash
set -euo pipefail

umask 077

die() {
  printf 'production smoke failed: %s\n' "$1" >&2
  exit 1
}

for command_name in curl grep mktemp openssl python3 cmp; do
  command -v "$command_name" >/dev/null 2>&1 || die "missing required command: $command_name"
done

: "${WEB_URL:?WEB_URL is required}"
: "${API_URL:?API_URL is required}"

validate_origin() {
  python3 - "$1" "$2" <<'PY'
import ipaddress
import re
import sys
from urllib.parse import urlsplit

label, raw = sys.argv[1:]
try:
    parsed = urlsplit(raw)
    hostname = parsed.hostname or ""
    if parsed.port is not None:
        raise ValueError
except ValueError:
    raise SystemExit(f"{label} must be a canonical HTTPS origin")

reserved = (
    "localhost", "local", "internal", "lan", "localdomain", "home.arpa",
    "test", "invalid", "example", "onion", "alt", "example.com",
    "example.net", "example.org",
)
labels = hostname.split(".")
canonical_host = (
    1 < len(labels)
    and len(hostname) <= 253
    and all(
        len(part) <= 63
        and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part)
        for part in labels
    )
)
try:
    ipaddress.ip_address(hostname)
except ValueError:
    is_ip = False
else:
    is_ip = True

is_reserved = any(hostname == suffix or hostname.endswith("." + suffix) for suffix in reserved)
canonical = (
    parsed.scheme == "https"
    and not parsed.username
    and not parsed.password
    and parsed.path == ""
    and not parsed.query
    and not parsed.fragment
    and parsed.netloc == hostname
    and raw == f"https://{hostname}"
)
if not canonical or not canonical_host or is_ip or is_reserved:
    raise SystemExit(f"{label} must be a canonical public HTTPS origin")
PY
}

validate_origin WEB_URL "$WEB_URL"
validate_origin API_URL "$API_URL"
[[ "$WEB_URL" != "$API_URL" ]] || die "WEB_URL and API_URL must be different origins"

web_url=$WEB_URL
api_url=$API_URL
api_proxy="$web_url/api/v1"
image_path=${SMOKE_IMAGE_PATH:-docs/design/ai-exam-diagnosis-dashboard-selected.png}

[[ -f "$image_path" && ! -L "$image_path" && -r "$image_path" ]] \
  || die "SMOKE_IMAGE_PATH must be a readable regular image file, not a symlink"

image_path=$(python3 - "$image_path" <<'PY'
import os
import sys

path = os.path.realpath(sys.argv[1])
if any(character in path for character in ("\n", "\r", ";", ",")):
    raise SystemExit("SMOKE_IMAGE_PATH contains an unsupported character")
print(path)
PY
)

image_mime=$(python3 - "$image_path" <<'PY'
import os
import sys

path = sys.argv[1]
size = os.path.getsize(path)
if not 0 < size <= 10 * 1024 * 1024:
    raise SystemExit("SMOKE_IMAGE_PATH must be between 1 byte and 10 MiB")
with open(path, "rb") as source:
    header = source.read(16)
if header.startswith(b"\x89PNG\r\n\x1a\n"):
    print("image/png")
elif header.startswith(b"\xff\xd8\xff"):
    print("image/jpeg")
elif header[:4] == b"RIFF" and header[8:12] == b"WEBP":
    print("image/webp")
else:
    raise SystemExit("SMOKE_IMAGE_PATH must be a PNG, JPEG, or WebP image")
PY
)

state_created=0
state_written=0
if [[ -n ${SMOKE_STATE_FILE:-} ]]; then
  state_file=$SMOKE_STATE_FILE
  [[ "$state_file" = /* ]] || die "SMOKE_STATE_FILE must be an absolute path"
  [[ ! -L "$state_file" && ! -d "$state_file" ]] \
    || die "SMOKE_STATE_FILE must not be a symlink or directory"
else
  state_file=$(mktemp "${TMPDIR:-/tmp}/kaogong-smoke-state.XXXXXX")
  state_created=1
fi

state_tmp=""
tmp_dir=""
cleanup() {
  local exit_code=$?
  trap - EXIT
  [[ -n ${state_tmp:-} && -e ${state_tmp:-} ]] && rm -f -- "$state_tmp"
  [[ -n ${tmp_dir:-} && -d ${tmp_dir:-} ]] && rm -rf -- "$tmp_dir"
  if [[ "$state_created" = 1 && "$state_written" = 0 ]]; then
    rm -f -- "$state_file"
  fi
  exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

state_dir=$(dirname "$state_file")
state_name=$(basename "$state_file")
[[ -d "$state_dir" && -w "$state_dir" ]] || die "SMOKE_STATE_FILE parent must be writable"
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/kaogong-production-smoke.XXXXXX")
state_tmp=$(mktemp "$state_dir/.${state_name}.tmp.XXXXXX")
chmod 600 "$state_tmp"

email=${SMOKE_EMAIL:-"codex-smoke-$(date +%s)-$$@example.com"}
password=${SMOKE_PASSWORD:-}
if [[ -z "$password" ]]; then
  password="smoke-$(openssl rand -hex 24)"
fi
(( ${#password} >= 8 && ${#password} <= 128 )) \
  || die "SMOKE_PASSWORD must contain 8 to 128 characters"
case "$password" in
  *$'\n'*|*$'\r'*) die "SMOKE_PASSWORD must not contain newlines" ;;
esac

password_file="$tmp_dir/password"
printf '%s' "$password" >"$password_file"
chmod 600 "$password_file"
unset password

credentials_file="$tmp_dir/credentials.json"
python3 - "$credentials_file" "$email" "$password_file" <<'PY'
import json
import sys

output, email, password_path = sys.argv[1:]
with open(password_path, encoding="utf-8") as source:
    password = source.read()
with open(output, "w", encoding="utf-8") as target:
    json.dump({"email": email, "password": password}, target)
PY

wrong_file="$tmp_dir/not-an-image.txt"
printf 'not an image\n' >"$wrong_file"
oversize_file="$tmp_dir/oversize.png"
python3 - "$oversize_file" <<'PY'
import sys

with open(sys.argv[1], "wb") as target:
    target.truncate(10 * 1024 * 1024 + 1)
PY

curl_common=(
  --silent
  --show-error
  --connect-timeout 10
  --max-time 120
  --proto '=https'
  --tlsv1.2
  --compressed
)

http_request() {
  local expected=$1
  local body_file=$2
  local header_file=$3
  shift 3
  local status
  : >"$body_file"
  : >"$header_file"
  if ! status=$(curl "${curl_common[@]}" \
    --dump-header "$header_file" \
    --output "$body_file" \
    --write-out '%{http_code}' \
    "$@"); then
    die "HTTP transport failed"
  fi
  [[ "$status" = "$expected" ]] \
    || die "unexpected HTTP status: expected $expected, received $status"
}

assert_exact_json() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    actual = json.load(source)
expected = json.loads(sys.argv[2])
if actual != expected:
    raise SystemExit("unexpected JSON response")
PY
}

json_field() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
value = payload[sys.argv[2]]
if not isinstance(value, str):
    raise SystemExit("expected a string JSON field")
print(value)
PY
}

assert_uuid() {
  python3 - "$1" <<'PY'
import sys
import uuid

value = sys.argv[1]
if str(uuid.UUID(value)) != value:
    raise SystemExit("expected a canonical UUID")
PY
}

api_health="$tmp_dir/api-health.json"
http_request 200 "$api_health" "$tmp_dir/api-health.headers" "$api_url/health"
assert_exact_json "$api_health" '{"status":"ok","provider_mode":"demo"}'

api_ready="$tmp_dir/api-ready.json"
ready=0
for ((attempt = 1; attempt <= 30; attempt++)); do
  status=""
  if status=$(curl "${curl_common[@]}" --output "$api_ready" --write-out '%{http_code}' "$api_url/ready"); then
    if [[ "$status" = 200 ]]; then
      ready=1
      break
    fi
  fi
  sleep 2
done
[[ "$ready" = 1 ]] || die "API readiness did not reach HTTP 200"
assert_exact_json "$api_ready" '{"status":"ready","provider_mode":"demo"}'

web_health="$tmp_dir/web-health.json"
http_request 200 "$web_health" "$tmp_dir/web-health.headers" "$web_url/health"
assert_exact_json "$web_health" '{"status":"ok"}'
http_request 200 "$tmp_dir/login.html" "$tmp_dir/login.headers" "$web_url/login"
grep -q '登录' "$tmp_dir/login.html" || die "Web login page marker is missing"

http_request 200 "$tmp_dir/preflight.body" "$tmp_dir/preflight.headers" \
  --request OPTIONS \
  --header "Origin: $web_url" \
  --header 'Access-Control-Request-Method: POST' \
  --header 'Access-Control-Request-Headers: content-type' \
  "$api_url/api/v1/auth/login"
grep -Fqi "access-control-allow-origin: $web_url" "$tmp_dir/preflight.headers" \
  || die "allowed CORS origin was not echoed"
grep -Fqi 'access-control-allow-credentials: true' "$tmp_dir/preflight.headers" \
  || die "CORS credentials header is missing"
grep -Eqi '^access-control-allow-headers:.*content-type' "$tmp_dir/preflight.headers" \
  || die "CORS content-type header is missing"

http_request 400 "$tmp_dir/rejected-origin.body" "$tmp_dir/rejected-origin.headers" \
  --request OPTIONS \
  --header 'Origin: https://evil.invalid' \
  --header 'Access-Control-Request-Method: POST' \
  "$api_url/api/v1/auth/login"
if grep -Fqi 'access-control-allow-origin:' "$tmp_dir/rejected-origin.headers"; then
  die "rejected CORS origin received an allow-origin header"
fi

cookie_jar="$tmp_dir/cookies"
http_request 201 "$tmp_dir/register-response.json" "$tmp_dir/register.headers" \
  --cookie-jar "$cookie_jar" \
  --header 'Content-Type: application/json' \
  --data-binary "@$credentials_file" \
  "$api_proxy/auth/register"
grep -Eqi '^set-cookie:[[:space:]]*kaogong_session=' "$tmp_dir/register.headers" \
  || die "session cookie is missing"
for attribute in 'Path=/' 'Max-Age=604800' 'HttpOnly' 'Secure' 'SameSite=lax'; do
  grep -Fqi "$attribute" "$tmp_dir/register.headers" \
    || die "session cookie attribute is missing"
done
if grep -Eqi '^set-cookie:.*;[[:space:]]*Domain=' "$tmp_dir/register.headers"; then
  die "session cookie must remain host-only"
fi

python3 - "$cookie_jar" "$web_url" <<'PY'
import sys
import time
from urllib.parse import urlsplit

cookie_path, web_url = sys.argv[1:]
expected_host = urlsplit(web_url).hostname
found = False
with open(cookie_path, encoding="utf-8") as source:
    for raw_line in source:
        line = raw_line.rstrip("\n")
        if line.startswith("#HttpOnly_"):
            line = line.removeprefix("#HttpOnly_")
        elif not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7 or fields[5] != "kaogong_session":
            continue
        domain, _include_subdomains, path, secure, expires, _name, value = fields
        if domain.lstrip(".") != expected_host or path != "/" or secure != "TRUE":
            raise SystemExit("session cookie is not first-party, secure, and root-scoped")
        if int(expires) <= int(time.time()) or not value:
            raise SystemExit("session cookie is empty or expired")
        found = True
if not found:
    raise SystemExit("session cookie was not stored in the cookie jar")
PY

canonical_email=$(json_field "$tmp_dir/register-response.json" email)
http_request 200 "$tmp_dir/me.json" "$tmp_dir/me.headers" \
  --cookie "$cookie_jar" "$api_proxy/auth/me"
python3 - "$tmp_dir/me.json" "$canonical_email" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("email") != sys.argv[2]:
    raise SystemExit("authenticated email mismatch")
PY

http_request 415 "$tmp_dir/wrong-mime.json" "$tmp_dir/wrong-mime.headers" \
  --cookie "$cookie_jar" \
  --form "file=@$wrong_file;type=text/plain" \
  "$api_proxy/uploads/questions"
http_request 413 "$tmp_dir/oversize.json" "$tmp_dir/oversize.headers" \
  --cookie "$cookie_jar" \
  --form "file=@$oversize_file;type=image/png" \
  "$api_proxy/uploads/questions"

http_request 201 "$tmp_dir/upload.json" "$tmp_dir/upload.headers" \
  --cookie "$cookie_jar" \
  --form "file=@$image_path;type=$image_mime" \
  "$api_proxy/uploads/questions"
upload_id=$(json_field "$tmp_dir/upload.json" id)
assert_uuid "$upload_id"
http_request 200 "$tmp_dir/uploaded-image" "$tmp_dir/upload-download.headers" \
  --cookie "$cookie_jar" "$api_proxy/uploads/$upload_id"
cmp -s "$image_path" "$tmp_dir/uploaded-image" || die "downloaded upload differs from source"

printf '{"upload_id":"%s"}' "$upload_id" >"$tmp_dir/ocr-request.json"
http_request 200 "$tmp_dir/ocr.json" "$tmp_dir/ocr.headers" \
  --cookie "$cookie_jar" \
  --header 'Content-Type: application/json' \
  --data-binary "@$tmp_dir/ocr-request.json" \
  "$api_proxy/ocr"
python3 - "$tmp_dir/ocr.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("is_demo") is not True:
    raise SystemExit("OCR did not use the demo provider")
for key in ("stem", "options", "correct_answer", "original_explanation", "raw_text"):
    if not payload.get(key):
        raise SystemExit(f"OCR field is empty: {key}")
PY

python3 - "$tmp_dir/ocr.json" "$tmp_dir/question.json" "$upload_id" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    ocr = json.load(source)
payload = {
    "exam_type": "国考",
    "module": "言语理解",
    "stem": ocr["stem"] + "（Railway production smoke）",
    "options": ocr["options"],
    "user_answer": ocr["user_answer"] or "A",
    "correct_answer": ocr["correct_answer"],
    "original_explanation": ocr["original_explanation"],
    "source": "Railway production smoke",
    "notes": "正式环境自动化验收",
    "image_path": f"/uploads/{sys.argv[3]}",
    "ocr_raw_text": ocr["raw_text"],
    "knowledge_points": [],
    "mastery_status": "未掌握",
    "analysis_status": "未分析",
    "tags": ["railway-smoke"],
}
with open(sys.argv[2], "w", encoding="utf-8") as target:
    json.dump(payload, target, ensure_ascii=False)
PY

http_request 201 "$tmp_dir/created-question.json" "$tmp_dir/created-question.headers" \
  --cookie "$cookie_jar" \
  --header 'Content-Type: application/json' \
  --data-binary "@$tmp_dir/question.json" \
  "$api_proxy/questions"
question_id=$(json_field "$tmp_dir/created-question.json" id)
assert_uuid "$question_id"

http_request 200 "$tmp_dir/analysis.json" "$tmp_dir/analysis.headers" \
  --request POST --cookie "$cookie_jar" \
  "$api_proxy/questions/$question_id/analyze"
python3 - "$tmp_dir/analysis.json" "$question_id" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("question_id") != sys.argv[2] or payload.get("is_demo") is not True:
    raise SystemExit("analysis identity or demo marker mismatch")
if payload.get("provider_name") != "demo":
    raise SystemExit("analysis did not use the demo provider")
for key in ("cause_analysis", "knowledge_points", "correct_approach", "study_advice"):
    if not payload.get(key):
        raise SystemExit(f"analysis field is empty: {key}")
PY

printf '%s' '{"result_status":"复习中","review_note":"Railway 正式环境 smoke"}' \
  >"$tmp_dir/review-request.json"
http_request 201 "$tmp_dir/review.json" "$tmp_dir/review.headers" \
  --request POST --cookie "$cookie_jar" \
  --header 'Content-Type: application/json' \
  --data-binary "@$tmp_dir/review-request.json" \
  "$api_proxy/reviews/$question_id"
python3 - "$tmp_dir/review.json" "$question_id" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("question_id") != sys.argv[2] or payload.get("result_status") != "复习中":
    raise SystemExit("review response mismatch")
PY

http_request 200 "$tmp_dir/question-after-review.json" "$tmp_dir/question-after-review.headers" \
  --cookie "$cookie_jar" "$api_proxy/questions/$question_id"
python3 - "$tmp_dir/question-after-review.json" "$question_id" "$upload_id" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("id") != sys.argv[2]:
    raise SystemExit("question identity mismatch")
if payload.get("image_path") != f"/uploads/{sys.argv[3]}":
    raise SystemExit("question upload reference mismatch")
if payload.get("analysis_status") != "已完成" or payload.get("mastery_status") != "复习中":
    raise SystemExit("question analysis or mastery state mismatch")
analysis = payload.get("current_analysis") or {}
if analysis.get("is_demo") is not True or analysis.get("provider_name") != "demo":
    raise SystemExit("persisted analysis marker mismatch")
PY

http_request 200 "$tmp_dir/review-history.json" "$tmp_dir/review-history.headers" \
  --cookie "$cookie_jar" "$api_proxy/reviews/questions/$question_id"
python3 - "$tmp_dir/review-history.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("total", 0) < 1:
    raise SystemExit("review history is empty")
if not any(item.get("result_status") == "复习中" for item in payload.get("items", [])):
    raise SystemExit("review history does not contain the submitted state")
PY

http_request 200 "$tmp_dir/dashboard.json" "$tmp_dir/dashboard.headers" \
  --cookie "$cookie_jar" "$api_proxy/dashboard"
python3 - "$tmp_dir/dashboard.json" "$question_id" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("provider_mode") != "demo":
    raise SystemExit("dashboard provider mode mismatch")
if not any(item.get("id") == sys.argv[2] for item in payload.get("recent_questions", [])):
    raise SystemExit("dashboard recent questions omit the smoke question")
today = payload.get("today_review") or {}
if today.get("completed_count", 0) < 1:
    raise SystemExit("dashboard review completion was not recorded")
PY

http_request 200 "$tmp_dir/analytics.json" "$tmp_dir/analytics.headers" \
  --cookie "$cookie_jar" "$api_proxy/analytics/summary"
python3 - "$tmp_dir/analytics.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("total_questions", 0) < 1 or payload.get("is_demo") is not True:
    raise SystemExit("analytics summary mismatch")
PY

other_email="other-$(date +%s)-$$@example.com"
other_credentials="$tmp_dir/other-credentials.json"
python3 - "$other_credentials" "$other_email" "$password_file" <<'PY'
import json
import sys

output, email, password_path = sys.argv[1:]
with open(password_path, encoding="utf-8") as source:
    password = source.read()
with open(output, "w", encoding="utf-8") as target:
    json.dump({"email": email, "password": password}, target)
PY

other_cookie_jar="$tmp_dir/other-cookies"
http_request 201 "$tmp_dir/other-register.json" "$tmp_dir/other-register.headers" \
  --cookie-jar "$other_cookie_jar" \
  --header 'Content-Type: application/json' \
  --data-binary "@$other_credentials" \
  "$api_proxy/auth/register"
http_request 404 "$tmp_dir/question-isolation.json" "$tmp_dir/question-isolation.headers" \
  --cookie "$other_cookie_jar" "$api_proxy/questions/$question_id"
http_request 404 "$tmp_dir/upload-isolation.json" "$tmp_dir/upload-isolation.headers" \
  --cookie "$other_cookie_jar" "$api_proxy/uploads/$upload_id"

http_request 204 "$tmp_dir/logout.body" "$tmp_dir/logout.headers" \
  --request POST --cookie "$cookie_jar" --cookie-jar "$cookie_jar" \
  "$api_proxy/auth/logout"
http_request 401 "$tmp_dir/logged-out-me.json" "$tmp_dir/logged-out-me.headers" \
  --cookie "$cookie_jar" "$api_proxy/auth/me"

http_request 200 "$tmp_dir/login-response.json" "$tmp_dir/login-response.headers" \
  --cookie-jar "$cookie_jar" \
  --header 'Content-Type: application/json' \
  --data-binary "@$credentials_file" \
  "$api_proxy/auth/login"
http_request 200 "$tmp_dir/persisted-question.json" "$tmp_dir/persisted-question.headers" \
  --cookie "$cookie_jar" "$api_proxy/questions/$question_id"
http_request 200 "$tmp_dir/persisted-reviews.json" "$tmp_dir/persisted-reviews.headers" \
  --cookie "$cookie_jar" "$api_proxy/reviews/questions/$question_id"
http_request 200 "$tmp_dir/persisted-upload" "$tmp_dir/persisted-upload.headers" \
  --cookie "$cookie_jar" "$api_proxy/uploads/$upload_id"
cmp -s "$image_path" "$tmp_dir/persisted-upload" || die "persisted upload differs from source"
python3 - "$tmp_dir/persisted-question.json" "$tmp_dir/persisted-reviews.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    question = json.load(source)
with open(sys.argv[2], encoding="utf-8") as source:
    reviews = json.load(source)
analysis = question.get("current_analysis") or {}
if question.get("analysis_status") != "已完成" or question.get("mastery_status") != "复习中":
    raise SystemExit("question state did not persist across login")
if analysis.get("is_demo") is not True:
    raise SystemExit("analysis did not persist across login")
if reviews.get("total", 0) < 1:
    raise SystemExit("review history did not persist across login")
PY

python3 - "$tmp_dir" "$password_file" "$credentials_file" "$other_credentials" <<'PY'
import os
import re
import sys

root = sys.argv[1]
skip = {os.path.realpath(path) for path in sys.argv[2:]}
pattern = re.compile(r"railway\.internal|postgres(?:ql)?(?:\+[^:]*)?://", re.IGNORECASE)
for directory, _subdirectories, filenames in os.walk(root):
    for filename in filenames:
        path = os.path.join(directory, filename)
        if os.path.realpath(path) in skip:
            continue
        try:
            with open(path, encoding="utf-8") as source:
                content = source.read()
        except (OSError, UnicodeError):
            continue
        if pattern.search(content):
            raise SystemExit("a response exposed an internal service or database URL")
PY

python3 - "$state_tmp" "$canonical_email" "$upload_id" "$question_id" <<'PY'
import json
import sys

payload = {
    "email": sys.argv[2],
    "upload_id": sys.argv[3],
    "question_id": sys.argv[4],
}
with open(sys.argv[1], "w", encoding="utf-8") as target:
    json.dump(payload, target, ensure_ascii=False, sort_keys=True)
    target.write("\n")
PY
chmod 600 "$state_tmp"
mv -f -- "$state_tmp" "$state_file"
state_tmp=""
chmod 600 "$state_file"
python3 - "$state_file" <<'PY'
import json
import os
import stat
import sys
import uuid

path = sys.argv[1]
if stat.S_IMODE(os.lstat(path).st_mode) != 0o600 or os.path.islink(path):
    raise SystemExit("state file mode or type is unsafe")
with open(path, encoding="utf-8") as source:
    payload = json.load(source)
if set(payload) != {"email", "upload_id", "question_id"}:
    raise SystemExit("state file contains unexpected fields")
for key in ("upload_id", "question_id"):
    if str(uuid.UUID(payload[key])) != payload[key]:
        raise SystemExit(f"state file {key} is not a canonical UUID")
PY
state_written=1

printf 'production smoke passed; state=%s\n' "$state_file"
