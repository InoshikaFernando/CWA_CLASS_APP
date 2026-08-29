"""Grade a number pattern — the one the student invents, and the one the
question prints with gaps in it.

A question that asks the student to invent one has no single right answer, so
there is nothing to store in an ``Answer`` row: "Create your own tricky
subtraction number pattern of six numbers and write down the rule you used"
is answered correctly by ``20, 18, 16, 14, 12, 10`` and by infinitely many
other sequences. Until this module existed they were authored with no correct
answer at all, which the typed-answer grader reads as "nothing matches" — so
*every* student who answered one was marked wrong, forever, no matter what
they wrote.

The fix is to grade the answer against the *question's requirements* rather
than against a stored string:

  * the numbers must form a real pattern — the same step (or the same
    multiplier) between every consecutive pair;
  * they must move the way the question asks (a subtraction pattern goes
    down, a multiplication pattern scales up);
  * there must be as many of them as the question asks for;
  * a rule the student states must agree with the numbers they wrote.

Two deliberate calls, both about being fair to a child in an instant-feedback
quiz rather than to a marking scheme:

  * **A missing rule does not fail the answer.** When the question asks the
    student to write the rule down and they only wrote the numbers, the
    pattern is still right — the rule is visible in it — so it is marked
    correct with a note asking for the rule next time. A rule that
    *contradicts* the numbers does fail: that is a real mistake worth
    catching.
  * **Every outcome carries feedback naming what happened** ("your numbers go
    up by 2, but the question asks for a subtraction pattern"). A bare
    "Incorrect" on a question with no printable answer tells the student
    nothing at all.

The second half of the module (from "Completing a pattern the QUESTION
prints") grades the opposite shape — "complete the pattern: 30, ___, 60, 75,
___, ___. What is the rule?", which DOES have a stored answer but stores only
half of what it asks for, so a student who wrote both halves matched nothing.

Pure functions, no Django imports — the routing lives in
``maths.models.Question.grade_text_answer`` and ``quiz.views``.
"""
import re
from fractions import Fraction

# --------------------------------------------------------------------------
# What the question is asking for
# --------------------------------------------------------------------------
ADD = 'add'
SUBTRACT = 'subtract'
MULTIPLY = 'multiply'
DIVIDE = 'divide'

# How each operation reads in feedback: (name, "how it moves" phrase).
_OP_PHRASE = {
    ADD: ('an addition', 'goes up by'),
    SUBTRACT: ('a subtraction', 'goes down by'),
    MULTIPLY: ('a multiplication', 'multiplies by'),
    DIVIDE: ('a division', 'divides by'),
}

# Words in the QUESTION that name the operation. Alternatives are written
# longest-first within each entry; between entries the operation named
# EARLIEST in the question wins, so "subtraction pattern ... write the rule"
# reads as subtraction rather than being pulled around by a later word.
_QUESTION_OPS = [
    (r'subtraction|subtract|take\s*away|taking\s*away|minus|counting\s+back|'
     r'count\s+back|decreas\w*', SUBTRACT),
    (r'addition|adding|add|plus|increas\w*|counting\s+on|count\s+on', ADD),
    (r'multiplication|multiplying|multiply|times\s+table|times|doubling|double',
     MULTIPLY),
    (r'division|dividing|divide|halving|halve', DIVIDE),
]

_NUMBER_WORDS = {
    'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
    'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12,
}

# "... pattern of six numbers", "... five numbers long", "... 6 terms"
_COUNT_RE = re.compile(
    r'\b(\d{1,2}|' + '|'.join(_NUMBER_WORDS) + r')\s+(?:numbers?|terms?)\b',
    re.IGNORECASE,
)

# "write down the rule you used", "state the rule", "and give your rule"
_ASKS_FOR_RULE_RE = re.compile(
    r'\b(?:write|writing|state|give|say|explain|describe|record|show|tell)\b'
    r'[^.?!]{0,60}?\brules?\b',
    re.IGNORECASE,
)

