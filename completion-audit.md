# MVP completion audit

Date: 2026-07-11
Audited revision: `630e6845db0c2cd24e4feb3e97de6e2b54473d62`

This audit maps every item in design specification section 13 and the PRD P0 success criteria to current automated, runtime, and Chrome evidence. A passing test is cited only where its scope directly covers the requirement.

## Fresh global gates

- API: `uv run pytest -q` — 100 passed.
- Web: `npm test -- --run` — 27 files / 67 tests passed.
- Static and production checks: `npm run lint` and `npm run build` passed; Next.js produced all 11 app routes.
- Runtime: PostgreSQL and API healthy; Web available at `http://localhost:3000`; API health returned `{"status":"ok","provider_mode":"demo"}`.
- Database: `alembic current` returned `0005_review_records (head)`.
- Seed: `python -m app.seed` completed idempotently for `demo@example.com`.
- Authenticated runtime smoke: `API_URL=http://localhost:18000 WEB_URL=http://localhost:3000 bash scripts/smoke.sh` returned `smoke checks passed`.
- Committed Compose config publishes db/api/web only on `127.0.0.1`; the live QA override keeps the user's occupied port 8000 untouched and uses API port 18000.
- Repository: `git diff --check` passed. The feature worktree was clean at the start of this audit.
- Product Design: project-root `design-qa.md` records two same-input comparison passes and ends with `final result: passed`.

## Requirement-by-requirement matrix

| # | Required outcome | Automated evidence | Runtime / Chrome evidence | Result |
|---|---|---|---|---|
| 1 | Register and sign in | `test_register_sets_http_only_cookie`, `test_login_sets_session_and_me_returns_current_user`; Web register/login form tests | A synthetic account registered, reached Dashboard, and remained signed in after reload | Proven |
| 2 | Upload one question screenshot | Upload validation and owner-scoped download tests in `test_uploads.py` | Chrome selected a real PNG, displayed the preview, and enabled the explicit upload action; `10-ocr-result.png` | Proven |
| 3 | Recognize image text | `test_demo_ocr_returns_editable_fields`; strict OpenAI image/schema adapter test | Chrome ran OCR and received stem, four options, answers, and explanation with a visible demo label; `10-ocr-result.png` | Proven |
| 4 | Edit OCR results | Web `fills OCR fields without saving automatically` and field-preservation tests | Chrome changed module, knowledge points, error reason, source, and note before save; `10-ocr-result.png` | Proven |
| 5 | Save a question | `test_question_crud_has_defaults_and_updates`; Web `creates a question and navigates to its API id` | OCR question saved and navigated to `/questions/5a488fd6-6159-4a23-b51d-f5a88aa586c1`; `11-ocr-analysis.png` | Proven |
| 6 | Manually trigger AI analysis | `test_manual_analysis_persists_structured_result`, reanalysis/history/failure tests; Web explicit retry test | The saved detail initially showed “开始分析”; Chrome clicked it and received one labeled demo result | Proven |
| 7 | Return cause, knowledge points, and correct approach | Demo/provider schema tests plus persisted analysis assertions | Detail rendered 错因诊断、正确思路、建议复习的知识点、学习建议; `11-ocr-analysis.png` | Proven |
| 8 | Filter the question library | `test_filters_question_library_and_paginates`, status/date tests; Web URL-state filter tests | Chrome filtered by 资料分析 and retained the filter in the URL; mobile priority-field rendering is captured in `07-library-mobile.png` | Proven |
| 9 | Enter and complete today's review | Review scoring, limit, stable ordering, completed/pending, and isolation tests; Web answer-reveal/submission tests | Chrome revealed the answer, entered a note, submitted 复习中, and advanced from 0 / 9 to 1 / 9; `03-review-session.png` | Proven |
| 10 | Modify mastery status | Review submission/update assertions and scoped bulk-status test | Chrome changed three filtered questions to 已掌握 and submitted one review as 复习中 | Proven |
| 11 | View base statistics | `test_analytics_aggregates_only_current_user_and_fills_trends`; Web labeled module/distribution/trend tests | Chrome verified total, five modules, knowledge/error rankings, mastery, and both 7/30-day trend states; `04-analytics.png` | Proven |
| 12 | Isolate all data by user | Question, analysis, upload/download, review-history/submission, dashboard, and analytics owner-scope tests | A second account opening the demo user's detail ID received the privacy-safe not-found/permission state and no question content | Proven |
| 13 | Bulk delete and bulk status | `test_bulk_status_and_delete_are_scoped_and_report_missing_ids`; Web confirmation, focus trap, Escape, retry, and selected-ID tests | Chrome exercised multi-select and bulk status; destructive delete requires the tested confirmation dialog | Proven |
| 14 | Keep login state | Signed-cookie `/auth/me`, invalid-session, logout, and secure-cookie tests; Web session redirect test | Synthetic account stayed authenticated across an actual Chrome reload | Proven |

## Cross-cutting constraints

- Authentication and privacy: Argon2 password hashing, seven-day signed HttpOnly/SameSite cookie, production Secure toggle, Origin enforcement, stable non-leaking errors, and auth rate limits are covered in `test_auth.py`.
- Upload safety: JPEG/PNG/WebP allow-list, byte limit, pixel/decode validation, sanitized metadata, random paths, scoped download, OCR rate limit, and stable Provider errors are covered in `test_uploads.py`.
- Provider boundary: deterministic demo OCR/analysis/advice, strict Responses schemas, preserved raw response, disabled SDK retries, server-side validation after mutation, stable error mapping, and per-user rate limits are covered in provider/question/analytics tests.
- Review rules: allowed limits 10/20/30/50, default 20, required score weights, stable ordering, remaining capacity, and same-day completion behavior are covered in `test_reviews.py`.
- Responsive and visible accessibility: 1440 × 1024 and 390 × 844 Chrome captures show no horizontal overflow; mobile navigation is a dialog, controls have names/labels, charts have numeric alternatives, and console warnings/errors were empty. This is visible/semantic evidence, not a claim of full WCAG conformance.
- Runtime reproducibility: committed Dockerfiles, Compose, `.env.example`, migrations, idempotent seed, Make targets, preflight, authenticated smoke script, and README are present; Task 10 rereview returned APPROVED after the loopback and Docker-context secret fixes.
- Scope discipline: the OpenAPI surface contains only the MVP auth, upload/OCR, question, review, analytics, dashboard, and health routes. No paid, institution, recommendation, password-reset, or free-tag product scope was added.

## Evidence limits

- Live OpenAI calls were intentionally not billed during acceptance. The real Provider contract is verified with strict mocked Responses API protocol tests, while the complete user journey runs through the visibly labeled deterministic demo Provider as required by the approved specification.
- The visible/semantic accessibility pass does not replace a dedicated screen-reader, complete keyboard-order, 200%/400% zoom, reduced-motion, or instrumented contrast audit.

Audit conclusion: every PRD P0 success criterion and every design-spec MVP matrix item has direct current evidence; no required item remains unimplemented or unverified.
