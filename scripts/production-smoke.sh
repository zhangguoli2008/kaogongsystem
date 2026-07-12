#!/usr/bin/env bash
set +x
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
else
  state_file=$(mktemp "${TMPDIR:-/tmp}/kaogong-smoke-state.XXXXXX")
  state_created=1
fi

state_file=$(python3 - "$state_file" <<'PY'
import os
import stat
import sys

path = os.path.abspath(sys.argv[1])
if os.path.lexists(path) and stat.S_ISLNK(os.lstat(path).st_mode):
    raise SystemExit("SMOKE_STATE_FILE must not be a symlink")
parent = os.path.realpath(os.path.dirname(path))
if not os.path.isdir(parent):
    raise SystemExit("SMOKE_STATE_FILE parent must be a directory")
print(os.path.join(parent, os.path.basename(path)))
PY
)

state_tmp=""
state_tmp_guard=""
state_guard=""
tmp_dir=""

guarded_unlink() {
  local path=$1
  local guard=$2
  python3 - "$path" "$guard" <<'PY'
import os
import stat
import sys

path, guard = sys.argv[1:]
parent, name = os.path.dirname(path), os.path.basename(path)
expected_parent_dev, expected_parent_ino, expected_dev, expected_ino = map(
    int, guard.split(":")
)
flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
directory = os.open(parent, flags)
try:
    parent_status = os.fstat(directory)
    if (parent_status.st_dev, parent_status.st_ino) != (
        expected_parent_dev,
        expected_parent_ino,
    ):
        raise SystemExit("guarded unlink parent changed")
    status = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != os.geteuid()
        or status.st_nlink != 1
        or (status.st_dev, status.st_ino) != (expected_dev, expected_ino)
    ):
        raise SystemExit("guarded unlink target changed")
    os.unlink(name, dir_fd=directory)
finally:
    os.close(directory)
PY
}

cleanup() {
  local exit_code=$?
  trap - EXIT
  if [[ -n ${state_tmp:-} && -n ${state_tmp_guard:-} ]]; then
    guarded_unlink "$state_tmp" "$state_tmp_guard" >/dev/null 2>&1 || true
  fi
  [[ -n ${tmp_dir:-} && -d ${tmp_dir:-} ]] && rm -rf -- "$tmp_dir"
  if [[ "$state_written" = 0 && -n ${state_tmp_guard:-} ]]; then
    guarded_unlink "$state_file" "$state_tmp_guard" >/dev/null 2>&1 || true
  fi
  if [[ "$state_created" = 1 && "$state_written" = 0 && -n ${state_guard:-} ]]; then
    guarded_unlink "$state_file" "$state_guard" >/dev/null 2>&1 || true
  fi
  exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

state_dir=$(dirname "$state_file")
state_name=$(basename "$state_file")
[[ -d "$state_dir" && -w "$state_dir" ]] || die "SMOKE_STATE_FILE parent must be writable"
read -r reserved_state state_guard < <(
  python3 - "$state_dir" "$state_name" "$state_created" <<'PY'
import os
import stat
import sys

parent, name, created_hint = sys.argv[1:]
flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
directory = os.open(parent, flags)
try:
    parent_status = os.fstat(directory)
    try:
        status = os.stat(name, dir_fd=directory, follow_symlinks=False)
        reserved = int(created_hint)
    except FileNotFoundError:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory,
        )
        try:
            status = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        reserved = 1
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != os.geteuid()
        or status.st_nlink != 1
        or status.st_size != 0
        or stat.S_IMODE(status.st_mode) != 0o600
    ):
        raise SystemExit(
            "SMOKE_STATE_FILE must be missing or an owned, empty, mode-0600 regular file"
        )
    guard = ":".join(
        str(value)
        for value in (
            parent_status.st_dev,
            parent_status.st_ino,
            status.st_dev,
            status.st_ino,
        )
    )
    print(reserved, guard)
finally:
    os.close(directory)
