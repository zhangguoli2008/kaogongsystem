# Tencent QuestionSplitOCR 正式环境验收报告

验收日期：2026-07-14（Asia/Shanghai）

验收范围：AI 公考错题诊断系统的 QuestionSplitOCR 增量接入、演示 AI、模拟 OCR、Railway 正式环境、Web 同源 API 代理和 GitHub 发布前质量门禁。

部署源码提交：7f5d8f1（feat: complete QuestionSplitOCR workflow）

正式地址：

- Web：https://web-production-3ce0.up.railway.app
- API：https://api-production-f136.up.railway.app
- API 最新验收部署：a1835ffe-b32e-463a-9356-1937e6ae628e
- Web 验收部署：760d81e8-e2bf-44ad-a026-cd443df546a8

结论：用户批准的“演示 AI + 模拟 OCR”正式环境范围已通过自动化、PostgreSQL 17、生产冒烟和 API 重部署持久化验收。真实腾讯云付费调用未执行；生产 Chrome 自动化因 Chrome 控制连接器在打开页面前发生运行时错误而未执行，已由此前本地 Chrome 全流程验收和本次正式环境 HTTP 端到端测试补充覆盖。

## 1. 原 OCR 与上传流程

系统没有另建第二套录题页面。现有“新增错题”页继续提供手工录入和图片/PDF 识别，上传、OCR 草稿、人工修改、保存错题、主动触发 AI 诊断组成一条连续流程。

上传文件先进入受用户隔离的 UploadedAsset，再由 OCR 任务引用。源文件、整题裁剪、Figure、Table 和选项裁剪都通过受鉴权的资产接口读取，不暴露真实磁盘路径。

## 2. 方案与架构

调用链为：浏览器 → Web 同源 /api/v1 代理 → FastAPI → OCRService → Mock 或 Tencent Provider → 规范化 → 可编辑多题草稿 → 用户保存 → 演示 AI。

PROVIDER_MODE 与 OCR_PROVIDER 相互独立。本次生产固定为 PROVIDER_MODE=demo、OCR_PROVIDER=mock，避免任何 OpenAI 或腾讯云付费调用。

## 3. 主要变更文件

后端核心文件：

- apps/api/app/services/ocr/service.py：持久化编排、幂等、租约、并发和终态 CAS。
- apps/api/app/services/ocr/tencent.py：官方 SDK Provider。
- apps/api/app/services/ocr/normalizer.py：QuestionSplitOCR 多题结构规范化。
- apps/api/app/services/ocr/cropper.py：受限裁剪生成。
- apps/api/app/services/ocr/mock.py：确定性多题演示数据。
- apps/api/app/core/upload_body_limit.py：解析 multipart 前的请求体上限与入口并发保护。
- apps/api/app/core/async_tasks.py：取消安全的线程任务等待。
- apps/api/alembic/versions/0006_question_split_ocr.py：OCR 任务与资产元数据迁移。

前端核心文件：

- apps/web/src/components/questions/image-ocr-panel.tsx：上传、PDF 页码、识别状态和多题草稿。
- apps/web/src/components/questions/ocr-question-card.tsx：单题校对、答案/解析确认和视觉素材。
- apps/web/src/components/questions/question-form.tsx：连续保存与待处理状态保护。

运维与测试文件：

- scripts/production-smoke.sh
- docs/deployment/railway.md
- docs/tencent-question-split-ocr.md
- apps/api/tests/test_tencent_ocr_e2e.py

## 4. 依赖变更

后端使用官方 tencentcloud-sdk-python-ocr；pypdf 处理 PDF 指定页；Pillow 验证和裁剪图片；现有 FastAPI、SQLAlchemy、Alembic 与 PostgreSQL 架构保持不变。依赖锁文件已经由 uv 校验。

## 5. 配置策略

生产环境只写入非敏感 OCR 限额、超时、并发、租约和速率参数。TENCENTCLOUD_REGION 为可选空配置，本次未在 Railway 创建该变量，由应用使用空默认值。未读取、未部署、未提交 OPENAI_API_KEY、TENCENTCLOUD_SECRET_ID 或 TENCENTCLOUD_SECRET_KEY。

应用启动时校验跨参数约束，例如每分钟限制不得大于每小时限制，处理租约必须覆盖排队、所有重试和额外 30 秒安全余量。

## 6. Provider 位置

