# AI Usage Limits — Validation & Quota Dashboard

**Epic:** CPP-251
**Status:** Sprint 1 (Foundation) in progress

## Problem Statement

Schools subscribe to tiered AI modules (Question Import, Answer Grading) with monthly page quotas. Several enforcement gaps exist:

1. **Bypass bug** — `if remaining > 0 and page_count > remaining` allows uploads when remaining is exactly 0
2. **Hardcoded limits** — page quotas live in a Python dict, not in the database
3. **No centralised enforcement** — quota logic is scattered in `ai_import/views.py` instead of `billing/entitlements.py`
4. **No pro-rata** for mid-period module activations (Sprint 2)
5. **No dashboard visibility** of remaining quota (Sprint 3)
6. **No AI grading quota** surfaced to users (Sprint 3)

## Sprint 1 — Foundation

### Changes

1. **Bug fix**: Change `if remaining > 0 and page_count > remaining` to `if page_count > remaining` in `ai_import/views.py`
2. **Schema**: Add `pages_per_month` (nullable PositiveIntegerField) to `ModuleProduct`
3. **Data migration**: Seed existing AI import modules with their quota values (300/600/1000)
4. **Centralise**: New `check_ai_import_quota(school)` function in `billing/entitlements.py` that reads from `ModuleProduct.pages_per_month`
5. **Refactor**: `_get_remaining_pages()` in `ai_import/views.py` delegates to the centralised function
6. **Error UX**: Distinct messages for "quota exhausted" vs "PDF too large for remaining"

### Data Model

```
ModuleProduct (existing)
  + pages_per_month: PositiveIntegerField(null=True, blank=True)
    - NULL = not applicable (non-AI modules)
    - 0 = unlimited
    - >0 = monthly page limit
```

### API

```python
# billing/entitlements.py
def check_ai_import_quota(school) -> tuple[int, int, int]:
    """Returns (remaining, limit, used). (0, 0, 0) if no AI module active."""
```

## Sprint 2 — Pro-Rata (future)

- Calculate proportional limits for mid-period module activations
- Auto-reset on next billing period
- Track `activated_at` on `ModuleSubscription` (already exists)

## Sprint 3 — Dashboard & UX (future)

- Quota widget on HoI/HoD/Teacher dashboards with progress bars
- Graceful AI grading fallback to `pending_teacher` when quota exceeded

## Sprint 4 — Testing (future)

- Integration tests for upload blocking, grading fallback, pro-rata via Stripe webhook
- Manual QA checklist
