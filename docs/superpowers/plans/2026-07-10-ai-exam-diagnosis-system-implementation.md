# AI 公考错题诊断系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 交付 PRD 中完整可运行、可测试、可用 Chrome 验收的 AI 公考错题诊断系统 P0 MVP。

**Architecture:** 仓库采用 apps/web 与 apps/api 两个应用。Next.js App Router 负责响应式界面，FastAPI 负责认证、错题、上传、Provider、复习与统计，PostgreSQL 保存业务数据，本地卷保存图片。Provider 统一封装 OpenAI Responses API 和确定性演示实现，默认无密钥也可完成全部流程。

**Tech Stack:** Next.js App Router、React、TypeScript、Tailwind CSS 4、TanStack Query、React Hook Form、Zod、Recharts、Vitest；FastAPI、Pydantic、SQLAlchemy 2、Alembic、PostgreSQL、OpenAI Python SDK、pytest；Docker。

## Global Constraints

- 只实现设计规格中的 P0 MVP，不加入付费、机构后台、同类题推荐、忘记密码、自由标签 UI 或复杂多题自动拆分。
- 默认 PROVIDER_MODE=auto；无 OPENAI_API_KEY 时自动进入明确标注的演示模式。
- 登录使用有效期 7 天的签名令牌，存入 HttpOnly、SameSite=Lax Cookie；生产环境启用 Secure。
- 上传只接受 JPEG、PNG、WebP，默认上限 10 MiB，API 必须验证真实图片内容。
- 每日复习数量只能是 10、20、30、50，默认 20。
- 复习排序分数：未掌握 100、复习中 60、最近 7 天新增 30、前三薄弱知识点 20；同分按 created_at 与 id 倒序。
- 所有按 ID 读取、修改、删除和下载必须同时限定当前用户；跨用户访问统一返回 404。
- 用户原有的 gitInit.txt 删除状态不属于本计划，任何提交都不得暂存该路径。
- UI 必须匹配 docs/design/ai-exam-diagnosis-dashboard-selected.png；不使用 Emoji、手绘 SVG、装饰性 3D 素材或通用 KPI 卡片墙。
- 每个任务严格走红—绿—重构循环，并只提交该任务列出的文件。

---

## 文件结构

~~~text
.
├── .env.example
├── Makefile
├── README.md
├── docker-compose.yml
├── apps
│   ├── api
│   │   ├── Dockerfile
│   │   ├── alembic.ini
│   │   ├── pyproject.toml
│   │   ├── alembic/env.py
│   │   ├── alembic/versions/0001_initial.py
│   │   ├── app
│   │   │   ├── main.py
│   │   │   ├── api/deps.py
│   │   │   ├── api/router.py
│   │   │   ├── api/routes/auth.py
│   │   │   ├── api/routes/uploads.py
│   │   │   ├── api/routes/providers.py
│   │   │   ├── api/routes/questions.py
│   │   │   ├── api/routes/reviews.py
│   │   │   ├── api/routes/analytics.py
│   │   │   ├── api/routes/dashboard.py
│   │   │   ├── core/config.py
│   │   │   ├── core/database.py
│   │   │   ├── core/errors.py
│   │   │   ├── core/rate_limit.py
│   │   │   ├── core/security.py
│   │   │   ├── models/base.py
│   │   │   ├── models/user.py
│   │   │   ├── models/upload.py
│   │   │   ├── models/question.py
│   │   │   ├── models/analysis.py
│   │   │   ├── models/review.py
│   │   │   ├── schemas/common.py
│   │   │   ├── schemas/auth.py
│   │   │   ├── schemas/upload.py
│   │   │   ├── schemas/question.py
│   │   │   ├── schemas/analysis.py
│   │   │   ├── schemas/review.py
│   │   │   ├── schemas/analytics.py
│   │   │   ├── services/storage.py
│   │   │   ├── services/review.py
│   │   │   ├── services/analytics.py
│   │   │   ├── services/providers/base.py
│   │   │   ├── services/providers/demo.py
│   │   │   ├── services/providers/openai.py
│   │   │   ├── services/providers/factory.py
│   │   │   └── seed.py
│   │   └── tests
│   │       ├── conftest.py
│   │       ├── test_health.py
│   │       ├── test_auth.py
│   │       ├── test_uploads.py
│   │       ├── test_providers.py
│   │       ├── test_questions.py
│   │       ├── test_reviews.py
│   │       └── test_analytics.py
│   └── web
│       ├── Dockerfile
│       ├── package.json
│       ├── vitest.config.ts
│       └── src
│           ├── app/layout.tsx
│           ├── app/globals.css
│           ├── app/login/page.tsx
│           ├── app/register/page.tsx
│           ├── app/(app)/layout.tsx
│           ├── app/(app)/dashboard/page.tsx
│           ├── app/(app)/questions/page.tsx
│           ├── app/(app)/questions/new/page.tsx
│           ├── app/(app)/questions/[id]/page.tsx
│           ├── app/(app)/review/page.tsx
│           ├── app/(app)/analytics/page.tsx
│           ├── components/ui
│           ├── components/layout
│           ├── components/questions
│           ├── components/dashboard
│           ├── components/review
│           ├── components/analytics
│           ├── hooks/use-session.ts
│           ├── lib/api.ts
│           ├── lib/cn.ts
│           ├── lib/query-client.tsx
│           ├── lib/schemas.ts
│           ├── test/setup.ts
│           ├── test/test-utils.tsx
│           └── types/api.ts
└── scripts
    ├── dev-preflight.sh
    └── smoke.sh