PY
)
state_created=$reserved_state
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/kaogong-production-smoke.XXXXXX")
state_tmp=$(mktemp "$state_dir/.${state_name}.tmp.XXXXXX")
state_tmp_guard=$(python3 - "$state_tmp" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
parent = os.path.dirname(path)
directory = os.open(
    parent,
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
)
try:
    parent_status = os.fstat(directory)
    status = os.stat(os.path.basename(path), dir_fd=directory, follow_symlinks=False)
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != os.geteuid()
        or status.st_nlink != 1
        or status.st_size != 0
        or stat.S_IMODE(status.st_mode) != 0o600
    ):
        raise SystemExit("state temporary file is unsafe")
    print(
        ":".join(
            str(value)
            for value in (
                parent_status.st_dev,
                parent_status.st_ino,
                status.st_dev,
                status.st_ino,
            )
        )
    )
finally:
    os.close(directory)
PY
)

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

assert_api_error() {
  python3 - "$1" "$2" "$3" <<'PY'
import json
import sys

body_path, header_path, expected_code = sys.argv[1:]
with open(body_path, encoding="utf-8") as source:
    payload = json.load(source)
if not isinstance(payload, dict) or set(payload) != {
    "code",
    "message",
    "field_errors",
    "request_id",
}:
    raise SystemExit("API error response shape mismatch")
if payload["code"] != expected_code:
    raise SystemExit("API error code mismatch")
if not isinstance(payload["message"], str) or not payload["message"]:
    raise SystemExit("API error message is missing")
if payload["field_errors"] is not None:
    raise SystemExit("unexpected API field errors")
if not isinstance(payload["request_id"], str) or not payload["request_id"]:
    raise SystemExit("API request ID is missing")

headers = {}
with open(header_path, encoding="iso-8859-1") as source:
    for raw_line in source:
        if ":" not in raw_line:
            continue
        name, value = raw_line.split(":", 1)
        headers.setdefault(name.strip().lower(), []).append(value.strip())
content_types = headers.get("content-type", [])
if len(content_types) != 1 or not content_types[0].lower().startswith("application/json"):
    raise SystemExit("API error content type mismatch")
request_ids = headers.get("x-request-id", [])
if request_ids != [payload["request_id"]]:
    raise SystemExit("API request ID header mismatch")
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
python3 - "$tmp_dir/register.headers" <<'PY'
import sys

session_cookies = []
with open(sys.argv[1], encoding="iso-8859-1") as source:
    for raw_line in source:
        if ":" not in raw_line:
            continue
        header, value = raw_line.split(":", 1)
        if header.strip().lower() != "set-cookie":
            continue
        value = value.strip()
        cookie_pair = value.split(";", 1)[0]
        if "=" not in cookie_pair:
            continue
        name, _cookie_value = cookie_pair.split("=", 1)
        if name.strip() == "kaogong_session":
            session_cookies.append(value)
if len(session_cookies) != 1:
    raise SystemExit("expected exactly one session Set-Cookie header")

parts = [part.strip() for part in session_cookies[0].split(";")]
attributes = {}
flags = set()
for part in parts[1:]:
    if "=" in part:
        name, value = part.split("=", 1)
        attributes[name.strip().lower()] = value.strip()
    else:
        flags.add(part.lower())
if attributes.get("path") != "/":
    raise SystemExit("session cookie Path mismatch")
if attributes.get("max-age") != "604800":
    raise SystemExit("session cookie Max-Age mismatch")
if attributes.get("samesite", "").lower() != "lax":
    raise SystemExit("session cookie SameSite mismatch")
if "secure" not in flags or "httponly" not in flags:
    raise SystemExit("session cookie security flags are missing")
if "domain" in attributes:
    raise SystemExit("session cookie must remain host-only")
PY

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
        domain, include_subdomains, path, secure, expires, _name, value = fields
        if (
            domain != expected_host
            or domain.startswith(".")
            or include_subdomains != "FALSE"
            or path != "/"
            or secure != "TRUE"
        ):
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

redirect_status=$(curl "${curl_common[@]}" \
  --path-as-is \
  --dump-header "$tmp_dir/proxy-redirect.headers" \
  --output "$tmp_dir/proxy-redirect.body" \
  --write-out '%{http_code}' \
  --cookie "$cookie_jar" \
  "$api_proxy/questions/") || die "proxy redirect transport failed"
case "$redirect_status" in
  307|308) ;;
  *) die "proxy trailing-slash redirect did not return HTTP 307 or 308" ;;
