"""
audit_comma_answers.py — paste-and-run audit of comma-separated stored answers.

READ-ONLY. Writes nothing, changes nothing. Safe on production.

Answers "can a student score full marks for typing one value of a multi-value
answer?" — the CPP-378 defect. Runs against either code version and says which
one it found, so the same command verifies the bank before and after the fix:

    LIVE      the grading this deployment actually runs accepts a fragment.
              These are real, present-day mismarks. After CPP-378 deploys the
              only ones left are data faults — a redundant Answer row holding
              one value of another row's list — which code cannot fix.
    LEGACY    the deleted comma-as-alternatives rule would accept a fragment.
              Only reported on a pre-CPP-378 deployment; it is what the fix
              closed, and it is 0 afterwards because the rule is gone.

    cd /home/cwa/CWA_CLASS_APP
    PYTHONIOENCODING=utf-8 venv/bin/python cwa_classroom/manage.py shell \
        < scripts/audit_comma_answers.py

Locally:
    cd cwa_classroom && python manage.py shell < ../scripts/audit_comma_answers.py

PYTHONIOENCODING is not optional: question text carries unicode (cm2 as cm²,
angles as 50°) and a droplet with LANG unset dies on the first print without it.

Each flagged answer is also bucketed, to show what the comma means there:

    ALTERNATIVES  the parts are the same number written two ways ("1/2, 0.5").
    PARTS         the parts are different numbers ("32, 2"), so the comma joins
                  ONE answer and a fragment is half of it.
    UNKNOWN       non-numeric parts ("red, blue"). Needs a human decision.

Note ALTERNATIVES is a *candidate* bucket, not a verdict: parts that reduce to
the same number are often both required ("write 30% as a fraction and a
decimal" stores "3/10, 0.3"; a symmetric coordinate stores "(4,4)"). The
production run of this script found 14 such candidates and every one was a
list, not an alternative.
"""
from fractions import Fraction
import re

from maths.models import Question, _split_answer_list
from quiz.views import _correct_answer_texts

# Which code version are we auditing? The legacy comma-as-alternatives rule
# lived in this helper; CPP-378 deleted it along with the whole function.
try:
    from quiz.views import _grade_short_answer
    LEGACY_RULE_PRESENT = True
except ImportError:
    _grade_short_answer = None
    LEGACY_RULE_PRESENT = False

REAL_COMMA = re.compile(r',(?!\d{3}\b)')          # not a digit-grouping comma
NUMERIC = re.compile(r'^-?\d+(?:\s+\d+/\d+|\.\d+|/\d+)?$')


def as_number(text):
    """The part's numeric value, or None if it isn't plainly numeric."""
    s = text.strip().rstrip('%').strip()
    s = re.sub(r'[^\d./\s-]', '', s).strip()      # drop units: "5 cm" -> "5"
    if not NUMERIC.match(s):
        return None
    try:
        if ' ' in s:                               # mixed number "2 1/4"
            whole, frac = s.split()
            sign = -1 if whole.startswith('-') else 1
            return Fraction(whole) + sign * Fraction(frac)
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        return None


def classify(parts):
    """Is the comma separating equivalent FORMS, or components of one answer?"""
    values = [as_number(p) for p in parts]
    if all(v is not None for v in values):
        return 'ALTERNATIVES' if len(set(values)) == 1 else 'PARTS'
    return 'UNKNOWN'


questions = (
    Question.objects
    .filter(answer_format=Question.ANSWER_FORMAT_TEXT)
    .exclude(question_type__in=(Question.MULTIPLE_CHOICE, Question.TRUE_FALSE))
    .select_related('topic', 'level')
    .prefetch_related('answers')
    .order_by('id')
)

live = {'ALTERNATIVES': [], 'PARTS': [], 'UNKNOWN': []}
legacy = {'ALTERNATIVES': [], 'PARTS': [], 'UNKNOWN': []}
scanned = 0

for q in questions:
    texts = _correct_answer_texts(q)
    if not texts:
        continue
    scanned += 1

    for text in texts:
        if not REAL_COMMA.search(text):
            continue
        parts = [p for p in _split_answer_list(text) if p]
        if len(parts) < 2:
            continue

        # A fragment the *deployed* grader accepts is a mismark happening today.
        live_hits = [p for p in parts if q.grade_text_answer(p)]
        # A fragment only the legacy comma rule accepted — what CPP-378 closed.
        legacy_hits = []
        if LEGACY_RULE_PRESENT:
            legacy_hits = [p for p in parts
                           if p not in live_hits
                           and _grade_short_answer(q, p, texts)]

        if live_hits:
            live[classify(parts)].append((q, text, live_hits))
        if legacy_hits:
            legacy[classify(parts)].append((q, text, legacy_hits))
        break

W = 78


def report(title, buckets, note):
    total = sum(len(rows) for rows in buckets.values())
    print(f'\n{"#" * W}\n# {title}  —  {total} question(s)\n# {note}\n{"#" * W}')
    for kind, header in (
        ('PARTS',        'Comma joins ONE answer - a fragment is wrongly accepted'),
        ('UNKNOWN',      'Non-numeric - needs a human eye'),
        ('ALTERNATIVES', 'Parts reduce to the same number - usually still a list'),
    ):
        rows = buckets[kind]
        print(f'\n{"=" * W}\n{kind}  ({len(rows)})\n  {header}\n{"=" * W}')
        for q, text, hits in rows:
            year = q.level.level_number if q.level_id else '?'
            topic = q.topic.name if q.topic_id else '(no topic)'
            print(f'  Q{q.id} [year {year} / {topic}] {q.question_text[:60]}')
            print(f'      stored  : {text!r}')
            print(f'      accepts : {", ".join(repr(h) for h in hits)}  (alone)')
    return total


live_total = report(
    'LIVE — accepted by the grading this deployment runs',
    live,
    'Real mismarks, happening now. Each needs a content fix.')

legacy_total = 0
if LEGACY_RULE_PRESENT:
    legacy_total = report(
        'LEGACY — accepted only by the comma-as-alternatives rule',
        legacy,
        'What CPP-378 removes. Zero once this deployment carries the fix.')

print(f'\n{"=" * W}')
print(f'Code version                   : '
      f'{"PRE-CPP-378 (comma rule present)" if LEGACY_RULE_PRESENT else "CPP-378 (comma rule deleted)"}')
print(f'Typed-answer questions scanned : {scanned}')
print(f'  leaking now (LIVE)           : {live_total}')
if LEGACY_RULE_PRESENT:
    print(f'  leaking via the comma rule   : {legacy_total}')
print('=' * W)

if not live_total:
    print('\nVERDICT: no question accepts a fragment of a multi-value answer.')
else:
    print(f'\nVERDICT: {live_total} question(s) still accept a fragment. Code cannot')
    print('fix these — each is a redundant Answer row holding one value of')
    print("another row's list. Delete the row, or split the list into one row")
    print('per genuinely accepted alternative. Reported as FRAGMENT-ROW by')
    print('`manage.py verify_question_answers`.')