# A rule the QUESTION fixes for the student: "using the rule -3", "rule of 4",
# "that goes down by 5", "adding 7 each time". Distinguished from "the rule you
# used" by requiring a number.
_QUESTION_RULE_RE = re.compile(
    r'\brule\s*(?:of|is|:|=)?\s*([+-]?\d+(?:\.\d+)?)'
    r'|\b(?:up|down)\s+by\s+(\d+(?:\.\d+)?)'
    r'|\b(?:add|adding|subtract|subtracting|take\s*away|minus|plus)\s+'
    r'(\d+(?:\.\d+)?)',
    re.IGNORECASE,
)

# Marks a question as "invent your own", as opposed to "continue this one".
_CREATE_YOUR_OWN_RE = re.compile(
    r'\b(?:create|make|write|design|invent|think\s+of|come\s+up\s+with|give)\b'
    r'[^.?!]{0,40}?\byour\s+own\b'
    r'|\bmake\s+up\b[^.?!]{0,40}?\b(?:pattern|sequence)\b'
    r'|\bof\s+your\s+own\b',
    re.IGNORECASE,
)
_PATTERN_WORD_RE = re.compile(r'\b(?:patterns?|sequences?)\b', re.IGNORECASE)


class PatternRequest:
    """What a "create your own pattern" question requires of an answer.

    Every field is optional: a question that names none of them ("Make up your
    own number pattern") is satisfied by any real pattern of three or more
    numbers.
    """

    def __init__(self, operation=None, length=None, step=None, needs_rule=False):
        self.operation = operation      # ADD / SUBTRACT / MULTIPLY / DIVIDE / None
        self.length = length            # how many numbers, or None
        self.step = step                # Fraction the question fixes, or None
        self.needs_rule = needs_rule    # question asks the student to state it

    def __repr__(self):
        return (f'PatternRequest(operation={self.operation!r}, '
                f'length={self.length!r}, step={self.step!r}, '
                f'needs_rule={self.needs_rule!r})')

    def __eq__(self, other):
        return isinstance(other, PatternRequest) and (
            (self.operation, self.length, self.step, self.needs_rule)
            == (other.operation, other.length, other.step, other.needs_rule))


class PatternGrade:
    """The outcome of grading one answer, with the feedback to show for it."""

    def __init__(self, is_correct, feedback):
        self.is_correct = is_correct
        self.feedback = feedback

    def __repr__(self):
        return f'PatternGrade({self.is_correct!r}, {self.feedback!r})'

    def __bool__(self):
        return self.is_correct


# --------------------------------------------------------------------------
# Reading the question
# --------------------------------------------------------------------------

def looks_like_pattern_question(question_text):
    """True when *question_text* asks the student to invent a pattern.

    Used to FIND these questions in an existing catalogue (see the
    ``set_pattern_answer_format`` command) — never at grading time, where the
    question's ``answer_format`` decides. "Write down the next three numbers in
    this pattern" has both a verb and the word "pattern" but is not an
    invitation to invent one, so "your own" (or "make up") is required.
    """
    text = _normalise(question_text or '')
    return bool(_PATTERN_WORD_RE.search(text) and _CREATE_YOUR_OWN_RE.search(text))


def parse_pattern_request(question_text):
    """Extract the requirements from *question_text*. Never returns None —
    anything the question does not specify is simply left unconstrained."""
    text = _normalise(question_text or '')

    operation = None
    earliest = len(text) + 1
    for words, op in _QUESTION_OPS:
        match = re.search(words, text, re.IGNORECASE)
        if match and match.start() < earliest:
            earliest, operation = match.start(), op

    length = None
    count = _COUNT_RE.search(text)
    if count:
        token = count.group(1).lower()
        length = _NUMBER_WORDS.get(token) or int(token)
        # A pattern needs at least three numbers to show a repeated step; a
        # bigger count than any real question uses is a misread, not a rule.
        if not 2 <= length <= 30:
            length = None

    step = None
    fixed = _QUESTION_RULE_RE.search(text)
    if fixed:
        raw = next(g for g in fixed.groups() if g is not None)
        step = abs(Fraction(raw))

    # A question that hands the student the rule ("using the rule -3") is not
    # also asking them to state it back, however its wording reads.
    needs_rule = step is None and bool(_ASKS_FOR_RULE_RE.search(text))

    return PatternRequest(
        operation=operation,
        length=length,
        step=step,
        needs_rule=needs_rule,
    )


