# 腾讯云 QuestionSplitOCR 接入与运维

本文只记录 `kaogongsystem` 当前已经实现的行为。示例不含真实凭证；任何真实密钥都只能写入未被 Git 跟踪的后端 `.env` 或 Railway API 服务变量。

## 1. 本系统使用 QuestionSplitOCR

系统在现有 `POST /api/v1/ocr` 后接入腾讯云试卷切题接口 `QuestionSplitOCR`，没有新增重复 OCR 页面或第二套 API。调用链为：现有录题页 → 同源 Web API 代理 → FastAPI → `OCRService` → `TencentOCRProvider` → 腾讯云 → 规范化多题草稿 → 人工校对 → 保存错题 → 用户主动启动 AI 分析。

接口契约固定为 `Action=QuestionSplitOCR`、`Version=2018-11-19`、`Endpoint=ocr.tencentcloudapi.com`。参考腾讯云的 [QuestionSplitOCR 产品文档](https://cloud.tencent.com/document/product/866/115930) 和 [API 参考](https://cloud.tencent.com/document/api/866/115930)。

## 2. 为什么选择试卷切题

通用印刷体 OCR 主要返回文字行，无法可靠表达“一页里有几道题”、题干与选项的归属、Figure、Table 和整题坐标。`QuestionSplitOCR` 原生返回 `ResultList`、`Question`、`Option`、`Figure`、`Table`、`Answer`、`Parse` 与 `Coord`，适合整页多题、公考图形推理和资料分析。系统不根据普通 OCR 文本猜题目边界，也不伪造置信度。

## 3. 开通腾讯云 OCR

1. 登录腾讯云，进入 [文字识别控制台](https://console.cloud.tencent.com/ocr/overview)。
2. 按控制台提示开通文字识别服务，并确认账户实名认证、计费方式和可用额度。
3. 在接口列表或在线调试中确认账号可调用“试卷切题 / QuestionSplitOCR”。
4. 在正式接入前先检查资源包、后付费开关和费用告警策略；不要用生产账号反复试错。

腾讯云控制台步骤可能调整，以控制台当前提示和官方文档为准。

## 4. 获取 SecretId 与 SecretKey

在 [访问密钥管理](https://console.cloud.tencent.com/cam/capi) 为专用身份创建或轮换云 API 密钥。`SecretKey` 通常只在创建时完整展示一次，应立即存入合规的秘密管理系统，不应保存到聊天、截图、代码、数据库或文档。

如果密钥曾经出现在聊天、终端历史、日志或截图中，应先禁用并删除旧密钥，再创建新密钥；不要继续把旧值部署到生产环境。

## 5. 子账号与最小权限

不要让应用持有主账号密钥。创建只允许编程访问的 CAM 子用户，并按最小权限授予 OCR 的 `QuestionSplitOCR` 操作。腾讯云的 [CAM OCR 操作清单](https://cloud.tencent.com/document/product/598/107102) 将 `QuestionSplitOCR` 列为操作级权限；自定义策略应只包含实际调用所需动作，例如 `ocr:QuestionSplitOCR`，资源范围按控制台当前支持范围配置。

为子用户启用密钥轮换、使用告警和 IP 限制（若当前账户与产品支持），定期检查最后使用时间。腾讯云也明确建议用有限权限的子账号代替主账号操作。

## 6. 后端环境变量

复制 `.env.example` 为未跟踪的 `.env`，只在后端配置：

```dotenv
OCR_PROVIDER=tencent_question_split
TENCENTCLOUD_SECRET_ID=
TENCENTCLOUD_SECRET_KEY=
TENCENTCLOUD_REGION=
TENCENTCLOUD_OCR_TIMEOUT_SECONDS=30
TENCENTCLOUD_OCR_MAX_CONCURRENCY=2
TENCENTCLOUD_OCR_QUEUE_TIMEOUT_SECONDS=5
TENCENTCLOUD_OCR_MAX_RETRIES=2
OCR_PROCESSING_LEASE_SECONDS=180
OCR_RATE_LIMIT_PER_MINUTE=5
OCR_RATE_LIMIT_PER_HOUR=50
OCR_CORRECTED_IMAGE_MAX_BYTES=10485760
OCR_CORRECTED_IMAGES_MAX_TOTAL_BYTES=10485760
OCR_CROP_MAX_ARTIFACTS=100
OCR_CROP_MAX_TOTAL_PNG_BYTES=10485760
MAX_UPLOAD_BYTES=10485760
UPLOAD_MAX_CONCURRENCY=2
UPLOAD_QUEUE_TIMEOUT_SECONDS=5
UPLOAD_RATE_LIMIT_PER_MINUTE=10
UPLOAD_RATE_LIMIT_PER_HOUR=100
```

`TENCENTCLOUD_REGION` 可留空；本接口不强制虚构地域。Endpoint 和三个布尔请求参数是服务端固定安全契约，不接受浏览器或环境覆盖。严禁创建 `NEXT_PUBLIC_TENCENTCLOUD_*`、`VITE_TENCENTCLOUD_*` 等前端变量。

OCR 数值配置在启动时执行闭区间校验，越界会直接拒绝启动，避免负超时、零并发、失控重试或过量内存/磁盘分配：

| 变量 | 合法范围 |
|---|---:|
| `TENCENTCLOUD_OCR_TIMEOUT_SECONDS` | 1–60 秒 |
| `TENCENTCLOUD_OCR_MAX_CONCURRENCY` | 1–10 |
| `TENCENTCLOUD_OCR_QUEUE_TIMEOUT_SECONDS` | 1–60 秒 |
| `TENCENTCLOUD_OCR_MAX_RETRIES` | 0–2 |
| `OCR_PROCESSING_LEASE_SECONDS` | 60–3600 秒 |
| `OCR_RATE_LIMIT_PER_MINUTE` | 1–60 |
| `OCR_RATE_LIMIT_PER_HOUR` | 1–1000 |
| `OCR_CORRECTED_IMAGE_MAX_BYTES` | 1–10485760 字节 |
| `OCR_CORRECTED_IMAGES_MAX_TOTAL_BYTES` | 1–10485760 字节 |
| `OCR_CROP_MAX_ARTIFACTS` | 1–100 |
| `OCR_CROP_MAX_TOTAL_PNG_BYTES` | 1–10485760 字节 |
| `MAX_UPLOAD_BYTES` | 1048576–10485760 字节（Base64 编码后） |
| `UPLOAD_MAX_CONCURRENCY` | 1–10 |
| `UPLOAD_QUEUE_TIMEOUT_SECONDS` | 0.1–60 秒 |
| `UPLOAD_RATE_LIMIT_PER_MINUTE` | 1–60 |
| `UPLOAD_RATE_LIMIT_PER_HOUR` | 1–1000 |

处理租约还必须满足交叉约束：`OCR_PROCESSING_LEASE_SECONDS >= TENCENTCLOUD_OCR_QUEUE_TIMEOUT_SECONDS + TENCENTCLOUD_OCR_TIMEOUT_SECONDS × (TENCENTCLOUD_OCR_MAX_RETRIES + 1) + 30`。额外 30 秒用于规范化、裁剪、写盘和数据库提交；不满足时 API 拒绝启动，避免没有 heartbeat 时误回收仍活跃的 worker。默认组合为 5 秒排队、30 秒请求、2 次重试、180 秒租约，最低要求为 125 秒。`OCR_RATE_LIMIT_PER_MINUTE` 也不得大于 `OCR_RATE_LIMIT_PER_HOUR`。

上传分钟限额不能大于小时限额。专用 ASGI 中间件在 FastAPI 解析 multipart 和解析登录依赖前先检查声明的 `Content-Length`，并对无长度或 chunked 请求逐块累计实际字节；标准 10 MiB Base64 预算对应 7.5 MiB 原文件，再只预留 64 KiB multipart 封装，超出即返回 `OCR_FILE_TOO_LARGE`。入口本身也使用共享 Semaphore 和同一排队超时，因此未认证的并发大请求不能绕过资源边界。通过入口后，上传接口再按用户执行双窗口限流，并在独立处理 Semaphore 中限制解码、检查、哈希和写盘重处理；默认并发 2，排队超过 5 秒返回 `UPLOAD_RATE_LIMITED`。`UploadFile` 只执行有界读取，CPU/磁盘重处理和数据库提交失败后的文件清理均在线程池中完成；请求取消会 shield 并等真实 worker 或 commit 得到确定结果，未提交文件清理完成后才释放处理名额。当前 Railway 生产拓扑固定为一个 API 副本；若以后水平扩容，需要把限流与并发配额迁移到跨副本协调设施后再提高副本数。

若 `OCR_PROVIDER=tencent_question_split` 但任一密钥缺失，应用仍正常启动，`GET /api/v1/ocr/status` 返回 `configured=false`，实际识别返回 `OCR_NOT_CONFIGURED`；其他业务不受影响。

## 7. 安装依赖

项目使用 Python 3.12、uv 和腾讯云官方产品级 SDK；不自行实现 TC3 签名。

```bash
cd apps/api
uv sync --locked
```

依赖声明位于 `apps/api/pyproject.toml`，锁文件为 `apps/api/uv.lock`，核心包是 `tencentcloud-sdk-python-ocr`（并由其带入 common SDK）。

## 8. 本地启动

默认先用演示 OCR，确保不产生云调用：

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api alembic upgrade head
```

打开 `http://localhost:3000/questions/new`，选择“图片识别”。需要真实 OCR 时，在后端 `.env` 写入轮换后的有效凭证并将 `OCR_PROVIDER` 改为 `tencent_question_split`，再重启 API。AI 可继续保持 `PROVIDER_MODE=demo`，两套 Provider 相互独立。

## 9. Docker 配置

Compose 从仓库根目录 `.env` 注入 API 变量。真实密钥不得写入 Dockerfile、镜像层、Compose 文件或 Web build args。上传原文件和裁剪图保存在 API 的 `/data/uploads` 持久目录；生产环境应挂载持久卷。浏览器只访问同源 `/api/v1`，由 Next.js 服务端代理到 API。

修改环境变量后执行：

```bash
docker compose up --build -d api web
docker compose logs --tail=100 api
```

日志检查只确认错误码、RequestId 和计数，不复制请求对象、图片字节或凭证。

## 10. Mock 测试

`OCR_PROVIDER=mock` 返回明确标注 `is_demo=true` 的确定性多题样本，覆盖言语理解、数量关系、Figure 图形推理、Table 资料分析和 PDF 不同页，不冒充腾讯生产结果。

```bash
cd apps/api
uv run pytest -q

cd ../web
npm test -- --run
```

默认测试会 mock SDK 或使用演示 Provider，不调用腾讯、不消耗额度。未开通、资源包耗尽、超时、限流和未知错误也通过本地异常对象测试。

## 11. 真实冒烟测试

真实测试默认及 CI 均跳过。先确保后端 `.env` 使用轮换后的子账号凭证，并准备一张本地 PNG 试卷图片；然后只运行指定用例：

```bash
cd apps/api
RUN_TENCENT_QUESTION_SPLIT_OCR_E2E=1 \
TENCENT_QUESTION_SPLIT_OCR_E2E_IMAGE=/absolute/path/to/local-question.png \
uv run pytest -q -s tests/test_tencent_ocr_e2e.py
```

该测试最多调用 SDK 一次，只输出经格式约束的 RequestId、题目数量及每题题干前 50 个字符，不输出密钥、Base64 或请求对象。它不会生成或回退到假样本：图片变量缺失、路径不存在、内容不是有效 PNG/JPEG/BMP，或 Base64 长度超过 `MAX_UPLOAD_BYTES` 时，都会在构造 Provider 前直接失败，SDK 调用数为零。必须使用一张真实且不含敏感信息的公考试题截图。不要在普通 `pytest` 前设置该开关。

## 12. 支持的文件格式

上传接口支持 PNG、JPG/JPEG、BMP 和 PDF，不支持 WebP。服务端按实际文件内容解码，不只相信扩展名或浏览器 MIME。空文件、损坏图片、损坏 PDF、不支持格式和伪装文件会得到稳定中文业务错误。按标准 `MAX_UPLOAD_BYTES=10485760` 配置，原文件最大为 7.5 MiB，因为前后端都以 Base64 编码后的 10 MiB 为预算。

## 13. Base64 上限

发给腾讯的 `ImageBase64` 不得超过 10 MiB。前端按 `4 * ceil(file.size / 3)` 精确计算 Base64 长度，编码后超过 10 MiB 的文件会在选择时直接拒绝；在标准配置下，这对应原文件最大 7.5 MiB。服务端在上传和调用 SDK 前再次校验同一预算。若部署时把 `MAX_UPLOAD_BYTES` 调低，服务端会执行更严格的上限；前端固定文案描述的是标准 10 MiB 契约。可通过压缩或减少无效空白区域减小体积。

`ImageBase64` 只存在于后端调用内存中；不会写数据库、日志、前端响应或题目 metadata。

## 14. 建议分辨率

建议试卷图片至少 600×800 像素，文字清晰、方向正确、对比度充足，并尽量避免透视、反光、折痕和大面积无关背景。更高分辨率不等于无限制；应同时满足文件、像素、Base64 和腾讯接口约束。

## 15. PDF 每次一页

前端读取上传结果中的 `page_count`，要求用户输入 1 到总页数之间的页码。每次请求只向腾讯发送一个 `PdfPageNumber`；页码进入服务端幂等键，所以同一 PDF 的不同页是不同任务。图片请求强制归一为第 1 页，客户端不能用伪页码绕过缓存。

## 16. UseNewModel=false

当前固定 `UseNewModel=false`，与本次批准的接口规格一致。该值定义在后端 `app/services/ocr_contract.py`，前端、请求体和环境变量均不能改变；状态接口会返回 `use_new_model=false` 供 UI 说明。

## 17. EnableImageCrop=true

当前固定 `EnableImageCrop=true`，请求腾讯返回矫正图以辅助 Figure、Table、选项和整题裁剪。返回的矫正图有单图、累计字节、累计像素、裁剪数量和 PNG 总量预算；超限时跳过并给出核对提醒，不把腾讯 Base64 持久化。

## 18. EnableOnlyDetectBorder=false

当前固定 `EnableOnlyDetectBorder=false`，确保请求完整试卷切题识别，而不是只检测边框。服务端测试直接检查官方 SDK 请求对象，防止升级时参数漂移。

## 19. 限流与并发

默认每用户 5 次/分钟且 50 次/小时；应用内全局 OCR 并发为 2，等待信号量最多 5 秒。一个许可覆盖 Provider 调用、规范化、裁剪、资产持久化和终态 CAS 的完整处理阶段，避免 SDK 返回后裁剪/写盘无界并发。可重试上游错误最多重试 2 次，并带短退避抖动。

同一文件、用户、页码、Provider 和参数版本生成确定性幂等键，成功结果直接复用。`processing` 任务默认租约 180 秒：未过期时重复请求返回 `OCR_IN_PROGRESS`；超过租约后，新请求按 `updated_at` 原子换入新的 claim token。成功、失败和取消的终态写入都必须同时匹配 `status=processing` 与当前 token，所以旧 worker 晚到不会覆盖新 owner；旧 worker 生成但未赢得终态 CAS 的裁剪文件和数据库行会被清理。

当前用户级速率桶是单进程内存实现。若 Railway 把 API 扩为多个实例，总额度会按实例放大；在未接入 Redis 等共享限流器前，应保持 API 单实例，或把该限制计入容量设计。

## 20. 资源包耗尽

腾讯返回资源包耗尽或额度不足时，系统映射为 `OCR_RESOURCE_PACKAGE_RUN_OUT`，不把上游原始消息暴露给用户。到 OCR 控制台核对资源包余额、适用接口与后付费设置，再决定购买资源包或暂停真实 OCR。腾讯云说明资源包耗尽后的行为与后付费开关相关，应以 [计费 FAQ](https://cloud.tencent.com/document/faq/866/33509) 为准。

不要通过循环重试解决额度问题；这会增加无效请求和潜在费用。

## 21. 账号欠费

欠费映射为 `OCR_ACCOUNT_IN_ARREARS`，计费状态异常映射为 `OCR_BILLING_ERROR`。腾讯云说明账户停服后，即使预付费包仍有余额也可能暂停抵扣，充值后才恢复；参考 [OCR 欠费说明](https://cloud.tencent.com/document/product/866/30576)。先在费用中心处理账户状态，再重试一次，不要反复部署或更换代码。

## 22. 图形推理

规范化层保留题目 `Coord`、每个 `Figure` 的文字与坐标。裁剪层优先从腾讯矫正图或原图生成整题图、Figure 图和带图选项图，使用当前用户拥有的上传资产持久化。保存题目时只提交资产 UUID；后端重新验证归属并派生受认证的 `/uploads/{id}` URL。AI 分析按整题裁剪、Figure、Table、选项、原图的顺序选取最多 8 张、总计最多 20 MiB 的真实图片。

裁剪失败时不删除识别文字；详情页会显示文字回退，并提示回看原始文件。

## 23. 资料分析

`Table` 的文字、坐标和可用裁剪图与 Figure 分开保存，不拼成普通题干后丢失结构。详情页单独展示表格素材；AI 分析也把 Table 图作为独立视觉输入。表格数字容易受清晰度、旋转和网格线影响，必须对照原图逐项核对。

## 24. OCR 结果必须人工校对

识别完成后只生成浏览器本地多题草稿，题干、题号、题型、选项标签和正文、Figure/Table 文字、OCR 原文、识别答案与解析均可编辑。重新识别会在草稿已修改时确认，载入右侧表单也会在存在未保存内容时确认。删除草稿、载入表单和保存错题都是不同的显式动作。

## 25. OCR 不会自动生成正确答案

腾讯返回的 `Answer` 保存为 `recognized_answer`，显示“未确认”，不会写入正式 `correct_answer`。用户只有点击“采用识别答案”才会把当前卡片载入表单并填写正确答案；多题之间会核对卡片身份并保护既有未保存内容。

## 26. OCR 不会自动生成 AI 解析

腾讯返回的 `Parse` 保存为 `recognized_parse`，与用户确认的 `original_explanation` 及系统 AI `Analysis` 三者分离。识别不会自动触发 `/questions/{id}/analyze`。用户必须先采用所需内容、保存正式错题、进入详情页，再主动点击“开始分析”；演示 AI 与真实 OpenAI Provider 也不会改变这个顺序。

## 27. 前端绝不能保存腾讯密钥

Web 代码、Next.js public 环境、浏览器存储、表单、URL、Cookie、API 响应和构建产物都不得出现腾讯密钥。`GET /api/v1/ocr/status` 只返回 provider、configured 和能力布尔值，不返回配置内容，也不调用腾讯。生产 Web 固定 `NEXT_PUBLIC_API_URL=/api/v1`；腾讯凭证只属于 Railway 的 API 服务。

## 28. 常见故障排查

| 现象/错误码 | 处理 |
|---|---|
| `OCR_NOT_CONFIGURED` / 页面显示尚未配置 | 检查 API 服务的 Provider 与两个密钥变量是否同时存在；轮换后重启 API。 |
| `OCR_SERVICE_NOT_OPEN` | 在 OCR 控制台开通试卷切题，并检查 CAM 子用户是否允许 `QuestionSplitOCR`。 |
| `OCR_CREDENTIAL_ERROR` | 检查密钥是否已禁用、删除、含多余空格或无权限；不要把密钥贴到日志。 |
| `OCR_FILE_TOO_LARGE` | 压缩文件；确认 Base64 后不超过 10 MiB。 |
| `UPLOAD_RATE_LIMITED` | 上传过频时等待分钟/小时窗口恢复；服务繁忙时等待队列释放后再试。 |
| `OCR_IMAGE_DECODE_FAILED` / `OCR_INVALID_PDF` | 重新导出为合法 PNG/JPEG/BMP/PDF，确认文件内容与扩展名一致。 |
| `OCR_INVALID_PDF_PAGE` | 输入 1 到 `page_count` 的页码，每次只识别一页。 |
| `OCR_NO_QUESTION` | 提高分辨率、纠正方向、裁掉无关背景，确认图片确实包含完整题目。 |
| `OCR_RATE_LIMITED` | 等待窗口恢复；检查是否重复点击、队列超时或腾讯侧限流。 |
| `OCR_IN_PROGRESS` | 同一幂等任务仍在有效租约内；等待当前请求完成。若 worker 已退出，最多等待 `OCR_PROCESSING_LEASE_SECONDS` 后再试。 |
| `OCR_RESOURCE_PACKAGE_RUN_OUT` | 到资源包管理检查余额与接口适用范围，不要循环重试。 |
| `OCR_ACCOUNT_IN_ARREARS` / `OCR_BILLING_ERROR` | 到费用中心处理欠费或计费状态后再试。 |
| `OCR_PROVIDER_TIMEOUT` / `OCR_PROVIDER_ERROR` | 记录安全的本地 request ID 和腾讯 RequestId，稍后重试；持续失败时查腾讯状态与 API 日志。 |
| 图片在详情页 401/404 | 必须通过已登录的同源 `/api/v1/uploads/{id}` 访问；确认 Web 同源代理与 Cookie 正常。 |
| PDF 没有裁剪图 | 部分响应没有可用矫正图；系统仍保留原 PDF、题目文字和核对提醒。 |

腾讯云对部分失败调用的计费规则可能变化，可查 [OCR 错误码计费说明](https://cloud.tencent.com/document/product/866/45470)。排障时不得打印 SecretId、SecretKey、签名、完整 ImageBase64、二进制文件或完整 SDK 请求对象。