~~~

## Task 1: 项目骨架、配置与健康检查

**Files:**
- Create: apps/api/pyproject.toml
- Create: apps/api/app/core/config.py
- Create: apps/api/app/core/database.py
- Create: apps/api/app/core/errors.py
- Create: apps/api/app/main.py
- Create: apps/api/tests/conftest.py
- Create: apps/api/tests/test_health.py
- Create: apps/web 下 create-next-app 基础文件
- Modify: .gitignore

**Interfaces:**
- Produces: create_app(settings: Settings | None = None) -> FastAPI
- Produces: get_session() -> AsyncIterator[AsyncSession]
- Produces: GET /health -> {"status": "ok", "provider_mode": str}

- [ ] **Step 1: 写健康检查失败测试**

~~~python
from fastapi.testclient import TestClient
from app.main import create_app


def test_health_reports_demo_mode(test_settings):
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider_mode": "demo"}
~~~

- [ ] **Step 2: 运行并确认失败**

Run: cd apps/api && uv run pytest tests/test_health.py -q
Expected: FAIL，提示 app.main 不存在。

- [ ] **Step 3: 创建后端依赖与最小应用**

pyproject.toml 声明 Python 3.12；运行依赖为 fastapi、uvicorn、sqlalchemy、psycopg、alembic、pydantic-settings、pwdlib[argon2]、pyjwt、python-multipart、pillow、openai、httpx；开发依赖为 pytest、pytest-cov、aiosqlite。

~~~python
# app/core/config.py
from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://kaogong:kaogong@db:5432/kaogong"
    jwt_secret: str = "development-secret-change-in-production"
    provider_mode: Literal["auto", "live", "demo"] = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"
    upload_dir: Path = Path("/data/uploads")
    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_origins: list[str] = ["http://localhost:3000"]
    cookie_secure: bool = False
    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

    @property
    def effective_provider_mode(self) -> Literal["live", "demo"]:
        if self.provider_mode == "live" and not self.openai_api_key:
            raise ValueError("PROVIDER_MODE=live requires OPENAI_API_KEY")
        if self.provider_mode == "demo":
            return "demo"
        return "live" if self.openai_api_key else "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
~~~

~~~python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="AI 公考错题诊断系统")
    app.state.settings = resolved
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "provider_mode": resolved.effective_provider_mode}

    return app


app = create_app()
~~~

~~~python
# app/core/database.py
from collections.abc import AsyncIterator
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def create_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session
~~~

- [ ] **Step 4: 创建前端基础**

Run: npx create-next-app@latest apps/web --typescript --eslint --tailwind --app --src-dir --import-alias "@/*" --use-npm
Expected: apps/web 创建成功，globals.css 使用 @import "tailwindcss"。

安装运行依赖 @tanstack/react-query、react-hook-form、@hookform/resolvers、zod、lucide-react、recharts、clsx、tailwind-merge；安装开发依赖 vitest、jsdom、@testing-library/react、@testing-library/jest-dom、@testing-library/user-event、msw。

- [ ] **Step 5: 运行最小检查**

Run: cd apps/api && uv run pytest tests/test_health.py -q
Expected: 1 passed.

Run: cd apps/web && npm run lint && npm run build
Expected: 两条命令退出码均为 0。

- [ ] **Step 6: 提交**

~~~bash
git add .gitignore apps/api apps/web
git commit -m "chore: scaffold web and API applications"
~~~

## Task 2: 认证、会话与用户隔离基础

**Files:**
- Create: apps/api/app/models/base.py
- Create: apps/api/app/models/user.py
- Create: apps/api/app/models/review.py
- Create: apps/api/app/schemas/auth.py
- Create: apps/api/app/core/security.py
- Create: apps/api/app/core/rate_limit.py
- Create: apps/api/app/api/deps.py
- Create: apps/api/app/api/router.py
- Create: apps/api/app/api/routes/auth.py
- Create: apps/api/alembic.ini
- Create: apps/api/alembic/env.py
- Create: apps/api/alembic/versions/0001_initial.py
- Create: apps/api/tests/test_auth.py
- Modify: apps/api/app/main.py

**Interfaces:**
- Produces: hash_password、verify_password、create_session_token、get_current_user
- Produces: POST /api/v1/auth/register、login、logout；GET /api/v1/auth/me

- [ ] **Step 1: 写认证失败测试**

~~~python
def test_register_sets_http_only_cookie(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "learner@example.com", "password": "strong-pass-123"},
    )
    assert response.status_code == 201
    assert response.json()["email"] == "learner@example.com"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]


