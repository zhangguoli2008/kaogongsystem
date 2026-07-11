# Railway Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing AI 公考错题诊断系统 for production, deploy its Web/API/PostgreSQL/upload-volume stack to Railway through direct CLI uploads, and prove the complete demo-AI workflow and persistence in Chrome.

**Architecture:** Keep Next.js, FastAPI, PostgreSQL, Alembic, and the POSIX upload volume. The browser talks only to the Railway Web origin at `/api/v1`; a Next.js catch-all handler streams requests to the FastAPI service over Railway private networking, so the existing Secure/HttpOnly/SameSite=Lax session cookie remains first-party. FastAPI runs as one replica, migrates in Railway's pre-deploy phase, verifies PostgreSQL and upload-volume readiness, and explicitly uses the deterministic demo provider.

**Tech Stack:** Next.js 16.2, React 19, TypeScript 5, Vitest 4, FastAPI, Pydantic Settings, SQLAlchemy async, Alembic, PostgreSQL 17, Python 3.12, Docker, Bash/curl, Railway CLI 5.26.0, Chrome.

## Global Constraints

- Work only in `/Users/zhangguoli/Documents/Code/kaogongsystem/.worktrees/ai-exam-system` on `codex/ai-exam-system`.
- Do not stop, remove, seed, migrate, or alter the user's existing local Docker stack, local PostgreSQL volume, or local uploads.
- Use TDD for application behavior: add one focused failing test, observe the intended failure, add the minimum implementation, then run the focused and affected suites.
- Railway production must use `APP_ENV=production`, `PROVIDER_MODE=demo`, no `OPENAI_API_KEY`, a random secret of at least 32 bytes, Secure/HttpOnly/SameSite=Lax cookies, and exact HTTPS origins.
- Browser requests must remain same-origin at the Web hostname; never switch production cookies to `SameSite=None`.
- API must run one replica on `PORT=8000`; `/data/uploads` must be a required persistent mount; Web reaches API through `http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000`.
- Do not write secrets, test passwords, Railway tokens, database credentials, or raw variable dumps to Git, command output, screenshots, or QA documents.
- Never run `python -m app.seed` in Railway production.
- Stop for user input only when Railway OAuth/device verification is required, a plan/payment upgrade is requested, or an existing external resource would be overwritten.
- Use only the user's Chrome for browser validation; do not substitute Playwright or another browser.
- A successful build or health response alone is not completion: remote workflow, restart persistence, cookie/CORS/host checks, migration revision, and visual QA all need direct evidence.

## File Responsibility Map

- `apps/api/app/core/config.py`: environment model and fail-closed production startup validation.
- `apps/api/app/core/database.py`: Railway/PostgreSQL URL normalization and async session creation.
- `apps/api/app/core/readiness.py`: non-destructive PostgreSQL and upload-volume readiness probes.
- `apps/api/app/main.py`: startup validation, trusted hosts, liveness, and readiness endpoints.
- `apps/api/app/entrypoint.py`: Railway port selection, upload-volume ownership bootstrap, privilege drop, and Uvicorn launch.
- `apps/api/railway.json`: API Docker build, one replica, required mount, pre-deploy migration, healthcheck, and restart contract.
- `apps/web/src/lib/api-proxy.ts`: same-origin streaming proxy to Railway private API.
- `apps/web/src/app/api/v1/[...path]/route.ts`: Next.js method exports for the proxy.
- `apps/web/src/app/health/route.ts`: Web deployment health endpoint.
- `apps/web/railway.json`: Web Docker build, one replica, healthcheck, and restart contract.
- `scripts/production-smoke.sh`: remote API/proxy/cookie/CORS/upload/OCR/analysis/review/statistics/isolation smoke test.
- `docs/deployment/railway.md`: reproducible provisioning, deployment, rollback, secret-handling, and verification runbook.
- `docs/qa/railway-production-audit.md`: final public URLs, commit/revision, evidence, restart result, Chrome QA, and known limitations without secrets.

---

### Task 1: Fail-closed production configuration and Railway database URLs

**Files:**
- Create: `apps/api/tests/test_config.py`
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/app/core/database.py`
- Modify: `apps/api/alembic/env.py`
- Modify: `apps/api/app/main.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `Settings.validate_for_startup() -> None`.
- Produces: `normalize_database_url(database_url: str) -> str`.
- Preserves: `Settings.effective_provider_mode -> Literal["live", "demo"]`.
- Consumers: Alembic and `create_session_factory()` both use `normalize_database_url`.

- [ ] **Step 1: Write failing production-contract tests**

Create `apps/api/tests/test_config.py` with these focused tests:

```python
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.database import normalize_database_url
from app.main import create_app


def production_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql://user:pass@postgres.railway.internal:5432/kaogong",
        "jwt_secret": "a" * 64,
        "provider_mode": "demo",
        "openai_api_key": None,
        "upload_dir": Path("/data/uploads"),
        "allowed_origins": ["https://web-production.example.up.railway.app"],
        "allowed_hosts": [
            "api-production.example.up.railway.app",
            "api.railway.internal",
            "healthcheck.railway.app",
        ],
        "cookie_secure": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_explicit_demo_production_configuration_is_accepted(tmp_path: Path) -> None:
    app = create_app(production_settings(tmp_path))
    assert app.state.settings.effective_provider_mode == "demo"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"jwt_secret": "short"}, "JWT_SECRET"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"provider_mode": "auto"}, "PROVIDER_MODE"),
        ({"openai_api_key": "must-not-be-stored"}, "OPENAI_API_KEY"),
        ({"database_url": "sqlite+aiosqlite:///tmp/prod.db"}, "DATABASE_URL"),
        ({"database_url": "postgresql://user:pass@localhost/db"}, "DATABASE_URL"),
        ({"allowed_origins": ["http://localhost:3000"]}, "ALLOWED_ORIGINS"),
        ({"allowed_hosts": ["*"]}, "ALLOWED_HOSTS"),
        ({"upload_dir": Path("/tmp/uploads")}, "UPLOAD_DIR"),
    ],
)
def test_production_configuration_rejects_unsafe_values(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        create_app(production_settings(tmp_path, **overrides))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "postgresql://user:pass@postgres.railway.internal:5432/kaogong",
            "postgresql+psycopg://user:pass@postgres.railway.internal:5432/kaogong",
        ),
        (
            "postgres://user:pass@postgres.railway.internal:5432/kaogong",
            "postgresql+psycopg://user:pass@postgres.railway.internal:5432/kaogong",
        ),
        (
            "postgresql+psycopg://user:pass@postgres.railway.internal:5432/kaogong",
            "postgresql+psycopg://user:pass@postgres.railway.internal:5432/kaogong",
        ),
        ("sqlite+aiosqlite:///tmp/test.db", "sqlite+aiosqlite:///tmp/test.db"),
    ],
)
def test_database_url_normalization(source: str, expected: str) -> None:
    assert normalize_database_url(source) == expected
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
cd apps/api
uv run pytest tests/test_config.py -q
```