Provider 接口和工厂位于 apps/api/app/services/ocr。mock 返回确定性 QuestionSplitOCR 形状的数据；tencent_question_split 是唯一真实腾讯实现。GET /api/v1/ocr/status 可在不暴露密钥的前提下报告 Provider、是否已配置、能力和固定 API 名称。

## 7. 官方 SDK 调用

真实 Provider 固定使用：

- Action：QuestionSplitOCR
- Version：2018-11-19
- Endpoint：ocr.tencentcloudapi.com
- UseNewModel：false
- EnableImageCrop：true
- EnableOnlyDetectBorder：false

请求只向官方 SDK 提交受控的 ImageBase64；日志和 API 响应均禁止输出 Base64、SecretId、SecretKey 或内部 storage_name。

## 8. API 路径

保留并扩展以下路径：

- POST /api/v1/uploads/questions：上传图片或 PDF。
- GET /api/v1/uploads/{asset_id}：读取本人资产。
- POST /api/v1/ocr：按 upload_id 和可选 PDF 页码识别。
- GET /api/v1/ocr/status：读取安全能力状态。
- POST /api/v1/questions：保存人工确认后的单题。
- POST /api/v1/questions/{question_id}/analyze：用户主动触发 AI 诊断。

正式 Web 通过同源 /api/v1 路径代理 API，302/307/308 Location 会被约束在 Web 公共域名。

## 9. 前端行为

识别结果以多张可编辑题卡呈现。用户可以逐题修改题干、选项、科目、题型、正确答案、本人答案和解析；保存一题后页面不跳走，已保存题卡消失，其余草稿和同一次 OCR 结果保留。

保存过程中整张表单与 OCR 面板锁定，防止延迟响应期间改文件、重识别、删除草稿或把回调绑定到另一道题。保存完成后提供已保存题目的详情链接。

## 10. 请求参数

图片支持 PNG、JPEG/JPG、BMP；PDF 每次显式选择一页。客户端与服务端都使用 4 × ceil(raw_bytes / 3) 不超过 10 MiB 的精确 Base64 上限，因此原始文件最大为 7.5 MiB。

真实 Provider 的可计费调用默认不自动重试业务请求；生产配置最多两次重试只针对明确可重试错误。真实付费 smoke 会临时把最大重试设为 0。

## 11. 规范化

Normalizer 将腾讯 ResultList 转换为稳定 API Schema，保留 question_number、question_type、full_text、Question、Option、Figure、Table、Answer、Parse、Coord 和 warnings。缺失字段采用显式空值或警告，不猜测题目边界，不伪造置信度。

## 12. 题干

Question 元素按书序聚合为可编辑题干，同时保留完整 full_text 和坐标。模拟数据包含言语理解、数量关系、图形推理与资料分析，便于无需外部密钥验证全链路。

## 13. 选项

选项按标签保存，文本、坐标和可选裁剪资产一起返回。前端允许人工修改，最终保存使用用户看到并确认的值，不直接把 OCR 原始值写入错题库。

## 14. Figure

Figure 结构保留 index、text、coord 和 asset_id。裁剪数量、单批总 PNG 字节数以及总产物数量均受配置限制；详情页和 AI 上下文通过受鉴权资产引用呈现图形推理素材。

## 15. Table

Table 结构与 Figure 一致保留文本、坐标和裁剪资产，支持资料分析题。模拟 OCR 的第四题包含表格，生产冒烟已验证视觉元数据可以保存并重新读取。

## 16. 答案与解析

QuestionSplitOCR 返回的 Answer 与 Parse 只作为“识别到但未确认”的候选。系统不会自动采用、自动保存或自动触发 AI。用户必须分别点击采用或手工录入；API 元数据保留确认状态，避免把机器识别误当作标准答案。

## 17. 数据库迁移

0006_question_split_ocr 新增持久化 OCR 任务以及所需索引和资产元数据。任务记录包含用户、上传、页码、Provider、请求指纹、状态、处理租约和结果，用于幂等、恢复和审计。

PostgreSQL 17 实测完成 0001 → 0006、alembic check、0006 → 0005、0005 → 0006 和最终 check；Railway 生产 current 为 0006_question_split_ocr (head)。

## 18. 错误处理

错误统一映射为安全的 API 代码，包括未配置、文件类型、文件过大、PDF 页码、限流、排队超时、腾讯服务未开通、欠费、鉴权、SDK 超时和上游错误。响应只带本地 request ID 或安全的腾讯 RequestId，不返回密钥、Base64 或堆栈。

