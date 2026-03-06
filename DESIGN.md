# CWA School — Design Specification
**Version:** 1.0
**Application:** classroom.wizardslearninghub.co.nz
**Last Revised:** 2026-03-07

---

## Table of Contents
1. [Brand Identity](#1-brand-identity)
2. [Design Tokens](#2-design-tokens)
3. [Typography](#3-typography)
4. [Spacing & Layout Grid](#4-spacing--layout-grid)
5. [Component Library](#5-component-library)
6. [Page Layouts](#6-page-layouts)
7. [Subject App Theming](#7-subject-app-theming)
8. [Navigation Patterns](#8-navigation-patterns)
9. [Responsive Design](#9-responsive-design)
10. [Interaction & Motion](#10-interaction--motion)
11. [Iconography](#11-iconography)
12. [Imagery & Illustration](#12-imagery--illustration)
13. [Forms & Validation](#13-forms--validation)
14. [Empty & Error States](#14-empty--error-states)
15. [Accessibility](#15-accessibility)

---

## 1. Brand Identity

### 1.1 Logo
The CWA School logo is a green robot character (sticker-style illustration).

| Usage | Size | Context |
|-------|------|---------|
| Topbar (authenticated) | `h-9` (36 px) | Left of app name |
| Public nav | `h-9` (36 px) | Left of "Classroom" wordmark |
| Auth pages (login/register) | `h-16` (64 px) | Centred above form |
| Favicon | 32×32 px | Browser tab |

**Rules:**
- Never distort or stretch the logo
- Minimum clear space: equal to the height of the robot's head on all sides
- On dark backgrounds use the full-colour version with white outline
- Never place on a busy background — use a solid or lightly patterned surface

### 1.2 App Name Wordmark
`Classroom` — rendered in **Fredoka One** (Google Fonts), `text-primary`, `text-2xl`.
On public pages the wordmark appears to the right of the logo, separated by 8 px gap.

### 1.3 Tagline
*"Discover the magic of learning"* — used on the public landing hero only.

---

## 2. Design Tokens

### 2.1 Colour Palette

#### Brand Colours
| Token | Hex | Tailwind Class | Usage |
|-------|-----|----------------|-------|
| `primary` | `#16a34a` | `text-primary` / `bg-primary` | Primary actions, active nav, brand green |
| `primary-dark` | `#15803d` | `bg-primary-dark` | Hover state on primary |
| `primary-light` | `#bbf7d0` | `bg-primary-light` | Tinted backgrounds, badges |
| `accent` | `#eab308` | `bg-accent` | Stars, achievements, secondary CTAs |
| `accent-dark` | `#ca8a04` | `bg-accent-dark` | Hover on accent |
| `accent-light` | `#fef9c3` | `bg-accent-light` | Soft highlight backgrounds |

#### Surface Colours
| Token | Hex | Usage |
|-------|-----|-------|
| `surface` | `#ffffff` | Cards, modals, panels |
| `surface-alt` | `#f0fdf4` | Page background |
| `border` | `#d1fae5` | Card borders, dividers |

#### Text Colours
| Token | Hex | Usage |
|-------|-----|-------|
| `text-primary` | `#14532d` | Headings, important labels |
| `text-body` | `#374151` | Body copy, descriptions |
| `text-muted` | `#6b7280` | Secondary text, placeholders |

#### Semantic Colours
| Token | Hex | Usage |
|-------|-----|-------|
| `danger` | `#ef4444` | Errors, destructive actions |
| `warning` | `#f59e0b` | Warnings, below-average indicators |
| `info` | `#3b82f6` | Info banners, tips |
| `success` | `#22c55e` | Confirmations, correct answers |

### 2.2 Subject Accent Colours
Each subject app has its own accent colour used for headers and active states.

| Subject | Primary Colour | Light Tint | Hex |
|---------|---------------|------------|-----|
| Maths | Green | Green-50 | `#16a34a` / `#f0fdf4` |
| Science | Teal | Teal-50 | `#0d9488` / `#f0fdfa` |
| Coding | Indigo | Indigo-50 | `#4f46e5` / `#eef2ff` |
| Music | Purple | Purple-50 | `#7c3aed` / `#f5f3ff` |

### 2.3 Role Badge Colours
| Role | Badge Classes |
|------|--------------|
| Admin | `bg-red-100 text-red-700` |
| Teacher | `bg-blue-100 text-blue-700` |
| Student | `bg-green-100 text-green-700` |
| Individual Student | `bg-purple-100 text-purple-700` |
| Head of Department | `bg-orange-100 text-orange-700` |
| Accountant | `bg-gray-100 text-gray-700` |

---

## 3. Typography

### 3.1 Font Stack

| Role | Font Family | Weights | Import |
|------|------------|---------|--------|
| Display / Logo / Headings | `Fredoka One` | 400 | Google Fonts |
| Body / UI | `Nunito` | 400, 600, 700 | Google Fonts |
| Monospace (scores, code) | `JetBrains Mono` | 400 | Google Fonts |

```html
<!-- Google Fonts import (in base.html <head>) -->
<link href="https://fonts.googleapis.com/css2?family=Fredoka+One&family=Nunito:wght@400;600;700&family=JetBrains+Mono&display=swap" rel="stylesheet">
```

### 3.2 Type Scale

| Name | Size | Weight | Line Height | Usage |
|------|------|--------|-------------|-------|
| Display XL | `4xl` (36 px) | 400 (Fredoka) | 1.2 | Hero headings |
| Display L | `3xl` (30 px) | 400 (Fredoka) | 1.25 | Page titles |
| Heading | `2xl` (24 px) | 700 (Nunito) | 1.3 | Section headings |
| Subheading | `xl` (20 px) | 700 (Nunito) | 1.4 | Card titles, subheadings |
| Body | `base` (16 px) | 400 (Nunito) | 1.6 | Body copy |
| Body Strong | `base` (16 px) | 600 (Nunito) | 1.6 | Emphasis, labels |
| Small | `sm` (14 px) | 400 (Nunito) | 1.5 | Captions, helper text |
| XSmall | `xs` (12 px) | 600 (Nunito) | 1.4 | Badges, tags |
| Mono | `sm` (14 px) | 400 (JetBrains) | 1.4 | Scores, code snippets |

---

## 4. Spacing & Layout Grid

### 4.1 Spacing Scale
Uses Tailwind's default spacing scale (base unit = 4 px).

| Token | px | Use |
|-------|-----|-----|
| `1` | 4 px | Micro gaps (icon to label) |
| `2` | 8 px | Tight component padding |
| `3` | 12 px | Button horizontal padding |
| `4` | 16 px | Standard component padding |
| `6` | 24 px | Card internal padding |
| `8` | 32 px | Section spacing |
| `12` | 48 px | Large section gaps |
| `16` | 64 px | Hero section padding |

### 4.2 Layout Structure (Authenticated App)

```
┌──────────────────────────────────────────────┐
│  TOPBAR (fixed, h-16, z-50)                  │
├──────────────┬───────────────────────────────┤
│              │                               │
│  SIDEBAR     │   MAIN CONTENT               │
│  (w-64)      │   (flex-1, overflow-y-auto)  │
│  hidden md   │                               │
│  flex        │   max-w-7xl mx-auto px-4     │
│              │   py-8                        │
│              │                               │
└──────────────┴───────────────────────────────┘
│  BOTTOM NAV (mobile only, fixed, h-16)       │
└──────────────────────────────────────────────┘
```

### 4.3 Content Width
| Context | Max Width | Tailwind |
|---------|-----------|---------|
| Standard page content | 80 rem (1280 px) | `max-w-7xl` |
| Narrow (forms, auth) | 28 rem (448 px) | `max-w-md` |
| Reading width | 42 rem (672 px) | `max-w-2xl` |
| Full bleed | 100% | — |

---

## 5. Component Library

### 5.1 Buttons

| Variant | Classes |
|---------|---------|
| Primary | `bg-primary text-white hover:bg-primary-dark rounded-xl px-5 py-2.5 font-semibold transition` |
| Accent | `bg-accent text-white hover:bg-accent-dark rounded-xl px-5 py-2.5 font-semibold transition` |
| Secondary | `bg-white border border-primary text-primary hover:bg-primary-light rounded-xl px-5 py-2.5 font-semibold transition` |
| Danger | `bg-red-500 text-white hover:bg-red-600 rounded-xl px-5 py-2.5 font-semibold transition` |
| Ghost | `text-primary hover:bg-primary-light rounded-xl px-5 py-2.5 font-semibold transition` |
| Link | `text-primary underline hover:text-primary-dark font-semibold` |

**Sizes:**
- Default: `px-5 py-2.5 text-sm`
- Large: `px-6 py-3 text-base`
- Small: `px-3 py-1.5 text-xs`

**States:** `disabled:opacity-50 disabled:cursor-not-allowed`

### 5.2 Cards

```html
<!-- Standard card -->
<div class="rounded-2xl bg-white border border-border shadow-sm hover:shadow-md transition p-6">
```

```html
<!-- Subject card (hub page) -->
<div class="rounded-2xl bg-white border-2 border-primary/20 shadow-sm hover:shadow-md hover:border-primary/40 transition p-6">
```

```html
<!-- Stat card -->
<div class="rounded-xl bg-surface-alt border border-border p-4 text-center">
```

### 5.3 Form Inputs

```html
<!-- Text input -->
<input class="w-full rounded-lg border border-gray-300 px-4 py-2.5
              focus:ring-2 focus:ring-primary focus:border-transparent
              placeholder:text-text-muted text-text-body">

<!-- Select -->
<select class="w-full rounded-lg border border-gray-300 px-4 py-2.5
               focus:ring-2 focus:ring-primary focus:border-transparent">

<!-- Textarea -->
<textarea class="w-full rounded-lg border border-gray-300 px-4 py-2.5
                 focus:ring-2 focus:ring-primary focus:border-transparent
                 resize-none">
```

**Error state:** `border-danger ring-2 ring-danger/30`

### 5.4 Badges & Pills

```html
<!-- Role badge -->
<span class="rounded-full px-3 py-1 text-xs font-semibold bg-green-100 text-green-700">
  Teacher
</span>

<!-- Coming Soon badge -->
<span class="rounded-full px-3 py-1 text-xs font-semibold bg-accent-light text-amber-700">
  Coming Soon
</span>

<!-- Active/success badge -->
<span class="rounded-full px-2.5 py-0.5 text-xs font-semibold bg-primary-light text-primary">
  Active
</span>
```

### 5.5 Alerts & Toasts

```html
<!-- Success toast -->
<div class="fixed bottom-4 right-4 md:bottom-6 md:right-6 z-50
            bg-white border border-green-200 rounded-xl shadow-lg
            p-4 flex items-center gap-3 min-w-72">
  <!-- icon + message -->
</div>

<!-- Error alert (inline) -->
<div class="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
```

**Toast behaviour:** Auto-dismiss after 4 s. Bottom-right on desktop, top-centre on mobile.

### 5.6 Navigation Items (Sidebar)

```html
<!-- Active nav item -->
<a class="flex items-center gap-3 px-4 py-3 rounded-xl
          text-white font-semibold bg-white/20 transition">

<!-- Inactive nav item -->
<a class="flex items-center gap-3 px-4 py-3 rounded-xl
          text-white font-semibold hover:bg-white/10 transition">
```

### 5.7 Progress Bars

```html
<!-- Standard progress bar -->
<div class="w-full bg-gray-200 rounded-full h-2">
  <div class="bg-primary h-2 rounded-full transition-all" style="width: 65%"></div>
</div>
```

**Score colour bands (quiz results):**
| Score | Background | Text |
|-------|-----------|------|
| ≥ 90% | `bg-green-600` | `text-white` |
| ≥ 75% | `bg-green-400` | `text-white` |
| ≥ 60% | `bg-green-200` | `text-green-900` |
| ≥ 45% | `bg-yellow-200` | `text-yellow-900` |
| ≥ 30% | `bg-orange-200` | `text-orange-900` |
| < 30% | `bg-red-200` | `text-red-900` |

---

## 6. Page Layouts

### 6.1 Public Landing Page (`/`)
```
┌────────────────────────────────────┐
│  PUBLIC NAV (logo + links + CTA)   │
├────────────────────────────────────┤
│  HERO                              │
│  • Headline (Fredoka, 4xl)         │
│  • Subheading (Nunito, lg)         │
│  • CTA buttons (Primary + Ghost)   │
│  • Decorative illustration         │
├────────────────────────────────────┤
│  FEATURES (3-col grid)             │
├────────────────────────────────────┤
│  SUBJECTS PREVIEW (card grid)      │
├────────────────────────────────────┤
│  FOOTER                            │
└────────────────────────────────────┘
```

### 6.2 Subject Hub (`/hub/`)
```
┌────────────────────────────────────┐
│  TOPBAR                            │
├──────────┬─────────────────────────┤
│ SIDEBAR  │  Welcome, {Name}!       │
│          │  ─────────────          │
│          │  YOUR SUBJECTS          │
│          │  ┌──┐ ┌──┐ ┌──┐ ┌──┐  │
│          │  │Ma│ │Sc│ │Co│ │Mu│  │
│          │  └──┘ └──┘ └──┘ └──┘  │
│          │  (subject cards)        │
└──────────┴─────────────────────────┘
```

### 6.3 Auth Pages (login, register)
```
┌────────────────────────────────────┐
│  Gradient background               │
│  ┌──────────────────────────────┐  │
│  │  Logo (h-16, centred)        │  │
│  │  App name                    │  │
│  │  ──────────────              │  │
│  │  Form fields                 │  │
│  │  Submit button               │  │
│  │  Links (forgot pw, signup)   │  │
│  └──────────────────────────────┘  │
└────────────────────────────────────┘
```

### 6.4 Subject App Layout (Maths, etc.)

Each subject app uses the shared **topbar + sidebar** layout but with the subject's accent colour on the sidebar.

```
┌────────────────────────────────────┐
│  TOPBAR (shared, primary green)    │
├──────────┬─────────────────────────┤
│ SUBJECT  │                         │
│ SIDEBAR  │   SUBJECT CONTENT       │
│ (accent  │                         │
│ colour)  │                         │
└──────────┴─────────────────────────┘
```

---

## 7. Subject App Theming

Each subject app can override the sidebar colour via a CSS variable or Tailwind class on the sidebar container.

| Subject | Sidebar Gradient | Icon |
|---------|-----------------|------|
| Maths | `from-green-700 to-green-600` | Calculator |
| Science | `from-teal-700 to-teal-600` | Flask |
| Coding | `from-indigo-700 to-indigo-600` | Code brackets |
| Music | `from-purple-700 to-purple-600` | Music note |

### Subject Card (Hub Page)

```
┌───────────────────────────────┐
│  [Icon 48px]                  │
│                               │
│  Subject Name   (heading)     │
│  Description    (text-muted)  │
│                               │
│  [Go to {Subject} →] button   │
│  or                           │
│  [Coming Soon] badge          │
└───────────────────────────────┘
```

**Active subject card:** full colour icon, primary border, clickable button
**Coming soon card:** greyed-out icon (`opacity-40`), no button, yellow "Coming Soon" badge

---

## 8. Navigation Patterns

### 8.1 Topbar (authenticated, all apps)

```
[☰ hamburger (mobile)] [Logo] [App Name]     [Role Badge] [🔔] [Avatar ▾]
```

- Height: `h-16` (64 px), fixed, `z-50`
- Background: `bg-white border-b border-border shadow-sm`
- Logo links to `/hub/`
- Avatar dropdown: Profile, Change Password, Sign Out

### 8.2 Public Nav (landing pages)

```
[Logo] [Classroom]     [Home] [Subjects] [Contact] [Join Class]   [Sign In]
```

- Height: `h-16`, sticky on scroll
- Background: `bg-white/95 backdrop-blur border-b border-border`
- On mobile: collapsed to hamburger menu

### 8.3 Sidebar (desktop, authenticated)

- Width: `w-64`, fixed left, `top-16` (below topbar), full height
- Background: subject accent colour gradient
- Nav items: icon (20 px SVG) + label, `rounded-xl` hover states
- Active state: `bg-white/20`
- Bottom section: Profile link (always last)

### 8.4 Bottom Navigation (mobile, authenticated)

- Fixed bottom, `h-16`, `z-40`
- Background: subject accent colour
- 3–4 icons: subject-specific primary actions + More (☰)
- Active icon: white + label, inactive: `white/60`

---

## 9. Responsive Design

### 9.1 Breakpoints (Tailwind defaults)
| Name | Width | Usage |
|------|-------|-------|
| `sm` | 640 px | Small phones (rarely targeted explicitly) |
| `md` | 768 px | Tablet — sidebar appears, bottom nav hides |
| `lg` | 1024 px | Desktop layout fully visible |
| `xl` | 1280 px | Content max-width reached |

### 9.2 Responsive Behaviour

| Element | Mobile | Desktop (md+) |
|---------|--------|---------------|
| Sidebar | Hidden — slide-out drawer | Fixed left, always visible |
| Bottom nav | Fixed bottom `flex` | Hidden (`hidden`) |
| Content area | Full width, `px-4` | Left margin `ml-64`, `px-8` |
| Card grids | 1 column | 2–3 columns |
| Topbar | Logo + hamburger | Logo + full nav items |

---

## 10. Interaction & Motion

### 10.1 Transition Defaults
All interactive elements use `transition` (150 ms ease-in-out).
For transforms (hover scale effects): `transition-transform duration-150`.

### 10.2 Standard Hover Effects
- Buttons: background colour shift (defined per variant)
- Cards: `hover:shadow-md` (box-shadow increase)
- Nav items: background `hover:bg-white/10`
- Links: colour darkens (`hover:text-primary-dark`)

### 10.3 HTMX Transitions
Partial updates use HTMX with no page reload. Loading state: spinner icon replaces submit button text.
Quiz question transitions: `hx-swap="innerHTML transition:true"`.

### 10.4 Toast Notifications
- Appear bottom-right with `translateY(0)` from `translateY(100%)`
- Duration: 300 ms ease-out
- Auto-dismiss: 4 000 ms
- Manual dismiss: × button

---

## 11. Iconography

All icons use **Heroicons** (24 px outline style) from `heroicons.com`.
Inline SVG only — no icon font or sprite sheet.

**Standard icon sizes:**
| Context | Size | Tailwind |
|---------|------|---------|
| Sidebar nav | 20 px | `w-5 h-5` |
| Button icons | 16 px | `w-4 h-4` |
| Feature icons | 48 px | `w-12 h-12` |
| Subject card icons | 48 px | `w-12 h-12` |
| Inline text icons | 16 px | `w-4 h-4 inline` |

**Subject icons:**
| Subject | Icon name |
|---------|-----------|
| Maths | `CalculatorIcon` |
| Science | `BeakerIcon` |
| Coding | `CodeBracketIcon` |
| Music | `MusicalNoteIcon` |

---

## 12. Imagery & Illustration

### 12.1 Logo Robot
- Sticker-style green robot illustration
- Used in nav, auth pages, coming-soon pages, email headers
- File: `static/images/logo.png`
- Do not use as a background pattern or at very small sizes (< 24 px)

### 12.2 Hero Illustration (`hero.svg`)
- Abstract green circle/blob decorative element
- Used on the public landing page hero section
- Positioned absolutely, behind content, `opacity-20`

### 12.3 Question Images
- Uploaded by teachers, stored in `MEDIA_ROOT/questions/`
- Displayed at `max-w-full rounded-lg` within quiz cards
- Alt text is always provided (question context)

---

## 13. Forms & Validation

### 13.1 Field Labels
- Always above the input (never inside as placeholder-only)
- `text-sm font-semibold text-text-body mb-1`

### 13.2 Placeholders
- Supplementary hint only, not a replacement for a label
- `text-text-muted`

### 13.3 Error Display

```html
<!-- Field error (inline, below input) -->
<p class="mt-1 text-xs text-danger font-medium">This field is required.</p>

<!-- Form-level error (top of form) -->
<div class="rounded-xl bg-red-50 border border-red-200 px-4 py-3 mb-4">
  <ul class="text-sm text-danger space-y-1">
    <li>• Username is already taken.</li>
  </ul>
</div>
```

### 13.4 Success State
After successful submission: redirect with a Django `messages.success()` toast notification. Do not show inline success states on form fields.

---

## 14. Empty & Error States

### 14.1 Empty States
When a list or grid has no items:
```html
<div class="text-center py-12 text-text-muted">
  <svg class="w-12 h-12 mx-auto mb-3 opacity-40"> ... </svg>
  <p class="font-semibold">No classes yet</p>
  <p class="text-sm mt-1">Create your first class to get started.</p>
</div>
```

### 14.2 404 Page
- Centred layout on `bg-surface-alt`
- Logo + "404" in large Fredoka
- Message: "Oops! Page not found"
- Back to Home button

### 14.3 500 Page
- Same layout as 404
- Message: "Something went wrong on our end"
- Retry / Back to Home

---

## 15. Accessibility

### 15.1 Colour Contrast
All text/background combinations must meet **WCAG AA** (4.5:1 for normal text, 3:1 for large text).

| Combination | Ratio | Pass |
|-------------|-------|------|
| `#14532d` on `#ffffff` | 12.5:1 | ✅ |
| `#374151` on `#ffffff` | 9.7:1 | ✅ |
| `#ffffff` on `#16a34a` | 4.6:1 | ✅ |
| `#6b7280` on `#ffffff` | 4.6:1 | ✅ |

### 15.2 Focus States
All interactive elements must have a visible focus ring:
`focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2`

### 15.3 ARIA
- All icon-only buttons must have `aria-label`
- Sidebar nav uses `role="navigation"` and `aria-label="Main navigation"`
- Quiz options use `role="radio"` / `role="radiogroup"`
- Toast notifications use `role="alert"` and `aria-live="polite"`

### 15.4 Keyboard Navigation
- All interactive elements reachable by Tab
- Modal/drawer: focus trapped inside, Esc to close
- Quiz: arrow keys to navigate answer options

---

*This document is the design source of truth for the CWA School platform. All new UI work should reference these tokens, components, and patterns.*