Expected: collection/import fails because `normalize_database_url` does not exist, and no production configuration contract exists yet.

- [ ] **Step 3: Implement the minimum production contract**

In `apps/api/app/core/config.py`:

```python
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

AppEnvironment = Literal["development", "test", "production"]
DEFAULT_DATABASE_URL = "postgresql+psycopg://kaogong:kaogong@db:5432/kaogong"
DEFAULT_JWT_SECRET = "development-secret-change-in-production"


class Settings(BaseSettings):
    app_env: AppEnvironment = "development"
    database_url: str = DEFAULT_DATABASE_URL
    jwt_secret: str = DEFAULT_JWT_SECRET
    provider_mode: Literal["auto", "live", "demo"] = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"
    upload_dir: Path = Path("/data/uploads")
    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_origins: list[str] = ["http://localhost:3000"]
    allowed_hosts: list[str] = ["*"]
    cookie_secure: bool = False
    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

    def validate_for_startup(self) -> None:
        _ = self.effective_provider_mode
        if self.app_env != "production":
            return

        errors: list[str] = []
        if len(self.jwt_secret.encode("utf-8")) < 32 or self.jwt_secret == DEFAULT_JWT_SECRET:
            errors.append("JWT_SECRET must be a non-default value of at least 32 bytes")
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true")
        if self.provider_mode == "auto":
            errors.append("PROVIDER_MODE must be explicit in production")
        if self.provider_mode == "demo" and self.openai_api_key:
            errors.append("OPENAI_API_KEY must be unset in demo production")

        try:
            database = make_url(self.database_url)
            database_is_remote_postgres = (
                database.get_backend_name() in {"postgres", "postgresql"}
                and database.host not in {None, "localhost", "127.0.0.1", "db"}
            )
        except ValueError:
            database_is_remote_postgres = False
        if not database_is_remote_postgres:
            errors.append("DATABASE_URL must use remote PostgreSQL")

        if len(self.allowed_origins) != 1 or any(
            urlsplit(origin).scheme != "https"
            or urlsplit(origin).hostname in {None, "localhost", "127.0.0.1"}
            for origin in self.allowed_origins
        ):
            errors.append("ALLOWED_ORIGINS must contain only HTTPS non-local origins")
        if (
            not self.allowed_hosts
            or "*" in self.allowed_hosts
            or "healthcheck.railway.app" not in self.allowed_hosts
            or "api.railway.internal" not in self.allowed_hosts
        ):
            errors.append("ALLOWED_HOSTS must include API private and healthcheck hosts")
        if self.upload_dir != Path("/data/uploads"):
            errors.append("UPLOAD_DIR must be /data/uploads")

        if errors:
            raise ValueError("Invalid production configuration: " + "; ".join(errors))
```

In `apps/api/app/core/database.py`:

```python
from sqlalchemy.engine import make_url


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url.removeprefix("postgres://")
    url = make_url(database_url)
    if url.get_backend_name() == "postgresql" and url.get_driver_name() != "psycopg":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def create_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(normalize_database_url(database_url), pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)
```

In `apps/api/alembic/env.py`, normalize the selected URL before `set_main_option`:

```python
from app.core.database import normalize_database_url

database_url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
config.set_main_option("sqlalchemy.url", normalize_database_url(database_url))
```

At the start of `create_app()` in `apps/api/app/main.py`:

```python
resolved = settings or get_settings()
resolved.validate_for_startup()
provider_mode = resolved.effective_provider_mode
```

Add non-secret local defaults to `.env.example`:

```dotenv
APP_ENV=development
ALLOWED_ORIGINS=["http://localhost:3000"]
ALLOWED_HOSTS=["*"]
```

- [ ] **Step 4: Verify GREEN and regression coverage**

Run:

```bash
cd apps/api
uv run pytest tests/test_config.py tests/test_health.py tests/test_migrations.py -q
```

Expected: all selected tests pass; the Alembic fresh/current/downgrade test still reports head `0005_review_records`.

- [ ] **Step 5: Commit**

```bash
git add .env.example apps/api/app/core/config.py apps/api/app/core/database.py apps/api/alembic/env.py apps/api/app/main.py apps/api/tests/test_config.py
git commit -m "feat: fail closed for production configuration"
```

---

### Task 2: API readiness and trusted-host enforcement

**Files:**
- Create: `apps/api/app/core/readiness.py`
- Create: `apps/api/tests/test_readiness.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/tests/test_health.py`

**Interfaces:**
- Produces: `async probe_readiness(session_factory, upload_dir: Path) -> None`.
- Produces: `ReadinessError(component: Literal["database", "uploads"])` without sensitive details in HTTP responses.
- Produces: `GET /ready -> {"status": "ready", "provider_mode": "demo"}` or HTTP 503 `{"status": "not_ready"}`.
- Preserves: `GET /health` as connection-free liveness.

- [ ] **Step 1: Add failing readiness and host tests**

Create `apps/api/tests/test_readiness.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_ready_checks_database_and_upload_storage(test_settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "provider_mode": "demo"}
    assert list(test_settings.upload_dir.glob(".readiness-*")) == []


def test_ready_returns_503_when_database_is_unavailable(test_settings, tmp_path: Path) -> None:
    settings = test_settings.model_copy(
        update={"database_url": f"sqlite+aiosqlite:///{tmp_path / 'missing' / 'db.sqlite'}"}
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_ready_returns_503_when_upload_path_is_not_a_directory(test_settings, tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    settings = test_settings.model_copy(update={"upload_dir": blocked})
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_explicit_allowed_hosts_rejects_unknown_host(test_settings) -> None:
    settings = test_settings.model_copy(
        update={"allowed_hosts": ["api.railway.internal", "healthcheck.railway.app"]}
    )
    with TestClient(create_app(settings)) as client:
        rejected = client.get("/health", headers={"Host": "evil.example"})
        accepted = client.get("/health", headers={"Host": "healthcheck.railway.app"})
    assert rejected.status_code == 400
    assert accepted.status_code == 200
```

- [ ] **Step 2: Verify RED**

Run:

```bash
cd apps/api
uv run pytest tests/test_readiness.py -q
```

Expected: `/ready` returns 404 and the unknown Host is still accepted.

- [ ] **Step 3: Implement a non-destructive probe**

Create `apps/api/app/core/readiness.py`:

```python
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class ReadinessError(RuntimeError):
    def __init__(self, component: Literal["database", "uploads"]):
        super().__init__(component)
        self.component = component


async def probe_readiness(
    session_factory: async_sessionmaker[AsyncSession], upload_dir: Path
) -> None:
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ReadinessError("database") from exc

    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="wb", prefix=".readiness-", dir=upload_dir, delete=True
        ) as probe:
            probe.write(b"ready")
            probe.flush()
    except OSError as exc:
        raise ReadinessError("uploads") from exc
```