def test_duplicate_email_is_rejected(client):
    payload = {"email": "same@example.com", "password": "strong-pass-123"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "email_already_registered"
~~~

- [ ] **Step 2: 运行并确认失败**

Run: cd apps/api && uv run pytest tests/test_auth.py -q
Expected: FAIL，认证路由返回 404。

- [ ] **Step 3: 实现安全函数和模型**

~~~python
from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash

SESSION_COOKIE = "kaogong_session"
ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_session_token(user_id: str, secret: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode({"sub": user_id, "exp": expires}, secret, algorithm=ALGORITHM)
~~~

User 使用 UUID 字符串主键、规范化唯一邮箱、password_hash、created_at、updated_at；UserSettings 与 User 一对一，daily_review_limit 默认 20。

- [ ] **Step 4: 实现路由、Cookie 与限制**

~~~python
response.set_cookie(
    key=SESSION_COOKIE,
    value=create_session_token(user.id, settings.jwt_secret),
    max_age=7 * 24 * 60 * 60,
    httponly=True,
    samesite="lax",
    secure=settings.cookie_secure,
    path="/",
)
~~~

get_current_user 从 Cookie 解码 sub，并按 User.id 查询。无效令牌返回 401。register/login 每 IP 每分钟最多 10 次；错误响应统一为 code、message、field_errors、request_id。

- [ ] **Step 5: 运行迁移和测试**

Run: cd apps/api && uv run alembic upgrade head && uv run pytest tests/test_auth.py -q
Expected: users、user_settings 表创建，认证测试全部通过。

- [ ] **Step 6: 提交**

~~~bash
git add apps/api/app apps/api/alembic apps/api/alembic.ini apps/api/tests/test_auth.py
git commit -m "feat: add secure email authentication"
~~~

## Task 3: 错题领域、筛选与批量操作

**Files:**
- Create: apps/api/app/models/question.py
- Create: apps/api/app/models/analysis.py
- Create: apps/api/app/schemas/common.py
- Create: apps/api/app/schemas/question.py
- Create: apps/api/app/api/routes/questions.py
- Create: apps/api/tests/test_questions.py
- Modify: apps/api/alembic/versions/0001_initial.py
- Modify: apps/api/app/api/router.py

**Interfaces:**
- Produces: QuestionCreate、QuestionUpdate、QuestionRead、QuestionPage
- Produces: /api/v1/questions CRUD、bulk-status、bulk-delete

- [ ] **Step 1: 写 CRUD 与隔离失败测试**

~~~python
def test_question_is_isolated_by_user(client, register):
    first = register("first@example.com")
    created = client.post("/api/v1/questions", cookies=first.cookies, json=question_payload()).json()
    second = register("second@example.com")
    response = client.get("/api/v1/questions/" + created["id"], cookies=second.cookies)
    assert response.status_code == 404


def test_filters_question_library(client, auth_cookies):
    create_question(client, auth_cookies, module="资料分析", error_reason="计算错")
    create_question(client, auth_cookies, module="言语理解", error_reason="理解错")
    response = client.get(
        "/api/v1/questions?module=资料分析&error_reason=计算错",
        cookies=auth_cookies,
    )
    assert [item["module"] for item in response.json()["items"]] == ["资料分析"]
~~~

- [ ] **Step 2: 运行并确认失败**

Run: cd apps/api && uv run pytest tests/test_questions.py -q
Expected: FAIL，Question 模型或路由不存在。

- [ ] **Step 3: 实现枚举、模型和 Schema**

~~~python
class ExamType(str, Enum):
    NATIONAL = "国考"
    PROVINCIAL = "省考"
    INSTITUTION = "事业编"
    OTHER = "其他"


class ExamModule(str, Enum):
    VERBAL = "言语理解"
    QUANT = "数量关系"
    REASONING = "判断推理"
    DATA = "资料分析"
    KNOWLEDGE = "常识判断"


class MasteryStatus(str, Enum):
    UNMASTERED = "未掌握"
    REVIEWING = "复习中"
    MASTERED = "已掌握"


class QuestionOption(BaseModel):
    label: str = Field(min_length=1, max_length=4)
    content: str = Field(min_length=1, max_length=2000)
~~~

Question 包含设计规格全部字段；options、knowledge_points、tags 使用 JSON；mastery_status 默认未掌握；analysis_status 默认未分析；current_analysis_id 可空。Analysis 表先创建完整结构以解决外键顺序。

- [ ] **Step 4: 实现服务端筛选与写操作**

列表默认 page=1、page_size=20，最大 100；支持 module、knowledge_point、error_reason、mastery_status、analysis_status、created_from、created_to。每条查询从 user_id 条件开始。批量请求最多 100 个 ID；跨用户 ID 计为 not_found，不泄露归属。

~~~python
class BulkStatusRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    mastery_status: MasteryStatus
~~~

- [ ] **Step 5: 运行测试**

Run: cd apps/api && uv run pytest tests/test_questions.py -q
Expected: CRUD、筛选、批量和隔离测试全部通过。

- [ ] **Step 6: 提交**

~~~bash
git add apps/api/app/models apps/api/app/schemas apps/api/app/api/routes/questions.py apps/api/app/api/router.py apps/api/alembic apps/api/tests/test_questions.py
git commit -m "feat: add isolated wrong-question library"
~~~

## Task 4: 图片上传、受控下载与 OCR Provider

**Files:**
- Create: apps/api/app/models/upload.py
- Create: apps/api/app/schemas/upload.py
- Create: apps/api/app/services/storage.py
- Create: apps/api/app/services/providers/base.py
- Create: apps/api/app/services/providers/demo.py
- Create: apps/api/app/services/providers/openai.py
- Create: apps/api/app/services/providers/factory.py
- Create: apps/api/app/api/routes/uploads.py
- Create: apps/api/app/api/routes/providers.py
- Create: apps/api/tests/test_uploads.py
- Create: apps/api/tests/test_providers.py
- Modify: apps/api/app/api/router.py
- Modify: apps/api/alembic/versions/0001_initial.py

**Interfaces:**
- Produces: OcrResult
- Produces: AIProvider.ocr(image_bytes, mime_type) -> OcrResult
- Produces: POST /uploads/questions、GET /uploads/{id}、POST /ocr

- [ ] **Step 1: 写上传与 OCR 失败测试**

~~~python
def test_rejects_non_image(client, auth_cookies):
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=auth_cookies,
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_image_type"


def test_demo_ocr_returns_editable_fields(client, auth_cookies, png_bytes):
    upload = upload_question_image(client, auth_cookies, png_bytes)
    response = client.post("/api/v1/ocr", cookies=auth_cookies, json={"upload_id": upload["id"]})
    assert response.json()["is_demo"] is True
    assert response.json()["stem"]
    assert len(response.json()["options"]) == 4
~~~

- [ ] **Step 2: 运行并确认失败**

Run: cd apps/api && uv run pytest tests/test_uploads.py tests/test_providers.py -q
Expected: FAIL，上传和 Provider 路由不存在。

- [ ] **Step 3: 实现安全存储**

save_image 最多读取 max_upload_bytes + 1 字节；用 Pillow verify 与 load 双重校验；以 UUID 加规范扩展名写入 upload_dir。UploadedAsset 保存 user_id、storage_name、original_name、mime_type、size_bytes、created_at。

~~~python
ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


def inspect_image(raw: bytes) -> tuple[str, str]:
    with Image.open(BytesIO(raw)) as image:
        image.verify()
    with Image.open(BytesIO(raw)) as image:
        detected = image.format
        image.load()
    if detected not in ALLOWED_FORMATS:
        raise UnsupportedImageType()
    return ALLOWED_FORMATS[detected]
~~~

下载路由先按 id 与 user_id 查询 UploadedAsset，再返回 FileResponse；跨用户返回 404。

- [ ] **Step 4: 定义 Provider 协议和演示实现**

~~~python
class OcrResult(BaseModel):
    stem: str
    options: list[QuestionOption]
    user_answer: str = ""
    correct_answer: str
    original_explanation: str
    raw_text: str
    is_demo: bool


class AIProvider(Protocol):
    async def ocr(self, image_bytes: bytes, mime_type: str) -> OcrResult: ...
    async def analyze(self, payload: AnalysisInput) -> AnalysisResult: ...
~~~

DemoProvider.ocr 固定返回一题资料分析示例。factory 根据 effective_provider_mode 返回 DemoProvider 或 OpenAIProvider。

- [ ] **Step 5: 实现 OpenAI OCR**

~~~python
response = await self.client.responses.create(
    model=self.model,
    instructions=OCR_INSTRUCTIONS,
    input=[{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "识别这一道公考题并按结构返回。"},
            {"type": "input_image", "image_url": data_url},
        ],
    }],
    text={"format": {
        "type": "json_schema",
        "name": "ocr_result",
        "strict": True,
        "schema": OcrResult.model_json_schema(),
    }},
)
result = OcrResult.model_validate_json(response.output_text)
return result.model_copy(update={"is_demo": False})
~~~

