# Railway production acceptance audit

Date: 2026-07-12 (Asia/Shanghai)

## Release identity

- Railway project: `kaogong-ai-exam` (`660e7ed2-ccc8-4ba5-bdf4-115f0ea9f2cb`)
- Environment: `production`
- Release commit: `69ca6626d08e63f4c569f3ed307737d772e6ef0e`
- Web deployment: `b90da45e-f27b-4e0b-9cb7-b6d0d3ad4cd4` (`SUCCESS`)
- API deployment: `dd2057e6-cd59-4a52-ba18-4fda45ddda8a` (`SUCCESS`)
- PostgreSQL deployment: `bc390c28-b50e-4595-b3c6-82996f555565` (`SUCCESS`)
- Web URL: <https://web-production-3ce0.up.railway.app>
- API URL: <https://api-production-f136.up.railway.app>
- Provider mode: `demo`; no OpenAI key is configured.

## Automated verification

- API: 175 tests passed. The 169 emitted warnings are the previously documented Starlette TestClient cookie deprecations.
- Web: 141 tests passed across 29 files.
- Web ESLint: passed.
- Next.js production build with `NEXT_PUBLIC_API_URL=/api/v1`: passed.
- Git whitespace check: passed.
- Independent logout/security review: no Critical, Important, or Minor findings after remediation.

The logout regression was developed test-first. The first test failed because no accessible `退出登录` action existed. Follow-up RED tests proved that account-private React Query data survived a session-only cache removal and that logout failure had no visible feedback. The final implementation clears the entire query client, shows a retryable accessible error on failure, and performs a full-document replacement after success so late callbacks from the previous account cannot cross the account boundary.

## Railway and remote smoke

- Exactly three services exist: `Postgres`, `api`, and `web`.
- API has exactly one ready volume mounted at `/data/uploads`.
- API `/health` and `/ready` returned the exact demo-mode payloads.
- Web `/health` returned `{"status":"ok"}`.
- Unauthenticated Web same-origin `/api/v1/auth/me` returned the expected HTTP 401.
- Web deployment and bounded log audits found no traceback, panic, crash, configuration error, secret name, private Railway hostname, or unexpected browser error.
- Alembic is exactly at `0005_review_records (head)`.
- The serving API process runs as UID/GID 10001 and the upload volume passed a write, fsync, read, and self-delete probe as that identity.
- Host validation accepted the public, Railway-private, and health-check hosts and rejected an unknown host.
- The production smoke covered registration, login, secure cookie handling, CORS, same-origin JSON and multipart proxying, image upload/download, demo OCR, question save, demo analysis, review, analytics, user isolation, invalid MIME, oversize upload, redirects, and private-value leak checks.

## Restart persistence

- API restart: readiness returned, then a fresh login recovered the smoke question, demo analysis, mastery state, single review record, image content type, and byte-for-byte identical uploaded image.
- PostgreSQL restart: the database process start time changed to `2026-07-12 15:19:15 UTC`; readiness returned afterward, and the same protected smoke state and byte-identical uploaded image passed the persistence verifier.
- A temporary Railway status instance-ID gate was intentionally not used as final evidence because the managed PostgreSQL restart reused its instance ID. Process start time plus post-restart application persistence are the authoritative evidence.

## Chrome acceptance

The following complete user flow was directly observed in Chrome:

1. Logged in with a dedicated synthetic production test account and confirmed persisted Dashboard data.
2. Uploaded a real PNG, confirmed preview, completed upload, and observed the `演示模式识别结果` label.
3. Ran demo OCR, edited recognized fields, and saved a new question.
4. Opened the detail page, ran demo AI diagnosis, and verified diagnosis, reasoning, knowledge points, suggestion, and `演示模式` labeling.
5. Filtered the question library to `未掌握`, reduced the result to one record, and opened it through the result link.
6. Completed today’s review, saved a review note, and changed the question to `已掌握`.
7. Confirmed Dashboard progress `2 / 2`, the updated recent-question state, and analytics totals/distributions.
8. Logged out through the new header action, reached `/login`, logged back in, and recovered both questions, analysis, review status, and statistics.
9. At 390 × 844, confirmed the mobile card layout, icon-only accessible logout action, navigation drawer, Escape close, and focus restoration to `打开导航`.
10. Chrome console warning/error audit returned zero unexpected entries.

## Evidence limits

The saved images are representative end states, not a frame-by-frame recording. Upload/OCR, library filtering, logout/re-login, and the open mobile drawer were verified from their visible DOM state, resulting URL, enabled/selected state, focus state, and persisted data, but were not separately saved as screenshots. This avoids retaining a login form containing credential fields and keeps the evidence set focused; the automated production smoke independently exercises the same network paths.

Desktop screenshots intentionally show the randomly generated, non-personal QA email so the persisted account boundary remains auditable. The email is not an authentication secret. Its high-entropy password and all local session artifacts were deleted and are not committed.

## Visual evidence

- [Reference and production Dashboard comparison](railway-production/dashboard-comparison.png) — both panes use the same 1487 × 1058 viewport; data and active-task state differ as expected, while the approved palette, spacing, card hierarchy, sidebar, header, and typography remain consistent. No cropped content, broken padding, or blocking visual regression was found.
- [Production Dashboard desktop](railway-production/dashboard-desktop.jpg)
- [Production Dashboard narrow](railway-production/dashboard-narrow.jpg)
- [Question detail with demo AI](railway-production/question-detail-ai-demo.jpg)
- [Question detail narrow](railway-production/question-detail-narrow.jpg)
- [Review complete](railway-production/review-complete.jpg)
- [Analytics](railway-production/analytics.jpg)

## Acceptance result

PASS. The production deployment satisfies the approved Railway deployment design and the PRD’s first-release path, including same-origin API proxying, demo AI disclosure, secure logout, restart persistence, desktop and narrow-screen usability, and Chrome end-to-end operation.

Synthetic smoke and Chrome QA records remain in the dedicated production test account because the approved smoke workflow has no destructive remote cleanup step. Local plaintext password and session artifacts were deleted after final verification.
