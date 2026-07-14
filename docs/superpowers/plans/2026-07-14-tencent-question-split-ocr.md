# 腾讯云 QuestionSplitOCR 增量接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` for independent tasks and keep every implementation task in red-green-refactor order.

**Goal:** 在现有 AI 公考错题诊断系统中完成安全、可测试、可部署的腾讯云 QuestionSplitOCR 多题识别流程，同时保留演示 AI 和现有保存/分析闭环。

**Architecture:** 复用现有上传与 `/ocr` 路由；新增独立 OCR Provider、Service、Normalizer 和一个持久化 `ocr_tasks` 表。腾讯同步 SDK 在线程池中受 Semaphore、重试、双窗口用户限流和幂等控制。前端只扩展现有 `/questions/new` 页面为多题可编辑草稿，不接触腾讯云。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、Pydantic、Pillow、pypdf、腾讯云官方 Python OCR SDK、pytest；Next.js 16、React 19、TypeScript、React Hook Form、Vitest。

## 全局约束

- 不重建项目，不创建重复 OCR 页面、上传接口或草稿表。
- 固定 `QuestionSplitOCR`、`2018-11-19`、`ocr.tencentcloudapi.com`、`UseNewModel=false`、`EnableImageCrop=true`、`EnableOnlyDetectBorder=false`。
- 前端只调用同源后端；密钥、签名、Base64 和腾讯矫正图不得进入前端、日志、数据库、测试夹具或 Git。
- OCR 不推断最终答案，不生成 AI 解析，不自动保存正式错题。
- 默认测试全 Mock，真实冒烟必须显式开关且最多一次。
- 不推送远程；保留所有无关用户修改。

## Task 1：建立验收护栏和依赖

**Files:**
- Modify: `apps/api/pyproject.toml`, `apps/api/uv.lock`
- Modify: `.env.example`, `docker-compose.yml`
- Modify: `apps/api/app/core/config.py`
- Modify/Create: `apps/api/tests/test_config.py`, `apps/api/tests/test_ocr_status.py`

- [ ] 先写失败测试：OCR 配置默认值、缺密钥不阻止启动、Tencent 未配置状态、固定参数不可由客户端覆盖。
- [ ] 确认红灯。
- [ ] 添加已核实的官方 OCR SDK和 `pypdf` 锁定依赖。
- [ ] 实现 OCR 专用 Settings；Compose 只向 API 传递后端变量。
- [ ] 实现不计费的 `/ocr/status` 最小切片。
- [ ] 运行定向测试并确认绿灯。

## Task 2：扩展上传与真实文件验证

**Files:**
- Modify: `apps/api/app/services/storage.py`
- Modify: `apps/api/app/api/routes/uploads.py`
- Modify: `apps/api/app/schemas/upload.py`
- Modify: `apps/api/tests/test_uploads.py`
- Create: `apps/api/tests/fixtures/*` 中程序化最小图片/PDF辅助代码（不得包含 Base64 大块）

- [ ] 先写 PNG/JPEG/BMP/PDF、空文件/空名、伪装/损坏、WEBP 拒绝、页数和 Base64 上限的失败测试。
- [ ] 确认红灯。
- [ ] 用 Pillow/pypdf 实现真实内容验证、SHA-256、元数据、质量 warning 与受控保存。
- [ ] 保持用户隔离下载和 UUID 路径规则。
- [ ] 运行上传测试与原有回归。

## Task 3：定义 OCR 领域结构与腾讯规范化器

**Files:**
- Create: `apps/api/app/schemas/ocr.py`
- Create: `apps/api/app/services/ocr/types.py`
- Create: `apps/api/app/services/ocr/normalizer.py`
- Create: `apps/api/tests/test_ocr_normalizer.py`

- [ ] 先为单题、多题、题号、题型、Question/Option 排序、全角标签、缺标签回退、坐标、Figure、Table、Answer、Parse、空结果写失败测试。
- [ ] 确认红灯。
- [ ] 实现纯函数规范化器；不纠正文意，不伪造置信度，不输出腾讯 ImageBase64。
- [ ] 覆盖需求后端用例 1–14、41、46 的结构部分。

## Task 4：实现独立 OCR Provider 与错误映射

**Files:**
- Create: `apps/api/app/services/ocr/base.py`
- Create: `apps/api/app/services/ocr/tencent.py`
- Create: `apps/api/app/services/ocr/mock.py`
- Create: `apps/api/app/services/ocr/factory.py`
- Create: `apps/api/app/services/ocr/errors.py`
- Create: `apps/api/tests/test_tencent_ocr_provider.py`

- [ ] 先用假 SDK 客户端写请求参数、客户端复用、图片/PDF、线程池、重试和全部错误映射失败测试。
- [ ] 确认红灯。
- [ ] 构造固定 `QuestionSplitOCRRequest`，只设置 ImageBase64。
- [ ] 在线程池执行同步 SDK；实现超时、最多 2 次选择性重试和安全异常转换。
- [ ] 实现明确标记的 Mock 多题 Provider，绝不冒充生产结果。
- [ ] 运行 Provider 测试，证明普通测试没有网络调用。

## Task 5：持久化幂等、并发、限流与裁剪

**Files:**
- Create: `apps/api/app/models/ocr_task.py`
- Create: `apps/api/alembic/versions/0006_question_split_ocr.py`
- Modify: `apps/api/alembic/env.py`, `apps/api/app/models/__init__.py`（如存在）
- Create: `apps/api/app/services/ocr/service.py`
- Create: `apps/api/app/services/ocr/cropper.py`
- Modify: `apps/api/app/core/rate_limit.py`, `apps/api/app/main.py`
- Create: `apps/api/tests/test_ocr_service.py`, `apps/api/tests/test_migrations.py`

