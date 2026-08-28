# UI tests (Playwright)

The Playwright suite is split into one package per **app area**, so CI can run
only the areas a change actually touched:

```
ui_tests/
├── conftest.py        shared fixtures (do_login, _make_user, live_server, …)
├── helpers.py         shared assertions
├── live_helpers.py    helpers for --live-url runs
├── xls_fixtures.py    spreadsheet builders for the upload tests
├── billing/           invoices, payments, fees, currency, discounts, revenue
├── brainbuzz/         BrainBuzz sessions, images, reveal
├── classroom/         classes, attendance, students, teachers, enrolment, progress
├── coding/            coding homework + coding question upload
├── feedback/          feedback widget and triage
├── homework/          homework assign/submit/monitor/leaderboard
├── live/              deployed-environment tests (-m live / -m migration)
├── maths/             interactive maths question types + maths upload
├── navigation/        login/logout, sidebars per role, hub, breadcrumbs
├── parent/            parent portal, child switcher, parent progress
├── quiz/              quiz answering and end-to-end quiz journeys
├── uploads/           question import (XLS, PDF page selection, templates)
└── worksheets/        worksheet builder, sessions, async upload
```

## Running them

```bash
cd cwa_classroom
playwright install --with-deps chromium     # once
pytest ui_tests/billing -n auto             # one area
pytest ui_tests -n auto                     # everything (~33 min)
pytest ui_tests -m smoke -n auto            # quick core-journey sanity check
```

`ui_tests/live/` needs a deployed target and skips without one:

```bash
pytest ui_tests/live --live-url=https://dev.wizardslearninghub.co.nz -n 0
```

## Adding a test

Put it in the package for the area it exercises — **not** at the `ui_tests/`
root. CI runs `pytest ui_tests/<group>`, so a file at the root would belong to
no job and would never run. `tests_workflows.py` fails the build if that
happens, and also if a group package has no matching `ui_<group>:` path filter
in `.github/workflows/ci.yml`.

Shared fixtures live one level up, so import them with two dots:

```python
from ..conftest import do_login, _make_user, TEST_PASSWORD
from ..helpers import assert_page_has_text
```

`tests_workflows.py` resolves every relative import in these packages
statically — including the ones tucked inside a function body, which pytest
would otherwise only fail on mid-run.

## How CI picks what to run

`.github/workflows/ci.yml` declares one `ui_<group>:` paths-filter per package,
listing the group's own tests plus **every app its tests actually drive** — not
just the one it is named after. `ui_tests/parent/`, for instance, drives
classroom views through accounts auth with homework and maths content, so all
four apps trigger it; a homework change that breaks the parent homework page
runs the parent group too. `tests_workflows.py` derives that set from the
tests' imports, URL literals and `reverse()` namespaces and fails the build if a
filter misses one.

| Event | What runs |
|-------|-----------|
| Pull request | the groups whose watched paths changed, in full |
| Push to `test` | the same path filter, against the previous `test` tip |
| Either, touching `ui_core` or `shared` | every group (base templates, sidebars, static and shared fixtures can break any page) |
| Push to `test` landing a tree a PR already passed | nothing; the PR run covered it, and `ui-already-tested` says so |
| Push to `main` | nothing; that tree already passed on `test` |

### Groups are packed onto runners

Selecting the groups is only half of it. A runner per group meant every group
paid its own checkout, `pip install` and Playwright browser install — about 50
seconds before its first test — and GitHub bills each job rounded **up** to a
whole minute. On a full 15-group matrix that was 53 minutes of tests billed as
87.

So `ui-matrix` packs the selected groups onto a handful of runners, heaviest
first onto whichever runner is lightest so far, up to a budget set just above
the longest single group (`billing`, ~10 min). That group already decides how
long the suite takes, so filling the others to the same depth costs nothing in
wall clock: the same 15 groups now run on 5 runners for ~60 billed minutes, in
about the same 12 minutes end to end. A partial selection packs by the same
rule and only gets cheaper — three small groups that were three billed minutes
become one.

Each runner runs one `pytest` over all of its groups, which is how the suite
ran before it was split, and why there is a single `ui_tests/conftest.py`
rather than one per group.

Adding a new group means: create the package, add the `ui_<group>:` filter and
its `ui_<group>` output in `ci.yml`, and add a `<group>:<seconds>` line to
`UI_WEIGHTS` in the `ui-matrix` job so the packing can balance it.
`tests_workflows.py` fails the build if any of the three is missing.

### The required check

The matrix jobs are named after the groups packed onto each runner (`UI Tests
(billing feedback)`, …), so that set of names changes whenever a group is added
or the packing shifts. Branch protection therefore hangs off
`ui-tests-gate`, which always runs, is named **`UI Tests (Playwright)`**, and is
red exactly when the UI suite is red. Point required checks at that name and
leave it alone — `tests_workflows.py` fails the build if it is renamed or stops
running unconditionally.
