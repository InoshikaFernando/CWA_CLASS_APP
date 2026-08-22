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
    text = str(question_text)
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
        issues.append(Issue(NO_CORRECT, 'no option flagged is_correct'))
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
