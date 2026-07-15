# Railway 正式腾讯 OCR 切换设计

- 日期：2026-07-15
- 状态：用户已选择方案 A 并批准设计
- 实施分支：codex/tencent-question-split-ocr
- 目标环境：Railway / production
- Web：https://web-production-3ce0.up.railway.app
- API：https://api-production-f136.up.railway.app

## 1. 目标与成功定义

在不改变现有业务流程和 AI 模式的前提下，把正式环境 OCR Provider 从 mock 切换为 tencent_question_split，并用用户明确提供的非敏感公考试题图片完成一次真实 QuestionSplitOCR 付费调用。允许加入只服务于“一次付费验收”的 fail-closed 安全护栏。

完成必须同时满足：

1. PROVIDER_MODE 保持 demo。
2. Railway API 服务存在新轮换的 TENCENTCLOUD_SECRET_ID 和 TENCENTCLOUD_SECRET_KEY；密钥值不经过聊天、源码、Git、日志或命令参数。
3. OCR_PROVIDER 最终为 tencent_question_split。
4. 真实调用前 TENCENTCLOUD_OCR_MAX_RETRIES 临时为 0。
5. 生产同源 API 返回 provider=tencent_question_split、configured=true、api_name=QuestionSplitOCR。
6. 只发出一次真实 OCR HTTP 请求，返回安全的腾讯 RequestId、至少一道题以及可用题干。
7. 调用结束后 TENCENTCLOUD_OCR_MAX_RETRIES 恢复为 2，并经新部署验证。
8. API、Web、Postgres 保持健康，数据库仍为 0006_question_split_ocr (head)。
9. Chrome 只查看该次已保存结果，不再次触发付费 OCR。

## 2. 不在本次范围内

- 不启用 OpenAI，PROVIDER_MODE 不改为 live 或 auto。
- 不创建、轮换或读取腾讯云密钥；用户已在腾讯 CAM 创建新凭据。
- 不把密钥写入本地 .env。
- 不修改 QuestionSplitOCR 固定契约。
- 不用个人照片、姓名、考号或其他敏感材料做测试。
- 不执行第二次真实 OCR 来“确认”第一次结果。

## 3. 当前状态

正式 API、Web、Postgres 已部署且运行。代码已经实现 tencent_question_split Provider、持久化幂等、租约、并发、限流、裁剪、错误映射和真实 smoke 的 fail-closed 开关。

Railway 当前没有 TENCENTCLOUD_SECRET_ID 和 TENCENTCLOUD_SECRET_KEY，OCR_PROVIDER 仍不是 tencent_question_split。切换前生产仍使用 mock，不会调用腾讯云。

## 4. 密钥输入与权限边界

使用 Chrome 打开 Railway 项目中 API 服务的 production Variables 页面。用户亲自创建或更新：

- TENCENTCLOUD_SECRET_ID
- TENCENTCLOUD_SECRET_KEY

助手只负责导航并在输入前交还控制权，不读取、复制、粘贴或截取密钥。用户完成保存后，助手通过 Railway CLI 仅断言两个变量键存在，不输出原值。

TENCENTCLOUD_REGION 不创建；应用的安全默认值为空。这样避免 Railway CLI 拒绝空值，同时保持固定 Endpoint ocr.tencentcloudapi.com。

## 5. 测试图片

本次真实调用使用用户于 2026-07-15 明确提供的文件 17715122101_img_01.png。

- 格式：PNG / RGB
- 尺寸：2224 × 2852
- 文件字节：482226
- Base64 预计字节：642968
- SHA-256：09a5739276b827c01cd2fa4a262688eec529426e864b487077285e8e1f57f788
- 内容：内蒙古公考选择题；姓名与考号为空

调用前必须重新验证文件仍为常规文件、不是符号链接、可完整解码、SHA-256 未变化，且 Base64 不超过 10 MiB。

## 6. 分阶段切换

### 阶段 A：写入秘密但不切流

用户在 Railway 页面写入两个新密钥时，OCR_PROVIDER 保持 mock。此阶段即使误输，现有 OCR 仍可用且不产生腾讯费用。

### 阶段 B：部署真实 Provider

通过 Railway CLI 只设置非秘密变量：

- OCR_PROVIDER=tencent_question_split
- TENCENTCLOUD_OCR_MAX_RETRIES=0

随后从当前干净提交上传 apps/api，等待 Build、Pre-Deploy Alembic 与 /ready 成功。通过已登录的同源接口验证 OCR status 精确为真实 Provider 且 configured=true。

### 阶段 C：单次真实调用

使用 scripts/production-smoke.sh、独立的 mode-0600 状态文件、临时随机 smoke 密码和用户提供图片。设置 EXPECTED_OCR_PROVIDER=tencent_question_split，并使用与完整部署 SHA 绑定的固定 smoke 邮箱、批准图片的固定 SHA-256，以及外部 mode-0700 目录中的原子 one-shot 标记。调用前先完整解码批准图片并复制到私有只读快照；上传后再回读服务器文件并匹配同一摘要。

