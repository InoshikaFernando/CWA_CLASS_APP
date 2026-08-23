"""Fill-in-the-blank questions — find the blanks, grade them, build the spec.

A fill-in-the-blank question is an ordinary sentence with the answers cut out of
it::

    "Out of 100 000 births, 99 231 females are expected to survive to the age
     of ___. From that age, the survivors are expected to ___ for another 67.0
     years."

The blanks live in ``Question.question_text`` as runs of underscores — that IS
the marker, and the only one. Everything else about the question (which words
are acceptable in each gap) lives in ``Question.blank_spec``::

    {"blanks": [{"answers": ["15"]},
                {"answers": ["live", "survive"]}]}

``blanks`` is positional: entry *i* holds every accepted spelling of the *i*-th
underscore run, left to right. The number of entries must equal the number of
runs in the text — a spec that has drifted out of step with its sentence would
silently mis-grade, so ``validate_blank_spec`` refuses it.

Graded all-or-nothing (:func:`grade_fill_blank`), matching ``grade_table``: a
sentence is right only when every gap in it is right. Each gap is matched with
the same :func:`~maths.algebra_grading.fold_answer` rules a short answer gets,
so "Fifty-Three" and "fifty three" are the same word in a blank exactly as they
are in a whole answer.

Pure and framework-agnostic (no Django import) so the model's ``clean()``, the
AI importer and the ``convert_fill_blanks`` command all share one definition of
what a blank is.
"""
import json
import re

from maths.algebra_grading import fold_answer

# A run of two or more underscores is a blank. Two rather than one because a
# lone "_" turns up as a subscript in ordinary maths text ("a_1"), where a run
# of them never does.
BLANK_RE = re.compile(r'_{2,}')

# Guard rails. A sentence with more gaps than words is authoring gone wrong, not
# a question, and the take page would render an unusable wall of inputs.
MAX_BLANKS = 12

# Separators tried, in order, when splitting ONE stored answer row across
# several blanks (see derive_blank_spec). Semicolon first: a comma is too often
# part of a single value ("1,000") to be the first guess.
_ROW_SPLITS = (';', ',')

# Within one blank, "|" separates equally acceptable spellings — the same
# convention algebra answers already use.
_ALT_SPLIT = '|'


def count_blanks(question_text):
    """How many blanks ``question_text`` contains."""
    if not question_text:
        return 0
    return len(BLANK_RE.findall(str(question_text)))


def split_on_blanks(question_text):
    """The literal text around the blanks: ``count_blanks() + 1`` segments.

    ``split_on_blanks("age of ___. Then ___ years")`` →
    ``['age of ', '. Then ', ' years']``, so a template can render
    segment, input, segment, input, segment and rebuild the sentence exactly.
    """
    if not question_text:
        return ['']
    return BLANK_RE.split(str(question_text))


def blank_answers(blank_spec):
    """The accepted answers per blank as a list of lists, or ``[]`` if unusable.

    Never raises — render and grading paths call it on whatever is stored.
    """
    if not isinstance(blank_spec, dict):
        return []
    blanks = blank_spec.get('blanks')
    if not isinstance(blanks, list):
        return []
    out = []
    for entry in blanks:
        if not isinstance(entry, dict):
            return []
        answers = entry.get('answers')
        if not isinstance(answers, list):
            return []
        texts = [str(a).strip() for a in answers if str(a).strip()]
        if not texts:
            return []
        out.append(texts)
    return out


def validate_blank_spec(blank_spec, question_text=None):
    """Validate a ``blank_spec``; raise ``ValueError`` if bad.

    Pure and framework-agnostic (no Django import) so it is reused by the
    model's ``clean()`` AND by any importer before persisting, so a malformed
    spec can't slip in through either path. Mirrors ``validate_table_spec``.

    When ``question_text`` is given the count is cross-checked against the
    underscore runs in it — the check that actually matters, because a spec with
    the right shape but the wrong number of entries mis-grades every attempt.
    """
    if not isinstance(blank_spec, dict):
        raise ValueError('blank_spec must be a JSON object.')

    blanks = blank_spec.get('blanks')
    if not isinstance(blanks, list) or not blanks:
        raise ValueError('blank_spec.blanks must be a non-empty list.')
    if len(blanks) > MAX_BLANKS:
        raise ValueError(f'blank_spec.blanks must not exceed {MAX_BLANKS} blanks.')

    for i, entry in enumerate(blanks):
        if not isinstance(entry, dict):
            raise ValueError(f'blank_spec.blanks[{i}] must be a JSON object.')
        answers = entry.get('answers')
        if not isinstance(answers, list) or not answers:
            raise ValueError(
                f'blank_spec.blanks[{i}].answers must be a non-empty list of '
                f'accepted answers.'
            )
        for a in answers:
            if not isinstance(a, str) or not a.strip():
                raise ValueError(
                    f'blank_spec.blanks[{i}].answers value must be a non-empty '
                    f'string; got {a!r}.'
                )

    if question_text is not None:
        found = count_blanks(question_text)
        if found != len(blanks):
            raise ValueError(
                f'blank_spec has {len(blanks)} blank(s) but the question text '
                f'has {found}. Mark each blank in the text with "___" — the '
                f'spec is positional, so a mismatch mis-grades every answer.'
            )