# --------------------------------------------------------------------------
# Reading the answer
# --------------------------------------------------------------------------

def _normalise(text):
    """Fold the dashes and symbols a keypad or a phone keyboard produces."""
    return (text.replace('−', '-')        # −  minus sign
                .replace('–', '-')        # –  en dash
                .replace('—', '-')        # —  em dash
                .replace('×', 'x')        # ×
                .replace('÷', '/'))       # ÷


_DIGITS_RE = re.compile(r'\d+(?:\.\d+)?')
_GROUPED_RE = re.compile(r'(?<=\d),(?=\d{3}(?!\d))')

# Words that introduce the RULE rather than another number of the pattern, used
# to tell "21, 18, 15, 12, 9, 6 — rule: subtract 3" (six numbers and a rule)
# from "21, 18, 15, 12, 9, 6, 3" (seven numbers). A bare "-" is deliberately
# absent: between two numbers it is far more likely to be an arrow or a dash
# than the start of a rule.
_RULE_LEAD_IN_RE = re.compile(
    r'rule|subtract\w*|minus|take\s*away|add\w*|plus|times|multipl\w*|'
    r'divid\w*|halv\w*|double|each\s+time|going|goes|count\w*|step',
    re.IGNORECASE,
)


def prepare(text):
    """The answer text as the parsers below read it: folded symbols, and
    digit-grouping commas removed so ``1,000`` is one number, not two."""
    return _GROUPED_RE.sub('', _normalise(text or ''))


def extract_numbers(text):
    """Every number in *text* as ``(value, start, end)``, in reading order.

    Offsets index into ``prepare(text)``. A leading ``-`` counts as a sign only
    when the previous non-space character is not a digit, so ``4, -2`` reads as
    two numbers while ``20 - 2`` reads as one operator and one number.
    """
    text = prepare(text)
    found = []
    for match in _DIGITS_RE.finditer(text):
        start = match.start()
        head = text[:start].rstrip()
        if head.endswith('-'):
            before = head[:-1].rstrip()
            if not (before and before[-1].isdigit()):
                found.append((Fraction(match.group()) * -1,
                              len(head) - 1, match.end()))
                continue
        found.append((Fraction(match.group()), start, match.end()))
    return found


def _arithmetic_step(values):
    """The common difference of *values*, or None if they don't share one."""
    if len(values) < 2:
        return None
    step = values[1] - values[0]
    if step == 0:
        return None
    for a, b in zip(values, values[1:]):
        if b - a != step:
            return None
    return step


def _geometric_ratio(values):
    """The common multiplier of *values*, or None if they don't share one."""
    if len(values) < 2 or any(v == 0 for v in values):
        return None
    ratio = values[1] / values[0]
    if ratio == 1:
        return None
    for a, b in zip(values, values[1:]):
        if b / a != ratio:
            return None
    return ratio


def _describe(values):
    """(operation, size) for a consistent run, or (None, None).

    Arithmetic is tested first: 2, 4, 6, 8 is an addition pattern even though
    2, 4, 8, 16 is a multiplication one.
    """
    step = _arithmetic_step(values)
    if step is not None:
        return (ADD if step > 0 else SUBTRACT), abs(step)
    ratio = _geometric_ratio(values)
    if ratio is not None:
        return (MULTIPLY if abs(ratio) > 1 else DIVIDE), (
            abs(ratio) if abs(ratio) > 1 else 1 / abs(ratio))
    return None, None


