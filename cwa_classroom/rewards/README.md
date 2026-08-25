# rewards

Cross-subject student points and the global leaderboard. Owns the one number
that answers *"how much work has this student done on the system?"* — regardless
of subject, topic, year, or which app the work happened in.

## Why this app exists

Every activity app already had its own `points` column, and none of them could
be summed into a lifetime total:

| Problem | Where |
|---------|-------|
| **Attempt rows are pruned** to the last 10 per series, so a summed total *shrinks* the more a student practises | `classroom.attempt_retention.prune_to_last_n`, called from `maths.StudentFinalAnswer.prune_old_attempts` and `homework.HomeworkSubmission.prune_old_attempts` |
| **Not all columns are additive** — a coding row stores the student's *best so far*, so summing rows multiplies one success by the attempt count | `coding/views.py` (`points=best_points`) |
| **Scales disagree** — BrainBuzz awards up to 1000 per *question*, everything else caps at 100 per *attempt* | `brainbuzz/scoring.py` vs `maths.calculate_points` |
| **Several activities awarded nothing at all** | worksheets, number puzzles, coding exercises |

So this app owns a single normalised ledger that every activity writes through
`rewards.services.award_points`.

## The unit of account

One **unit of work** — a topic quiz, a homework, a coding problem, a worksheet,
a puzzle level, a live BrainBuzz session — is worth up to `POINTS_PER_UNIT`
(100) points, scored on how well the student did it. A student keeps their
**best** result per unit, mirroring the `Max('points')` semantics every existing
reader in the codebase already uses.

The total therefore grows with **breadth and mastery**, not with grinding:
re-sitting one quiz can only raise that unit's score, while a new topic,
homework or problem adds a new unit. It is also stable — a replay can never
lower a total, and pruning attempt history can never erase one.

## Key models

`PointsAward` — one row per `(student, source, unit_key)` holding the best score
for that unit. `unit_key` names the unit *within* its source and is opaque
outside `services.py`.

`StudentPointsTotal` — one row per student, denormalised from `PointsAward` so a
rank is a single indexed `COUNT(total_points > mine)` rather than an aggregate
over the whole ledger. Also carries `is_ranked` (a teacher who previews a quiz
earns points but never displaces a child from the podium) and
`leaderboard_shown_on` (gates the once-a-day pop-up, stored here rather than in
the session so it holds across devices).

## Award sites

Every one of these calls `award_points_safe` — a failure is logged at ERROR and
never breaks a student's submission, but is never silently swallowed either.

| Source | Unit | Scored on | Written in |
|--------|------|-----------|------------|
| `maths_quiz` | topic + level, or mixed + level | `StudentFinalAnswer.points` | `quiz/views.py` |
| `times_tables` | operation + table + order | `StudentFinalAnswer.points` | `quiz/views.py` |
| `basic_facts` | subtopic + level | `BasicFactsResult.points` | `quiz/views.py` |
| `homework` | one homework | percentage — see below | `homework/views.py` |
| `coding_problem` | one problem | `StudentProblemSubmission.points` (best-of) | `coding/views.py` |
| `coding_exercise` | one exercise | 100 on completion | `coding/views.py` |
| `worksheet` | one assignment | percentage | `worksheets/views.py` |
| `number_puzzle` | one level | best score / questions | `number_puzzles/views.py` |
| `brainbuzz` | one session | score / Σ`points_base` answered | `brainbuzz/views.py` |

**Global questions** (`school IS NULL`) are covered by `maths_quiz`:
`TopicQuizView` serves `Question.objects.global_only()`, so finishing one of
those quizzes credits the ledger exactly like a school quiz does.

**Homework is scored on percentage, not `submission.points`**, because that
column has two writers on two different scales — the submit path sets
`calculate_points(...)` (0–100) while `_recalculate_submission_score` sums
`points_earned` (roughly one per question). Percentage is what they agree on,
and it is the homework leaderboard's own primary sort key.

## Backfill

Run once after deploying, so students arrive with the points they already
earned rather than everyone starting at zero. Idempotent — it goes through
`award_points`, which keeps the better of the stored and computed score, so
re-running repairs a drifted ledger without ever lowering anyone.

```bash
python manage.py rebuild_points_ledger
python manage.py rebuild_points_ledger --student alice --dry-run
```

Attempt history is pruned, so a unit whose every surviving attempt is worse than
a deleted one is rebuilt at the best score still on record. Going forward the
ledger is written at submit time and never loses that.

## Scopes

`services.board_queryset(school=None)` defines a board's population, and
`get_standings(student)` returns every board that student belongs on, in display
order:

| Scope | Population | Shown to |
|-------|-----------|----------|
| `school` | active members of the student's first active school | school students, **first** |
| `global` | every ranked student on the system | everyone |

The school tab leads because a field a student can realistically climb beats one
where the honest answer is "you are 400th". An individual student belongs to no
school, gets the system-wide board alone, and sees no tab strip.

Membership is **joined, not denormalised** onto `StudentPointsTotal`: a student
who changes school would otherwise leave a stale copy behind. The join is cheap
against a table holding one row per student.

The winner's message names the scope it actually won — "top of your whole
school" and "number one across every school on the system" are very different
achievements, and the board must not claim the larger one.

Country and class boards slot in the same way: add the filter to
`board_queryset()` and an entry to `get_standings()`. `CustomUser.country`
already exists; class membership is `classroom.ClassStudent`.

## Where it shows

The student hub (`templates/hub/home.html`, rendered by
`classroom.views.SubjectsHubView`):

- a **"Top Wizards" card** that stays on the page all day
- a **pop-up** on the first hub load of each local day

Both render `templates/hub/_leaderboard.html`, one tab per `Standing`. Because
both copies are on the page at once, every element id is namespaced with the
`prefix` the includer passes (`card` / `popup`) — a shared id would make the
pop-up's tabs drive the card's panels. A test pins that.

The board names the top three; a student already on the podium is not shown a
duplicate rank line.

Names are shown as **first name + last initial** — the board spans every school
and country, so it must not identify a child in full to strangers.

Two boards cost 12 queries per hub load. `get_standings()` reads the student's
own total once and lends it to both rather than repeating the identical query.

## Tests

```bash
pytest rewards/            # ledger, ranking, award sites, backfill, hub
pytest ui_tests/navigation/test_hub_leaderboard.py    # the pop-up and card
```

`rewards/tests/test_award_sites.py` drives the **real** award site in each app
rather than calling `award_points` directly, so a refactor that stops crediting
an activity fails there instead of shipping a board that quietly stops moving.
The `rewards` CI filter therefore watches every app that awards points, not just
`rewards/`.