APIConnectionError、APITimeoutError、RateLimitError、APIStatusError 映射稳定错误码；日志只记录 OpenAI request_id、状态码和本地 request_id。

- [ ] **Step 6: 运行测试并提交**

Run: cd apps/api && uv run pytest tests/test_uploads.py tests/test_providers.py -q
Expected: 上传、损坏文件、跨用户下载、演示 OCR、OpenAI 请求 Mock 全部通过。

~~~bash
git add apps/api/app/models/upload.py apps/api/app/schemas/upload.py apps/api/app/services apps/api/app/api/routes/uploads.py apps/api/app/api/routes/providers.py apps/api/app/api/router.py apps/api/alembic apps/api/tests
git commit -m "feat: add secure uploads and OCR providers"
~~~

## Task 5: AI 错因分析与分析历史

**Files:**
- Create: apps/api/app/schemas/analysis.py
- Modify: apps/api/app/models/analysis.py
- Modify: apps/api/app/services/providers/demo.py
- Modify: apps/api/app/services/providers/openai.py
- Modify: apps/api/app/api/routes/questions.py
- Modify: apps/api/tests/test_providers.py
- Modify: apps/api/tests/test_questions.py

**Interfaces:**
- Produces: AnalysisInput、AnalysisResult
- Produces: POST /api/v1/questions/{id}/analyze
- Produces: QuestionRead.current_analysis

- [ ] **Step 1: 写分析失败测试**

~~~python
def test_manual_analysis_persists_structured_result(client, auth_cookies):
    question = create_question(client, auth_cookies)
    response = client.post("/api/v1/questions/" + question["id"] + "/analyze", cookies=auth_cookies)
    analysis = response.json()
    assert response.status_code == 200
    assert analysis["is_demo"] is True
    assert analysis["cause_analysis"]
    assert analysis["knowledge_points"]
    assert analysis["correct_approach"]


def test_reanalysis_keeps_history(client, auth_cookies):
    question = create_question(client, auth_cookies)
    first = analyze(client, auth_cookies, question["id"])
    second = analyze(client, auth_cookies, question["id"])
    detail = get_question(client, auth_cookies, question["id"])
    assert detail["current_analysis"]["id"] == second["id"]
    assert first["id"] != second["id"]