def _first_break(values):
    """Index of the first number that breaks the run the answer started."""
    if len(values) < 3:
        return len(values) - 1
    step = values[1] - values[0]
    for i in range(2, len(values)):
        if values[i] - values[i - 1] != step:
            return i
    return len(values) - 1


def _segments(numbers, text):
    """*numbers* split wherever a rule phrase interrupts them.

    "21, 18, 15, 12, 9, 6 — rule: subtract 3" has to read as six numbers and a
    rule. Reading it as seven numbers would fail a student whose pattern was
    right *because* their rule happens to continue it.
    """
    text = prepare(text)
    segments, current, cursor = [], [], 0
    for number in numbers:
        gap = text[cursor:number[1]]
        if _RULE_LEAD_IN_RE.search(gap):
            if current:
                segments.append(current)
            current = []
        current.append(number)
        cursor = number[2]
    if current:
        segments.append(current)
    return segments


def _consistent(numbers):
    return _describe([value for value, _, _ in numbers])[0] is not None


def _choose_sequence(numbers, length, text):
    """Pick the numbers that are the student's *pattern*.

    Students routinely write the rule alongside the numbers, and the rule's
    digits are numbers too. In order of preference:

    1. a run with the rule split off that is a pattern of the requested length
       — the common case, and the one a naive read gets wrong;
    2. the whole answer, when that is itself one pattern — so a student who
       wrote seven numbers is told they wrote seven, not quietly marked on six
       of them;
    3. the longest run that is a pattern, so the feedback can say what is wrong
       with it;
    4. any window of the requested length, for rules written without a word
       ("20, 18, 16, 14, 12, 10 -2").
    """
    segments = _segments(numbers, text)
    for segment in segments:
        if _consistent(segment) and (length is None or len(segment) == length):
            return segment

    if _consistent(numbers):
        return numbers

    runs = sorted((s for s in segments if _consistent(s)), key=len, reverse=True)
    if runs:
        return runs[0]

    if length and len(numbers) > length:
        for start in range(len(numbers) - length + 1):
            window = numbers[start:start + length]
            if _consistent(window):
                return window
    return numbers


# --------------------------------------------------------------------------
# Reading the rule the student stated
# --------------------------------------------------------------------------

# An operator SYMBOL only counts as a rule when a number follows it: "rule -2"
# states a rule, but the dash in "20, 18, 16 — rule: subtract 2" is punctuation.
# Folding em/en dashes to "-" (so a typed minus is read whichever character the
# student reached for) means that punctuation would otherwise be read as
# "subtract" and contradict any addition rule written beside it — which failed
# a correct answer to every "create your own ADDITION pattern" question.
_RULE_WORDS = [
    (r'take\s*away|takeaway|subtract\w*|minus|less|down|back|smaller|'
     r'decreas\w*', SUBTRACT),
    (r'add\w*|plus|up|more|bigger|larger|increas\w*', ADD),
    (r'multipl\w*|times|double|doubl\w*', MULTIPLY),
    (r'divid\w*|halve|halv\w*|half', DIVIDE),
    (r'-\s*\d', SUBTRACT),
    (r'\+\s*\d', ADD),
    (r'[x*]\s*\d', MULTIPLY),
    (r'/\s*\d', DIVIDE),
]


def _stated_rule(remainder):
    """(operation, size) the student *said* they used — either may be None.

    *remainder* is the answer with the numbers of the pattern itself removed,
    so a negative value inside the pattern can never be misread as a rule.
    """
    text = _normalise(remainder or '')
    operation, earliest = None, len(text) + 1
    for words, op in _RULE_WORDS:
        match = re.search(words, text, re.IGNORECASE)
        if match and match.start() < earliest:
            earliest, operation = match.start(), op
    sizes = _DIGITS_RE.findall(text)
    size = Fraction(sizes[0]) if sizes else None
    return operation, size