- [ ] 先写每分钟 5、每小时 50、Semaphore=2、队列有界、重复文件只计费一次、失败可重试、裁剪越界、文件清理的失败测试。
- [ ] 确认红灯。
- [ ] 新增唯一幂等任务表，结果只保存规范化 JSON。
- [ ] 实现每键锁、持久化结果复用、跨实例处理中保护和失败状态恢复。
- [ ] 实现受控题目/Figure/Table 裁剪与失败清理；不保存腾讯 Base64。
- [ ] 完成定向测试与 Alembic upgrade/downgrade 测试。

## Task 6：接入现有 OCR 路由

**Files:**
- Modify: `apps/api/app/api/routes/providers.py`
- Modify: `apps/api/app/api/router.py`
- Modify: `apps/api/app/api/deps.py`
- Modify: `apps/api/app/main.py`
- Replace/modify: `apps/api/tests/test_uploads.py`, `apps/api/tests/test_ocr_api.py`

- [ ] 先写认证、状态、请求/响应、RequestId、无题、未配置、错误 envelope、幂等 API 测试。
- [ ] 确认红灯。
- [ ] 路由只做认证、输入校验和 Service 调用；不直接接触 SDK。
- [ ] 保留 `/api/v1/ocr` 路径并扩展 JSON 请求，不新建重复识别接口。
- [ ] 记录结构化安全日志并验证响应无密钥、Base64、绝对路径和栈。

## Task 7：保存视觉上下文并传递给现有 AI

**Files:**
- Modify: `apps/api/app/models/question.py`
- Modify: `apps/api/app/schemas/question.py`, `apps/api/app/schemas/analysis.py`
- Modify: `apps/api/app/api/routes/questions.py`
- Modify: `apps/api/app/services/providers/base.py`, `demo.py`, `openai.py`
- Modify: `apps/api/alembic/versions/0006_question_split_ocr.py`
- Modify: `apps/api/tests/test_questions.py`, `apps/api/tests/test_providers.py`

- [ ] 先写 OCR metadata 所有权、识别答案不自动成为正确答案、受控图片载入、AI 同时收到文字与图像的失败测试。
- [ ] 确认红灯。
- [ ] 给 Question 增加一个可选 `ocr_metadata` JSON 字段，不改变现有字段语义。
- [ ] 保存前验证所有上传/裁剪资源归属当前用户。
- [ ] 分析时读取受控资源字节；Demo 忽略视觉输入，OpenAI 使用输入图像但不暴露内部 URL。

## Task 8：扩展现有前端为多题草稿

**Prerequisite:** 在写 Next.js 代码前查阅 `apps/web/AGENTS.md` 指定的已安装 Next.js 16 文档。

**Files:**
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/components/questions/image-ocr-panel.tsx`
- Create: `apps/web/src/components/questions/ocr-question-card.tsx`
- Modify: `apps/web/src/components/questions/question-form.tsx`
- Modify: `apps/web/src/components/questions/question-detail.tsx`
- Modify: `apps/web/src/components/questions/question-form.test.tsx`
- Create: `apps/web/src/components/questions/image-ocr-panel.test.tsx`, `ocr-question-card.test.tsx`

- [ ] 先写需求列出的 18 个前端行为的失败测试，并确认红灯。
- [ ] 支持图片/拍照/PDF、页码、预览、状态、明确 loading 和按钮禁用。
- [ ] 显示独立多题卡片、题数、题号、题型、原图/裁剪、Figure/Table、warning、识别答案/解析。
- [ ] 卡片全部文本可编辑，可删除；载入现有表单前保护用户已编辑内容。
- [ ] 识别答案/解析只通过显式“采用”动作进入正式字段。
- [ ] OCR 不自动保存；保存后详情显示视觉上下文并复用现有 AI 按钮。
- [ ] 运行 Vitest、ESLint 和独立 TypeScript 检查。

## Task 9：部署、文档与真实冒烟入口

**Files:**
- Modify: `README.md`, `docs/deployment/railway.md`
- Create: `docs/tencent-question-split-ocr.md`
- Create: `apps/api/tests/test_tencent_ocr_e2e.py`
- Modify: `scripts/production-smoke.sh`（只做兼容性修正，不默认计费）

- [ ] 写清 QuestionSplitOCR 选择原因、服务开通、最小权限子账号、28 项运行文档内容和故障处理。
- [ ] E2E 测试默认 skip；仅显式开关、有效密钥和用户提供的样本文件下调用一次。
- [ ] 更新 Railway 后端变量清单；不写真实值，不自动购买或开通付费服务。
- [ ] 在被 Git 忽略的根 `.env` 写入用户授权的本地配置，权限设为 600，验证时绝不输出值。

## Task 10：完整验证与 Chrome 验收

- [ ] API：完整 pytest、后端 lint、类型检查、应用启动、OpenAPI、认证、status。
- [ ] Web：完整 Vitest、ESLint、`tsc --noEmit`、生产 build。
- [ ] DB：全新 PostgreSQL `alembic upgrade head`、`alembic check`、必要的 downgrade/upgrade。
- [ ] 安全：扫描受跟踪文件中的密钥名误用、真实密钥、长 Base64、TODO/pass/空实现；确认 `.env` 未跟踪。
- [ ] Chrome 桌面与窄屏：Mock 图片多题、Figure、Table、PDF 页码、错误提示、重新识别确认、删除、载入、保存、详情和 AI 分析。
- [ ] 如真实凭证已轮换且显式开关打开，仅执行一次真实 OCR smoke；记录脱敏 RequestId 和题数。
- [ ] 对 54 项完成条件逐条给出证据，未完成项如实标记。
- [ ] 输出需求指定的 28 节最终报告、实际命令结果和 `git diff` 摘要；不推送。