def grade_fill_blank(blank_spec, payload):
    """Grade a ``fill_blank`` answer. Returns ``True``/``False``, never raises.

    All-or-nothing: correct when EVERY blank matches one of its accepted
    answers, folded by :func:`~maths.algebra_grading.fold_answer` so a blank is
    as forgiving about case, spacing and hyphens as a whole short answer is.

    ``payload`` is the JSON the client serialises, ``{"blanks": ["15", "live"]}``
    — positional, one entry per blank. A malformed spec or payload, a missing
    entry, or a blank left empty simply grades wrong.
    """
    accepted = blank_answers(blank_spec)
    # A spec with no blanks is unanswerable — never silently "correct".
    if not accepted:
        return False

    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    given = data.get('blanks')
    if not isinstance(given, list) or len(given) != len(accepted):
        return False

    for typed, options in zip(given, accepted):
        if typed is None:
            return False
        typed = fold_answer(str(typed).strip())
        if not typed:
            return False
        if not any(typed == fold_answer(o) for o in options):
            return False
    return True


def describe_blank_answer(payload, blank_spec=None):
    """A student's ``fill_blank`` payload as readable text for review surfaces.

    ``{"blanks": ["15", "live"]}`` → ``"15, live"``. A blank left empty shows as
    "—" so a partly-filled sentence reads as partly filled rather than as a
    shorter answer. Returns the raw payload unchanged when it isn't a blanks
    payload at all, so a review page that calls this on every typed answer still
    shows something truthful rather than nothing.
    """
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        return payload if isinstance(payload, str) else ''
    if not isinstance(data, dict) or not isinstance(data.get('blanks'), list):
        return payload if isinstance(payload, str) else ''
    return ', '.join(
        (str(v).strip() or '—') if v is not None else '—'
        for v in data['blanks']
    )


def describe_blank_spec(blank_spec):
    """The correct answers as readable text, e.g. ``"15, live or survive"``.

    Alternatives within one blank are joined with " or ", mirroring
    ``Question.correct_answer_display``; the blanks themselves with ", ".
    """
    return ', '.join(' or '.join(o) for o in blank_answers(blank_spec))


# ---------------------------------------------------------------------------
# Building a spec from a question that already exists
# ---------------------------------------------------------------------------
def _split_row(text, n):
    """Split one stored answer row into ``n`` values, or None if it won't.

    Tries each separator in turn and takes the first that yields exactly ``n``
    non-empty parts. Returning None rather than guessing is the point: a row
    that can't be split unambiguously is reported for a human to fix, never
    silently mapped onto the wrong blanks.
    """
    for sep in _ROW_SPLITS:
        if sep not in text:
            continue
        parts = [p.strip() for p in text.split(sep)]
        if len(parts) == n and all(parts):
            return parts
    return None


def _alternatives(text):
    """One blank's accepted spellings — "live|survive" → ``['live', 'survive']``."""
    parts = [p.strip() for p in str(text).split(_ALT_SPLIT)]
    return [p for p in parts if p]


def derive_blank_spec(question_text, correct_texts):
    """Build a ``blank_spec`` from a question's text + its correct answer rows.

    Returns ``(spec, reason)``: exactly one is set. ``reason`` explains, in
    words a person can act on, why the question could not be converted — it is
    printed by ``convert_fill_blanks`` and surfaced by the AI importer rather
    than being swallowed, because a wrongly-mapped blank marks a correct student
    wrong and nobody would know.

    ``correct_texts`` is every ``is_correct`` answer's text, in ``order`` — the
    caller supplies them so this stays free of Django.

    The mapping rules, in order:

    * **one blank** — every row is an accepted spelling of it. Always safe:
      alternatives are what several rows already mean everywhere else.
    * **N blanks, N rows** — row *i* fills blank *i*. This is how a multi-blank
      question is authored by hand.
    * **N blanks, 1 row** — the row is split on ";" then "," and must yield
      exactly N parts ("15; live"). This is how the AI extractor writes them.
    * **anything else** — refused, with the counts named.

    In every case "a|b" within a value lists alternatives for that one blank.
    """
    n = count_blanks(question_text)
    if n == 0:
        return None, 'no blanks in the question text (mark them with "___")'
    if n > MAX_BLANKS:
        return None, f'{n} blanks — more than the {MAX_BLANKS} a question may have'

    texts = [t.strip() for t in correct_texts if t and t.strip()]
    if not texts:
        return None, 'no correct answer stored to fill the blank(s) with'

    if n == 1:
        values = [sum((_alternatives(t) for t in texts), [])]
    elif len(texts) == n:
        values = [_alternatives(t) for t in texts]
    elif len(texts) == 1:
        parts = _split_row(texts[0], n)
        if parts is None:
            return None, (
                f'{n} blanks but one answer row ({texts[0]!r}) that does not '
                f'split into {n} values on ";" or ","'
            )
        values = [_alternatives(p) for p in parts]
    else:
        return None, (
            f'{n} blanks but {len(texts)} correct answer rows — needs either '
            f'{n} rows (one per blank) or one row listing all {n} values'
        )

    if not all(values):
        return None, 'a blank ended up with no accepted answer'

    return {'blanks': [{'answers': v} for v in values]}, ''
