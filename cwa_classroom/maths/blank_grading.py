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

A sentence is *correct* only when every gap in it is right
(:func:`grade_fill_blank`), but it is not worth *nothing* short of that:
:func:`grade_fill_blank_parts` grades the gaps one at a time so nine right out
of ten earn nine tenths of the marks and the tenth gets named. Each gap is
matched with the same :func:`~maths.algebra_grading.fold_answer` rules a short
answer gets, so "Fifty-Three" and "fifty three" are the same word in a blank
exactly as they are in a whole answer.

Pure and framework-agnostic (no Django import) so the model's ``clean()``, the
AI importer and the ``convert_fill_blanks`` command all share one definition of
what a blank is.
"""
import json
import re

from maths.algebra_grading import fold_answer, match_value

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

# A single number written with thousands separators — "1,000", "1,000,000",
# "12,500.75". Splitting one of these on the comma yields parts that look like
# values ("1", "000") and are fragments of one, so a two-gap question answered
# "1,000" would teach gap 1 to expect "1". Deliberately strict: it requires no
# space after the comma, so "122, 121" (two values) is still split.
_THOUSANDS_NUMBER_RE = re.compile(r'^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$')

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


def grade_fill_blank(blank_spec, payload, answer_format='text'):
    """Grade a ``fill_blank`` answer. Returns ``True``/``False``, never raises.

    Correct when EVERY blank matches one of its accepted answers, folded by
    :func:`~maths.algebra_grading.fold_answer` so a blank is as forgiving about
    case, spacing and hyphens as a whole short answer is.

    ``payload`` is the JSON the client serialises, ``{"blanks": ["15", "live"]}``
    — positional, one entry per blank. A malformed spec or payload, a missing
    entry, or a blank left empty simply grades wrong.

    ``answer_format`` is the question's, and each gap is judged by it through
    :func:`~maths.algebra_grading.match_value` — so an algebra question keeps
    accepting "2ba" for "2ab" after conversion, and every gap keeps the
    commuted-expression allowance a plain typed answer has.

    This is the boolean view of :func:`grade_fill_blank_parts`, which grades the
    same gaps one at a time so a nine-out-of-ten answer can be given nine tenths
    of the marks. Both agree on what "correct" means: every gap right.
    """
    grade = grade_fill_blank_parts(blank_spec, payload, answer_format)
    return grade is not None and grade.is_correct


def grade_fill_blank_parts(blank_spec, payload, answer_format='text'):
    """Grade a ``fill_blank`` answer gap by gap, for partial credit.

    Returns a :class:`~maths.partial_credit.PartialGrade` — one
    :class:`~maths.partial_credit.Part` per gap, in order, each carrying what
    the student typed, what was accepted and whether it matched — or ``None``
    when there is nothing to grade against: a spec with no blanks, a payload
    that isn't a blanks payload, or one whose length has drifted from the
    spec's. ``None`` means "no verdict", and every caller treats it as the
    zero-scoring wrong answer :func:`grade_fill_blank` has always returned,
    rather than inventing a fraction from a payload it can't line up.

    Never raises: it is called on whatever a student's browser posted.
    """
    from maths.partial_credit import Part, PartialGrade

    accepted = blank_answers(blank_spec)
    # A spec with no blanks is unanswerable — never silently "correct".
    if not accepted:
        return None

    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    given = data.get('blanks')
    # A payload of the wrong length cannot be lined up with the gaps: gap 3's
    # value might be gap 4's. Scoring it part by part would hand out credit for
    # matches that are coincidences, so it gets no verdict at all.
    if not isinstance(given, list) or len(given) != len(accepted):
        return None

    parts = []
    for index, (typed, options) in enumerate(zip(given, accepted)):
        typed = '' if typed is None else str(typed).strip()
        is_correct = bool(typed) and any(
            match_value(typed, o, answer_format) for o in options
        )
        parts.append(Part(
            label=f'Blank {index + 1}',
            typed=typed,
            expected=' or '.join(options),
            is_correct=is_correct,
        ))
    return PartialGrade(parts, noun='blank')


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
    if _THOUSANDS_NUMBER_RE.match(text.strip()):
        # One number, not a list — see _THOUSANDS_NUMBER_RE.
        return None

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


def bare_unit_answers(question_text, correct_texts):
    """The bare values to store BESIDE answers that repeat their gap's unit.

    The other half of :func:`unit_repeat_blanks`. That function names the
    defect — "Convert to millilitres: 5.3 L = ___ mL" answered "5300 mL" reads
    inline as "= [5300 mL] mL" and marks the obvious "5300" wrong — and this
    works out what to store to fix it, so the fix is applied from the same
    reading of the sentence that refused the question rather than by hand,
    fourteen times, with a typo in one of them.

    Returns texts to ADD, never a replacement. "5300 mL" stays an accepted
    answer: a student who writes the unit was marked correct before the gap
    went inline and must still be. Adding an accepted spelling is also true
    of the question in its single-box form, so this is a safe write even if
    the conversion that follows is later reverted.

    Single-gap questions only. Deciding which row feeds which gap on a
    multi-gap question is the exact ambiguity :func:`derive_blank_spec`
    refuses to guess at, and stripping the unit off a row that fills a
    different gap would corrupt the answer rather than repair it.

    Returns ``[]`` when there is nothing to add — no gap, no unit after it, an
    answer that already omits the unit, or the bare value already stored — so
    running it twice adds nothing the second time.
    """
    if count_blanks(question_text) != 1:
        return []

    texts = [t.strip() for t in correct_texts if t and t.strip()]
    if not texts:
        return []

    segments = split_on_blanks(question_text)
    if len(segments) != 2:
        return []
    match = _UNIT_TOKEN_RE.match(segments[1] or '')
    if not match:
        return []
    unit = match.group(1)

    options = sum((_alternatives(t) for t in texts), [])
    # Only when EVERY spelling repeats the unit. If one already reads "5300",
    # the student can answer without repeating it and there is no defect to
    # repair — the same test unit_repeat_blanks applies before flagging.
    if not all(_repeats_unit(option, unit) for option in options):
        return []

    out = []
    for option in options:
        bare = option[:-len(unit)].strip()
        if bare and bare not in options and bare not in out:
            out.append(bare)
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
    * **N blanks, at least one row splitting into N** — that row is a whole
      answer listing all N values, so it says what goes in each gap: gap *i*
      accepts the *i*-th value of every row that splits, and rows that do not
      split are dropped as prose spellings of the same answer. Strictly safer
      than the rule below, and tried first.
    * **N blanks, N rows** — row *i* fills gap *i*, but only when
      ``positional_rows`` is set AND the rows look like per-gap values rather
      than spellings of one answer (see :func:`_looks_positional`).
    * **anything else** — refused, with the counts named.

    Then, only for what those rules refuse: a question that PRINTS a number
    pattern with gaps in it ("complete the pattern: 30, ___, 60, 75, ___, ___")
    fills them from the sequence itself rather than from the rows, which store
    its rule and never its gap values. The one gap the pattern does not fill
    takes the rule — and if the sentence has no gap for the rule it is refused
    rather than converted, because a rule asked for in prose alone would stop
    being marked at all (see :func:`_values_from_pattern`).

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

    values, reason = _values_from_rows(texts, n, positional_rows)
    if values is None:
        # The rows say nothing usable about the gaps — but the question often
        # says plenty itself: a printed number pattern, printed arithmetic, or
        # a stored answer that IS the question with its blanks filled in.
        route_reason = ''
        for route in (_values_from_pattern, _values_from_arithmetic,
                      _values_from_worked_answer):
            values, refusal = route(question_text, texts, n)
            if values is not None:
                break
            # The first route to recognise the question and still refuse it is
            # the one with something to say; the rows' own refusal stands when
            # none of them did.
            route_reason = route_reason or refusal
        if values is None:
            return None, route_reason or reason

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


def _values_from_rows(texts, n, positional_rows):
    """The accepted answers for each of *n* gaps, read off the stored rows.

    ``(values, reason)`` — exactly one is set, and ``reason`` is what
    :func:`derive_blank_spec` reports when nothing else can fill the gaps
    either. The mapping rules are the ones documented there.
    """
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
    elif any(_split_row(t, n) is not None for t in texts):
        # At least one row lists all N values, so THAT row says what goes in
        # each gap: gap i accepts the i-th value of every row that splits.
        # Rows that do not split are prose spellings of the whole answer and
        # are dropped — "up by 2" beside "up, 2" is the same answer written
        # twice, and only the second says where the halves go.
        #
        # Preferred over the row-per-gap rule below, and tried first: given
        # rows ["up by 2", "up, 2"] that rule would hand gap 1 the whole
        # string "up by 2".
        values = [[] for _ in range(n)]
        for text in texts:
            parts = _split_row(text, n)
            if parts is None:
                continue
            for index, part in enumerate(parts):
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

    return values, ''


# --------------------------------------------------------------------------
# The gaps a printed number pattern fills for itself
# --------------------------------------------------------------------------
# "Complete the pattern: 30, ___, 60, 75, ___, ___. What is the rule?" stores
# its answer as the RULE ("+15", "add 15", "+ 15") and never as the values of
# its gaps, so the row rules above have nothing to map onto its three blanks
# and refuse it — rightly, since row 1 is "+15" and gap 1 is 45, and mapping
# one onto the other marks a correct student wrong.
#
# But those gap values are not a guess: the sequence is printed in the question
# and solves itself, 45, 90 and 105 with it (maths.pattern_grading). So they
# are filled from the arithmetic, and the stored rows are kept for the one gap
# they DO describe — the rule, when the sentence has a gap for it.
#
# The rule needs a gap of its own: a fill-in-the-blank sentence is graded gap by
# gap, so a rule asked for only in prose would stop being marked at all. That is
# the one thing this must never do quietly, so a question whose answer is the
# rule and whose gaps are all the pattern's is REFUSED, and named, until a gap
# for the rule exists — see ``add_rule_blank`` and
# ``convert_fill_blanks --add-rule-blank``.

# Appended to the question text to give the rule a gap of its own: its own
# line, and labelled.
#
# The first version of this appended a bare " ___", on the reasoning that the
# question's own wording already asked for the rule. On the page it landed
# under the sequence with nothing beside it — a child reading
# "132, [ ], 140, [ ], 148, [ ]" followed by a lone box has no way to know
# that box wants a rule rather than another number.
RULE_BLANK_SUFFIX = '\nThe rule is: ___'

# What the first version appended. Nothing writes it; --revert still knows it,
# so a question converted by that run comes back cleanly.
_LEGACY_RULE_BLANK_SUFFIXES = (' ___',)


def pattern_blank_values(question_text):
    """``(values_by_blank, pattern)`` for the gaps a printed sequence solves.

    ``values_by_blank`` maps the index of a blank in *question_text* (counting
    every "___" run, left to right) to the value that belongs in it.
    ``({}, None)`` when the question prints no solvable sequence, or when the
    sequence's gaps are not exactly the "___" runs inside it — a sequence
    written "30, ?, 60" solves, but a "?" is not a blank anybody can type into.
    """
    from maths.pattern_grading import prepare, read_printed_pattern

    pattern = read_printed_pattern(question_text)
    if pattern is None:
        return {}, None
    # Blanks are counted in the SAME text the pattern's span indexes — prepare()
    # drops digit-grouping commas, which shifts every offset after one. It never
    # touches underscores, so a run's ordinal is the same in either text.
    runs = list(BLANK_RE.finditer(prepare(question_text)))
    start, end = pattern.span
    inside = [i for i, run in enumerate(runs) if start <= run.start() < end]
    if len(inside) != len(pattern.missing):
        return {}, None
    return dict(zip(inside, pattern.missing)), pattern


def _values_from_pattern(question_text, texts, n):
    """The accepted answers per gap when the QUESTION prints the pattern.

    ``(values, reason)``. A reason is given only where this route recognised
    the question and still refused it; otherwise it is empty, which leaves
    :func:`derive_blank_spec` reporting what the rows themselves could not do —
    the more actionable of the two on a question that is not this shape.
    """
    from maths.pattern_grading import (
        format_value, rule_spellings, states_the_rule)

    values_by_blank, pattern = pattern_blank_values(question_text)
    if not values_by_blank:
        return None, ''

    values = [None] * n
    for index, value in values_by_blank.items():
        values[index] = [format_value(value)]
    spare = [i for i, entry in enumerate(values) if entry is None]

    # Every stored row has to be accounted for. Rows that state the rule are
    # this route's business; anything else means the question is not what it
    # looks like, and the row rules' own refusal is the better report.
    if not all(states_the_rule(text, pattern) for text in texts):
        return None, ''

    if not spare:
        return None, (
            f'the pattern fills all {n} gap(s) by itself, but the stored '
            f'answer is its RULE ({texts[0]!r}) and no gap asks for that — '
            f'converting as-is would stop the rule being marked at all. Give '
            f'the rule a gap (end the question with "___"), or run '
            f'convert_fill_blanks --add-rule-blank, which appends one'
        )
    if len(spare) > 1:
        return None, (
            f'{len(spare)} gaps sit outside the pattern and only the rule is '
            f'stored, so what goes in the others is anybody\'s guess'
        )

    # One gap left, and every row is a spelling of the rule: that gap is where
    # the rule goes. The stored rows come first — they are the author's own
    # wording — followed by the ordinary spellings of the same rule, because a
    # gap is graded by exact match and a child who writes "add 15" for a stored
    # "+15" must not start being marked wrong by the conversion.
    accepted = list(texts)
    for spelling in rule_spellings(pattern):
        if spelling not in accepted:
            accepted.append(spelling)
    values[spare[0]] = accepted
    return values, ''


def add_rule_blank(question_text, correct_texts):
    """*question_text* with a gap appended for the rule — or ``(None, reason)``.

    The repair for the questions ``_values_from_pattern`` refuses: the sentence
    prints a pattern that fills every one of its gaps, and the stored answer is
    the rule, which then has nowhere to be typed. Appending a blank is what
    makes the conversion honest — every part of the question the student is
    asked for is a part they are marked on.

    Returns ``(text, '')`` on success. Refuses anything it has not proved:
    a question with no solvable pattern, one whose gaps are not all the
    pattern's, or one whose rows are not all spellings of that pattern's rule.
    """
    from maths.pattern_grading import states_the_rule

    texts = [t.strip() for t in correct_texts if t and t.strip()]
    if not texts:
        return None, 'no correct answer stored'

    values_by_blank, pattern = pattern_blank_values(question_text)
    if not values_by_blank:
        return None, 'the question prints no pattern that solves its gaps'
    if len(values_by_blank) != count_blanks(question_text):
        return None, 'the question already has a gap outside its pattern'
    if not all(states_the_rule(text, pattern) for text in texts):
        return None, (
            'the stored answer is not the rule of the pattern the question '
            'prints, so there is nothing to put in the gap this would add'
        )
    return question_text.rstrip() + RULE_BLANK_SUFFIX, ''


def strip_rule_blank(question_text):
    """*question_text* without the gap :func:`add_rule_blank` appended.

    ``None`` when the text does not end in one — proved rather than assumed,
    because reverting must never eat a blank that was always part of the
    sentence. The proof is that the trailing blank is the ONE gap the printed
    pattern does not fill: "…30, ___, 60, 75, ___, ___", whose last blank is
    the pattern's own, is refused on exactly that test.

    Both wordings are recognised, so a question converted by an earlier run
    reverts as cleanly as one converted today.
    """
    if not question_text:
        return None
    for suffix in (RULE_BLANK_SUFFIX,) + _LEGACY_RULE_BLANK_SUFFIXES:
        if question_text.endswith(suffix):
            break
    else:
        return None

    values_by_blank, _ = pattern_blank_values(question_text)
    total = count_blanks(question_text)
    if not values_by_blank or total - len(values_by_blank) != 1:
        return None
    if total - 1 in values_by_blank:
        return None
    return question_text[:-len(suffix)]


def _values_from_arithmetic(question_text, texts, n):
    """The accepted answers per gap when the QUESTION prints its own sums.

    ``(values, reason)``. "Write the sum and then write the product:
    4 + 4 + 4 + 4 + 4 + 4 = ______ and 4 x 6 = ______" stores one answer, 24,
    against two gaps — the row rules cannot say which gap it is, and both of
    them are 24. The arithmetic is printed, so it is solved instead
    (:mod:`maths.arithmetic_gaps`) and the stored answer is used for what it
    can prove: that the question was read the way its author meant it.

    That check is not a formality. A stored answer matching nothing the
    arithmetic comes to means one of the two is wrong, and neither a
    mis-parsed question nor a wrong answer key is something to convert on top
    of — so it is reported for a person instead.
    """
    from maths.arithmetic_gaps import read_arithmetic_gaps
    from maths.pattern_grading import format_value

    by_blank = read_arithmetic_gaps(question_text)
    if not by_blank or len(by_blank) != n:
        return None, ''

    values = [[format_value(by_blank[index])] for index in range(n)]
    computed = {fold_answer(entry[0]) for entry in values}
    if any(fold_answer(text) in computed for text in texts):
        return values, ''

    shown = ', '.join(entry[0] for entry in values)
    return None, (
        f'the arithmetic printed in this question fills its {n} gaps with '
        f'{shown}, but the stored answer is {texts[0]!r}, which is none of '
        f'them — the question and its answer key disagree, so neither is safe '
        f'to convert on'
    )


def _values_from_worked_answer(question_text, texts, n):
    """The accepted answers per gap when a stored row IS the question, filled.

    ``(values, reason)``. "__ + __ + __ + __ + __ + __ + __ = 63, so ___ x ___
    = 63" stores its answer as the whole thing worked out — "9 + 9 + 9 + 9 + 9
    + 9 + 9 = 63, 7 x 9 = 63" — which the row rules cannot split, because the
    separators it would split on are the question's own plus signs.

    Lined up against the question it completes, though, it says exactly what
    goes in each gap, and says it better than arithmetic could: seven equal
    addends of 63 are 9 each, but "___ x ___ = 63" is 7 x 9 or 9 x 7 and only
    the row knows which the author wrote.

    The alignment is the proof, so nothing else is checked against it — see
    :func:`maths.arithmetic_gaps.read_worked_answer` for what it demands. Rows
    that do not line up are the prose and partial spellings that live beside
    the worked one ("9", "9, 7 x 9"), and they are dropped, exactly as the row
    rules drop a prose row beside a separated one.
    """
    from maths.arithmetic_gaps import read_worked_answer
    from maths.pattern_grading import format_value

    aligned = [read_worked_answer(question_text, text) for text in texts]
    aligned = [filled for filled in aligned if filled and len(filled) == n]
    if not aligned:
        return None, ''

    worked = aligned[0]
    if any(other != worked for other in aligned[1:]):
        return None, (
            'two stored answers complete this question differently, so which '
            'of them fills the gaps is not a choice this can make'
        )
    return [[format_value(worked[index])] for index in range(n)], ''
