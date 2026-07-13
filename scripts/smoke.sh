#!/usr/bin/env bash
set -euo pipefail

api_url=${API_URL:-http://localhost:8000}
web_url=${WEB_URL:-http://localhost:3000}
cookie_jar=$(mktemp)
trap 'rm -f "$cookie_jar"' EXIT

curl --fail --silent --show-error "$api_url/health" | grep -q '"status":"ok"'
curl --fail --silent --show-error "$web_url/login" | grep -q '登录'
curl --fail --silent --show-error \
  --cookie-jar "$cookie_jar" \
  --header 'Content-Type: application/json' \
  --header 'Origin: http://localhost:3000' \
  --data '{"email":"demo@example.com","password":"demo-pass-123"}' \
  "$api_url/api/v1/auth/login" | grep -q '"email":"demo@example.com"'
curl --fail --silent --show-error \
  --cookie "$cookie_jar" \
  "$api_url/api/v1/auth/me" | grep -q '"email":"demo@example.com"'
curl --fail --silent --show-error \
  --cookie "$cookie_jar" \
  "$api_url/api/v1/dashboard" | grep -q '"today_review"'

printf 'smoke checks passed\n'
