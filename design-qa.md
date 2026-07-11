# Design QA

## Comparison target

- Source visual truth path: `docs/design/ai-exam-diagnosis-dashboard-selected.png`
- Implementation screenshot path: `docs/qa/chrome-audit/09-dashboard-final-desktop-pass2.png`
- Viewport: Chrome, 1440 × 1024 CSS pixels; the implementation screenshot is full-page, and the comparison uses its 1440 × 1024 viewport crop.
- State: signed-in demo learner on `/dashboard`, light theme, seeded data, today's review at 1 / 9.
- Full-view comparison evidence: `docs/qa/chrome-audit/dashboard-comparison-pass1.png` and `docs/qa/chrome-audit/dashboard-comparison-pass2.png`.
- Focused region comparison evidence: `docs/qa/chrome-audit/dashboard-comparison-focus-pass2.png` covers the header, navigation, review hero, quick entry, and AI advice cards at readable scale.

## Findings

- No actionable P0, P1, or P2 findings remain.
- Typography: the implementation preserves the source's Chinese sans-serif hierarchy, strong navy headings, compact supporting text, readable line height, and restrained weight changes. Long real question text truncates on desktop tables and wraps without clipping on mobile cards.
- Spacing and layout rhythm: the fixed sidebar, top bar, dominant review card, two-column secondary cards, and recent-question table preserve the source's hierarchy and density. Card radii, borders, section gaps, and page margins remain consistent across the screen.
- Colors and visual tokens: navy text, indigo actions, pale lavender accents, light gray canvas, white cards, and semantic mastery colors map consistently to the source direction and remain legible in the captured states.
- Image quality and asset fidelity: the source does not rely on photography or illustration. Product icons use one consistent Lucide stroke family; the product mark and functional icons remain sharp at desktop and mobile sizes. The OCR preview uses the uploaded raster image without distortion.
- Copy and content: all app-specific copy is coherent in standalone use. Differences from the visual target's sample greeting, dates, counts, and question content are intentional live-product data differences rather than visual drift.
- Responsiveness: `docs/qa/chrome-audit/06-dashboard-mobile.png` and `docs/qa/chrome-audit/07-library-mobile.png` show the 390 × 844 layout. Chrome measurements reported `scrollWidth === clientWidth` on both routes, the sidebar becomes an accessible navigation dialog, and persistent actions remain visible.
- Interaction and accessibility evidence: registration/login persistence, per-user 404 isolation, manual entry, screenshot upload, OCR, editable recognition results, save, explicit AI analysis, filters, bulk status updates, review submission, analytics range switching, empty states, and mobile navigation were exercised. Semantic headings, named form controls, a labeled progress bar, and the navigation dialog were present. Chrome console errors and warnings: none.

## Comparison history

### Pass 1 — blocked

- Earlier finding: `[P2][spacing]` the desktop header date and account metadata visually touched, weakening grouping and scanability.
- Evidence: `docs/qa/chrome-audit/dashboard-comparison-pass1.png` and `docs/qa/chrome-audit/08-dashboard-final-desktop.png`.
- Fix made: `AppHeader` now wraps date and account metadata in one `gap-6` group with the accessible label `学习日期与当前用户`; a component regression test covers the grouping.

### Pass 2 — passed

- Post-fix evidence: `docs/qa/chrome-audit/09-dashboard-final-desktop-pass2.png`, `docs/qa/chrome-audit/dashboard-comparison-pass2.png`, and `docs/qa/chrome-audit/dashboard-comparison-focus-pass2.png`.
- Result: the header separation is clear, the five required fidelity surfaces remain consistent, and no actionable P0/P1/P2 difference remains.

## Primary browser interactions tested

1. Register a new user, reload, and confirm session persistence.
2. Open another user's question URL and confirm the privacy-safe not-found/permission state.
3. Select a PNG, upload it, start OCR, edit recognized fields, and save the question.
4. Start AI diagnosis only after the explicit user action and confirm the labeled demo result.
5. Filter the library, select multiple questions, and update mastery status in bulk.
6. Reveal a review answer, submit a note and result, and confirm dashboard progress updates.
7. Switch analytics between 7-day and 30-day views.
8. Open the mobile navigation and inspect dashboard/library reflow at 390 × 844.

## Residual verification limits

- This run checked visible structure, responsive behavior, semantic DOM output, and console health. It does not claim full WCAG conformance; a dedicated screen-reader, full keyboard traversal, zoom/text-scaling, and instrumented contrast pass would still be required for that claim.

final result: passed
