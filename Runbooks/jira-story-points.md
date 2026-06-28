# CWA Classroom — Jira Story-Point Estimation Runbook

**Applies to:** Every Jira work item in project **CPP** (worked by an engineer or
an AI agent).
**Audience:** Engineer / Agent — a standing estimation convention, plus the
bulk-fill procedure for unestimated issues.

---

## Convention (going forward)

Every issue carries story points so the burndown (`/sprints/burndown/`, fed by
`sync_sprint_burndown`) can actually trend **down** as work completes. A burndown
only slopes when *pointed* issues move to Done — unpointed work is invisible to it.

**Standard point-per-type scheme:**

| Issue type | Story points |
|------------|--------------|
| **Story**  | **3** |
| **Task**   | **2** |
| **Bug**    | **3** if priority is High/Highest (big bug), else **2** (small bug) |
| **Subtask**| *skip — leave empty* |
| Epic       | *never points* (roll-up only; excluded from the burndown JQL) |

Bugs are split big/small by **Priority** because Jira has no inherent
"big/small" field: High/Highest ⇒ 3, everything else (Medium/Low/Lowest/none)
⇒ 2.

- **Subtasks stay unpointed on purpose** — pointing them double-counts their
  parent Story's estimate and inflates scope.
- These are **default baselines**, not a ceiling. Re-estimate a genuinely large
  or trivial issue to a truer value when you know it — the scheme just guarantees
  nothing sits at 0 by neglect.
- **Point work as you do it, and keep the points when you close it.** A Done
  issue with 0 points subtracts nothing from the burndown, so closing it does
  nothing visible. (Pairs with [`jira-task-dates.md`](jira-task-dates.md): dates +
  points together are what make the chart meaningful.)

The story-points field is `customfield_10016` (override via
`JIRA_STORY_POINTS_FIELD`). CPP is a **team-managed** project, where this is the
"Story point estimate" field.

---

## Bulk-fill procedure (unestimated existing issues)

Run on prod where Jira creds live (`/etc/cwa/cwa.env`). This **mutates real Jira
data**, so it dry-runs by default and only writes with `APPLY=1`. It's
idempotent — the JQL matches only issues with *empty* points, so re-running never
overwrites existing estimates.

> Run Django as the `cwa` user with the venv python, never bare `python` as root
> (root-owned `.pyc` files break the next `cwa` deploy).

**1. Create the script** (owned by `cwa`):

```bash
sudo -u cwa tee /tmp/estimate_cpp.py >/dev/null <<'PYEOF'
import os, requests
from collections import Counter
from django.conf import settings
from cwa_classroom.jira_client import base_config
from sprints import services

APPLY = os.environ.get('APPLY') == '1'
STORY_TASK = {'Story': 3, 'Task': 2}        # fixed per type
BIG_BUG_PRIORITIES = {'Highest', 'High'}     # -> Bug=3, else Bug=2
# Subtask & any other type => skipped (left empty)

def points_for(itype, priority):
    if itype in STORY_TASK:
        return STORY_TASK[itype]
    if itype == 'Bug':
        return 3 if priority in BIG_BUG_PRIORITIES else 2
    return None

cfg = base_config()
if not cfg:
    print('ABORT: Jira not configured'); raise SystemExit
base_url, auth = cfg
field = getattr(settings, 'JIRA_STORY_POINTS_FIELD', '') or 'customfield_10016'
print('Mode:', 'APPLY' if APPLY else 'DRY-RUN', '| points field:', field)

jql = 'project = "CPP" AND issuetype != Epic AND cf[10016] is EMPTY'
issues, tok = [], None
while True:
    params = {'jql': jql, 'fields': 'issuetype,priority', 'maxResults': 100}
    if tok: params['nextPageToken'] = tok
    r = requests.get(base_url + '/rest/api/3/search/jql', params=params, auth=auth, timeout=30)
    r.raise_for_status()
    d = r.json()
    for iss in d.get('issues') or []:
        f = iss.get('fields') or {}
        it = (f.get('issuetype') or {}).get('name')
        pr = (f.get('priority') or {}).get('name')
        issues.append((iss['key'], it, pr))
    tok = d.get('nextPageToken')
    if not tok or d.get('isLast'): break

print('Unestimated found:', len(issues), '->', dict(Counter(t for _, t, _ in issues)))
plan = [(k, it, pr, points_for(it, pr)) for k, it, pr in issues]
to_write = [x for x in plan if x[3] is not None]
print('Will set points on:', len(to_write), '| skipping (subtask/other):', len(plan) - len(to_write))
print('Points distribution:', dict(Counter(p for *_, p in to_write)))
bug_split = Counter((3 if pr in BIG_BUG_PRIORITIES else 2) for k, it, pr, p in plan if it == 'Bug')
print('Bug split (3=big/High+, 2=small):', dict(bug_split))

if not APPLY:
    print('DRY-RUN: nothing written. Re-run with APPLY=1 to apply.')
    raise SystemExit

ok = fail = 0
for k, it, pr, p in to_write:
    resp = requests.put(base_url + '/rest/api/3/issue/' + k,
                        json={'fields': {field: p}}, auth=auth, timeout=30)
    if resp.status_code == 204:
        ok += 1
    else:
        fail += 1
        print('FAIL', k, resp.status_code, resp.text[:200])
print('Updated:', ok, '| Failed:', fail)

days = services.backfill_project_history()
print('Backfilled snapshot days:', days)
PYEOF
```

**2. Dry-run** (no changes — review the counts):

```bash
cd /home/cwa/CWA_CLASS_APP
sudo -u cwa venv/bin/python cwa_classroom/manage.py shell < /tmp/estimate_cpp.py
```

**3. Apply** (writes points, then rebuilds the burndown history):

```bash
cd /home/cwa/CWA_CLASS_APP
sudo -u cwa env APPLY=1 venv/bin/python cwa_classroom/manage.py shell < /tmp/estimate_cpp.py
```

### Notes / troubleshooting

- **`FAIL … 400 … Field cannot be set`** — the Story-points field isn't on that
  issue type's edit screen. Add the field to the screen (Project settings →
  Issue types) or set the correct `JIRA_STORY_POINTS_FIELD`, then re-run.
- The pointing covers **open *and* Done** issues by design: pointing the Done
  ones lets `backfill_project_history()` reconstruct a real *historical*
  downward slope (each issue burns off on its resolution date).
- No silent failure: every non-204 write is printed with its status + body.

---

## See also

- [`jira-task-dates.md`](jira-task-dates.md) — Start/End date convention; dates +
  points together are what make the burndown honest.
- `cwa_classroom/MANAGEMENT_COMMANDS.md` → `sync_sprint_burndown` (and its
  `--backfill`) — the daily sync that consumes the points.
