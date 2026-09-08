"""Verify that a question's stored answers are *correct*, not merely present.

Complements ``maths.answer_values`` (which only asks whether two options denote
the same number). This module answers the harder question: **is the flagged
answer actually the right answer to the question asked?**

Two independent layers:

1. **Structural checks** — apply to every choice question regardless of subject:
   no correct option, several correct options, duplicate options, a distractor
   equal to the correct answer (the CPP-377 defect), too few options.

2. **Arithmetic check** — for questions whose text is a self-contained
   expression ("Calculate: 9/10 - 3/5"), the expression is evaluated exactly
   with ``Fraction`` and compared to the flagged answer. This catches a wrong
   answer *key*, which no amount of structural checking can find.

The arithmetic layer is deliberately narrow. It refuses anything it cannot read
unambiguously — word problems, expressions containing variables, anything with
stray letters — and reports those as UNVERIFIED rather than guessing. A silent
"looks fine" on a question nobody actually checked would be worse than no tool
at all.
"""
import re
from fractions import Fraction

from maths.answer_values import (
    find_equivalent_options, group_by_quantity, parse_answer_quantity,
    parse_answer_value)

# --------------------------------------------------------------------------
# Issue codes
# --------------------------------------------------------------------------
NO_CORRECT = 'NO-CORRECT'
MULTI_CORRECT = 'MULTI-CORRECT'
DUPLICATE_OPTION = 'DUPLICATE-OPTION'
DUPLICATE_CORRECT = 'DUPLICATE-CORRECT'
EQUIVALENT_OPTION = 'EQUIVALENT-OPTION'
DUPLICATE_VALUE = 'DUPLICATE-VALUE'
TOO_FEW_OPTIONS = 'TOO-FEW-OPTIONS'
TOO_MANY_OPTIONS = 'TOO-MANY-OPTIONS'
BLANK_OPTION = 'BLANK-OPTION'
WRONG_ANSWER_KEY = 'WRONG-ANSWER-KEY'

# Typed-answer codes (CPP-378). Both describe authoring that only a human can
# resolve — the grader cannot tell from the stored text what the question means.
UNMARKED_SET = 'UNMARKED-SET'
FRAGMENT_ROW = 'FRAGMENT-ROW'


class Issue:
    """One problem found on one question."""

    def __init__(self, code, detail):
        self.code = code
        self.detail = detail

    def __repr__(self):
        return f'Issue({self.code}, {self.detail!r})'

    def __eq__(self, other):
        return (isinstance(other, Issue)
                and (self.code, self.detail) == (other.code, other.detail))


# --------------------------------------------------------------------------
# Arithmetic evaluation
# --------------------------------------------------------------------------
# Only question text of this shape is evaluated. Anything else is UNVERIFIED.
# The separator after the instruction word is ':' ONLY. It used to allow '-'
# as well, which silently ate the minus sign off a negative first term: "What
# is -7 + 12?" was evaluated as "7 + 12" = 19 and every correct integer answer
# in Year 8 Number › Integers was reported as a wrong answer key. A dash there
# is far more likely to BE the number than to separate anything.
_PROMPT_RE = re.compile(
    r'^\s*(?:calculate|compute|evaluate|work\s+out|what\s+is)\s*:?\s*(.+?)\s*[?.]?\s*$',
    re.IGNORECASE,
)

# The other shape arithmetic questions come in: a bare equation ending in a
# placeholder. "5531 - 4414 = ?" carries no instruction word, so it was never
# evaluated — which is why a question with no stored answer at all could not be
# repaired automatically. The letter guard in extract_expression still rejects
# algebra ("3x + 2 = ?") and multi-part answers ("C = 8, D = 3").
_EQUATION_RE = re.compile(r'^\s*(.+?)\s*=\s*[?_\s]*$')