def _remainder(raw, sequence):
    """*raw* with the span covered by the chosen pattern numbers cut out."""
    text = prepare(raw)
    if not sequence:
        return text
    return text[:sequence[0][1]] + ' ' + text[sequence[-1][2]:]


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def _fmt(value):
    """A Fraction as a child would write it: 6, -2, 2.5, 1/3."""
    if value.denominator == 1:
        return str(value.numerator)
    as_float = float(value)
    if as_float == round(as_float, 4):
        return f'{as_float:g}'
    return f'{value.numerator}/{value.denominator}'


def _join(values):
    return ', '.join(_fmt(v) for v in values)


def example_answer(request):
    """A model answer for *request* — used in feedback and by the grading sweep.

    Chosen so it always satisfies the request it was built from: that is what
    makes it safe for ``verify_quiz_grading`` to submit as the "right answer"
    for a question that has none stored.
    """
    length = request.length or 6
    operation = request.operation or SUBTRACT
    step = request.step or (Fraction(3) if operation in (ADD, SUBTRACT)
                            else Fraction(2))
    if operation in (MULTIPLY, DIVIDE) and step <= 1:
        step = Fraction(2)

    if operation == ADD:
        values = [Fraction(5) + step * i for i in range(length)]
    elif operation == SUBTRACT:
        values = [step * (length + 1) - step * i for i in range(length)]
    elif operation == MULTIPLY:
        values = [Fraction(2) * step ** i for i in range(length)]
    else:
        values = [Fraction(2) * step ** (length - 1 - i) for i in range(length)]

    answer = _join(values)
    if request.needs_rule:
        verb = {ADD: 'add', SUBTRACT: 'subtract',
                MULTIPLY: 'multiply by', DIVIDE: 'divide by'}[operation]
        answer += f' — rule: {verb} {_fmt(step)}'
    return answer


# --------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------

def grade_pattern(question_text, raw):
    """Grade *raw* as an answer to a "create your own pattern" question.

    Returns a :class:`PatternGrade` — always, so no caller can fall through to
    "no stored answer, therefore wrong".
    """
    request = parse_pattern_request(question_text)
    numbers = extract_numbers(raw)
    wanted = request.length

    if len(numbers) < 2:
        return PatternGrade(False, (
            'I could not find your pattern. Write your numbers separated by '
            'commas, then the rule you used.'))

    sequence = _choose_sequence(numbers, wanted, raw)
    values = [value for value, _, _ in sequence]

    if len(set(values)) == 1:
        return PatternGrade(False, (
            f'Your numbers all stay on {_fmt(values[0])}, so they are not a '
            f'pattern yet — each number has to change by the same amount.'))

    operation, size = _describe(values)
    if operation is None:
        broke = _first_break(values)
        return PatternGrade(False, (
            f'Your numbers do not change by the same amount each time — '
            f'{_fmt(values[broke - 1])} to {_fmt(values[broke])} breaks the '
            f'pattern you started.'))

    if wanted and len(values) != wanted:
        return PatternGrade(False, (
            f'That is a real pattern, but the question asks for {wanted} '
            f'numbers and you wrote {len(values)}.'))

    if wanted is None and len(values) < 3:
        # Two numbers never show a rule — 20, 18 is the start of "take away 2"
        # and of half a dozen other patterns.
        return PatternGrade(False, (
            'Two numbers do not show a rule yet — write at least three so the '
            'pattern is clear.'))

    _, moves = _OP_PHRASE[operation]
    if request.operation and operation != request.operation:
        wanted_article, _ = _OP_PHRASE[request.operation]
        return PatternGrade(False, (
            f'Your pattern {moves} {_fmt(size)} each time. The question asks '
            f'for {wanted_article} pattern.'))

    if request.step is not None and size != request.step:
        return PatternGrade(False, (
            f'The question asks for a rule of {_fmt(request.step)}, but your '
            f'pattern {moves} {_fmt(size)} each time.'))

    stated_op, stated_size = _stated_rule(_remainder(raw, sequence))
    if stated_op is not None and stated_op != operation:
        stated_article, _ = _OP_PHRASE[stated_op]
        return PatternGrade(False, (
            f'Your pattern {moves} {_fmt(size)} each time, but your rule says '
            f'{stated_article} rule. Check which one you meant.'))
    if stated_size is not None and stated_size != size:
        return PatternGrade(False, (
            f'Your rule says {_fmt(stated_size)}, but your pattern {moves} '
            f'{_fmt(size)} each time.'))

    praise = f'Nice pattern — it {moves} {_fmt(size)} each time.'
    if request.needs_rule and stated_op is None and stated_size is None:
        # The rule is there in the numbers, so the pattern is not wrong — but
        # the question did ask for it in words, so say so.
        praise += (' The question also asks for the rule, so next time write '
                   f'it down too: "rule: {"-" if operation == SUBTRACT else ""}'
                   f'{_fmt(size)}".')
    return PatternGrade(True, praise)


