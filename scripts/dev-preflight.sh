#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  printf 'Docker is required. Install Docker Desktop or Docker Engine first.\n' >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  printf 'Docker Compose v2 is required. Install the docker-compose-plugin, then retry.\n' >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  printf 'Docker is installed, but its daemon is not reachable. Start Docker and retry.\n' >&2
  exit 1
fi

for port in 3000 8000 5432; do
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    printf 'Port %s is already in use. Stop that process or the conflicting container first.\n' "$port" >&2
    exit 1
  fi
done

printf 'Development preflight passed.\n'
