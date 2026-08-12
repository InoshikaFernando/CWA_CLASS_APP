# CPP-372: Classes Page UI Update

## Problem

The Head of Department / Head of Institute **Manage Classes** page
(`/department/manage-classes/`, `HoDManageClassesView` →
`templates/hod/manage_classes.html`) defaulted to a cramped list view:

- It opened in **list** view, not grid.
- The grid view was capped at **2 columns** (the shared `partials/view_toggle.html`
  grid tops out at two), so a full page was 2 × 5 = 10 tiles instead of a dense
  grid.
- Tiles omitted two facts staff want at a glance: the class **location**
  (its school) and its **level(s)**.
- Action buttons carried full text captions (*Edit* / *Assign Staff* / *Delete*),
  which crowd a compact tile.
- There was **no way to reorder** the list — it was always alphabetical by name.

## Fix

All changes are scoped to this page; the shared `view_toggle.html` partial is
left untouched so the teacher / student / parent class pages are unaffected.

### 1. Grid is the default view

The `view_toggle` include now passes `default_view="grid"`, and the card
container is rendered with `class="cwa-grid"` on first load. (A returning user's
saved `localStorage` choice still wins, as before.)

### 2. Four columns, 40 tiles per page

Page-scoped CSS overrides the shared 2-column cap: `#hod-classes.cwa-grid` uses
3 columns from the `lg` breakpoint and **4 columns** from `xl`. The Alpine
client-side pager's `perPage` was raised from 10 to **40**, so a full wide page
is 4 × 10 = 40 tiles.

### 3. Tiles show location + level

Each tile now shows the class's **school name** (with a map-pin icon) as its
location, and a row of **level badges** from `ClassRoom.levels`, in addition to
the existing name, department, code, schedule and staff. The view eager-loads
these (`select_related('school').prefetch_related('levels')`) to avoid an N+1.

### 4. Icon-only buttons in grid

The Edit / Assign Staff / Delete captions are wrapped in `<span class="cwa-btn-label">`
and hidden in grid via `#hod-classes.cwa-grid .cwa-btn-label { display: none; }`,
leaving icon-only buttons. `title` / `aria-label` attributes were added so the
icons stay accessible. Switching to list view brings the captions back.

### 5. Ordering control

A **Sort** dropdown (Name / Level / Date/Time) sits beside the view toggle. It
reloads the page with a `?sort=` param (folded into the existing
`applyFilters()` so school / department filters are preserved). The view orders
the queryset accordingly:

- **name** — `order_by('name')` (default).
- **level** — `annotate(Min('levels__level_number'))`, then by that minimum
  level and name.
- **schedule** (*Date/Time*) — the day + start time shown on each tile, mapping
  the weekday choice to an index (Monday → 0 … Sunday → 6, blank days last) via a
  `Case/When` annotation, then by `start_time` and name.

## Tests

- `classroom/tests/test_manage_classes_ui.py` — default grid class, `perPage: 40`,
  the 4-column CSS rule, location + level on tiles, wrapped icon-only captions,
  the sort control, and each of the three sort orders.
- `ui_tests/test_cpp372_manage_classes_ui.py` — Playwright: grid is the active
  default, captions hidden in grid and shown in list, location + level visible,
  and the level sort reorders the tiles.