In `apps/api/app/main.py`, add TrustedHost and readiness without exposing the exception:

```python
from fastapi import Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.core.readiness import ReadinessError, probe_readiness

if resolved.allowed_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=resolved.allowed_hosts)

@app.get("/ready")
async def ready(request: Request):
    try:
        await probe_readiness(
            request.app.state.session_factory,
            request.app.state.settings.upload_dir,
        )
    except ReadinessError:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready", "provider_mode": provider_mode}
```

Add middleware before the existing CORS middleware so CORS remains the outer wrapper.

- [ ] **Step 4: Verify GREEN and existing error/CORS behavior**

Run:

```bash
cd apps/api
uv run pytest tests/test_readiness.py tests/test_health.py tests/test_auth.py -q
```

Expected: all selected tests pass; `/health` does not query the database, `/ready` does, and CORS still wraps standard errors.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/readiness.py apps/api/app/main.py apps/api/tests/test_readiness.py apps/api/tests/test_health.py
git commit -m "feat: add production readiness checks"
```

---

### Task 3: Safe API container entrypoint and Railway API manifest

**Files:**
- Create: `apps/api/app/entrypoint.py`
- Create: `apps/api/tests/test_entrypoint.py`
- Create: `apps/api/railway.json`
- Create: `apps/api/.dockerignore`
- Modify: `apps/api/Dockerfile`
- Modify: `docs/superpowers/specs/2026-07-11-railway-production-deployment-design.md`

**Interfaces:**
- Produces: `resolve_port(raw_port: str | None) -> int`.
- Produces: `prepare_runtime(upload_dir: Path, uid: int = 10001, gid: int = 10001) -> None`.
- Produces: `python -m app.entrypoint` as the image start command.
- Railway contract: pre-deploy `alembic upgrade head`, one replica, `/ready`, and required `/data/uploads` mount.

- [ ] **Step 1: Write failing entrypoint tests**

Create `apps/api/tests/test_entrypoint.py`:

```python
from pathlib import Path

import pytest

from app import entrypoint


@pytest.mark.parametrize(("raw", "expected"), [(None, 8000), ("8000", 8000), ("49152", 49152)])
def test_resolve_port(raw: str | None, expected: int) -> None:
    assert entrypoint.resolve_port(raw) == expected


@pytest.mark.parametrize("raw", ["0", "65536", "not-a-port"])
def test_resolve_port_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError, match="PORT"):
        entrypoint.resolve_port(raw)


def test_prepare_runtime_chowns_volume_then_drops_root_privileges(
    monkeypatch, tmp_path: Path
) -> None:
    upload_dir = tmp_path / "uploads"
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entrypoint.os, "chown", lambda path, uid, gid: calls.append(("chown", path, uid, gid)))
    monkeypatch.setattr(entrypoint.os, "setgroups", lambda groups: calls.append(("setgroups", groups)))
    monkeypatch.setattr(entrypoint.os, "setgid", lambda gid: calls.append(("setgid", gid)))
    monkeypatch.setattr(entrypoint.os, "setuid", lambda uid: calls.append(("setuid", uid)))
    monkeypatch.setattr(entrypoint.os, "access", lambda path, mode: True)

    entrypoint.prepare_runtime(upload_dir)

    assert upload_dir.is_dir()
    assert calls == [
        ("chown", upload_dir, 10001, 10001),
        ("setgroups", []),
        ("setgid", 10001),
        ("setuid", 10001),
    ]


def test_prepare_runtime_fails_when_upload_directory_is_not_writable(
    monkeypatch, tmp_path: Path
) -> None:
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(entrypoint.os, "access", lambda path, mode: False)
    with pytest.raises(RuntimeError, match="UPLOAD_DIR"):
        entrypoint.prepare_runtime(upload_dir)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
cd apps/api
uv run pytest tests/test_entrypoint.py -q
```

Expected: import fails because `app.entrypoint` does not exist.

- [ ] **Step 3: Implement the minimum entrypoint**

Create `apps/api/app/entrypoint.py`:

```python
import os
from pathlib import Path

import uvicorn

from app.core.config import get_settings

APP_UID = 10001
APP_GID = 10001


def resolve_port(raw_port: str | None) -> int:
    try:
        port = int(raw_port or "8000")
    except ValueError as exc:
        raise ValueError("PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    return port


def prepare_runtime(
    upload_dir: Path, uid: int = APP_UID, gid: int = APP_GID
) -> None:
    upload_dir.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        os.chown(upload_dir, uid, gid)
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    if not os.access(upload_dir, os.W_OK | os.X_OK):
        raise RuntimeError("UPLOAD_DIR is not writable by the application user")


def main() -> None:
    settings = get_settings()
    settings.validate_for_startup()
    prepare_runtime(settings.upload_dir)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=resolve_port(os.environ.get("PORT")),
    )


if __name__ == "__main__":
    main()
```

Change the API Dockerfile command only:

```dockerfile
CMD ["python", "-m", "app.entrypoint"]
```

Create `apps/api/railway.json`:

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "preDeployCommand": ["alembic upgrade head"],
    "numReplicas": 1,
    "healthcheckPath": "/ready",
    "healthcheckTimeout": 300,
    "requiredMountPath": "/data/uploads",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

Create `apps/api/.dockerignore`:

```text
.venv
__pycache__
.pytest_cache
tests
*.db
```

Update the approved spec to state the already-approved corrections: `railway up apps/api --path-as-root`, the API manifest, `PORT=8000`, and the Web same-origin proxy.

- [ ] **Step 4: Verify tests, manifest syntax, and image build**

Run:

```bash
cd apps/api
uv run pytest tests/test_entrypoint.py tests/test_config.py tests/test_readiness.py -q
python -m json.tool railway.json >/dev/null
cd ../..
docker build -t kaogong-api:railway-plan apps/api
docker run --rm --entrypoint python kaogong-api:railway-plan -c 'from app.entrypoint import resolve_port; assert resolve_port("8000") == 8000'
```

Expected: tests pass, JSON is valid, image builds, and the container contract check exits 0.

- [ ] **Step 5: Commit**

```bash
git add apps/api/.dockerignore apps/api/Dockerfile apps/api/app/entrypoint.py apps/api/railway.json apps/api/tests/test_entrypoint.py docs/superpowers/specs/2026-07-11-railway-production-deployment-design.md
git commit -m "feat: prepare API container for Railway"
```

---

### Task 4: Same-origin Web API proxy and Web health endpoint

**Files:**
- Create: `apps/web/src/lib/api-proxy.ts`
- Create: `apps/web/src/lib/api-proxy.test.ts`
- Create: `apps/web/src/app/api/v1/[...path]/route.ts`
- Create: `apps/web/src/app/health/route.ts`
- Create: `apps/web/src/app/health/route.test.ts`

**Interfaces:**
- Produces: `proxyApiRequest(request: Request, path: string[]) -> Promise<Response>`.
- Consumes: server-only `API_INTERNAL_URL`, exactly `http://api.railway.internal:8000` or its Railway reference-variable equivalent.
- Browser contract: `NEXT_PUBLIC_API_URL=/api/v1`; cookies are first-party on the Web host.
- Proxy contract: preserve method, query, Cookie, Content-Type, streamed body, upstream status, response body, `Set-Cookie`, and `X-Request-ID`; strip `Host`, `Content-Length`, and hop-by-hop headers.

