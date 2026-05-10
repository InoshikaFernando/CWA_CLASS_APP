# number_puzzles

Number-puzzle mini-game for arithmetic practice. Levels are configurable by operator set, operand range, operand count, and bracket use. Students try to solve each puzzle in the fewest moves; sessions and attempts are tracked so progress can be shown later.

The app is mounted under the `/maths/` namespace, so puzzles appear inside the maths basic-facts area rather than as a standalone subject.

## Key models

- **NumberPuzzleLevel** — difficulty tier (number, name, operators_allowed, min/max operand, num_operands, brackets, unlock_threshold).
- **NumberPuzzle** — pre-generated puzzle (operands, target, display_template, solution, is_active).
- **PuzzleSession** — student attempt at a level (level, student, status: in_progress / completed / abandoned, attempts, time_taken_seconds).
- **PuzzleAttempt** — single solution attempt (session, solution_text, is_correct, time_taken_seconds).

## URL prefix & key routes

Mounted under `/maths/` so the user-facing prefix is `/maths/basic-facts/number-puzzles/`.

- `` — home / level selection
- `play/<level_slug>/` — play a puzzle at a level
- `results/<session_id>/` — session results

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'number_puzzles', ...]
```

In root `urls.py`:

```python
path('maths/', include('number_puzzles.urls')),
```

## Dependencies

- **accounts** — `CustomUser` is the player.

## External services

None.

## See also

[`docs/SPEC_NUMBER_PUZZLES.md`](../../docs/SPEC_NUMBER_PUZZLES.md) for the original feature spec.