上传、裁剪、数据库提交和任务取消都采用取消安全流程。若线程工作仍在运行，协程会等待真实工作完成再释放信号量；失败会清理未提交物理文件，已成功 CAS 的资产不会被误删。

## 19. 限流、并发与成本

上传和 OCR 分别有每用户分钟/小时双窗口限制、全局信号量和排队超时。过载返回 429，不无限排队。上传入口在 multipart 解析和鉴权前同时限制 Content-Length、实际 chunked 字节和并发，降低未认证大包耗尽内存的风险。

OCR 处理信号量覆盖 Provider、规范化、裁剪、持久化和终态 CAS。Railway API 保持单副本，使当前进程内速率和并发限制的语义明确。

## 20. 幂等与恢复

相同用户、上传、页码和 Provider 产生稳定请求指纹。成功任务复用结果；处理中任务返回冲突；超过 180 秒租约的任务可由新请求通过 updated_at 条件 CAS 回收。

每次领取都有 claim token。旧 Worker、已取消 Worker 或租约被接管的 Worker不能覆盖新所有者的成功/失败状态，也不能删除新所有者已提交的资产。

## 21. 验证命令

本地执行的质量门禁：

- uv lock --check
- ruff format --check 与 ruff check
- mypy app（strict）
- pytest 全量测试
- npm ci --dry-run --ignore-scripts --no-audit --no-fund
- npm test
- ESLint、tsc --noEmit、Next.js production build
- PostgreSQL 17 Alembic 升降级与 check
- bash -n scripts/production-smoke.sh
- docker compose config --quiet
- git diff --check
- 密钥、私钥、真实 .env 和长 Base64 扫描

## 22. 54 项验收矩阵

