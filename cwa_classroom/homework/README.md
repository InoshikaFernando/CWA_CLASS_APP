# homework

Teacher-assigned homework quizzes. A teacher selects a class, picks topics (or a mixed-topic mode), sets a number of questions, a due date, and an attempt limit. Students see assigned homework on their dashboard, submit attempts, and get scored. Teachers monitor submissions per class with on-time / late status.

Unlike practice quizzes, the question set for a homework is **fixed at create time** so every student answers the same questions in the same order.

## Key models

- **Homework** — assignment (classroom, homework_type, topics, num_questions, due_date, max_attempts).
- **HomeworkQuestion** — fixed question per homework, with display order.
- **HomeworkSubmission** — student attempt (homework, student, attempt_number, score, points, time_taken_seconds, submitted_at, on-time/late flag).

## URL prefix & key routes

Mounted at the project root (namespace `homework`).

- `/homework/monitor/` — teacher view: all submissions per class
- `/homework/class/<id>/create/` — teacher creates homework
- `/homework/<id>/` — teacher detail + submissions
- `/homework/student/` — student's assigned-homework list
- `/homework/<id>/take/` — student takes the quiz
- `/homework/result/<submission_id>/` — student result page

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'homework', ...]

TEMPLATES[0]['OPTIONS']['context_processors'] += [
    'homework.context_processors.new_homework_count',  # nav badge
]
```

In root `urls.py`:

```python
path('', include('homework.urls', namespace='homework')),
```

## Dependencies

- **accounts** — `CustomUser` (teacher and student).
- **classroom** — `ClassRoom`, `Topic`, `Level`.
- **maths** — `Question` is the question source for now (homework links to `maths.Question` rows).

## External services

None.
