"""
audit_comma_answers.py — paste-and-run audit of comma-separated stored answers.

READ-ONLY. Writes nothing, changes nothing. Safe on production.

Answers the one question the CPP-378 grading fix left open: can the legacy
comma-as-alternatives rule in quiz.views._grade_short_answer be deleted? It
can, iff no question actually relies on it to accept a correct answer.

    cd /home/cwa/CWA_CLASS_APP
    PYTHONIOENCODING=utf-8 venv/bin/python cwa_classroom/manage.py shell \
        < scripts/audit_comma_answers.py

PYTHONIOENCODING is not optional: question text carries unicode (cm2 as cm²,
angles as 50°) and a droplet with LANG unset dies on the first print without it.

Locally:
    cd cwa_classroom && python manage.py shell < ../scripts/audit_comma_answers.py

Each stored answer containing a real (non-digit-grouping) comma is bucketed:

    ALTERNATIVES  the parts are the same number written two ways ("1/2, 0.5").
                  The comma means OR — the legacy rule is load-bearing.
    PARTS         the parts are different numbers ("32, 2"). The comma joins
                  ONE answer, so accepting a part alone marks half an answer
                  correct — the hole this audit is looking for.
    UNKNOWN       non-numeric parts ("red, blue"). Needs a human decision.

Bucketing is empirical, not guesswork: a part is only reported when the comma
rule accepts it AND the shared rules (Question.grade_text_answer) reject it —
i.e. the legacy rule alone is carrying it.
"""
from fractions import Fraction
import re

from maths.models import Question, _split_answer_list
from quiz.views import _correct_answer_texts, _grade_short_answer

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
        # "1/2, 0.5" -> the same number twice = alternative spellings.
        # "32, 2"    -> different numbers    = two components of one answer.
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

buckets = {'ALTERNATIVES': [], 'PARTS': [], 'UNKNOWN': []}
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

        # Empirical, not guesswork: a part that the comma rule accepts and the
        # shared rules reject is a part the legacy rule alone is carrying.
        carried = [p for p in parts
                   if _grade_short_answer(q, p, texts) and not q.grade_text_answer(p)]
        if not carried:
            continue

        buckets[classify(parts)].append((q, text, carried))
        break

W = 78
for kind, header in (
    ('ALTERNATIVES', 'Comma means OR - the legacy rule is doing real work here'),
    ('PARTS',        'Comma joins ONE answer - a fragment is wrongly accepted'),
    ('UNKNOWN',      'Non-numeric - needs a human eye'),
):
    rows = buckets[kind]
    print(f'\n{"=" * W}\n{kind}  ({len(rows)})\n  {header}\n{"=" * W}')
    for q, text, carried in rows:
        year = q.level.level_number if q.level_id else '?'
        topic = q.topic.name if q.topic_id else '(no topic)'
        print(f'  Q{q.id} [year {year} / {topic}] {q.question_text[:60]}')
        print(f'      stored  : {text!r}')
        print(f'      accepts : {", ".join(repr(c) for c in carried)}  (alone)')

print(f'\n{"=" * W}')
print(f'Typed-answer questions scanned : {scanned}')
print(f'  relying on comma-as-OR       : {len(buckets["ALTERNATIVES"])}')
print(f'  leaking a partial answer     : {len(buckets["PARTS"])}')
print(f'  undecidable by machine       : {len(buckets["UNKNOWN"])}')
print('=' * W)

if not buckets['ALTERNATIVES'] and not buckets['UNKNOWN']:
    print('\nVERDICT: nothing depends on comma-as-OR. The legacy rule in')
    print('quiz.views._grade_short_answer can be deleted, which also closes')
    print(f'the partial-answer hole on the {len(buckets["PARTS"])} question(s) above.')
else:
    print(f'\nVERDICT: {len(buckets["ALTERNATIVES"]) + len(buckets["UNKNOWN"])} question(s) still need the rule (or a human')
    print('decision). Re-author those as one Answer row per alternative, then')
    print('the rule can go.')