| ID | 验收项 | 结果 | 证据摘要 |
|---:|---|---|---|
| 01 | 复用原新增错题页 | 通过 | 手工录入与图片识别并存，无重复页面。 |
| 02 | Web 同源 API 代理 | 通过 | 正式域名 /api/v1 可注册、上传、OCR、保存和分析。 |
| 03 | 鉴权与资产归属 | 通过 | 未登录拒绝；跨用户题目和上传返回 404。 |
| 04 | PNG/JPEG/BMP 上传 | 通过 | 魔数和 MIME 双重校验，测试覆盖三种格式。 |
| 05 | PDF 指定页 | 通过 | 页码校验；模拟 PDF 第 2 页返回独立两题。 |
| 06 | 鉴权前请求体保护 | 通过 | Content-Length 与 chunked 超限均在 multipart 前返回 413。 |
| 07 | 精确 Base64 上限 | 通过 | 客户端、API、脚本统一 10 MiB 编码上限。 |
| 08 | 文件内容识别 | 通过 | 错误 MIME/魔数返回 422，不只信任扩展名。 |
| 09 | 安全存储名 | 通过 | 随机 storage_name，API 不返回内部磁盘名。 |
| 10 | QuestionSplitOCR 契约 | 通过 | Action、Version、Endpoint 固定并有单元测试。 |
| 11 | 三个腾讯布尔参数 | 通过 | false、true、false 与批准规格一致。 |
| 12 | OCR 状态接口 | 通过 | 正式返回 provider=mock、configured=true、完整能力位。 |
| 13 | 演示 OCR 明示 | 通过 | is_demo=true，界面显示“演示 OCR（不会调用腾讯云）”。 |
| 14 | 四类模拟题 | 通过 | 言语、数量、Figure、Table 全覆盖。 |
| 15 | PDF 页间差异 | 通过 | page=2 不是图片默认样本，返回两道独立题。 |
| 16 | 题干规范化 | 通过 | question_text、full_text、元素顺序和题号保留。 |
| 17 | 选项规范化 | 通过 | label、text、coord、asset_id 可用。 |
| 18 | 坐标保留 | 通过 | 题目与子元素 Coord 进入稳定 Schema。 |
| 19 | Figure 素材 | 通过 | 裁剪、保存、详情读取和测试均通过。 |
| 20 | Table 素材 | 通过 | 表格元数据可保存并在生产重新读取。 |
| 21 | 来源与整题裁剪 | 通过 | source.file_id 与 crop_asset_id 均受鉴权。 |
| 22 | OCR 答案默认未确认 | 通过 | 不自动采用，须用户显式操作。 |
| 23 | OCR 解析默认未确认 | 通过 | 不自动保存或触发 AI。 |
| 24 | 多题题卡编辑 | 通过 | 字段、视觉素材、警告和确认操作可编辑。 |
| 25 | 不自动保存 | 通过 | OCR 结束只生成前端草稿。 |
| 26 | 连续逐题保存 | 通过 | 保存一题后保留其余草稿和本次 OCR。 |
| 27 | AI 仅主动触发 | 通过 | 保存与分析为两个明确动作。 |
| 28 | 演示 AI 明示 | 通过 | 正式诊断 is_demo=true。 |
| 29 | OCR 持久化幂等 | 通过 | ocr_tasks 请求指纹复用成功结果。 |
| 30 | processing 租约 | 通过 | 180 秒租约与跨参数边界验证。 |
| 31 | claim token 终态 CAS | 通过 | 旧 Worker 不能覆盖新领取者。 |
| 32 | 裁剪取消安全 | 通过 | 线程完成前不释放 OCR 信号量。 |
| 33 | 失败清理 | 通过 | 回滚失败时仍清理未提交物理产物。 |
| 34 | 上传取消安全 | 通过 | 文件写入和 DB commit 的歧义状态均有测试。 |
| 35 | 全局并发保护 | 通过 | 上传与 OCR 独立信号量。 |
| 36 | 排队过载 | 通过 | 超过 queue timeout 返回 429。 |
| 37 | 双窗口用户限流 | 通过 | 分钟/小时限制按用户隔离。 |
| 38 | 裁剪资源上限 | 通过 | 数量与总 PNG 字节均有硬限制。 |
| 39 | 超时与重试 | 通过 | 只重试可重试错误，超时被安全映射。 |
| 40 | 配置交叉校验 | 通过 | 租约、速率、容量边界由 Settings 拒绝无效组合。 |
| 41 | 腾讯错误映射 | 通过 | 开通、欠费、权限、频控和上游错误有稳定代码。 |
| 42 | 多租户与会话安全 | 通过 | 安全 Host-only Cookie；跨用户资源不可见。 |
| 43 | CORS | 通过 | 允许正式 Web Origin，恶意 Origin 不获 allow-origin。 |
| 44 | 代理重定向安全 | 通过 | trailing slash 308 Location 保持在 Web 同源域名。 |
| 45 | OCR 状态契约 | 通过 | API 名、PDF/多题/选项能力和 UseNewModel 值精确断言。 |
| 46 | 0006 生产迁移 | 通过 | Railway 返回 0006_question_split_ocr (head)。 |
| 47 | PostgreSQL 17 往返迁移 | 通过 | upgrade、check、downgrade、upgrade、check 全通过。 |
| 48 | 后端全量测试 | 通过 | 494 passed，1 个真实腾讯 E2E 默认跳过。 |
| 49 | 前端全量测试 | 通过 | 31 个文件、156 个测试通过。 |
| 50 | 静态检查与构建 | 通过 | Ruff、mypy 55 文件、ESLint、tsc、Next build 全通过。 |
| 51 | Railway 部署与健康 | 通过 | API/Web SUCCESS；health、ready 均为 demo 正常。 |
| 52 | 生产冒烟与重启持久化 | 通过 | 全链路 smoke 通过；API 重部署后题目、诊断、复习和原图仍一致。 |
| 53 | 正式环境 Chrome 自动化 | 未执行 | Chrome 控制连接器在打开页面前报运行时兼容错误；没有伪报通过。 |
| 54 | 真实腾讯云付费 E2E | 未执行 | 用户选择模拟 OCR；测试要求显式真实图片与轮换后密钥，默认 fail-closed。 |

## 23. 未执行项与边界

两项没有记为“通过”：

1. 正式环境 Chrome 自动化：Chrome 控制连接器初始化时报 Cannot redefine property: process，错误发生在打开页面之前。此前本地 Chrome 已实际完成图片四题、逐题保存、视觉素材、演示 AI 和 PDF 第 2 页流程；本次生产由同源代理端到端 smoke 与重部署持久化复核覆盖。
2. 真实腾讯云付费调用：用户明确选择“先用演示 AI”和模拟 OCR，且原材料中的腾讯密钥不应继续使用。真实 E2E 默认跳过是安全设计，不是测试遗漏。

## 24. 腾讯云人工操作

启用真实 OCR 前必须在腾讯云控制台：

1. 立即轮换/删除曾出现在需求材料中的 SecretId 与 SecretKey。
2. 创建只允许编程访问的 CAM 子用户。
3. 仅授予 QuestionSplitOCR 所需最小权限。
4. 开通试卷切题服务，确认资源包、余额和频控。
5. 在 Railway API 服务的 Secret Variables 中写入新密钥，禁止写入 Web、源码或 Git。