~~~

- [ ] **Step 2: 运行并确认失败**

Run: cd apps/api && uv run pytest tests/test_questions.py -k analysis -q
Expected: FAIL，analyze 路由返回 404。

- [ ] **Step 3: 实现结构化分析**

~~~python
class AnalysisInput(BaseModel):
    stem: str
    options: list[QuestionOption]
    user_answer: str
    correct_answer: str
    original_explanation: str = ""
    ocr_raw_text: str = ""
    module: ExamModule


class AnalysisResult(BaseModel):
    cause_analysis: str
    knowledge_points: list[str]
    correct_approach: str
    study_advice: str
    suggested_error_reason: ErrorReason
    raw_response: dict[str, object]
    provider_name: str
    model_name: str
    is_demo: bool
~~~

DemoProvider 按 module 生成确定性知识点和建议。OpenAIProvider 复用 Responses API 与 AnalysisResult JSON Schema。路由先把状态改为分析中，Provider 成功后新增 Analysis 并更新 current_analysis_id、knowledge_points、error_reason、analysis_status；失败时写入失败状态。每用户每分钟最多 10 次，服务端不做业务级自动重试。

- [ ] **Step 4: 运行测试并提交**

Run: cd apps/api && uv run pytest tests/test_questions.py tests/test_providers.py -q
Expected: 分析、失败状态、重新分析历史和隔离测试全部通过。

~~~bash
git add apps/api/app/schemas/analysis.py apps/api/app/models/analysis.py apps/api/app/services/providers apps/api/app/api/routes/questions.py apps/api/tests
git commit -m "feat: add structured AI mistake analysis"
~~~

## Task 6: 今日复习、统计与 Dashboard 聚合

**Files:**
- Create: apps/api/app/schemas/review.py
- Create: apps/api/app/schemas/analytics.py
- Create: apps/api/app/services/review.py
- Create: apps/api/app/services/analytics.py
- Create: apps/api/app/api/routes/reviews.py
- Create: apps/api/app/api/routes/analytics.py
- Create: apps/api/app/api/routes/dashboard.py
- Create: apps/api/tests/test_reviews.py
- Create: apps/api/tests/test_analytics.py
- Modify: apps/api/app/api/router.py

**Interfaces:**
- Produces: score_review_candidate(question, weak_points, now) -> int
- Produces: GET /reviews/today、POST /reviews/{question_id}
- Produces: GET /analytics/summary、GET /dashboard

- [ ] **Step 1: 写排序和统计失败测试**

~~~python
def test_review_score_matches_spec():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    question = Question(
        mastery_status="未掌握",
        created_at=now - timedelta(days=2),
        knowledge_points=["增长率计算"],
    )
    assert score_review_candidate(question, {"增长率计算"}, now) == 150


def test_reviewed_today_is_completed_not_pending(client, auth_cookies):
    question = create_question(client, auth_cookies)
    submit_review(client, auth_cookies, question["id"], "复习中")
    today = client.get("/api/v1/reviews/today", cookies=auth_cookies).json()
    assert question["id"] not in [item["id"] for item in today["pending"]]
    assert question["id"] in [item["question_id"] for item in today["completed"]]
~~~

- [ ] **Step 2: 运行并确认失败**

Run: cd apps/api && uv run pytest tests/test_reviews.py tests/test_analytics.py -q
Expected: FAIL，review 服务和路由不存在。

- [ ] **Step 3: 实现确定性复习算法**

~~~python
def score_review_candidate(question, weak_points: set[str], now: datetime) -> int:
    score = 0
    if question.mastery_status == MasteryStatus.UNMASTERED:
        score += 100
    elif question.mastery_status == MasteryStatus.REVIEWING:
        score += 60
    if question.created_at >= now - timedelta(days=7):
        score += 30
    if weak_points.intersection(question.knowledge_points):
        score += 20
    return score
~~~

候选集、当日排除和稳定排序严格遵循 Global Constraints。提交复习时新增 ReviewRecord 并更新 Question.mastery_status；daily_review_limit 只接受 10、20、30、50。

- [ ] **Step 4: 实现统计与 Dashboard 聚合**

AnalyticsSummary 返回 total_questions、module_distribution、knowledge_point_ranking、error_reason_distribution、mastery_distribution、trend_7d、trend_30d、ai_summary、is_demo。趋势按每天新录入错题数统计并补零。DashboardResponse 返回 today_review、current_question、recent_questions、weak_modules、trend_7d、ai_advice、provider_mode。

演示建议根据最高模块和知识点由模板生成。真实统计建议不会随页面加载自动产生付费调用，只有显式刷新才调用真实 Provider。

- [ ] **Step 5: 运行测试并提交**

Run: cd apps/api && uv run pytest tests/test_reviews.py tests/test_analytics.py -q
Expected: 排序、数量限制、日期补零、聚合与用户隔离测试全部通过。

Run: cd apps/api && uv run pytest -q
Expected: 后端全套测试通过。

~~~bash
git add apps/api/app/schemas apps/api/app/services/review.py apps/api/app/services/analytics.py apps/api/app/api/routes apps/api/tests
git commit -m "feat: add daily review and learning analytics"
~~~

## Task 7: 前端设计系统、认证页面与应用壳