- [ ] **Step 1: Write failing proxy and health tests**

Create `apps/web/src/lib/api-proxy.test.ts`:

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";

import { proxyApiRequest } from "./api-proxy";

afterEach(() => {
  delete process.env.API_INTERNAL_URL;
});

describe("proxyApiRequest", () => {
  it("fails safely when the private API target is missing", async () => {
    const response = await proxyApiRequest(
      new Request("https://web.example/api/v1/auth/me"),
      ["auth", "me"],
    );
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      code: "api_proxy_unavailable",
      message: "服务暂时不可用",
    });
  });

  it("forwards the request and preserves cookie response headers", async () => {
    process.env.API_INTERNAL_URL = "http://api.railway.internal:8000";
    const upstream = vi.fn(async () =>
      new Response(JSON.stringify({ email: "learner@example.com" }), {
        status: 201,
        headers: {
          "content-type": "application/json",
          "set-cookie": "kaogong_session=token; Path=/; HttpOnly; Secure; SameSite=lax",
          "x-request-id": "request-1",
        },
      }),
    );
    vi.stubGlobal("fetch", upstream);

    const response = await proxyApiRequest(
      new Request("https://web.example/api/v1/auth/register?source=smoke", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          cookie: "existing=value",
          host: "web.example",
        },
        body: JSON.stringify({ email: "learner@example.com", password: "strong-pass-123" }),
      }),
      ["auth", "register"],
    );

    const [target, init] = upstream.mock.calls[0];
    expect(String(target)).toBe(
      "http://api.railway.internal:8000/api/v1/auth/register?source=smoke",
    );
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("host")).toBeNull();
    expect(new Headers(init?.headers).get("cookie")).toBe("existing=value");
    expect(response.status).toBe(201);
    expect(response.headers.get("set-cookie")).toContain("kaogong_session=token");
    expect(response.headers.get("x-request-id")).toBe("request-1");
  });
});
```

Create `apps/web/src/app/health/route.test.ts`:

```typescript
import { expect, it } from "vitest";

import { GET } from "./route";