## 25. 环境变量名称

Provider 与腾讯连接：

- OCR_PROVIDER
- TENCENTCLOUD_SECRET_ID
- TENCENTCLOUD_SECRET_KEY
- TENCENTCLOUD_REGION
- TENCENTCLOUD_OCR_TIMEOUT_SECONDS
- TENCENTCLOUD_OCR_MAX_RETRIES
- TENCENTCLOUD_OCR_MAX_CONCURRENCY
- TENCENTCLOUD_OCR_QUEUE_TIMEOUT_SECONDS

OCR 任务与产物：

- OCR_PROCESSING_LEASE_SECONDS
- OCR_RATE_LIMIT_PER_MINUTE
- OCR_RATE_LIMIT_PER_HOUR
- OCR_CORRECTED_IMAGE_MAX_BYTES
- OCR_CORRECTED_IMAGES_MAX_TOTAL_BYTES
- OCR_CROP_MAX_ARTIFACTS
- OCR_CROP_MAX_TOTAL_PNG_BYTES

上传入口：

- MAX_UPLOAD_BYTES
- UPLOAD_MAX_CONCURRENCY
- UPLOAD_QUEUE_TIMEOUT_SECONDS
- UPLOAD_RATE_LIMIT_PER_MINUTE
- UPLOAD_RATE_LIMIT_PER_HOUR

## 26. 真实 OCR 冒烟步骤

真实测试必须使用非敏感、公考试题图片的绝对路径，并显式设置 TENCENT_QUESTION_SPLIT_OCR_E2E_IMAGE 或 SMOKE_IMAGE_PATH。测试不会生成或回退到示例图，不会在缺少图片时误发付费请求。

按 docs/deployment/railway.md 操作：先设置轮换后的 Secret Variables，将 OCR_PROVIDER 改为 tencent_question_split，临时设置最大重试为 0，等待部署健康，执行一次明确付费 smoke；无论成功、失败或中断，都由 trap 恢复最大重试为 2、重新部署并验证。

## 27. Git 差异与安全扫描

实现提交 7f5d8f1 包含 74 个文件、6078 行新增、663 行删除。提交前和部署后执行 git diff --check。

安全扫描结果：

- 受跟踪真实 .env：0
- AKID 形式密钥：0
- OpenAI sk 形式密钥：0
- 私钥块：0
- 文本中的异常长 Base64：0

.env.example 只含占位符。验收报告不包含账号、Cookie、密码、密钥或测试数据 UUID。

## 28. 原问题、根因与处理

| 问题 | 根因 | 处理 |
|---|---|---|
| 一页多题不能可靠拆分 | 普通文字 OCR 不表达题目层级 | 使用 QuestionSplitOCR ResultList，不猜边界。 |
| Figure/Table 在保存后丢失 | 原题目模型只关注文字 | 增加受鉴权资产引用和 OCR metadata。 |
| OCR 答案可能被误当标准答案 | 识别结果与人工确认没有状态边界 | Answer/Parse 默认未确认，必须显式采用。 |
| 连续保存可能串题 | 异步 mutation 使用了变化中的当前草稿 | 提交时捕获回调、metadata、AI 准备数据和临时 ID。 |
| 保存期间仍可改文件或重识别 | 只禁用了保存按钮 | pending 时锁定整张表单和 OCR 面板。 |
| 取消请求可能提前释放并发槽 | to_thread 在协程取消后仍继续工作 | shield 并等待真实线程结局，再清理和释放。 |
| Worker 超时恢复可能互相覆盖 | 只有 status，没有领取所有权 | processing lease、updated_at CAS 和 claim token。 |
| 未认证大 multipart 可先消耗内存 | 限制位于 FastAPI 解析之后 | 增加 ASGI 入口体积与并发中间件。 |
| 真实 smoke 可能意外多次计费 | 服务端重试配置仍启用 | 真实 smoke 临时设重试为 0，trap 强制恢复。 |
| Railway 前后端跨域复杂 | 浏览器直连 API 依赖 CORS 与 Cookie 域 | 采用批准的 Web 同源 API 代理。 |
| 生产密钥风险 | 需求材料出现过真实凭证 | 从未使用、记录、提交或部署；要求立即轮换。 |
| 首次生产 smoke TLS 超时 | Railway 边缘节点瞬时连接抖动 | 同路径复核稳定 308，严格重跑后全量通过。 |