**Files:**
- Create: apps/web/src/lib/api.ts
- Create: apps/web/src/lib/query-client.tsx
- Create: apps/web/src/lib/schemas.ts
- Create: apps/web/src/lib/cn.ts
- Create: apps/web/src/types/api.ts
- Create: apps/web/src/hooks/use-session.ts
- Create: apps/web/src/components/ui/button.tsx
- Create: apps/web/src/components/ui/input.tsx
- Create: apps/web/src/components/ui/field.tsx
- Create: apps/web/src/components/layout/sidebar.tsx
- Create: apps/web/src/components/layout/app-header.tsx
- Create: apps/web/src/app/login/page.tsx
- Create: apps/web/src/app/register/page.tsx
- Create: apps/web/src/app/(app)/layout.tsx
- Create: apps/web/src/test/setup.ts
- Create: apps/web/src/test/test-utils.tsx
- Modify: apps/web/src/app/globals.css
- Modify: apps/web/src/app/layout.tsx

**Interfaces:**
- Produces: apiFetch<T>(path, init) -> Promise<T>
- Produces: useSession() -> UseQueryResult<User>
- Produces: AppShell

- [ ] **Step 1: 写登录失败测试**

~~~tsx
it("submits credentials and redirects to dashboard", async () => {
  server.use(
    http.post("http://localhost:8000/api/v1/auth/login", () =>
      HttpResponse.json({ id: "u1", email: "learner@example.com" }),
    ),
  );
  renderWithProviders(<LoginPage />);
  await userEvent.type(screen.getByLabelText("邮箱"), "learner@example.com");
  await userEvent.type(screen.getByLabelText("密码"), "strong-pass-123");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(mockReplace).toHaveBeenCalledWith("/dashboard");
});
~~~

- [ ] **Step 2: 运行并确认失败**

Run: cd apps/web && npm test -- --run src/app/login
Expected: FAIL，登录页面或 Vitest 配置不存在。

- [ ] **Step 3: 实现 API 客户端和认证页面**

