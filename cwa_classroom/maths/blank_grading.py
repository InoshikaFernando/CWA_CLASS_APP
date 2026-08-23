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

# "26 and 29" is one answer listing two values, exactly as "26, 29" is. Tried
# last, and only when a row must yield exactly n parts, so an ordinary worded
# answer ("bread and butter") is never split by accident.
_AND_SPLIT_RE = re.compile(r'\s+and\s+', re.IGNORECASE)

# A per-gap value is atomic: one value, no list inside it. A row carrying any of
# these separators is a whole answer rather than one gap's worth of it — see
# _looks_positional.
_LIST_MARKERS = (';', ',')

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
        if _is_clean_split(parts, n, sep):
            return parts
    parts = [p.strip() for p in _AND_SPLIT_RE.split(text)]
    if _is_clean_split(parts, n, ' and '):
        return parts
    return None


def _is_clean_split(parts, n, sep):
    """Is this a real split into *n* values, or a coincidence?

    Right count, no empty part, and — the part that matters — no part still
    carrying a separator we tried EARLIER. "+4; 26, 30, 34" is a rule followed
    by three values; splitting it on "," happens to yield three parts, but the
    first is "+4; 26", which still holds the semicolon that should have divided
    rule from values. Taking that split would teach the first gap to expect
    "+4; 26" and mark the student who types "26" wrong.
    """
    if len(parts) != n or not all(parts):
        return False
    earlier = _ROW_SPLITS[:_ROW_SPLITS.index(sep)] if sep in _ROW_SPLITS else _ROW_SPLITS
    return not any(marker in part for part in parts for marker in earlier)


def _alternatives(text):
    """One blank's accepted spellings — "live|survive" → ``['live', 'survive']``."""
    parts = [p.strip() for p in str(text).split(_ALT_SPLIT)]
    return [p for p in parts if p]


def _looks_positional(texts):
    """Are these rows plausibly one value per gap, rather than N spellings of one answer?

    The row-per-gap rule is the one place this module can be confidently wrong:
    given three rows and three gaps it will fill gap *i* from row *i*, which is
    right when the rows really are per-gap values and badly wrong when they are
    alternative spellings of the whole answer. A real conversion run over the
    production bank turned up plenty of the latter — "+15" / "add 15" / "+ 15"
    for a three-gap question, where the gap values are not stored at all — and a
    gap filled from the wrong value marks a correct student wrong silently.

    Two signals say "these are not per-gap values", and either one is enough:

    * a row carries a list separator, so it is a whole answer, not one value
      ("+4; 26, 30, 34");
    * two rows fold to the same string, so they are spellings of one thing
      ("+15" and "+ 15").

    This only screens the row-per-gap rule. It cannot catch every case — three
    genuinely distinct spellings ("-3", "− 3", "subtract 3") pass it — which is
    why ``convert_fill_blanks`` declines the rule outright on legacy content
    whose rows were written for a single answer box.
    """
    if any(marker in t for t in texts for marker in _LIST_MARKERS):
        return False
    if any(_AND_SPLIT_RE.search(t) for t in texts):
        return False
    folded = [fold_answer(t) for t in texts]
    if len(set(folded)) == 1:
        # Every row the same value ("3", "3" for "___ sides and ___ angles").
        # Per-gap mapping hands each gap that value, which is what both readings
        # of the rows mean, so there is nothing to get wrong.
        return True
    # A PARTIAL duplicate is the alternatives signal: "+15", "add 15", "+ 15"
    # is one rule spelled three ways, not three per-gap values.
    return len(set(folded)) == len(folded)


_UNIT_TOKEN_RE = re.compile(r'^\s*([A-Za-z°%]+)')


def unit_repeat_blanks(question_text, blank_spec):
    """Indices of blanks whose every answer repeats the unit printed after them.

    "Convert to millilitres: 5.3 L = ___ mL" stored with the answer "5300 mL"
    reads, once the gap is laid into the sentence, as "= [5300 mL] mL" — and the
    obvious thing to type, "5300", is marked wrong. The stored answer was fine
    when it sat in a box below the question; it is a defect once the gap is
    inline.

    Only flagged when EVERY accepted answer for that gap repeats the unit, so a
    question that also stores the bare value ("27.445" alongside "27.445
    pounds") is left alone — a student can still answer it without repeating
    the unit.

    Returns ``[]`` for anything unrenderable, so callers can guard with one
    check. Never raises.
    """
    answers = blank_answers(blank_spec)
    if not answers:
        return []
    segments = split_on_blanks(question_text)
    if len(segments) != len(answers) + 1:
        return []

    out = []
    for index, options in enumerate(answers):
        match = _UNIT_TOKEN_RE.match(segments[index + 1] or '')
        if not match:
            continue
        unit = match.group(1)
        if all(_repeats_unit(option, unit) for option in options):
            out.append(index)
    return out


