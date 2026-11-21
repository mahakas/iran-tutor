# UI Polish Report (branch `arena/e8b0f850-iran-tutor`)

Status: **partial slice, Verification Gate reached.** The full scope in the
request (admin categorized sidebar, KPI dashboard, all per-screen items,
toasts, lightbox, stepper, timeline, notebook print QA) is NOT complete.

## Done in this slice

| Area | Change |
|---|---|
| Font | `@fontsource/vazirmatn` 5.3.0 installed locally; Arabic/Persian subsets 400/500/700 imported in `app/layout.tsx`. Works offline (woff files bundled by `next build`). |
| Tokens | `globals.css` `:root`: paper canvas `#f8f6f1`, Teal `#0f766e`, Teal-dark `#0b5d57`, Deep Indigo `--indigo`, Amber `--amber`, semantic `--success/--warning/--danger`, `--radius-pill`, `--touch-min: 44px`, `--focus-ring`. Default preset in `lib/preferences.ts` updated to match, since runtime inline CSS variables override the stylesheet. |
| Dark mode | Header toggle in `StudentApp.tsx` calls `updatePreferences({appearance:{color_mode}})`. This writes localStorage and syncs the server (existing path). Icon follows `data-theme` through a MutationObserver after mount (no hydration mismatch). |
| Focus & motion | Unified `:focus-visible` ring. `prefers-reduced-motion` media query added on top of the existing user setting. |
| Touch | `pointer: coarse` raises buttons, sidebar items, and admin tabs to 44px. |
| Numbers / code | `tabular-nums` on table cells and KPI grids. `pre`/`code` forced LTR, monospace. Wide content gets `overflow-x: auto`. |
| Responsive | Admin tabs become a horizontal scroll strip below 768px. Student topbar tightened below 640px. Flashcard SM-2 buttons become a 2×2 grid below 640px. |
| Immersive reader | Mobile tab switcher "صفحه کتاب \| گفت‌وگو با معلم" (`role="tablist"`) below 640px; layout stacks to one column. Desktop split view unchanged. |
| Primitives | `.skeleton` (shimmer, reduced-motion safe), `.empty-state` CSS. Not yet wired into screens. |
| Print | `@media print` hides chrome and actions and keeps RTL, for notebook/reading content. Not yet QA'd on a real print preview. |

## Not done (remaining work)

- Admin sidebar with categories (dashboard/monitoring, providers/routing, capabilities/Skills, books/KB, users/quotas) and mobile drawer. Currently the three-tab `AdminGate` shell and the internal section state in `app/admin/page.tsx` are unchanged.
- Toast system, lightbox for `source_figures`, Deep Solve stepper, mastery timeline, Memory Inspector timeline cards, provider Test Connection feedback, KPI redesign, Skill version compare, book-processing progress.
- Wiring skeletons and Persian empty states into existing lists.
- Chat `dvh` keyboard-safe input check on real mobile devices.
- Visual QA of KaTeX, Mermaid, SvgDiagram, and diff readability in light and dark themes, and print preview.

## Verification

- `npx tsc --noEmit`: exit 0.
- `npm run build`: exit 0 (Vazirmatn woff files present in `.next/static/media`).
- `pytest -q tests` (backend): 308 passed, 1 skipped (same as Phase 7 baseline; backend unchanged).
- No `console.log` added. No new `NEXT_PUBLIC_*` variables. No changes to DOMPurify, `securityLevel: "strict"`, `lib/safeVisual.ts`, or SvgDiagram/MermaidDiagram.
- **Not verified:** real browser rendering at 360/768/1024px and in dark mode. The sandbox cannot download Playwright's Chromium (CDN blocked), so these checks are still open and need a manual pass or a browser-enabled environment.