脚本只允许一个 POST /api/v1/ocr，并在该 POST 紧前以 O_CREAT|O_EXCL 消费 one-shot 标记。curl 必须禁用 ~/.curlrc 且显式 retry=0；腾讯 SDK ClientProfile 必须显式使用 NoopRetryer；应用重试为 0。因此本次部署自动化最多形成一次腾讯 QuestionSplitOCR 调用。验收按固定 smoke 邮箱查询本次全部 OCRTask，保存 provider、脱敏 RequestId、question_count、第一题题干、题目/选项结构和受保护上传资产，不保存腾讯原始 Base64。

### 阶段 D：恢复正式重试

EXIT trap 必须在阶段 B 的第一次 Railway 变量变更前安装。无论阶段 B/C 成功、失败或被中断，都必须：

1. 把 TENCENTCLOUD_OCR_MAX_RETRIES 恢复为 2。
2. 重新部署 API。
3. 通过 Railway SSH 断言运行进程实际读取到 2。
4. 验证 /ready 成功。

只有上述四项全部成功，真实 smoke 才能进入最终结论。若 live/retries=2 恢复无法验证，必须继续尝试 mock/retries=2 并用当前已验证的 apps/api 树重新部署。

## 7. 失败与回滚

在真实调用成功前发生任何错误时：

1. 先完成 retries=2 的恢复与部署验证。
2. 将 OCR_PROVIDER 恢复为 mock。
3. 再次部署并验证 OCR status 为 mock、configured=true。
4. 保留 AI 演示、手工录题、错题库和复习功能。
5. 只报告安全错误码、HTTP 状态、腾讯 RequestId（若有）和处置建议。

不得自动重试付费调用。凭证无效、服务未开通、CAM 权限不足、欠费或资源包耗尽都需要用户先在腾讯云处理，再由用户明确批准新的付费测试。

若真实调用成功，则不回滚 OCR_PROVIDER；只恢复 retries=2，正式环境继续使用 tencent_question_split。

## 8. Chrome 与电脑验收

真实 smoke 成功后，用 Chrome 登录同一个临时 smoke 账号，只执行读取操作：

- 打开新增错题页，确认显示“腾讯云真实 OCR”。
- 打开已保存题目，确认题干、选项、源图和 OCR 元数据存在。
- 确认演示 AI 标记仍存在。
- 确认页面没有再次发起 OCR。

优先使用 Chrome 控制组件。若其连接失败，先读取 Chrome 故障排查文档；由于用户同时明确请求电脑控制，仍无法恢复时才使用 Computer Use 操作同一个 Chrome 窗口。任何登录密码只来自临时 mode-0600 文件，不写入仓库或报告。

## 9. 安全与费用不变量

- 用户在 Railway 页面亲自输入密钥。
- 不运行会打印变量原值的命令；如果 CLI 必须返回 JSON，只在管道内转换为布尔断言。
- 不把环境变量快照写入磁盘。
- 不输出 Cookie、smoke 密码、SecretId、SecretKey、签名、Base64 或内部 storage_name。
- 图片只发送给正式 Web/API 与腾讯 QuestionSplitOCR，用途仅为本次验收。
- API 保持单副本，使现有进程级并发和速率限制仍是部署全局边界。
- 真实调用前重试为 0，成功后恢复为 2。
- 真实 smoke 邮箱与部署 SHA 绑定；同一提交的流程重启会在注册阶段停止，不能生成第二个 OCR 任务。
- one-shot 标记在唯一 OCR POST 紧前原子消费；传输结果不明确也视为本次额度已用，绝不自动重跑。
- curl 不读取用户配置且 retry=0；腾讯 SDK 内部 retryer 为 NoopRetryer。
- 所有部署使用同一个已推送提交生成的只读且运行用户可读快照（文件 0444、目录 0555）；激活、恢复与回滚均按 Railway CLI 5.26.0 的唯一 `meta.cliMessage` 认领精确 deployment ID，不能从可变工作树或含义不明确的 latest 部署推断成功。

## 10. 验证证据

最终报告必须包含：

- 部署提交 SHA。
- Railway API 最新 deployment ID 与 SUCCESS 状态。
- OCR status 的非敏感字段。
- 真实腾讯 RequestId 是否存在、question_count 和第一题题干摘要。
- retries 从 0 恢复为 2 的运行时断言。
- API/Web/Postgres 健康和 Alembic current。
- Chrome 或 Computer Use 的只读验收结果。
- Git 工作树与敏感信息扫描结果。

若任一证据缺失，不得宣称真实腾讯 OCR 已完成。