esac
python3 - "$tmp_dir/proxy-redirect.headers" "$web_url" <<'PY'
import sys
from urllib.parse import urljoin, urlsplit

headers = []
with open(sys.argv[1], encoding="iso-8859-1") as source:
    for raw_line in source:
        if ":" not in raw_line:
            continue
        name, value = raw_line.split(":", 1)
        if name.strip().lower() == "location":
            headers.append(value.strip())
if len(headers) != 1:
    raise SystemExit("expected exactly one proxy redirect Location")
location = headers[0]
resolved = urlsplit(urljoin(sys.argv[2] + "/", location))
expected = urlsplit(sys.argv[2])
if (
    resolved.scheme != "https"
    or resolved.hostname != expected.hostname
    or resolved.port is not None
    or resolved.username
    or resolved.password
    or resolved.path != "/api/v1/questions"
    or resolved.query
    or resolved.fragment
):
    raise SystemExit("proxy redirect escaped the public Web API origin")
PY

http_request 415 "$tmp_dir/wrong-mime.json" "$tmp_dir/wrong-mime.headers" \
  --cookie "$cookie_jar" \
  --form "file=@$wrong_file;type=text/plain" \
  "$api_proxy/uploads/questions"
assert_api_error \
  "$tmp_dir/wrong-mime.json" "$tmp_dir/wrong-mime.headers" unsupported_image_type
http_request 413 "$tmp_dir/oversize.json" "$tmp_dir/oversize.headers" \
  --cookie "$cookie_jar" \
  --form "file=@$oversize_file;type=image/png" \
  "$api_proxy/uploads/questions"
assert_api_error \
  "$tmp_dir/oversize.json" "$tmp_dir/oversize.headers" upload_too_large

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
python3 - "$tmp_dir/review-history.json" "$question_id" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
items = payload.get("items")
if (
    payload.get("page") != 1
    or payload.get("page_size") != 20
    or payload.get("total") != 1
    or not isinstance(items, list)
    or len(items) != 1
):
    raise SystemExit("review history count or pagination mismatch")
item = items[0]
if (
    item.get("question_id") != sys.argv[2]
    or item.get("result_status") != "复习中"
    or item.get("review_note") != "Railway 正式环境 smoke"
):
    raise SystemExit("review history does not match the submitted review")
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
recent = payload.get("recent_questions")
completed = today.get("completed")
if (
    payload.get("current_question") is not None
    or not isinstance(recent, list)
    or len(recent) != 1
    or recent[0].get("id") != sys.argv[2]
):
    raise SystemExit("dashboard fresh-account question count mismatch")
if (
    today.get("daily_review_limit") != 20
    or today.get("pending") != []
    or today.get("completed_count") != 1
    or today.get("total") != 1
    or not isinstance(completed, list)
    or len(completed) != 1
    or completed[0].get("question_id") != sys.argv[2]
    or completed[0].get("result_status") != "复习中"
):
    raise SystemExit("dashboard review completion count mismatch")
PY

http_request 200 "$tmp_dir/analytics.json" "$tmp_dir/analytics.headers" \
  --cookie "$cookie_jar" "$api_proxy/analytics/summary"
python3 - "$tmp_dir/analytics.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("total_questions") != 1 or payload.get("is_demo") is not True:
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
assert_api_error \
  "$tmp_dir/question-isolation.json" "$tmp_dir/question-isolation.headers" not_found
http_request 404 "$tmp_dir/upload-isolation.json" "$tmp_dir/upload-isolation.headers" \
  --cookie "$other_cookie_jar" "$api_proxy/uploads/$upload_id"
assert_api_error \
  "$tmp_dir/upload-isolation.json" "$tmp_dir/upload-isolation.headers" not_found