_TOKEN_RE = re.compile(r'''
      (?P<mixed>\d+\s+\d+\s*/\s*\d+)      # 2 3/5
    | (?P<frac>\d+\s*/\s*\d+)             # 3/10
    | (?P<dec>\d+\.\d+)                   # 0.75
    | (?P<int>\d+)                        # 7
    | (?P<op>[+\-*/x×✕✖·÷])               # operators (x only as multiply)
    | (?P<lpar>\()
    | (?P<rpar>\))
    | (?P<space>\s+)
''', re.VERBOSE | re.IGNORECASE)


class _ParseError(Exception):
    pass


def extract_expression(question_text):
    """Return the arithmetic expression in ``question_text``, or ``None``.

    Refuses anything containing letters other than a times-'x', so word
    problems and algebra fall through to UNVERIFIED instead of being
    mis-evaluated.
    """
    if not question_text:
        return None
    # A stem written with a typographic minus ("12 \u2013 5 = ?") would fail the
    # tokeniser's operator class and fall through as UNVERIFIED (CPP-407).
    from maths.algebra_grading import fold_dashes
    text = fold_dashes(str(question_text))
    match = _PROMPT_RE.match(text) or _EQUATION_RE.match(text)
    if not match:
        return None
    expr = match.group(1)
    if '=' in expr:
        # More than one equals sign means more than one statement.
        return None
    # Any letter disqualifies the expression, EXCEPT a whitespace-delimited 'x'
    # used as a times sign ("4/5 x 1/3"). The whitespace requirement is what
    # separates that from an algebraic term: in "3x + 2" the 'x' touches the
    # digit, so the expression is algebra and must not be evaluated as
    # arithmetic — without this guard it parsed as 3 * (+2) = 6 and would
    # report a correct algebra key as wrong.
    for letter in re.finditer(r'[A-Za-z]', expr):
        index = letter.start()
        delimited_times_x = (
            letter.group().lower() == 'x'
            and index > 0 and expr[index - 1].isspace()
            and index < len(expr) - 1 and expr[index + 1].isspace()
        )
        if not delimited_times_x:
            return None
    return expr


def _tokenize(expr):
    tokens, pos = [], 0
    while pos < len(expr):
        match = _TOKEN_RE.match(expr, pos)
        if not match:
            raise _ParseError(f'unreadable character at {pos}: {expr[pos]!r}')
        pos = match.end()
        kind = match.lastgroup
        text = match.group()
        if kind == 'space':
            continue
        if kind == 'mixed':
            whole, frac = text.split(None, 1)
            num, den = frac.split('/')
            if int(den) == 0:
                raise _ParseError('division by zero')
            tokens.append(('num', Fraction(int(whole)) + Fraction(int(num), int(den))))
        elif kind == 'frac':
            num, den = text.split('/')
            if int(den) == 0:
                raise _ParseError('division by zero')
            tokens.append(('num', Fraction(int(num), int(den))))
        elif kind in ('dec', 'int'):
            tokens.append(('num', Fraction(text)))
        elif kind == 'op':
            canonical = {'x': '*', '×': '*', '✕': '*', '✖': '*', '·': '*',
                         '÷': '/'}.get(text.lower(), text)
            tokens.append(('op', canonical))
        elif kind == 'lpar':
            tokens.append(('lpar', '('))
        elif kind == 'rpar':
            tokens.append(('rpar', ')'))
    return tokens


