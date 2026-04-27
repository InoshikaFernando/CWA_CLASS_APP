# App index

Per-app documentation. Each app's README lives next to its code in `cwa_classroom/<app>/README.md` so it stays in sync with the source.

## Core platform

| App | What it does | URL prefix |
|---|---|---|
| [accounts](../../cwa_classroom/accounts/README.md) | Auth, users, roles, profile, role switching | `/accounts/` |
| [classroom](../../cwa_classroom/classroom/README.md) | Schools, hierarchy, curriculum graph, admin dashboard, subject registry | `/` (root) |
| [billing](../../cwa_classroom/billing/README.md) | Packages, subscriptions, discounts, Stripe, entitlements | `/billing/` |
| [audit](../../cwa_classroom/audit/README.md) | Security & compliance event log | `/audit/` |
| [help](../../cwa_classroom/help/README.md) | In-product help articles, contextual help panels | `/help/` |
| [notifications](../../cwa_classroom/notifications/README.md) | Lifecycle email service (welcome, email/password changed) | — |

## Subject apps

| App | What it does | URL prefix |
|---|---|---|
| [maths](../../cwa_classroom/maths/README.md) | Maths curriculum, questions, quizzes, basic facts | `/maths/` |
| [coding](../../cwa_classroom/coding/README.md) | Coding exercises and problems (Piston sandbox) | `/coding/` |
| [music](../../cwa_classroom/music/README.md) | Stub — coming soon | `/music/` |
| [science](../../cwa_classroom/science/README.md) | Stub — coming soon | `/science/` |

## Activity apps

| App | What it does | URL prefix |
|---|---|---|
| [number_puzzles](../../cwa_classroom/number_puzzles/README.md) | Number-puzzle mini-game inside maths basic facts | `/maths/basic-facts/number-puzzles/` |
| [homework](../../cwa_classroom/homework/README.md) | Teacher-assigned homework quizzes | `/homework/` |
| [attendance](../../cwa_classroom/attendance/README.md) | Class-session attendance (mid-refactor — not in INSTALLED_APPS yet) | (via classroom) |

## Engines & utilities

| App | What it does | URL prefix |
|---|---|---|
| [quiz](../../cwa_classroom/quiz/README.md) | Generic quiz-taking engine + JSON API | `/maths/`, `/api/v1/` |
| [progress](../../cwa_classroom/progress/README.md) | Cross-subject progress dashboards & API | `/student-dashboard/`, `/api/v1/` |
| [ai_import](../../cwa_classroom/ai_import/README.md) | PDF → questions via Anthropic Claude | `/ai-import/` |

## Conventions

- **App README** lives at `cwa_classroom/<app>/README.md`. Each one covers: purpose, key models, URL prefix & key routes, integration (settings, urls, context processors, signals, middleware), dependencies on other apps, and external services.
- **Specs** (cross-cutting design docs) live in [`docs/`](..) — keep this `docs/apps/` directory limited to the index above.
- When adding a new app: drop a README beside the code following the same headings, then add a row to this index.