~~~typescript
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(
    (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1") + path,
    { ...init, headers, credentials: "include" },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => ({
      code: "network_error",
      message: "请求失败，请稍后重试",
    }));
    throw new ApiError(response.status, body);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
~~~

登录和注册使用 React Hook Form + Zod；中文字段错误不清空输入；成功跳转 /dashboard。useSession 请求 /auth/me，401 跳转 /login。

- [ ] **Step 4: 实现视觉 Token 和应用壳**

globals.css 使用背景 #F7F8FC、主文字 #0D1B4C、主色 #4F46E5、成功 #10B981、复习中 #F59E0B、错误 #EF5D68、边框 #E4E8F2。侧边栏桌面宽 240px，移动端为抽屉；导航顺序严格匹配视觉稿。图标仅使用 lucide-react，所有按钮具备 focus-visible 状态。

- [ ] **Step 5: 运行测试和构建**

Run: cd apps/web && npm test -- --run && npm run lint && npm run build
Expected: 登录、注册和应用壳测试通过，lint 与 build 退出码 0。

- [ ] **Step 6: 提交**

~~~bash
git add apps/web
git commit -m "feat: add authenticated application shell"
~~~

## Task 8: 错题录入、错题库与详情 UI

**Files:**
- Create: apps/web/src/components/questions/question-form.tsx
- Create: apps/web/src/components/questions/image-ocr-panel.tsx
- Create: apps/web/src/components/questions/question-filters.tsx
- Create: apps/web/src/components/questions/question-table.tsx
- Create: apps/web/src/components/questions/analysis-panel.tsx
- Create: apps/web/src/app/(app)/questions/page.tsx
- Create: apps/web/src/app/(app)/questions/new/page.tsx
- Create: apps/web/src/app/(app)/questions/[id]/page.tsx
- Create: apps/web/src/components/questions/question-form.test.tsx
- Create: apps/web/src/components/questions/question-table.test.tsx
- Modify: apps/web/src/types/api.ts

**Interfaces:**
- Produces: QuestionForm onSubmit contract
- Consumes: upload、ocr、questions、analyze API
- Produces: URL 驱动的 QuestionFilters

- [ ] **Step 1: 写 OCR 回填和批量操作失败测试**

~~~tsx
it("fills OCR fields without saving automatically", async () => {
  renderWithProviders(<QuestionForm mode="image" />);
  await uploadImageAndRunOcr();
  expect(screen.getByLabelText("题干")).toHaveValue("根据材料，下列说法正确的是？");
  expect(mockCreateQuestion).not.toHaveBeenCalled();
});


it("requires confirmation before bulk deletion", async () => {
  renderWithProviders(<QuestionTable items={twoQuestions} />);
  await selectAllRows();
  await userEvent.click(screen.getByRole("button", { name: "批量删除" }));
  expect(screen.getByRole("dialog", { name: "确认删除错题" })).toBeVisible();
});
~~~

- [ ] **Step 2: 运行并确认失败**

Run: cd apps/web && npm test -- --run src/components/questions
Expected: FAIL，问题组件不存在。

- [ ] **Step 3: 实现录入流程**

页面提供“图片识别”和“手动录入”切换。图片模式桌面左图右表，窄屏上下布局；上传后显式点击“开始识别”，OCR 结果只调用 form.reset 合并，不触发 create mutation。选项默认 A–D，可增删。保存成功跳转 /questions/{id}。

- [ ] **Step 4: 实现列表和详情**

筛选写入 searchParams。表格字段为题目摘要、模块、知识点、错因、掌握状态、AI 状态、创建时间、操作。批量删除必须确认。详情页显示题目、答案、解析、AI 分析、笔记、掌握状态和复习记录；编辑保存与 AI 分析独立。Provider 错误显示稳定中文提示与重新分析按钮；演示结果显示“演示模式”。

- [ ] **Step 5: 运行测试和构建**

Run: cd apps/web && npm test -- --run src/components/questions && npm run lint && npm run build
Expected: 录入、OCR 回填、筛选、批量确认、分析重试测试通过，构建成功。

- [ ] **Step 6: 提交**

~~~bash
git add apps/web/src/components/questions apps/web/src/app/\(app\)/questions apps/web/src/types/api.ts
git commit -m "feat: add question capture and library UI"
~~~

## Task 9: Dashboard、今日复习与统计 UI

**Files:**
- Create: apps/web/src/components/dashboard/review-hero.tsx
- Create: apps/web/src/components/dashboard/ai-advice.tsx
- Create: apps/web/src/components/dashboard/recent-questions.tsx
- Create: apps/web/src/components/review/review-session.tsx
- Create: apps/web/src/components/analytics/module-chart.tsx
- Create: apps/web/src/components/analytics/trend-chart.tsx
- Create: apps/web/src/components/analytics/distribution-list.tsx
- Create: apps/web/src/app/(app)/dashboard/page.tsx
- Create: apps/web/src/app/(app)/review/page.tsx
- Create: apps/web/src/app/(app)/analytics/page.tsx
- Create: apps/web/src/components/dashboard/review-hero.test.tsx
- Create: apps/web/src/components/review/review-session.test.tsx
- Create: apps/web/src/components/analytics/module-chart.test.tsx

**Interfaces:**
- Consumes: DashboardResponse、TodayReviewResponse、AnalyticsSummary
- Produces: 与视觉稿一致的首页和完整复习闭环

- [ ] **Step 1: 写主流程失败测试**

~~~tsx
it("shows today's review as the dominant dashboard action", () => {
  renderWithProviders(<ReviewHero data={dashboard.today_review} />);
  expect(screen.getByRole("heading", { name: "今日复习" })).toBeVisible();
  expect(screen.getByText("12 / 20")).toBeVisible();
  expect(screen.getByRole("link", { name: "继续复习" })).toHaveAttribute("href", "/review");
});


it("submits mastery and advances", async () => {
  renderWithProviders(<ReviewSession data={todayReview} />);
  await userEvent.click(screen.getByRole("button", { name: "查看答案与解析" }));
  await userEvent.click(screen.getByRole("button", { name: "复习中" }));
  expect(mockSubmitReview).toHaveBeenCalledWith(expect.objectContaining({
    result_status: "复习中",
  }));
});
~~~

- [ ] **Step 2: 运行并确认失败**

Run: cd apps/web && npm test -- --run src/components/dashboard src/components/review src/components/analytics
Expected: FAIL，组件不存在。

- [ ] **Step 3: 实现 Dashboard**

今日复习为最大区域；进度、预计时间、当前题目和继续复习同组；快速录入与 AI 建议为次级区域；最近错题为轻量表格。空状态引导录入，全部完成状态引导查看统计。

- [ ] **Step 4: 实现今日复习与统计**

复习一次聚焦一道题，默认隐藏答案；展开后提交三种状态与笔记。提交成功更新 Query 缓存且不重复出现。统计使用 Recharts，但每张图同时提供标题、数值和列表备用信息；颜色不是唯一编码。真实刷新建议必须由用户点击触发。

- [ ] **Step 5: 运行测试、构建并提交**

Run: cd apps/web && npm test -- --run && npm run lint && npm run build
Expected: 前端全部测试和构建通过。

~~~bash
git add apps/web/src/components/dashboard apps/web/src/components/review apps/web/src/components/analytics apps/web/src/app/\(app\)/dashboard apps/web/src/app/\(app\)/review apps/web/src/app/\(app\)/analytics
git commit -m "feat: add review cockpit and analytics UI"
~~~

## Task 10: 容器、演示数据、文档与全链路验收

**Files:**
- Create: apps/api/Dockerfile
- Create: apps/web/Dockerfile
- Create: docker-compose.yml
- Create: .env.example
- Create: Makefile
- Create: scripts/dev-preflight.sh
- Create: scripts/smoke.sh
- Create: apps/api/app/seed.py
- Create: README.md
- Modify: apps/web/src/app/page.tsx
- Modify: .gitignore

**Interfaces:**
- Produces: make dev、make test、make seed、make smoke
- Produces: demo@example.com / demo-pass-123
- Produces: Chrome 验收 URL http://localhost:3000

- [ ] **Step 1: 写烟雾测试脚本**

~~~bash
#!/usr/bin/env bash
set -euo pipefail
api=http://localhost:8000
web=http://localhost:3000
curl --fail --silent "$api/health" | grep -q '"status":"ok"'
curl --fail --silent "$web/login" | grep -q '登录'
printf 'smoke checks passed\n'
~~~

- [ ] **Step 2: 创建容器定义**

docker-compose.yml 定义 db、api、web；db 使用 postgres:17-alpine 和健康检查；api 等待 db 健康后执行 alembic upgrade head 再启动 uvicorn；web 监听 3000；uploads 与 postgres_data 使用命名卷。API Dockerfile 使用 Python 3.12 slim 与 uv；Web Dockerfile 使用 Node 24 多阶段构建并以非 root 用户运行。

- [ ] **Step 3: 创建幂等演示数据**

seed.py 创建 demo@example.com / demo-pass-123、五大模块各至少 2 道题、三种掌握状态、五种错因、分析和复习记录。重复运行不得新增重复用户或重复样例。

- [ ] **Step 4: 创建入口和文档**

~~~make
.PHONY: dev test seed smoke down
dev:
	docker compose up --build
test:
	cd apps/api && uv run pytest -q
	cd apps/web && npm test -- --run
	cd apps/web && npm run lint
	cd apps/web && npm run build
seed:
	docker compose exec api python -m app.seed
smoke:
	bash scripts/smoke.sh
down:
	docker compose down
~~~

README 包含依赖检查、Compose 启动、缺少 Compose 插件的安装提示、演示模式、真实 OpenAI 配置、迁移、测试、演示账号、端口和 Cookie 主机名问题。前后端统一使用 localhost，不混用 127.0.0.1。

- [ ] **Step 5: 运行自动验证**

Run: cd apps/api && uv run pytest -q
Expected: 全部通过。

Run: cd apps/web && npm test -- --run && npm run lint && npm run build
Expected: 全部通过。

Run: docker compose config
Expected: 配置合法；若当前 CLI 缺少 Compose 插件，先按 README 安装再重跑，不用其他 YAML 检查替代最终证据。

Run: docker compose up --build -d && docker compose exec api python -m app.seed && bash scripts/smoke.sh
Expected: smoke checks passed。

- [ ] **Step 6: 使用 Chrome 完成产品验收**

通过用户指定的 Chrome 打开 http://localhost:3000：

1. 注册并刷新，确认登录保持。
2. 上传 PNG，执行演示 OCR，修改题干后保存。
3. 手动执行 AI 分析，确认错因、知识点、正确思路和演示标签。
4. 在错题库筛选并批量修改状态。
5. 今日复习展开答案、填写笔记并标记复习中。
6. Dashboard 进度和最近错题同步更新。
7. 统计页五类统计与趋势有数据。
8. 第二个用户访问第一个用户的详情 ID 得到 404。
9. 1440×1024 与窄屏均无裁切和横向溢出。

- [ ] **Step 7: 对照视觉稿做 Design QA**

同一 1440×1024 视口捕获参考稿与实际 Dashboard。并排检查侧边栏、信息层级、间距、字体、边框、圆角、进度条、按钮和表格密度；修复差异后重新比较。

- [ ] **Step 8: 最终提交**

Run: git diff --check
Expected: 无输出。

Run: git status --short
Expected: 只保留用户原有的 D gitInit.txt，不存在未提交系统文件。

~~~bash
git add .env.example Makefile README.md docker-compose.yml apps/api/Dockerfile apps/api/app/seed.py apps/web/Dockerfile scripts apps/web/src/app/page.tsx .gitignore
git commit -m "docs: add reproducible local runtime and QA"
~~~

## 规格覆盖自查

| 设计规格范围 | 实施任务 |
|---|---|
| 项目目标、前后端分离、默认演示模式 | Task 1、Task 4、Task 10 |
| 注册、登录、会话保持、用户隔离 | Task 2、Task 3、Task 10 |
| 错题数据模型、CRUD、筛选、批量操作 | Task 3、Task 8 |
| 图片上传、受控下载、OCR 与人工修正 | Task 4、Task 8 |
| AI 错因、知识点、思路、建议、历史与重试 | Task 5、Task 8 |
| 今日复习算法、状态、笔记和每日数量 | Task 6、Task 9 |
| 五类统计、7/30 日趋势和 AI 总结 | Task 6、Task 9 |
| 选定 Dashboard 视觉、响应式、可访问性 | Task 7、Task 9、Task 10 |
| 统一错误结构、速率边界、上传和 Cookie 安全 | Task 2、Task 4、Task 5 |
| PostgreSQL、迁移、Compose、种子数据和运行文档 | Task 1、Task 2、Task 10 |
| 后端、前端、Chrome 与视觉对照验收 | 每个任务的测试步骤及 Task 10 |

自查结论：设计规格各节均有对应任务；没有缩减 P0 页面、流程、用户隔离或真实/演示 Provider 双路径。

## 完成审计

宣称完成前逐条检查设计规格第 13 节 MVP 验收矩阵，并为每项记录 pytest 测试名、Vitest 测试名、构建输出、Chrome 截图或实际 API 响应。缺少证据即视为未完成。

~~~bash
cd apps/api && uv run pytest -q
cd ../web && npm test -- --run && npm run lint && npm run build
cd ../.. && docker compose config
docker compose up --build -d
docker compose exec api python -m app.seed
bash scripts/smoke.sh
git diff --check
git status --short
~~~

## 官方实现参考

- Next.js App Router: https://nextjs.org/docs/app
- Next.js 安装: https://nextjs.org/docs/app/getting-started/installation
- Tailwind CSS + Next.js: https://tailwindcss.com/docs/installation/framework-guides/nextjs
- FastAPI 测试: https://fastapi.tiangolo.com/tutorial/testing/
- OpenAI Python SDK: https://github.com/openai/openai-python
- OpenAI Structured Outputs 类型: https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_create_params.py