class _Parser:
    """Recursive descent over the token list. No eval(), no exec()."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def expression(self):
        value = self.term()
        while True:
            kind, text = self.peek()
            if kind == 'op' and text in '+-':
                self.pos += 1
                right = self.term()
                value = value + right if text == '+' else value - right
            else:
                return value

    def term(self):
        value = self.factor()
        while True:
            kind, text = self.peek()
            if kind == 'op' and text in '*/':
                self.pos += 1
                right = self.factor()
                if text == '/':
                    if right == 0:
                        raise _ParseError('division by zero')
                    value = value / right
                else:
                    value = value * right
            else:
                return value

    def factor(self):
        kind, text = self.peek()
        if kind == 'op' and text == '-':
            self.pos += 1
            return -self.factor()
        if kind == 'op' and text == '+':
            self.pos += 1
            return self.factor()
        if kind == 'lpar':
            self.pos += 1
            value = self.expression()
            if self.peek()[0] != 'rpar':
                raise _ParseError('unbalanced parentheses')
            self.pos += 1
            return value
        if kind == 'num':
            self.pos += 1
            return text
        raise _ParseError(f'unexpected token: {text!r}')


def evaluate_expression(expr):
    """Exactly evaluate a fraction arithmetic expression, or return ``None``.

    ``None`` means "could not be read with certainty" — never "wrong".

    >>> evaluate_expression('9/10 - 3/5')
    Fraction(3, 10)
    >>> evaluate_expression('(-3/5) x (-2/3)')
    Fraction(2, 5)
    """
    if not expr:
        return None
    try:
        tokens = _tokenize(expr)
        if not tokens:
            return None
        parser = _Parser(tokens)
        value = parser.expression()
        if parser.pos != len(tokens):      # trailing junk — do not trust it
            return None
        return value
    except (_ParseError, ValueError, ZeroDivisionError):
        return None


# --------------------------------------------------------------------------
# Whole-question verification
# --------------------------------------------------------------------------
# House style is four options. More is not a grading fault — nobody is
# mismarked by a fifth choice — but it is worth surfacing so a super-admin can
# trim it, which is why the check reports it as advisory rather than blocking.
MAX_OPTIONS = 4

# Types where the Answer rows are OPTIONS the student picks between. Everywhere
# else — short_answer, calculation, fill_blank — the rows are the accepted
# answers for typed input, so one row is normal and several are legitimate
# alternative spellings. Applying the choice rules to those reported a
# perfectly good short-answer question as "too few options", which made a
# correct repair look like it had not worked.
CHOICE_TYPES = ('multiple_choice', 'true_false')

# Types whose answer is judged by a person or a rubric rather than matched
# against a stored row. An extended answer ("Show your working and explain your
# chosen strategy") HAS no single correct answer to store — that is the point of
# it — so reporting "no option flagged is_correct" was calling the format itself
# a defect, on questions that were working exactly as designed.
GRADED_TYPES = ('extended_answer',)

# answer_format of a question whose answer the student invents (Question.
# ANSWER_FORMAT_PATTERN — spelled out here to keep this module import-free of
# the models).
PATTERN_FORMAT = 'pattern'


# Types whose correct answer lives on the QUESTION itself rather than in Answer
# rows: a spec the grader compares against (number_line_spec, table_spec,
# plane_spec, grid_spec, shape_spec, blank_spec), a numeric field graded within a
# tolerance (numeric_answer), or the numbers the grader works the answer out from
# (dividend/divisor, target_number, operands/operator). ``Question.clean()``
# REFUSES answer options on most of them — "Number-line questions are graded by
# the marked/typed values and must not have answer options" — so reporting "no
# option flagged is_correct" called a working format a defect, and every fix the
# check page then offered (fill in the answer, use the option I ticked) would have
# been rejected by the model on save.
#
# The exemption is CONDITIONAL on the question actually carrying the thing it is
# graded against, because the graders all fall back to matching Answer rows when
# it is missing (maths.plugin.grade_answer). A number_line with no
# number_line_spec and no rows marks every student wrong, so it is still
# reported — with a detail that names what is missing rather than pointing at
# options the type is not allowed to have.
#
# Each entry is (question_type -> the attribute(s) that must be set). Values are
# spelled out as strings, not imported from maths.models, to keep this module
# import-free of the models like the constants above.
SELF_GRADED_ANSWER_FIELDS = {
    'measure': ('numeric_answer',),
    'read_graph': ('numeric_answer',),
    'draw_on_grid': ('grid_spec',),
    'shape_select': ('shape_spec',),
    'plot_points': ('plane_spec',),
    'plot_line': ('plane_spec',),
    'identify_coords': ('plane_spec',),
    'number_line': ('number_line_spec',),
    'table_of_values': ('table_spec',),
    'sketch_graph': ('sketch_spec',),
    'long_division': ('dividend', 'divisor'),
    'prime_factorization': ('target_number',),
    # ``column_result`` is the computed answer (None unless operands AND a
    # readable operator are both set), which is exactly what the grader checks.
    'column_operation': ('column_result',),
    # A fill_blank is only self-graded once it HAS a blank_spec; without one it
    # is the legacy single-box shape, still graded against its Answer rows.
    'fill_blank': ('blank_spec',),
}


# Fields where zero is a real answer, so "is it set?" means "is it not None?":
# a numeric_answer of 0 ("the arrow points at 0"), a column sum of 0 (5 - 5), a
# dividend of 0. Everywhere else — a divisor, a number to factorise, any spec —
# an empty or zero value is one the grader cannot use, and maths.plugin falls
# back to the Answer rows exactly as it does when the field is absent, so the
# question is checked as an ordinary one rather than exempted.
_ZERO_IS_AN_ANSWER = {'numeric_answer', 'column_result', 'dividend'}


def _self_graded_answer(question):
    """What grades this question instead of its Answer rows, or ``None``.

    Returns the name of the field carrying the answer when the question is a
    self-graded type AND that field is set — the signal that there is nothing
    here for the option checks to find fault with. Returns ``None`` both for the
    ordinary types and for a self-graded question whose field is missing, which
    is a real fault and must still be reported.
    """
    fields = SELF_GRADED_ANSWER_FIELDS.get(question.question_type)
    if not fields:
        return None
    for field in fields:
        value = getattr(question, field, None)
        if value is None:
            return None
        if not value and field not in _ZERO_IS_AN_ANSWER:
            return None
    return fields[0]


def _no_correct_detail(question):
    """Why this question has no stored correct answer, in the reader's terms.

    A self-graded type reaching this point is missing the spec or field it is
    graded by, and saying "no option flagged is_correct" about a question that
    is not ALLOWED to have options sends the reader to the wrong place.
    """
    fields = SELF_GRADED_ANSWER_FIELDS.get(question.question_type)
    if fields:
        return (f'{question.question_type} question with no '
                f'{" / ".join(fields)} and no answer row — nothing to grade '
                f'the answer against')
    return 'no option flagged is_correct'


def _is_graded_by_a_person(question):
    """Is this question's answer judged rather than matched?

    Both signals count. The TYPE is the strong one — an extended answer is
    written prose whatever else is set — and validation_type catches a question
    of any type explicitly marked for AI or human grading.
    """
    if question.question_type in GRADED_TYPES:
        return True
    return bool(getattr(question, 'needs_grading', False))


def verify_question(question, min_options=2, max_options=MAX_OPTIONS):
    """Return ``(issues, verified_arithmetically)``.

    ``issues`` is a list of :class:`Issue`. ``verified_arithmetically`` is True
    only when the question's maths was actually evaluated and checked — used to
    report honest coverage rather than implying everything was checked.
    """
    issues = []

    # A question a person or a rubric judges has nothing here to check: no
    # stored answer to compare, no options to count, and blank rows are the
    # editor's normal state rather than a fault. Returning early says that
    # plainly instead of reporting the format as broken.
    if _is_graded_by_a_person(question):
        return issues, False

    # Same for a "create your own number pattern" question: the student invents
    # the answer, so it is graded against the question's requirements
    # (maths.pattern_grading) and having no stored answer is its healthy state,
    # not the NO-CORRECT defect below.
    if getattr(question, 'answer_format', '') == PATTERN_FORMAT:
        return issues, False

    # And for a question graded against its own spec or numeric field — a
    # number line, a table of values, a plotted point, a measured angle. The
    # answer is stored on the question, the model forbids answer options
    # outright, and every check below is about options: running them reported
    # the whole interactive-question family as "no correct option" when nothing
    # was wrong with any of it.
    if _self_graded_answer(question):
        return issues, False

    options = list(question.answers.all())
    correct = [a for a in options if a.is_correct]
    is_choice = question.question_type in CHOICE_TYPES

    # ---- structural -------------------------------------------------------
    # Option-count rules apply only where the rows really are choices.
    if is_choice and len(options) < min_options:
        issues.append(Issue(
            TOO_FEW_OPTIONS, f'{len(options)} option(s)'))

    if is_choice and max_options and len(options) > max_options:
        issues.append(Issue(
            TOO_MANY_OPTIONS,
            f'{len(options)} options — the house rule is one correct answer '
            f'and at most {max_options - 1} wrong ones'))

    for option in options:
        if not (option.answer_text or '').strip():
            issues.append(Issue(BLANK_OPTION, f'A{option.id} is blank'))

    if not correct:
        issues.append(Issue(NO_CORRECT, _no_correct_detail(question)))
        return issues, False

    # Single-select grading accepts ANY option flagged correct
    # (quiz/views.py: `is_correct = bool(answer and answer.is_correct)`), so a
    # second flag does not mismark the student who picks it — it marks a WRONG
    # answer right. That is the mirror image of CPP-377 and just as damaging:
    # 'Square' and '6' both accepted for "What is the name of this shape?".
    if is_choice and len(correct) > 1:
        issues.append(Issue(
            MULTI_CORRECT,
            f'{len(correct)} options flagged correct — all of them are '
            f'accepted, so a wrong answer is marked right: '
            f'{[a.answer_text for a in correct]}'))

    # Repeated option text splits into two very different faults, and lumping
    # them together made the dashboard's "can mismark a student" count roughly
    # ten times the real figure — a backlog that size gets ignored.
    #
    #   DUPLICATE-CORRECT  the repeated text IS the correct answer, and at
    #                      least one copy is not flagged correct. A student who
    #                      picks the identical-looking option is marked wrong.
    #                      This is the CPP-377 defect exactly.
    #
    #   DUPLICATE-OPTION   a wrong option repeated. The question offers fewer
    #                      real choices than it appears to and reads sloppily,
    #                      but nobody is ever mismarked for it — advisory.
    groups = {}
    for option in (options if is_choice else []):
        key = (option.answer_text or '').strip().lower()
        if key:
            groups.setdefault(key, []).append(option)

    for key, group in groups.items():
        if len(group) < 2:
            continue
        text = group[0].answer_text
        correct_copies = [option for option in group if option.is_correct]
        if correct_copies and len(correct_copies) < len(group):
            issues.append(Issue(
                DUPLICATE_CORRECT,
                f'{text!r} is the correct answer but also appears as a '
                f'distractor — picking that copy is marked wrong'))
        else:
            issues.append(Issue(
                DUPLICATE_OPTION, f'{text!r} appears twice'))

    for distractor, correct_answer in (find_equivalent_options(question)
                                       if is_choice else []):
        issues.append(Issue(
            EQUIVALENT_OPTION,
            f'distractor {distractor.answer_text!r} == '
            f'correct {correct_answer.answer_text!r}'))

    # Two *distractors* worth the same number, e.g. '1/2' alongside '3/6'.
    # Nobody is mismarked — both are wrong — so this is not the CPP-377 defect,
    # and neither of the checks above sees it: EQUIVALENT-OPTION compares only
    # against the correct answer, and DUPLICATE-OPTION compares text. But the
    # question then offers fewer real choices than it appears to, and showing a
    # student the same number twice is confusing. Worth reporting, distinctly.
    # Quantity, not bare value — '4 g' and '4 kg' are different masses, and an
    # estimation question ("the mass of a pet cat") offers them deliberately.
    distractors = [o for o in options if not o.is_correct]
    for group in group_by_quantity(
            distractors, lambda o: parse_answer_quantity(o.answer_text)):
        if len(group) < 2:
            continue
        first, second = group[0], group[1]
        value = parse_answer_value(first.answer_text)
        issues.append(Issue(
            DUPLICATE_VALUE,
            f'{second.answer_text!r} and {first.answer_text!r} are both '
            f'{value} — the question offers fewer choices than it appears'))

    # ---- arithmetic -------------------------------------------------------
    expression = extract_expression(question.question_text)
    if expression is None:
        return issues, False

    expected = evaluate_expression(expression)
    if expected is None:
        return issues, False

    stored = parse_answer_value(correct[0].answer_text)
    if stored is None:
        return issues, False

    if stored != expected:
        issues.append(Issue(
            WRONG_ANSWER_KEY,
            f'{expression.strip()} = {expected} but the flagged answer is '
            f'{correct[0].answer_text!r} ({stored})'))

    return issues, True


# --------------------------------------------------------------------------
# Typed answers
# --------------------------------------------------------------------------
# Wording that asks for a *collection*: which values are given matters, the
# order they are given in does not.
_COLLECTION_RE = re.compile(
    r'\ball (?:the )?(?:factors|multiples|prime factors|pairs|'
    r'possible outcomes|outcomes)\b'
    r'|\b(?:factors|multiples|prime factors) of\b'
    r'|\blist (?:all|every|some)\b'
    r'|\bfind all\b'
    r'|\bname all\b',
    re.IGNORECASE)

# Wording that makes the order part of the answer. Checked first, because
# "arrange the factors in ascending order" is an ordered question that happens
# to mention factors.
_ORDERED_RE = re.compile(
    r'\b(?:order|ascending|descending|smallest|largest|arrange|sequence|'
    r'next|missing|consecutive|before|after|first|then)\b',
    re.IGNORECASE)


def verify_typed_answer_question(question):
    """Return the issues on a *typed*-answer question (short answer etc.).

    ``verify_question`` covers the choice types. Typed answers were never
    audited at all, which is how 559 questions came to accept one value of a
    list as a whole correct answer (CPP-378).

    Both checks here are deliberately the ones **code cannot fix for itself** —
    each needs a person to say what the question means:

    UNMARKED-SET   the question asks for a collection ("find all the factors of
                   360") but the answer is stored as ordinary text, so it grades
                   order-sensitively: a student who lists every correct value in
                   a different order is marked wrong. Only a human can tell this
                   apart from "arrange these in ascending order", where the order
                   *is* the answer. Fix: set answer_format='set'.

    FRAGMENT-ROW   one correct row holds a single value that is also one value of
                   another correct row's list ("3, 5, 7, 9" alongside a bare
                   "9"), so that fragment alone grades as the whole answer. Only
                   a human knows whether the extra row was deliberate.
                   Fix: delete the row, or split the list into one row per
                   accepted alternative.
    """
    from maths.models import Question, _split_answer_list

    issues = []
    if question.question_type in CHOICE_TYPES or _is_graded_by_a_person(question):
        return issues
    if question.answer_format != Question.ANSWER_FORMAT_TEXT:
        return issues

    correct = [
        (a.answer_text or '').strip()
        for a in question.answers.all()
        if a.is_correct and (a.answer_text or '').strip()
    ]
    if not correct:
        return issues

    values_by_row = [_split_answer_list(text) for text in correct]
    text = question.question_text or ''

    # ---- UNMARKED-SET -----------------------------------------------------
    if (any(len(values) > 1 for values in values_by_row)
            and _COLLECTION_RE.search(text)
            and not _ORDERED_RE.search(text)):
        longest = max(values_by_row, key=len)
        issues.append(Issue(
            UNMARKED_SET,
            f'asks for a collection but grades in order — a student who lists '
            f'the {len(longest)} values in another order is marked wrong; '
            f"set answer_format='set' if the order does not matter"))

    # ---- FRAGMENT-ROW -----------------------------------------------------
    for i, text_i in enumerate(correct):
        if len(values_by_row[i]) != 1:
            continue
        for j, values_j in enumerate(values_by_row):
            if i == j or len(values_j) < 2:
                continue
            if text_i in values_j:
                issues.append(Issue(
                    FRAGMENT_ROW,
                    f'{text_i!r} is also one value of {correct[j]!r}, so that '
                    f'fragment alone grades as the whole answer'))
                break

    return issues


# --------------------------------------------------------------------------
# Missing figures
# --------------------------------------------------------------------------
# A question can be perfectly well-formed — right answer, right options — and
# still be impossible to answer, because the picture it talks about never
# reaches the page. CPP-406 is the report: a student met "Measure X" with no
# figure above it and asked, reasonably, how they were supposed to know what X
# was. Nothing in the bank was looking for that.
#
# ``ai_import`` has flagged this at IMPORT time since the PDF pipeline learned
# to crop figures, but a question authored by hand, edited afterwards, or
# imported before that check existed was never looked at again. These constants
# live here so the import-time check and the bank-wide audit read the same
# wording and cannot drift apart; ``ai_import.verification`` imports them.

MISSING_FIGURE = 'MISSING-FIGURE'

# Deictic references to a concrete visual the question is meant to read off —
# "this shape", "the diagram", "the graph below", "shown opposite". A question
# whose text points at a figure like this but carries NO figure cannot be
# answered as it stands. Indefinite descriptions ("a rectangle with perimeter
# 20cm") are deliberately excluded — those are spelled out in the text and point
# at no picture, so requiring a definite/deictic marker in front of the visual
# noun keeps the false-positive rate down.
FIGURE_REFERENCE_RE = re.compile(
    r'\b(?:'
    r'(?:this|these|the)\s+'
    r'(?:shape|shapes|diagram|figure|pattern|net|graph|grid|'
    r'number\s+line|clock(?:\s+face)?|picture|image|table|chart|'
    r'arrangement|tiles?|solid)'
    r'|shown\s+(?:below|above|opposite|here|in|on)'
    r'|as\s+shown'
    r')\b',
    re.IGNORECASE,
)

# One- and two-letter words that are English, not labels. Without them
# "measure a line" and "the length of it" would read as labelled parts.
_NOT_A_LABEL = (r'(?:a|an|as|at|be|by|do|go|he|if|in|is|it|its|me|my|no|of|on|'
                r'or|so|the|to|up|us|we)')

# A bare letter used as a NAME — "Measure X", "measure AB". Outside a figure
# such a label denotes nothing at all, which is the CPP-406 wording exactly.
# Restricted to the measuring verbs and to a 1-2 character label, because a
# capital letter loose in a sentence is far more often algebra ("T = 5") or a
# multiple-choice marker than a point on a drawing.
LABEL_REFERENCE_RE = re.compile(
    r'\b(?:measure|estimate)\s+(?!' + _NOT_A_LABEL + r'\b)[A-Za-z]{1,2}\b',
    re.IGNORECASE,
)

# "pattern" is the one noun in FIGURE_REFERENCE_RE that a question routinely
# points at while printing the thing itself: "Look at the pattern 0, 2, 4, 6, 8"
# and "complete the pattern: 65, __, 75" need no picture — the sequence IS on
# the page. Left unhandled that single word produced most of the audit's 166
# MISSING-FIGURE flags, nearly all of Year 1-4 Number Patterns and Skip
# Counting, which is how a blocking check becomes noise nobody reads.
#
# A sequence counts as printed when three or more comma-separated terms appear
# in the stem — numbers, single letters, blanks, an ellipsis — and at least one
# of them is a number or a blank. That last requirement is what keeps "Which of
# these shapes is a kite? A, B, C, D" flagged: a run of bare letters is an
# option list, not a sequence.
_SEQUENCE_TERM = r'(?:-?\d+(?:\.\d+)?|[A-Za-z]|_+|\.{3}|…)'
INLINE_SEQUENCE_RE = re.compile(
    rf'{_SEQUENCE_TERM}(?:\s*,\s*{_SEQUENCE_TERM}){{2,}}')
_SEQUENCE_HAS_A_TERM_RE = re.compile(r'[\d_]')
PATTERN_NOUN_RE = re.compile(r'\bpattern\b', re.IGNORECASE)


def shows_its_own_sequence(text):
    """True when the stem prints a sequence rather than pointing at one."""
    return any(_SEQUENCE_HAS_A_TERM_RE.search(match.group(0))
               for match in INLINE_SEQUENCE_RE.finditer(text or ''))


# Types whose "grid" / "bracket" visual is scaffolding transcribed into the
# structured fields (never attached as a figure), so a figure reference in their
# text is not a missing image.
FIGURE_OPTIONAL_TYPES = {'long_division', 'column_operation'}

# Types whose ANSWER is read off — or drawn on — a figure. There is no wording
# to sniff here: a measure question with nothing to measure and a read-a-graph
# question with no graph are unanswerable whatever their stem says.
FIGURE_DEPENDENT_TYPES = {
    'measure', 'read_graph', 'draw_on_grid', 'shape_select',
    'plot_points', 'plot_line', 'identify_coords', 'number_line',
}


def verify_question_figure(question):
    """Return the issues on a question whose figure never reaches the student.

    Separate from ``verify_question`` because it applies to EVERY type — a
    multiple-choice question that says "which of these shapes…" is as broken
    without its picture as a measure question is. Returns a list of
    :class:`Issue`, empty when the question needs no figure or already has one.

    Two ways a question earns MISSING-FIGURE, both requiring that nothing at all
    renders (``Question.renders_a_figure``):

    TYPE     the question type reads its answer off a figure — ``measure``,
             ``read_graph``, ``identify_coords`` … — and there is none. The
             CPP-406 case: a length/mass ``measure`` question generates no
             figure (only angles are drawable true-to-scale), so without an
             uploaded image the student is shown a ruler and empty space.

    WORDING  the stem points at a figure ("this shape", "the diagram below",
             "measure X") that was never attached — typically a PDF import
             whose crop was skipped. Except where the stem prints the thing
             itself: "the pattern 0, 2, 4, 6, 8" points at nothing absent (see
             ``shows_its_own_sequence``).

    Blocking, not advisory: a question nobody can answer costs the student the
    mark just as surely as a wrong answer key does.
    """
    issues = []

    # Scaffolding-visual types transcribe their "grid" into structured fields,
    # so a figure word in their text is not a missing picture.
    if question.question_type in FIGURE_OPTIONAL_TYPES:
        return issues

    # A self-graded type with its spec missing is already reported as
    # NO-CORRECT, with a detail naming the very field that is absent. Adding
    # "and it draws no figure" points at the same single fix twice.
    if (question.question_type in SELF_GRADED_ANSWER_FIELDS
            and not _self_graded_answer(question)):
        return issues

    # ``renders_a_figure`` asks each spec-backed type to build its figure, and
    # a spec that arrived by bulk import never went through ``clean()``. One
    # unrenderable row must not take down a walk of the whole bank — and it is
    # a finding in its own right, because nothing reaches the student either
    # way. Report it, naming the cause, rather than crash or skip.
    try:
        has_figure = question.renders_a_figure
    except Exception as exc:                       # noqa: BLE001 — see above
        issues.append(Issue(
            MISSING_FIGURE,
            f'the figure this question draws itself from cannot be built, so '
            f'nothing renders: {type(exc).__name__}: {exc}'))
        return issues

    if has_figure:
        return issues

    if question.question_type in FIGURE_DEPENDENT_TYPES:
        issues.append(Issue(
            MISSING_FIGURE,
            f'a {question.question_type} question with no figure — its answer '
            f'is read off a picture, and neither an uploaded image nor a '
            f'generated one reaches the student'))
        return issues

    text = question.question_text or ''
    references = [m.group(0) for m in FIGURE_REFERENCE_RE.finditer(text)]
    if shows_its_own_sequence(text):
        # ...but only the sequence reference is answered by that. "the pattern
        # shown below" still points at a picture, and so does a second noun.
        references = [r for r in references if not PATTERN_NOUN_RE.search(r)]
    if references or LABEL_REFERENCE_RE.search(text):
        issues.append(Issue(
            MISSING_FIGURE,
            'the question points at a figure ("this shape" / "the diagram" / '
            'a labelled part) but no image is attached — the student is asked '
            'to read something that is not on the page'))
    return issues