it("reports Web liveness without calling the API", async () => {
  const response = await GET();
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ status: "ok" });
});
```

- [ ] **Step 2: Verify RED**

Run:

```bash
cd apps/web
npm test -- --run src/lib/api-proxy.test.ts src/app/health/route.test.ts
```

Expected: imports fail because the proxy and health route do not exist.

- [ ] **Step 3: Implement the streaming proxy**

Create `apps/web/src/lib/api-proxy.ts`:

```typescript
const HOP_BY_HOP_HEADERS = [
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

function safeUnavailable() {
  return Response.json(
    { code: "api_proxy_unavailable", message: "服务暂时不可用" },
    { status: 503 },
  );
}

export async function proxyApiRequest(
  request: Request,
  path: string[],
): Promise<Response> {
  const base = process.env.API_INTERNAL_URL;
  if (!base) return safeUnavailable();

  let target: URL;
  try {
    const suffix = path.map(encodeURIComponent).join("/");
    target = new URL(`/api/v1/${suffix}`, base);
    target.search = new URL(request.url).search;
  } catch {
    return safeUnavailable();
  }

  const headers = new Headers(request.headers);
  for (const name of HOP_BY_HOP_HEADERS) headers.delete(name);
  const incoming = new URL(request.url);
  headers.set("x-forwarded-host", incoming.host);
  headers.set("x-forwarded-proto", incoming.protocol.replace(":", ""));

  const hasBody = !new Set(["GET", "HEAD"]).has(request.method);
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    cache: "no-store",
    redirect: "manual",
  };
  if (hasBody) init.duplex = "half";

  try {
    const upstream = await fetch(target, init);
    const responseHeaders = new Headers(upstream.headers);
    for (const name of HOP_BY_HOP_HEADERS) responseHeaders.delete(name);
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch {
    return safeUnavailable();
  }
}
```

Create `apps/web/src/app/api/v1/[...path]/route.ts`:

```typescript
import { proxyApiRequest } from "@/lib/api-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Context = { params: Promise<{ path: string[] }> };

async function handler(request: Request, context: Context) {
  const { path } = await context.params;
  return proxyApiRequest(request, path);
}

export {
  handler as DELETE,
  handler as GET,
  handler as HEAD,
  handler as OPTIONS,
  handler as PATCH,
  handler as POST,
  handler as PUT,
};
```

Create `apps/web/src/app/health/route.ts`:

```typescript
export function GET() {
  return Response.json({ status: "ok" });
}
```

- [ ] **Step 4: Verify GREEN, type checking through build, and existing auth UI tests**

Run:

```bash
cd apps/web
npm test -- --run src/lib/api-proxy.test.ts src/app/health/route.test.ts src/app/login/page.test.tsx src/app/register/page.test.tsx
NEXT_PUBLIC_API_URL=/api/v1 API_INTERNAL_URL=http://api.railway.internal:8000 npm run build
```

Expected: selected tests pass and Next production build succeeds with the dynamic proxy route.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/api-proxy.ts apps/web/src/lib/api-proxy.test.ts apps/web/src/app/api/v1/\[...path\]/route.ts apps/web/src/app/health/route.ts apps/web/src/app/health/route.test.ts
git commit -m "feat: proxy production API through Web origin"
```

---

### Task 5: Web image contract and Railway Web manifest

**Files:**
- Create: `apps/web/railway.json`
- Create: `apps/web/.dockerignore`
- Modify: `apps/web/Dockerfile`

**Interfaces:**
- Build contract: `NEXT_PUBLIC_API_URL` is required and must be `/api/v1`, an HTTPS URL, or the existing local `http://localhost:*` form.
- Runtime contract: `API_INTERNAL_URL` is server-only; `PORT` remains overridable by Railway.
- Railway contract: Dockerfile builder, one replica, `/health`, 300-second health timeout, bounded restart retries.

- [ ] **Step 1: Make the missing build argument fail before changing the Dockerfile**

Run:

```bash
docker build -t kaogong-web:missing-api apps/web
```

Expected before the change: build succeeds because the Dockerfile silently bakes `http://localhost:8000/api/v1`; record this as the unsafe RED result.

- [ ] **Step 2: Make the Web build argument fail closed**

Replace the builder argument/default block in `apps/web/Dockerfile` with:

```dockerfile
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN case "${NEXT_PUBLIC_API_URL}" in \
      /api/v1|https://*/api/v1|http://localhost:*/api/v1) ;; \
      *) echo "NEXT_PUBLIC_API_URL must be /api/v1, HTTPS /api/v1, or local development" >&2; exit 1 ;; \
    esac
```

Keep `PORT=3000` as an image default; Railway's runtime value overrides it.

Create `apps/web/railway.json`:

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "numReplicas": 1,
    "healthcheckPath": "/health",
    "healthcheckTimeout": 300,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

Create `apps/web/.dockerignore`:

```text
node_modules
.next
coverage
*.log
```

- [ ] **Step 3: Verify the negative and positive image builds**

Run:

```bash
if docker build -t kaogong-web:missing-api apps/web; then
  echo "missing API build unexpectedly succeeded" >&2
  exit 1
fi
docker build --build-arg NEXT_PUBLIC_API_URL=/api/v1 -t kaogong-web:railway-plan apps/web
python3 -m json.tool apps/web/railway.json >/dev/null
```

Expected: first build fails with the explicit argument message; second build and JSON validation pass.

- [ ] **Step 4: Confirm local Compose still supplies its explicit development argument**

Run:

```bash
docker compose config --quiet
docker compose build web
```

Expected: Compose config and existing local Web image build pass without starting, restarting, or removing containers.

- [ ] **Step 5: Commit**

```bash
git add apps/web/.dockerignore apps/web/Dockerfile apps/web/railway.json
git commit -m "feat: add Railway Web deployment contract"
```

---

### Task 6: Production smoke harness and Railway runbook

**Files:**
- Create: `scripts/production-smoke.sh`
- Create: `docs/deployment/railway.md`
- Modify: `Makefile`
- Modify: `README.md`

**Interfaces:**
- Required smoke inputs: `WEB_URL`, `API_URL`.
- Optional smoke inputs: `SMOKE_EMAIL`, `SMOKE_PASSWORD`, `SMOKE_IMAGE_PATH`, `SMOKE_STATE_FILE`.
- Produces: a mode-600 JSON state file containing only email, upload ID, and question ID; password remains outside that file.
- Runbook pins `npx -y @railway/cli@5.26.0` and never prints secret values.

- [ ] **Step 1: Add the production smoke script**

Create executable `scripts/production-smoke.sh` with this complete flow:

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${WEB_URL:?WEB_URL is required}"
: "${API_URL:?API_URL is required}"

web_url=${WEB_URL%/}
api_url=${API_URL%/}
api_proxy="$web_url/api/v1"
image_path=${SMOKE_IMAGE_PATH:-docs/design/ai-exam-diagnosis-dashboard-selected.png}
state_file=${SMOKE_STATE_FILE:-$(mktemp)}
email=${SMOKE_EMAIL:-"codex-smoke-$(date +%s)-$$@example.com"}
password=${SMOKE_PASSWORD:-"smoke-$(openssl rand -hex 16)"}
tmp_dir=$(mktemp -d)
cookie_jar="$tmp_dir/cookies"
other_cookie_jar="$tmp_dir/other-cookies"
trap 'rm -rf "$tmp_dir"' EXIT

assert_json() {
  local path=$1 expression=$2
  python3 - "$path" "$expression" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
if not eval(sys.argv[2], {"__builtins__": {}}, {"payload": payload}):
    raise SystemExit(f"JSON assertion failed: {sys.argv[2]}")
PY
}

json_value() {
  python3 - "$1" "$2" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(payload[sys.argv[2]])
PY
}

curl --fail --silent --show-error "$api_url/health" >"$tmp_dir/api-health.json"
assert_json "$tmp_dir/api-health.json" 'payload == {"status": "ok", "provider_mode": "demo"}'
curl --fail --silent --show-error "$api_url/ready" >"$tmp_dir/api-ready.json"
assert_json "$tmp_dir/api-ready.json" 'payload == {"status": "ready", "provider_mode": "demo"}'
curl --fail --silent --show-error "$web_url/health" >"$tmp_dir/web-health.json"
assert_json "$tmp_dir/web-health.json" 'payload == {"status": "ok"}'
curl --fail --silent --show-error "$web_url/login" | grep -q '登录'

curl --silent --show-error --dump-header "$tmp_dir/preflight.headers" --output /dev/null \
  --request OPTIONS \
  --header "Origin: $web_url" \
  --header 'Access-Control-Request-Method: POST' \
  "$api_url/api/v1/auth/login"
grep -Fqi "access-control-allow-origin: $web_url" "$tmp_dir/preflight.headers"
grep -Fqi 'access-control-allow-credentials: true' "$tmp_dir/preflight.headers"

curl --silent --show-error --dump-header "$tmp_dir/rejected-origin.headers" --output /dev/null \
  --request OPTIONS \
  --header 'Origin: https://evil.example' \
  --header 'Access-Control-Request-Method: POST' \
  "$api_url/api/v1/auth/login"
if grep -Fqi 'access-control-allow-origin:' "$tmp_dir/rejected-origin.headers"; then
  echo 'unexpected CORS allow header for rejected origin' >&2
  exit 1
fi

python3 - "$tmp_dir/register.json" "$email" "$password" <<'PY'
import json, sys
json.dump({"email": sys.argv[2], "password": sys.argv[3]}, open(sys.argv[1], "w", encoding="utf-8"))
PY
status=$(curl --silent --show-error --write-out '%{http_code}' \
  --dump-header "$tmp_dir/register.headers" --output "$tmp_dir/register-response.json" \
  --cookie-jar "$cookie_jar" --header 'Content-Type: application/json' \
  --data-binary @"$tmp_dir/register.json" "$api_proxy/auth/register")
test "$status" = 201
grep -Fqi 'HttpOnly' "$tmp_dir/register.headers"
grep -Fqi 'Secure' "$tmp_dir/register.headers"
grep -Fqi 'SameSite=lax' "$tmp_dir/register.headers"

curl --fail --silent --show-error --cookie "$cookie_jar" "$api_proxy/auth/me" >"$tmp_dir/me.json"
assert_json "$tmp_dir/me.json" "payload['email'] == '$email'"

test -f "$image_path"
curl --fail --silent --show-error --cookie "$cookie_jar" \
  --form "file=@$image_path;type=image/png" \
  "$api_proxy/uploads/questions" >"$tmp_dir/upload.json"
upload_id=$(json_value "$tmp_dir/upload.json" id)

printf '{"upload_id":"%s"}' "$upload_id" >"$tmp_dir/ocr-request.json"
curl --fail --silent --show-error --cookie "$cookie_jar" \
  --header 'Content-Type: application/json' --data-binary @"$tmp_dir/ocr-request.json" \
  "$api_proxy/ocr" >"$tmp_dir/ocr.json"
assert_json "$tmp_dir/ocr.json" 'payload["is_demo"] is True'

python3 - "$tmp_dir/ocr.json" "$tmp_dir/question.json" "$upload_id" <<'PY'
import json, sys
ocr = json.load(open(sys.argv[1], encoding="utf-8"))
json.dump({
    "exam_type": "国考",
    "module": "言语理解",
    "stem": ocr["stem"] + "（Railway smoke）",
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
    "tags": []
}, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
PY
curl --fail --silent --show-error --cookie "$cookie_jar" \
  --header 'Content-Type: application/json' --data-binary @"$tmp_dir/question.json" \
  "$api_proxy/questions" >"$tmp_dir/created-question.json"
question_id=$(json_value "$tmp_dir/created-question.json" id)

curl --fail --silent --show-error --request POST --cookie "$cookie_jar" \
  "$api_proxy/questions/$question_id/analyze" >"$tmp_dir/analysis.json"
assert_json "$tmp_dir/analysis.json" 'payload["is_demo"] is True and payload["provider_name"] == "demo"'

curl --fail --silent --show-error --cookie "$cookie_jar" \
  --header 'Content-Type: application/json' \
  --data '{"result_status":"复习中","review_note":"Railway 正式环境 smoke"}' \
  "$api_proxy/reviews/$question_id" >"$tmp_dir/review.json"
assert_json "$tmp_dir/review.json" 'payload["result_status"] == "复习中"'

curl --fail --silent --show-error --cookie "$cookie_jar" "$api_proxy/dashboard" >"$tmp_dir/dashboard.json"
assert_json "$tmp_dir/dashboard.json" 'payload["provider_mode"] == "demo"'
curl --fail --silent --show-error --cookie "$cookie_jar" "$api_proxy/analytics/summary" >"$tmp_dir/analytics.json"
assert_json "$tmp_dir/analytics.json" 'payload["total_questions"] >= 1 and payload["is_demo"] is True'

other_email="other-$(date +%s)-$$@example.com"
python3 - "$tmp_dir/other-register.json" "$other_email" "$password" <<'PY'
import json, sys
json.dump({"email": sys.argv[2], "password": sys.argv[3]}, open(sys.argv[1], "w", encoding="utf-8"))
PY
curl --fail --silent --show-error --cookie-jar "$other_cookie_jar" \
  --header 'Content-Type: application/json' --data-binary @"$tmp_dir/other-register.json" \
  "$api_proxy/auth/register" >/dev/null
status=$(curl --silent --show-error --write-out '%{http_code}' --output "$tmp_dir/isolation.json" \
  --cookie "$other_cookie_jar" "$api_proxy/questions/$question_id")
test "$status" = 404

curl --fail --silent --show-error --request POST --cookie "$cookie_jar" \
  --cookie-jar "$cookie_jar" "$api_proxy/auth/logout" >/dev/null
status=$(curl --silent --show-error --write-out '%{http_code}' --output /dev/null \
  --cookie "$cookie_jar" "$api_proxy/auth/me")
test "$status" = 401

curl --fail --silent --show-error --cookie-jar "$cookie_jar" \
  --header 'Content-Type: application/json' --data-binary @"$tmp_dir/register.json" \
  "$api_proxy/auth/login" >/dev/null
curl --fail --silent --show-error --cookie "$cookie_jar" "$api_proxy/questions/$question_id" \
  >"$tmp_dir/persisted-question.json"
assert_json "$tmp_dir/persisted-question.json" 'payload["analysis_status"] == "已完成" and payload["mastery_status"] == "复习中"'

umask 077
python3 - "$state_file" "$email" "$upload_id" "$question_id" <<'PY'
import json, sys
json.dump({"email": sys.argv[2], "upload_id": sys.argv[3], "question_id": sys.argv[4]}, open(sys.argv[1], "w", encoding="utf-8"))
PY
printf 'production smoke passed; state=%s\n' "$state_file"
```

Run `chmod +x scripts/production-smoke.sh` as a mechanical permission change.

- [ ] **Step 2: Add Make and README entrypoints**

Add to `Makefile`:

```make
.PHONY: prod-smoke

prod-smoke:
	bash scripts/production-smoke.sh
```

Add a short README section that points to `docs/deployment/railway.md`, states that production uses Web same-origin `/api/v1`, and warns never to run the seed command remotely.

- [ ] **Step 3: Write the exact Railway runbook**

Create `docs/deployment/railway.md` with these ordered command groups and stop conditions:

```bash
RAILWAY='npx -y @railway/cli@5.26.0'
$RAILWAY login
$RAILWAY whoami
$RAILWAY init --name kaogong-ai-exam --json
$RAILWAY add --database postgres --json
$RAILWAY add --service api --json
$RAILWAY add --service web --json
$RAILWAY domain --service api --port 8000 --json
$RAILWAY domain --service web --port 3000 --json
$RAILWAY service link api
$RAILWAY volume add --mount-path /data/uploads --json
```

Set variables without triggering partial deployments:

```bash
openssl rand -hex 32 | $RAILWAY variable set JWT_SECRET --stdin --service api --environment production --skip-deploys
$RAILWAY variable set --service api --environment production --skip-deploys \
  APP_ENV=production \
  'DATABASE_URL=${{Postgres.DATABASE_URL}}' \
  COOKIE_SECURE=true \
  'ALLOWED_ORIGINS=["https://${{web.RAILWAY_PUBLIC_DOMAIN}}"]' \
  'ALLOWED_HOSTS=["${{api.RAILWAY_PUBLIC_DOMAIN}}","api.railway.internal","healthcheck.railway.app"]' \
  PROVIDER_MODE=demo \
  UPLOAD_DIR=/data/uploads \
  MAX_UPLOAD_BYTES=10485760 \
  PORT=8000 \
  RAILWAY_RUN_UID=0
$RAILWAY variable set --service web --environment production --skip-deploys \
  NEXT_PUBLIC_API_URL=/api/v1 \
  'API_INTERNAL_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000' \
  PORT=3000
```

Deploy the exact app subdirectories:

```bash
$RAILWAY up apps/api --path-as-root --service api --environment production --message "deploy api $(git rev-parse --short HEAD)"
$RAILWAY up apps/web --path-as-root --service web --environment production --message "deploy web $(git rev-parse --short HEAD)"
```

The runbook must also include:

- Verify `railway status --json`, `railway deployment list --service api --limit 1 --json`, and the Web equivalent.
- Inspect only bounded logs with `railway logs --service api --lines 100` and Web equivalent; do not dump variables.
- Verify `railway ssh --service api alembic current` reports `0005_review_records`.
- Verify volume UID/write with a remote temporary probe that deletes itself.
- Stop if Railway asks for payment/upgrade, names an existing project/resource, migration fails, or `/ready` is not 200.
- Roll back application code with the previous Railway deployment; do not run destructive Alembic downgrade or delete database/volume.
- Do not delete Railway resources after a failed test without explicit user authorization.

- [ ] **Step 4: Validate the script without touching remote state**

Run:

```bash
bash -n scripts/production-smoke.sh
shellcheck scripts/production-smoke.sh 2>/dev/null || true
git diff --check
```

Expected: Bash syntax and whitespace checks pass. If ShellCheck is installed, it reports no error-severity findings; absence of ShellCheck is not a failure.

- [ ] **Step 5: Commit**

```bash
git add Makefile README.md scripts/production-smoke.sh docs/deployment/railway.md
git commit -m "docs: add Railway deployment and smoke workflow"
```

---

### Task 7: Full local verification and pre-deployment review

**Files:**
- Modify only files needed to fix verified regressions within Tasks 1-6 scope.

**Interfaces:**
- Consumes all prior task deliverables.
- Produces a clean, committed SHA that is the only source uploaded to Railway.

- [ ] **Step 1: Run the complete repository verification**

Run:

```bash
make test
docker compose config --quiet
docker build -t kaogong-api:railway-final apps/api
docker build --build-arg NEXT_PUBLIC_API_URL=/api/v1 -t kaogong-web:railway-final apps/web
```

Expected: API tests, Web tests, lint, Next build, Compose validation, and both production image builds all exit 0.

- [ ] **Step 2: Rehearse PostgreSQL 17 migration on an isolated Docker network**

Use unique container/network names and expose no host ports:

```bash
network="kaogong-migration-check-$$"
database="kaogong-migration-db-$$"
cleanup_migration_check() {
  docker rm -f "$database" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup_migration_check EXIT
docker network create "$network" >/dev/null
docker run -d --name "$database" --network "$network" \
  -e POSTGRES_DB=kaogong -e POSTGRES_USER=kaogong -e POSTGRES_PASSWORD=migration-check \
  postgres:17-alpine >/dev/null
for _ in $(seq 1 30); do
  docker exec "$database" pg_isready -U kaogong -d kaogong >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$database" pg_isready -U kaogong -d kaogong >/dev/null
docker run --rm --network "$network" \
  -e DATABASE_URL="postgresql+psycopg://kaogong:migration-check@$database:5432/kaogong" \
  --entrypoint alembic kaogong-api:railway-final upgrade head
docker run --rm --network "$network" \
  -e DATABASE_URL="postgresql+psycopg://kaogong:migration-check@$database:5432/kaogong" \
  --entrypoint alembic kaogong-api:railway-final current | grep -q 0005_review_records
cleanup_migration_check
trap - EXIT
```

Expected: fresh migration and current revision pass. The throwaway container/network are removed; the user's existing Compose project is untouched.

- [ ] **Step 3: Verify the production-failure matrix and volume runtime**

Run the focused tests and a temporary container volume probe:

```bash
cd apps/api
uv run pytest tests/test_config.py tests/test_readiness.py tests/test_entrypoint.py -q
cd ../..
probe="kaogong-upload-probe-$$"
docker volume create "$probe" >/dev/null
docker run --rm -e RAILWAY_RUN_UID=0 -e UPLOAD_DIR=/data/uploads \
  -v "$probe:/data/uploads" --user 0 --entrypoint python \
  kaogong-api:railway-final -c 'from pathlib import Path; from app.entrypoint import prepare_runtime; prepare_runtime(Path("/data/uploads")); Path("/data/uploads/probe").write_text("ok"); Path("/data/uploads/probe").unlink()'
docker volume rm "$probe" >/dev/null
```

Expected: focused tests pass and the probe exits 0 without leaving a file or volume.

- [ ] **Step 4: Invoke Superpowers requesting-code-review**

Request review of the approved deployment spec, Tasks 1-6 diffs, all verification output, proxy cookie semantics, production validation, volume privilege drop, and Railway manifests. Resolve only substantiated findings and rerun the affected focused tests.

- [ ] **Step 5: Record the deployable source state**

Run:

```bash
git diff --check
test -z "$(git status --porcelain)"
git rev-parse HEAD
```

Expected: clean worktree and one full commit SHA. Do not deploy if the tree is dirty.

---

### Task 8: Provision and deploy the Railway production environment

**Files:**
- Do not store Railway CLI output or credentials in tracked files.
- Create later: `docs/qa/railway-production-audit.md` only after public endpoints exist.

**Interfaces:**
- Consumes the clean SHA from Task 7 and the exact runbook from Task 6.
- Produces Railway project `kaogong-ai-exam` with `Postgres`, `api`, `web`, API volume, public Web/API domains, and healthy deployments.

- [ ] **Step 1: Authenticate through the user-visible Railway OAuth flow**

Run:

```bash
npx -y @railway/cli@5.26.0 login
npx -y @railway/cli@5.26.0 whoami
```

Expected: the CLI identifies the user's Railway account. Pause for the user only if the browser/device confirmation is required. Stop before accepting any payment or plan upgrade.

- [ ] **Step 2: Create and inspect resources using the runbook**

Execute the `init`, database, API, Web, domain, service-link, and volume commands from `docs/deployment/railway.md`. After every mutation, inspect JSON output and `railway status --json`; do not re-run a create command if the resource already exists.

Expected: exactly three services and one API upload volume in one production environment.

- [ ] **Step 3: Set variables without exposing secrets**

Execute the runbook's stdin secret command and reference-variable commands. Check only variable key names from JSON output; do not request or print sealed values.

Expected keys:

```text
api: APP_ENV DATABASE_URL JWT_SECRET COOKIE_SECURE ALLOWED_ORIGINS ALLOWED_HOSTS PROVIDER_MODE UPLOAD_DIR MAX_UPLOAD_BYTES PORT RAILWAY_RUN_UID
web: NEXT_PUBLIC_API_URL API_INTERNAL_URL PORT
```

Confirm `OPENAI_API_KEY` is absent.

- [ ] **Step 4: Deploy API, wait for migration and readiness, then deploy Web**

Run the two runbook `railway up ... --path-as-root` commands in order. Do not use detached mode. Inspect bounded logs and the latest deployment records.

Expected:

- API build uses `apps/api/Dockerfile` and `apps/api/railway.json`.
- Pre-deploy migration exits 0 at `0005_review_records`.
- `/ready` reaches 200 before API deployment becomes active.
- Web build bakes `NEXT_PUBLIC_API_URL=/api/v1` and exposes `/health`.
- Neither log contains a secret, `OPENAI_API_KEY`, localhost production URL, traceback, or repeated crash.

- [ ] **Step 5: Verify public/private service contracts**

Run:

```bash
npx -y @railway/cli@5.26.0 ssh --service api alembic current
npx -y @railway/cli@5.26.0 ssh --service api python -c 'import os, pathlib, tempfile; root=pathlib.Path("/data/uploads"); f=tempfile.NamedTemporaryFile(dir=root, delete=True); f.write(b"ok"); f.flush(); print({"uid": os.geteuid(), "mount": str(root), "writable": True})'
```

Expected: revision `0005_review_records`, runtime UID `10001`, mount `/data/uploads`, and successful self-deleting probe.

---

### Task 9: Remote smoke, restart persistence, Chrome QA, and completion audit

**Files:**
- Create: `docs/qa/railway-production-audit.md`
- Create: `docs/qa/railway-production/` screenshots and comparison image selected by the Product Design QA workflow.

**Interfaces:**
- Consumes: `WEB_URL`, `API_URL`, a password kept in a mode-600 temp file outside Git, and the deployed SHA.
- Produces: requirement-by-requirement evidence for the approved spec with no credentials.

- [ ] **Step 1: Run production smoke through the Web origin**

Generate a password without printing it, then run:

```bash
secret_file=$(mktemp)
chmod 600 "$secret_file"
openssl rand -hex 24 >"$secret_file"
state_file=$(mktemp)
SMOKE_PASSWORD=$(<"$secret_file") \
WEB_URL="$WEB_URL" API_URL="$API_URL" SMOKE_STATE_FILE="$state_file" \
bash scripts/production-smoke.sh
```

Expected: script reports pass and the state file contains only email, upload ID, and question ID. Keep the password file only until restart and Chrome validation finish.

- [ ] **Step 2: Inspect security and HTTP evidence**

Verify directly:

- Login/register via `WEB_URL/api/v1` sets `Secure`, `HttpOnly`, `SameSite=Lax` on the Web host.
- Browser/API responses never reveal `API_INTERNAL_URL` or database details.
- Direct API CORS allows only `WEB_URL` and omits allow-origin for an unrelated Origin.
- Unknown Host returns 400 while `healthcheck.railway.app` and API domains work.
- Railway HTTP logs show successful Web proxy/API requests and no unexpected 5xx.

- [ ] **Step 3: Restart API and PostgreSQL, then prove persistence**

Capture IDs from the state file without printing the password. Restart API and Postgres one at a time:

```bash
npx -y @railway/cli@5.26.0 service restart --service api --yes --json
npx -y @railway/cli@5.26.0 service restart --service Postgres --yes --json
```

Wait for API `/ready` to return 200, then run the exact persistence checks through the Web origin:

```bash
for _ in $(seq 1 60); do
  curl --fail --silent --show-error "$API_URL/ready" >/dev/null 2>&1 && break
  sleep 2
done
curl --fail --silent --show-error "$API_URL/ready" | grep -q '"status":"ready"'

email=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["email"])' "$state_file")
question_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["question_id"])' "$state_file")
upload_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["upload_id"])' "$state_file")
cookie_jar=$(mktemp)
login_body=$(mktemp)
python3 - "$login_body" "$email" "$(<"$secret_file")" <<'PY'
import json, sys
json.dump({"email": sys.argv[2], "password": sys.argv[3]}, open(sys.argv[1], "w", encoding="utf-8"))
PY
curl --fail --silent --show-error --cookie-jar "$cookie_jar" \
  --header 'Content-Type: application/json' --data-binary @"$login_body" \
  "$WEB_URL/api/v1/auth/login" >/dev/null
