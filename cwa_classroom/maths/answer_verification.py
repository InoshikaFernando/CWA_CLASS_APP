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

from maths.answer_values import find_equivalent_options, parse_answer_value

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
_PROMPT_RE = re.compile(
    r'^\s*(?:calculate|compute|evaluate|work\s+out|what\s+is)\s*[:\-]?\s*(.+?)\s*[?.]?\s*$',
    re.IGNORECASE,
)

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
    match = _PROMPT_RE.match(str(question_text))
    if not match:
        return None
    expr = match.group(1)
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


def verify_question(question, min_options=2, max_options=MAX_OPTIONS):
    """Return ``(issues, verified_arithmetically)``.

    ``issues`` is a list of :class:`Issue`. ``verified_arithmetically`` is True
    only when the question's maths was actually evaluated and checked — used to
    report honest coverage rather than implying everything was checked.
    """
    issues = []
    options = list(question.answers.all())
    correct = [a for a in options if a.is_correct]

    # ---- structural -------------------------------------------------------
    if len(options) < min_options:
        issues.append(Issue(
            TOO_FEW_OPTIONS, f'{len(options)} option(s)'))

    if max_options and len(options) > max_options:
        issues.append(Issue(
            TOO_MANY_OPTIONS,
            f'{len(options)} options — more than the {max_options} the house '
            f'style uses'))

    for option in options:
        if not (option.answer_text or '').strip():
            issues.append(Issue(BLANK_OPTION, f'A{option.id} is blank'))

    if not correct:
        issues.append(Issue(NO_CORRECT, 'no option flagged is_correct'))
        return issues, False

    if len(correct) > 1:
        issues.append(Issue(
            MULTI_CORRECT,
            f'{len(correct)} options flagged correct: '
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
    for option in options:
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

    for distractor, correct_answer in find_equivalent_options(question):
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
    seen_values = {}
    for option in options:
        if option.is_correct:
            continue
        value = parse_answer_value(option.answer_text)
        if value is None:
            continue
        twin = seen_values.get(value)
        if twin is not None:
            issues.append(Issue(
                DUPLICATE_VALUE,
                f'{option.answer_text!r} and {twin.answer_text!r} are both '
                f'{value} — the question offers fewer choices than it appears'))
        else:
            seen_values[value] = option

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
