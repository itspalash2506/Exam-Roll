# ExamRoll — Design System

**Warm editorial, built for college staff, deliberately not a generic SaaS template.**

Exam departments live in paper — attestation sheets, roll lists, mark registers. The
UI borrows from that world: an old-style serif for numbers and headings, a warm
paper-white canvas instead of clinical grey, and restrained motion instead of the
usual flat-purple, Inter-everywhere AI-app look. Every token below is deliberate;
change values here rather than hardcoding hex/px in components.

Source of truth: [`frontend/src/styles/theme.css`](frontend/src/styles/theme.css)
(CSS variables) mirrored into [`frontend/tailwind.config.js`](frontend/tailwind.config.js)
(Tailwind theme), plus [`frontend/src/lib/motion.js`](frontend/src/lib/motion.js) for
motion tokens and reusable framer-motion variants.

---

## Typography

| Role | Font | Weights used |
|---|---|---|
| Display / headings / stat numbers / wordmark | **Fraunces** (variable) | 400 / 500 / 600, optical sizing on, `SOFT` axis ~28 for warmth |
| Body / UI / labels / tables / inputs | **Bricolage Grotesque** (variable) | 400 / 500 / 600 |

Self-hosted via `@fontsource-variable/fraunces` and `@fontsource-variable/bricolage-grotesque`
(npm packages, imported in `theme.css`) — no Google Fonts network call, works fully offline.
Headings get `-0.02em` letter-spacing; body text uses normal tracking at 1.5 line-height.

### Type scale (rem-based, `tailwind.config.js` → `theme.fontSize`)

| Token | Size | Line-height | Tracking | Use |
|---|---|---|---|---|
| `display` | 3rem | 1.05 | -0.02em | Hero numerals (404) |
| `h1` | 2.25rem | 1.1 | -0.02em | Page titles |
| `h2` | 1.5rem | 1.2 | -0.02em | Section titles |
| `h3` | 1.25rem | 1.3 | -0.01em | Card headings |
| `body` | 1rem | 1.5 | normal | Paragraphs |
| `small` | 0.875rem | 1.5 | normal | UI text, table cells |
| `caption` | 0.75rem | 1.4 | normal | Labels, meta text |

---

## Color — warm editorial canvas

| Token | Hex | Use |
|---|---|---|
| `canvas` | `#FAF8F4` | App background |
| `surface` | `#FFFFFF` | Cards, panels |
| `line` | `#EDE8E0` | Borders / hairlines — depth comes from borders, not shadow |
| `ink` | `#1F1B16` | Primary text |
| `muted` | `#6B6257` | Secondary text |
| `primary` / `primary-hover` | `#1F5D4C` / `#2E8168` | Deep teal-green — main accent, CTAs, links |
| `secondary` | `#C4623F` | Terracotta — sparing use: active step ring, count-row accent border |
| `success` | `#2E8168` | Positive status |
| `warning` | `#B7791F` | Caution status |
| `error` | `#B4442E` | Error status |
| `highlight` | `#F0E3C4` | Soft ochre — count rows, tinted "reading" surfaces (AI Insight card) |

**Contrast:** `ink` on `canvas`/`surface` exceeds AAA. `muted` on `canvas` is ~5.6:1 —
passes AA for all text and AAA for large text; it is used only for secondary/caption
text, never body copy that needs to carry meaning alone. White text on `primary`
is ~7.7:1 (AAA). Status badges use tinted backgrounds (`bg-{color}/10`) with the
solid color as text rather than solid fills with white text, which keeps every
badge combination at or above AA without introducing saturated, un-warm blocks of
color.

---

## Spacing, shape, depth

- **Spacing base:** 8px. Tailwind's default spacing scale (`1`=4px … `16`=64px)
  already matches the requested 4/8/12/16/24/32/48/64 scale, so no override was
  needed — just use standard spacing utilities.
- **Radius:** cards `rounded-2xl` (16px), inputs/buttons `rounded-xl` (12px),
  chips/pills `rounded-full`. These are Tailwind's built-in values, used consistently
  rather than redefined.
- **Shadow:** one soft, warm, low token — `shadow-warm`:
  `0 1px 2px rgba(31,27,22,.04), 0 8px 24px rgba(31,27,22,.05)` — plus `shadow-warm-lift`
  for modals/elevated hover states. Never a harsh grey drop shadow; borders (`border-line`)
  do most of the depth work.
- **Layout:** content is centered at `max-w-content` (1120px), applied once in
  `PageWrapper`; individual pages may nest a narrower column (e.g. the Upload wizard
  at `max-w-2xl`) where a tighter reading measure helps.

---

## Motion system

Tokens live in `frontend/src/lib/motion.js`.

- **Durations:** fast `0.18s`, base `0.28s`, slow `0.5s`.
- **Easing:** `standard` = `cubic-bezier(0.22, 1, 0.36, 1)`, `entrance` = `cubic-bezier(0.16, 1, 0.3, 1)`.
- **Page transitions:** fade + 8px upward slide at base duration (`PageWrapper`, via
  `AnimatePresence` + `useOutlet()`).
- **List/card entrance:** `staggerContainer` / `staggerItem` — ~60ms stagger, each
  child fades + rises 12px (Dashboard recent jobs, History rows, stat grids).
- **Stat numbers:** `useCountUp()` animates from the previous value to the new one
  on mount/update; jumps instantly if `prefers-reduced-motion: reduce`.
- **Buttons:** `whileTap` scale `0.98` (`buttonTap()`); hover is a plain
  `transition-colors duration-fast` background shift (no transform, so it's
  reduced-motion-safe by default).
- **Interactive cards:** `cardHover()` — lift 2px + border warms to `primary` on hover.
- **Reduced motion:** every framer-motion variant builder takes a `reduced` boolean
  (from `useReducedMotion()`) and drops transforms, keeping opacity-only fades. A
  global CSS rule in `theme.css` also collapses all plain CSS transitions/animations
  to ~0 under `prefers-reduced-motion: reduce`, so hand-written CSS transitions
  (borders, backgrounds) are covered without individual guards.

---

## Wordmark

A serifed **"ER"** monogram (Fraunces, set in a rounded-xl teal badge) beside the
"ExamRoll" wordmark in Fraunces — deliberately not a generic graduation-cap icon.
See `Navbar.jsx`.

---

## Rationale

This is a tool exam-cell staff use to turn paper attestation sheets into structured
data — the visual language leans into that (serif numerals, paper-warm canvas,
hairline borders) rather than borrowing the flat-purple-gradient, Inter-font
look common to AI-generated app scaffolds. Teal-green reads as institutional and
calm without being corporate-blue; terracotta and ochre are used sparingly as
accents, never as base colors, so the interface stays legible for long data-review
sessions.