curl --fail --silent --show-error --cookie "$cookie_jar" \
  "$WEB_URL/api/v1/questions/$question_id" >"$login_body.question"
python3 - "$login_body.question" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["analysis_status"] == "已完成"
assert payload["mastery_status"] == "复习中"
assert payload["current_analysis"]["is_demo"] is True
PY
curl --fail --silent --show-error --cookie "$cookie_jar" \
  "$WEB_URL/api/v1/reviews/questions/$question_id" >"$login_body.reviews"
python3 - "$login_body.reviews" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["total"] >= 1
assert any(item["result_status"] == "复习中" for item in payload["items"])
PY
curl --fail --silent --show-error --cookie "$cookie_jar" \
  "$WEB_URL/api/v1/uploads/$upload_id" >"$login_body.image"
test -s "$login_body.image"
rm -f "$cookie_jar" "$login_body" "$login_body.question" "$login_body.reviews" "$login_body.image"
```

Expected: account, question, current analysis, review record, mastery state, and original image all remain available.

- [ ] **Step 4: Load the Chrome control skill and run the full user journey**

Using only Chrome and the same dedicated test account:

1. Open the public Web URL and log in.
2. Verify the persisted Dashboard state.
3. Upload a real PNG and confirm preview.
4. Trigger OCR and confirm visible “演示模式” labeling.
5. Edit recognized fields, save, and open detail.
6. Trigger AI diagnosis and verify cause, knowledge points, approach, advice, and demo label.
7. Filter/open the question in the library.
8. Complete a review and verify mastery-state change.
9. Verify Dashboard and analytics updates.
10. Log out, log in again, and confirm state.
11. Check the main desktop and narrow-screen flows for visible regressions and keyboard focus.

Expected: every primary control works on the deployed origin, no mixed-content/cross-site-cookie error appears, and the Browser Network/Console shows no unexpected failure.

- [ ] **Step 5: Perform Product Design screenshot comparison**

Capture deployed Dashboard desktop and narrow-screen screenshots with Chrome. Compare the deployed desktop screenshot side by side with `docs/qa/chrome-audit/09-dashboard-final-desktop-pass2.png` in one combined image, inspect spacing, typography, clipping, borders, focus, and responsive layout, and fix only verified deployment regressions.

- [ ] **Step 6: Write and commit the production audit**

Create `docs/qa/railway-production-audit.md` containing:

- Web and API public URLs.
- Git commit SHA and Alembic revision.
- Service/volume topology and non-secret variable key list.
- Automated test/build results.
- Remote smoke account email only, with no password or session token.
- Cookie, CORS, Host, migration, upload-write, and isolation evidence.
- API/Postgres restart timestamps and persistence evidence.
- Chrome journey result and screenshot paths.
- Provider confirmation `demo`, with `OPENAI_API_KEY` absent.
- Known limitations: demo AI, one API replica, POSIX volume, in-process rate limiting, and manual CLI deploy.

Commit only non-secret evidence:

```bash
git add docs/qa/railway-production-audit.md docs/qa/railway-production
git commit -m "docs: record Railway production validation"
rm -f "$secret_file" "$state_file"
```

- [ ] **Step 7: Run verification-before-completion and audit every requirement**

Invoke `superpowers:verification-before-completion`, rerun the final bounded checks, and map each numbered completion requirement in `docs/superpowers/specs/2026-07-11-railway-production-deployment-design.md` to direct evidence. Do not mark the goal complete if any evidence is missing, indirect, or contradicted.
