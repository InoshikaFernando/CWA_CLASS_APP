# CWA Classroom — Documentation

Index of feature docs and implementation specs for the CWA Classroom app.

## Feature docs

Living documentation of how a feature works, kept in sync with the code.

- [Student Registration](STUDENT_REGISTRATION.md) — the single self-service
  registration path plus teacher-created onboarding, and why there is no
  separate "school student" registration (CPP-300 source of truth).

## Specs

Per-ticket specifications describing a change at the time it was built.

- [CPP-300 — Enforce Credit Card Details During Registration](specs/CPP-300_enforce_stripe_payment.md)
- [Worksheet Builder — Select Questions from Global Bank](specs/worksheet_builder.md)

---

### Conventions

- **Feature docs** (top of `docs/`) describe current behaviour and should be
  updated when the feature changes.
- **Specs** (`docs/specs/`, and `SPEC_*.md`) are point-in-time records tied to a
  Jira ticket. They are not updated after the ticket ships — write a new spec or
  update the feature doc instead.
- When adding a new doc, link it from this README.