# --------------------------------------------------------------------------
# Completing a pattern the QUESTION prints
# --------------------------------------------------------------------------
# Everything above grades a pattern the student *invented*. This grades the
# other shape: "Work out the number pattern rule and complete the pattern:
# 30, ___, 60, 75, ___, ___. What is the rule?" — which asks for two things
# and stores one. Its Answer rows are "+15", "add 15", "+ 15", so a student
# who did exactly what the question asked, and typed the missing numbers
# beside the rule ("add 15 — 45, 90, 105"), matched none of them and was told
# ❌ Incorrect under a correct answer that already said add 15.
#
# The fix is not to loosen the string match — "contains the stored answer"
# would accept "45, 90, 105 or maybe add 15?" and every other hedge. It is to
# check the answer against the sequence the question itself prints: solve the
# sequence, and both the missing values and the rule are known, so an answer
# can be accepted only when everything in it is right AND it says at least as
# much as the stored answer does (a question whose answer is the rule still
# demands the rule).

_BLANK_RE = re.compile(r'_{2,}|\?')
_SEQ_ITEM = r'(?:-?\d+(?:\.\d+)?|_{2,}|\?)'
# Three items or more: two numbers and a gap are the shortest thing that can
# show a rule at all.
_SEQUENCE_RE = re.compile(rf'{_SEQ_ITEM}(?:\s*,\s*{_SEQ_ITEM}){{2,}}')

NUMBERS = 'numbers'
RULE = 'rule'


class PrintedPattern:
    """The sequence a "complete the pattern" question prints, solved."""

    def __init__(self, values, missing, operation, size):
        self.values = values        # the full sequence, gaps filled
        self.missing = missing      # the gap values, in the order they appear
        self.operation = operation  # ADD / SUBTRACT / MULTIPLY / DIVIDE
        self.size = size            # step or multiplier, unsigned

    def __repr__(self):
        return (f'PrintedPattern({_join(self.values)!r}, '
                f'missing={_join(self.missing)!r}, '
                f'operation={self.operation!r}, size={_fmt(self.size)!r})')


def _solve(tokens):
    """Fill the ``None`` gaps in *tokens*, or None if they hide no one rule.

    Gaps may sit anywhere, so the step is taken from the first two KNOWN values
    and their distance apart — 30, _, 60 steps by 15, not by 30 — and then
    every other known value has to agree with it. Arithmetic is tried first, as
    it is everywhere else here: 2, 4, 6, 8 is an addition pattern even though
    2, 4, 8, 16 is a multiplication one.
    """
    known = [(i, v) for i, v in enumerate(tokens) if v is not None]
    if len(tokens) < 3 or len(known) < 2:
        return None

    (first, a), (second, b) = known[0], known[1]
    step = Fraction(b - a, second - first)
    if step != 0 and all(v == a + step * (i - first) for i, v in known):
        return [a + step * (n - first) for n in range(len(tokens))]

    # A multiplier is only read off two ADJACENT known values: 3, _, 27 is
    # ×3 and ×-3 alike, and guessing between them would mark a child wrong.
    if second - first == 1 and a != 0:
        ratio = b / a
        if ratio not in (0, 1) and all(
                v == a * ratio ** (i - first) for i, v in known):
            return [a * ratio ** (n - first) for n in range(len(tokens))]
    return None