def _repeats_unit(answer, unit):
    """Does *answer* end with *unit* as a separate trailing token?"""
    answer = answer.strip()
    if len(answer) <= len(unit):
        return False
    if answer[-len(unit):].lower() != unit.lower():
        return False
    # A separate token, not the tail of a longer word: "5300 mL" repeats "mL",
    # "130" does not repeat "cm", and "warm" does not repeat "m".
    return not answer[-len(unit) - 1].isalpha()


def derive_blank_spec(question_text, correct_texts, *, positional_rows=True):
    """Build a ``blank_spec`` from a question's text + its correct answer rows.

    Returns ``(spec, reason)``: exactly one is set. ``reason`` explains, in
    words a person can act on, why the question could not be converted — it is
    printed by ``convert_fill_blanks`` and surfaced by the AI importer, the
    spreadsheet upload and the teacher form rather than being swallowed, because
    a wrongly-mapped blank marks a correct student wrong and nobody would know.

    ``correct_texts`` is every ``is_correct`` answer's text, in ``order`` — the
    caller supplies them so this stays free of Django.

    The mapping rules, in order:

    * **one blank** — every row is an accepted spelling of it. Always safe:
      alternatives are what several rows already mean everywhere else.
    * **N blanks, one row** — the row is split on ";", then ",", then " and ",
      and must yield exactly N parts ("15; live").
    * **N blanks, every row splitting into N** — each row is a whole answer
      listing all N values, so they are alternatives: gap *i* accepts the *i*-th
      value of every row. Strictly safer than the rule below, and tried first.
    * **N blanks, N rows** — row *i* fills gap *i*, but only when
      ``positional_rows`` is set AND the rows look like per-gap values rather
      than spellings of one answer (see :func:`_looks_positional`).
    * **anything else** — refused, with the counts named.

    In every case "a|b" within a value lists alternatives for that one blank.

    ``positional_rows`` defaults to True, which is right where the rows were
    authored against the documented convention (one value per gap, in order) —
    the AI importer, the spreadsheet upload, the teacher form. The bulk
    conversion of legacy content passes False, because those rows were written
    to fill a single answer box and being three of them is no evidence at all
    that there is one per gap.
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
    elif len(texts) == 1:
        parts = _split_row(texts[0], n)
        if parts is None:
            return None, (
                f'{n} blanks but one answer row ({texts[0]!r}) that does not '
                f'split into {n} values on ";", "," or " and "'
            )
        values = [_alternatives(p) for p in parts]
    elif all(_split_row(t, n) is not None for t in texts):
        # Every row lists all N values, so the rows are alternative whole
        # answers: gap i accepts the i-th value of each. Preferred over the
        # row-per-gap rule below, which would instead hand one whole answer to
        # each gap.
        values = [[] for _ in range(n)]
        for text in texts:
            for index, part in enumerate(_split_row(text, n)):
                for option in _alternatives(part):
                    if option not in values[index]:
                        values[index].append(option)
    elif len(texts) == n:
        if not positional_rows:
            return None, (
                f'{n} blanks and {n} answer rows, but rows written for a single '
                f'answer box are no evidence there is one per blank — pass '
                f'--map-rows-to-gaps if they really are in gap order, or store '
                f'one row listing all {n} values separated by ";"'
            )
        if not _looks_positional(texts):
            return None, (
                f'{n} blanks and {n} answer rows, but they look like {n} '
                f'spellings of one answer rather than one value per blank '
                f'({texts!r}) — store one row listing all {n} values separated '
                f'by ";"'
            )
        values = [_alternatives(t) for t in texts]
    else:
        return None, (
            f'{n} blanks but {len(texts)} correct answer rows — needs either '
            f'{n} rows (one per blank) or one row listing all {n} values'
        )

    if not all(values):
        return None, 'a blank ended up with no accepted answer'

    spec = {'blanks': [{'answers': v} for v in values]}

    # A gap whose every answer repeats the unit already printed after it reads
    # as "= [5300 mL] mL" and rejects the obvious "5300". The stored answer was
    # serviceable in a box below the question and is a defect inline, so the
    # question keeps its single box and the content gets named.
    repeats = unit_repeat_blanks(question_text, spec)
    if repeats:
        shown = ', '.join(str(i + 1) for i in repeats)
        return None, (
            f'blank {shown} would repeat the unit already printed after it '
            f'(e.g. "= ___ mL" answered "5300 mL"), so "5300" would be marked '
            f'wrong — drop the unit from the stored answer, or store the bare '
            f'value as well'
        )

    return spec, ''