http_request 204 "$tmp_dir/logout.body" "$tmp_dir/logout.headers" \
  --request POST --cookie "$cookie_jar" --cookie-jar "$cookie_jar" \
  "$api_proxy/auth/logout"
http_request 401 "$tmp_dir/logged-out-me.json" "$tmp_dir/logged-out-me.headers" \
  --cookie "$cookie_jar" "$api_proxy/auth/me"
assert_api_error \
  "$tmp_dir/logged-out-me.json" "$tmp_dir/logged-out-me.headers" invalid_session

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
items = reviews.get("items")
if reviews.get("total") != 1 or not isinstance(items, list) or len(items) != 1:
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

python3 - \
  "$state_dir" "$state_name" "$(basename "$state_tmp")" \
  "$state_guard" "$state_tmp_guard" \
  "$canonical_email" "$upload_id" "$question_id" <<'PY'
import json
import os
import stat
import sys
import uuid

payload = {
    "email": sys.argv[6],
    "upload_id": sys.argv[7],
    "question_id": sys.argv[8],
}
for key in ("upload_id", "question_id"):
    if str(uuid.UUID(payload[key])) != payload[key]:
        raise SystemExit(f"state file {key} is not a canonical UUID")

parent, destination, temporary = sys.argv[1:4]
destination_guard = tuple(map(int, sys.argv[4].split(":")))
temporary_guard = tuple(map(int, sys.argv[5].split(":")))
flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
directory = os.open(parent, flags)


def checked_status(name: str, guard: tuple[int, int, int, int], *, empty: bool):
    parent_status = os.fstat(directory)
    if (parent_status.st_dev, parent_status.st_ino) != guard[:2]:
        raise SystemExit("state file parent changed")
    status = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != os.geteuid()
        or status.st_nlink != 1
        or stat.S_IMODE(status.st_mode) != 0o600
        or (status.st_dev, status.st_ino) != guard[2:]
        or (empty and status.st_size != 0)
    ):
        raise SystemExit("state file identity or permissions changed")
    return status


try:
    checked_status(destination, destination_guard, empty=True)
    checked_status(temporary, temporary_guard, empty=True)

    descriptor = os.open(
        temporary,
        os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory,
    )
    try:
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != os.geteuid()
            or status.st_nlink != 1
            or stat.S_IMODE(status.st_mode) != 0o600
            or (status.st_dev, status.st_ino) != temporary_guard[2:]
        ):
            raise SystemExit("state temporary file changed before write")
        os.ftruncate(descriptor, 0)
        serialized = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        view = memoryview(serialized)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SystemExit("state file write was incomplete")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

    checked_status(temporary, temporary_guard, empty=False)
    checked_status(destination, destination_guard, empty=True)
    os.replace(
        temporary,
        destination,
        src_dir_fd=directory,
        dst_dir_fd=directory,
    )
    os.fsync(directory)

    final_descriptor = os.open(
        destination,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory,
    )
    try:
        final_status = os.fstat(final_descriptor)
        if (
            not stat.S_ISREG(final_status.st_mode)
            or final_status.st_uid != os.geteuid()
            or final_status.st_nlink != 1
            or stat.S_IMODE(final_status.st_mode) != 0o600
            or (final_status.st_dev, final_status.st_ino) != temporary_guard[2:]
        ):
            raise SystemExit("published state file is unsafe")
        with os.fdopen(os.dup(final_descriptor), encoding="utf-8") as source:
            actual = json.load(source)
    finally:
        os.close(final_descriptor)

    published = os.stat(destination, dir_fd=directory, follow_symlinks=False)
    if (published.st_dev, published.st_ino) != temporary_guard[2:]:
        raise SystemExit("published state file changed during validation")
finally:
    os.close(directory)

if actual != payload or set(actual) != {"email", "upload_id", "question_id"}:
    raise SystemExit("state file contains unexpected fields")
PY
state_tmp=""
state_written=1

printf 'production smoke passed; state=%s\n' "$state_file"