def read_printed_pattern(question_text):
    """The pattern *question_text* prints with gaps in it, or ``None``.

    ``None`` for anything that is not one of these questions — no sequence, no
    gap in it, or a sequence whose visible numbers share no single rule. Every
    caller treats that as "this is not mine to grade" and leaves the answer to
    the ordinary matching, so a misread here can only ever decline to help.
    """
    text = prepare(question_text or '')
    best = None
    for match in _SEQUENCE_RE.finditer(text):
        items = [item.strip() for item in match.group().split(',')]
        gaps = [bool(_BLANK_RE.fullmatch(item)) for item in items]
        if not any(gaps):
            continue
        values = _solve([None if gap else Fraction(item)
                         for item, gap in zip(items, gaps)])
        if values is None:
            continue
        operation, size = _describe(values)
        if operation is None:
            continue
        found = PrintedPattern(
            values,
            [value for value, gap in zip(values, gaps) if gap],
            operation,
            size,
        )
        # The longest sequence wins: a question that prints one is talking
        # about it, and a shorter run elsewhere in the wording is incidental.
        if best is None or len(found.values) > len(best.values):
            best = found
    return best


def _run_of(numbers, wanted):
    """The consecutive numbers of *numbers* whose values are *wanted*, or None.

    Consecutive, so a rule written among them ("45, add 15, 90, 105") is not
    quietly read as the missing numbers.
    """
    if not wanted:
        return None
    for start in range(len(numbers) - len(wanted) + 1):
        run = numbers[start:start + len(wanted)]
        if [value for value, _, _ in run] == wanted:
            return run
    return None


def completion_parts(text, pattern):
    """Which of {NUMBERS, RULE} *text* supplies for *pattern* — or ``None``.

    ``None`` means the answer is not merely incomplete but *wrong*: it states a
    rule the pattern does not follow, or carries a number that is neither one
    of the missing values nor the size of the rule. Nothing is read as a
    partial answer, because this decides a mark: an answer is either all right
    or it is not accepted here at all.
    """
    body = prepare(text or '')
    numbers = extract_numbers(body)
    parts = set()

    run = _run_of(numbers, pattern.missing) or _run_of(numbers, pattern.values)
    remainder = body
    if run:
        parts.add(NUMBERS)
        remainder = body[:run[0][1]] + ' ' + body[run[-1][2]:]

    operation, size = _stated_rule(remainder)
    # Unsigned: "-15" states a subtraction rule of 15, and the sign is already
    # carried by the operation.
    left = [abs(value) for value, _, _ in extract_numbers(remainder)]
    if operation is not None:
        if operation != pattern.operation or size != pattern.size:
            return None
        parts.add(RULE)
        if left != [pattern.size]:
            return None
    elif left:
        # A number outside the pattern with no rule word to explain it.
        return None
    return parts or None


def completes_printed_pattern(question_text, correct_answers, text_answer):
    """True when *text_answer* completes the pattern *question_text* prints.

    A rescue, run only after the ordinary answer matching has already said no,
    for the "complete the pattern … what is the rule?" questions that ask for
    two things and store one. Two conditions, both required:

      * everything in the answer is right — any numbers in it are the missing
        values (or the whole sequence), any rule it states is the pattern's;
      * it says at least as much as one stored answer does, so a question
        answered "+15" still marks the numbers alone wrong, and one answered
        "45, 90, 105" still marks the rule alone wrong.

    A stored answer this cannot read leaves the question exactly as it was.
    """
    pattern = read_printed_pattern(question_text)
    if pattern is None:
        return False
    given = completion_parts(text_answer, pattern)
    if not given:
        return False
    return any(
        wanted and wanted <= given
        for wanted in (completion_parts(stored, pattern)
                       for stored in (correct_answers or ()))
    )
