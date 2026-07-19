# أثر / Athar — Design System

> App-adapted edition of `../DesignMD.txt` (the Cursor-style editorial system).
> Tokens transfer verbatim; this file documents the transfer, the Arabic/RTL
> adaptation, and the extensions DesignMD's "Known Gaps" section invites.
> Rule of rules: **use token refs, never inline hex** (`src/styles/tokens.css`).

## 1. Provenance
Source: `DesignMD.txt` — warm cream canvas, warm ink, one scarce orange accent,
display weight 400 ("magazine voice"), hairline-only depth, JetBrains Mono on
technical surfaces, five pastel AI-timeline pills, 8px CTA / 12px card radii.

## 2. Color
| Token | Value | Use |
|---|---|---|
| `canvas` | #f7f7f4 | page floor — never pure white |
| `canvas-soft` | #fafaf7 | inner panes, image placeholders |
| `card` | #ffffff | cards |
| `hairline / -soft / -strong` | #e6e5e0 / #efeee8 / #cfcdc4 | the only depth mechanism — **no shadows** |
| `ink` | #26251e | display + emphasis |
| `body / muted / muted-soft` | #5a5852 / #807d72 / #a09c92 | running text ladder |
| `primary` | #f54e00 | **one primary CTA per screen** + focus ring tint. Scarce. |
| `success / error / warning` | #1f8a65 / #cf2d56 / #b45309 | semantic. `warning` is an athar extension (needs-review). |

**Pastel pills** (`pill-thinking/triage/read/edit/done`) are re-scoped exactly as
DesignMD prescribes ("in-product agent visualizations only"): they appear **only**
in `PipelineProgress` — peach=تفكير عميق, mint=الفرز, blue=تحليل الإطارات,
lavender=التعليم, gold=اكتمل. Never for categories, statuses, or buttons.

**Category badge tokens** (extension, ≠ pastels): weapons #c25e4c ·
biological #a94464 · impressions #7b6fa8 · documents #4e7fa5 · markers #8a7b3c ·
trace #5e8f6c · human #6b6b6b (deliberately neutral/dignified). White text, AA on all.

**«سري» stamp**: error-red outline badge; appears in the top nav, login, report
preview chrome, and on every PDF page corner.

## 3. Typography — Arabic rules (CRITICAL)
- Family: **IBM Plex Sans Arabic** (replaces licensed CursorGothic); Inter for
  Latin fallback; **JetBrains Mono** for hashes, ids, model slugs, GPS, costs.
- Display stays **weight 400** — the magazine voice survives translation.
- **`letter-spacing: 0` on every Arabic run.** Negative tracking visually breaks
  Arabic cursive joining. The global reset enforces it; DesignMD's negative
  tracking exists only via the `.latin` utility on Latin/numeric spans.
- `caption-uppercase` → Arabic has no uppercase: mapped to 11px/600 label style,
  tracking 0.
- Arabic body line-height **1.7** (vs 1.5 Latin) — enforced on `body`.

## 4. Numerals policy
Arabic-Indic (٠١٢٣) in prose, counts, dates, badges (`lib/format.ts` is the only
formatter). Western digits in mono technical surfaces (hashes, slugs, dollar
costs). Raster annotation badges use Arabic-Indic digits only — digits are
non-joining, so they render correctly without a shaping engine; **no shaped
Arabic words are ever rasterized onto images**.

## 5. RTL
`<html dir="rtl">` + Tailwind logical utilities (`ms-* me-* ps-* pe-*`,
`text-start`). Mirrored by design: timeline axis (time flows **leftward**),
chevrons/arrows via lucide auto-flip where semantic. Video controls stay LTR
(`dir="ltr"` on the player container) — media time is a Latin-numeric surface.
Before/after slider handle math runs in an `dir="ltr"` container.

## 6. Depth & shape
Hairline-only. Radii: inputs/CTAs 8px (`rounded-md`), cards 12px (`rounded-lg`),
badges/pills 999px. No drop shadows anywhere — dialogs dim with an ink scrim.

## 7. Dark mode — warm-ink inversion (extension)
Light is the primary/official mode. `[data-theme="dark"]` remaps the neutral
ladder onto warm ink (#201f1a canvas → cream text); accents/semantics unchanged.
Toggle in the top nav, persisted in `localStorage`.

## 8. States (fills DesignMD "Known Gaps")
Focus: 2px primary-tinted outline, offset 2. Error fields: `error` hairline +
caption. Loading: `Spinner` (hairline ring, primary head). Motion ≤200ms,
disabled under `prefers-reduced-motion`.

## 9. Component inventory → token bindings
`Button` (primary/secondary/text/danger) · `Card` · `Badge` + `StatusBadge` +
`CategoryBadge` + `SeqBadge` (numbered circle matching raster badges) ·
`HashChip` (mono pill, click-to-copy) · `ConfidenceMeter` (hairline bar; <75% ⇒
warning tone + «يتطلب مراجعة بشرية») · `Dialog` · `UploadZone` ·
`PipelineProgress` (the pastel pills' only home) · `TimelineTrack` (RTL axis,
category-colored markers) · `EvidenceCard` (+ original/annotated toggle,
`BeforeAfterSlider`) · `AuditTable` (mono, verify band) · `OffsetEditor`.

## 10. Layout — sidebar shell
Desktop (`lg+`): fixed **264px sidebar on the inline-start edge** (right in RTL),
`bg-canvas` + `border-e` hairline — no shadow. Contents top→bottom: brand block +
«سري» badge, the app's **single primary CTA** («قضية جديدة»), global nav
(القضايا/التدقيق/الإعدادات), a **case section** that appears when a case is open
(its 8 views with icons, live run-status chip, pending-review count badge), and
a user block (avatar initials, role, theme toggle, logout). Active item: 2px
`primary` start-border + `canvas-soft` fill + primary-tinted icon. Content area:
`ms-64`, `max-w-5xl`. Mobile: 56px top bar with hamburger → start-side drawer
(72 = 288px) over an ink scrim; the case screen keeps a horizontal tab strip
`lg:hidden` so navigation never requires opening the drawer.

## 11. أثر Do / Don't
- **Do** keep orange to a single CTA per screen; **Don't** invent a second accent.
- **Do** render every hash/id in JetBrains Mono LTR; **Don't** mix digits systems in one string.
- **Don't** use stage pastels outside `PipelineProgress`.
- **Don't** add shadows, bold display type, or tracked Arabic.
- **Don't** show raw coordinates in user-facing text — human location phrases only
  (coordinates live in the DB and the overlay math).
