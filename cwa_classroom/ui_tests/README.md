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
listing both the group's own tests and the app/template directories it covers.

| Event | What runs |
|-------|-----------|
| Pull request | the groups whose watched paths changed, in full |
| PR touching `ui_core` or `shared` | every group (base templates, sidebars, static and shared fixtures can break any page) |
| Push to `test` | every group — the pre-production gate is never path-filtered |
| Push to `main` | nothing; that tree already passed the full suite on `test` |

Adding a new group means: create the package, add the `ui_<group>:` filter and
its `ui_<group>` output in `ci.yml`. The matrix is built from those filter
names, so nothing else needs editing.
