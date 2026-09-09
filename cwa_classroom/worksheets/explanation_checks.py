"""Deterministic checks that an extracted question's explanation agrees with itself.

The classifier writes an answer and an explanation. When it miscounts or slips
on arithmetic, the explanation usually betrays it — in its own words:

* **A count that disagrees with the list it wrote.** "There are 15 values in
  order: 14, 17, 18, 20, 22, 24, 25, 27, 28, 28, 29, 30, 33, 37" — fourteen
  numbers. The answer (a median taken as the 8th of 15) was wrong.
* **An ordinal that disagrees with the list.** "… the 8th value is 25" when the
  8th number it listed is 27.
* **Arithmetic that doesn't add up.** "10 + 5 + 2 = 18"; "3 + 8 + 4 = 15" is
  fine (the slip there was counting 4 leaves where there were 3, which the
  first check catches once the leaves are listed).

None of this needs a model, an image or a second opinion: it is the text
contradicting itself. A question that trips any check is routed to review with
the contradiction spelled out, so the teacher sees exactly what to re-check
instead of a wrong answer going into the bank looking confident. The checks
are deliberately conservative — they only fire on a contradiction *inside* the
explanation, never on a judgement about the maths — so a clean explanation is
never flagged.
"""
import re
from fractions import Fraction

# A number as it appears in prose: optional sign, thousands commas, decimals.
_NUM = r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?'

# A written-out list of at least three numbers: "14, 17, 18, 20" / "4, 7 and 8".
# A trailing unit glued to a number ("25°C", "3cm") is tolerated.
_LIST_RE = re.compile(
    r'(?<![\d.])((?:(?:' + _NUM + r')(?:\s?°?[A-Za-z%]{0,3})?\s*(?:,|;|\band\b)\s*){2,}'
    r'(?:' + _NUM + r')(?:\s?°?[A-Za-z%]{0,3})?)(?!\d|\.\d)'
)

# The nouns a count is a count OF. Deliberately concrete so "15 minutes" or
# "8 marks" never read as a claim about how many items were listed.
_COUNT_NOUN = (
    r'(?:values?|numbers?|leaves|leafs|items?|scores?|data\s+points?|entries|'
    r'observations?|results?|readings?|temperatures?|measurements?|'
    r'terms?|elements?|outcomes?|marks|dots?|tallies|tally\s+marks?|'
    r'towns?|students?|people|children|pupils|players|cars|coins|dice)'
)

# "There are 15 values in order: 14, 17, …" — the count precedes the list.
# The stretch between the noun and the colon may not cross a clause boundary
# ("(3 leaves); stem 2: 0, 2, 4" must not read as "3 leaves: 0, 2, 4").
_COUNT_THEN_LIST_RE = re.compile(
    r'\b(\d+)\s+' + _COUNT_NOUN + r'\b[^.:;()\n]{0,60}?:\s*(?=' + _NUM + r')',
    re.IGNORECASE,
)
# "stem 3: 0, 3, 7 → 3 leaves" / "4, 7, 8 (3 values)" — the count follows the list.
_LIST_THEN_COUNT_RE = re.compile(
    r'(?:→|->|=>|=|:|,|;|\(|\bso\b|\bgives?\b|\bgiving\b|\bthat\s+is\b|\bi\.e\.|'
    r'\bwhich\s+is\b|\bmaking\b|\bmakes\b|\btotal(?:ling)?\b|\bfor\b)?\s*'
    r'(?:a\s+total\s+of\s+)?(\d+)\s+' + _COUNT_NOUN + r'\b',
    re.IGNORECASE,
)

# "the 8th value is 25" / "the 7th and 8th values are 25 and 27".
_ORDINAL_RE = re.compile(
    r'\b(\d+)(?:st|nd|rd|th)\s+(?:value|number|term|score|item|entry|reading|'
    r'observation|data\s+point)\b[^.\n]{0,50}?\b(?:is|=|equals|was|being)\s+(' + _NUM + r')',
    re.IGNORECASE,
)

# "a + b + c = d" with + − × ÷ only, numbers only (no variables, powers, roots
# or percentages — those need context this check does not have).
_OPS = r'[+\-−–×x\*÷/]'
_ARITH_RE = re.compile(
    r'(?<![\w.^%])((?:' + _NUM + r')(?:\s*' + _OPS + r'\s*(?:' + _NUM + r'))+)'
    r'\s*=\s*(' + _NUM + r')(?!\d|\.\d|[\^%]|\s*[+\-−–×x\*÷/]\s*\d)',
)

_OP_MAP = {'+': '+', '-': '-', '−': '-', '–': '-', '×': '*', 'x': '*', '*': '*',
           '÷': '/', '/': '/'}


def _to_number(text):
    try:
        return Fraction(text.replace(',', ''))
    except (ValueError, ZeroDivisionError):
        return None


def _numbers_in(list_text):
    """The numbers of a written-out list, units stripped, as Fractions."""
    out = []
    for tok in re.split(r'\s*(?:,|;|\band\b)\s*', list_text):
        m = re.match(r'\s*(' + _NUM + r')', tok)
        if m:
            value = _to_number(m.group(1))
            if value is not None:
                out.append(value)
    return out


def _evaluate(expr):
    """Left-to-right evaluation honouring × ÷ before + −. None if unparseable."""
    tokens = re.findall(_NUM + r'|' + _OPS, expr)
    if not tokens:
        return None
    values, ops = [], []
    expect_number = True
    for tok in tokens:
        if expect_number:
            num = _to_number(tok)
            if num is None:
                return None
            values.append(num)
            expect_number = False
        else:
            op = _OP_MAP.get(tok)
            if op is None:
                return None
            ops.append(op)
            expect_number = True
    if expect_number or len(values) != len(ops) + 1:
        return None
    # Pass 1: × and ÷.
    vals, os_ = [values[0]], []
    for op, val in zip(ops, values[1:]):
        if op == '*':
            vals[-1] = vals[-1] * val
        elif op == '/':
            if val == 0:
                return None
            vals[-1] = vals[-1] / val
        else:
            os_.append(op)
            vals.append(val)
    total = vals[0]
    for op, val in zip(os_, vals[1:]):
        total = total + val if op == '+' else total - val
    return total


def _fmt(value):
    if value.denominator == 1:
        return str(value.numerator)
    return str(round(float(value), 4)).rstrip('0').rstrip('.')


def _stated_matches(actual, stated_text):
    """Does the stated result equal the computed one, allowing for the number of
    decimals the author chose to write (10 ÷ 3 = 3.33 is a rounding, not a slip)?"""
    stated = _to_number(stated_text)
    if stated is None:
        return True
    decimals = len(stated_text.split('.')[1]) if '.' in stated_text else 0
    tolerance = Fraction(1, 2) / (10 ** decimals) if decimals else Fraction(0)
    return abs(actual - stated) <= tolerance


def arithmetic_slips(text):
    """Equations in ``text`` whose stated result is not what the parts make.

    Returns ``[(expression, stated, actual), ...]`` as display strings.
    """
    slips = []
    for m in _ARITH_RE.finditer(text or ''):
        expr, stated = m.group(1), m.group(2)
        actual = _evaluate(expr)
        if actual is None:
            continue
        if not _stated_matches(actual, stated):
            slips.append((re.sub(r'\s+', ' ', expr).strip(), stated, _fmt(actual)))
    return slips


def count_slips(text):
    """Counts that disagree with the list they describe.

    Returns ``[(stated_count, listed_count, list_preview), ...]``.
    """
    text = text or ''
    slips = []
    seen = set()
    lists = [(m.start(), m.end(), _numbers_in(m.group(1))) for m in _LIST_RE.finditer(text)]
    lists = [(s, e, nums) for s, e, nums in lists if len(nums) >= 3]

    for m in _COUNT_THEN_LIST_RE.finditer(text):
        stated = int(m.group(1))
        # The list must start right where the colon ends.
        for s, e, nums in lists:
            if abs(s - m.end()) <= 1:
                if stated != len(nums) and (s, stated) not in seen:
                    seen.add((s, stated))
                    slips.append((stated, len(nums), _preview(nums)))
                break

    for s, e, nums in lists:
        tail = text[e:e + 40]
        m = _LIST_THEN_COUNT_RE.match(tail)
        if not m:
            continue
        stated = int(m.group(1))
        if stated != len(nums) and (s, stated) not in seen:
            seen.add((s, stated))
            slips.append((stated, len(nums), _preview(nums)))
    return slips


def ordinal_slips(text):
    """"The Nth value is X" claims that disagree with the list written before them.

    Returns ``[(ordinal, claimed, listed), ...]`` as display strings.
    """
    text = text or ''
    slips = []
    lists = [(m.start(), m.end(), _numbers_in(m.group(1))) for m in _LIST_RE.finditer(text)]
    lists = [(s, e, nums) for s, e, nums in lists if len(nums) >= 3]
    if not lists:
        return slips
    for m in _ORDINAL_RE.finditer(text):
        n = int(m.group(1))
        claimed = _to_number(m.group(2))
        if claimed is None:
            continue
        before = [entry for entry in lists if entry[1] <= m.start()]
        if not before:
            continue
        nums = before[-1][2]
        if 1 <= n <= len(nums) and nums[n - 1] != claimed:
            slips.append((f'{n}{_suffix(n)}', m.group(2), _fmt(nums[n - 1])))
    return slips


def _suffix(n):
    if 10 <= n % 100 <= 20:
        return 'th'
    return {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')


def _preview(nums, limit=6):
    shown = ', '.join(_fmt(v) for v in nums[:limit])
    return shown + (', …' if len(nums) > limit else '')


def explanation_problems(q):
    """Every self-contradiction in one question's explanation, as reasons for
    the teacher. Empty when the explanation agrees with itself."""
    explanation = (q or {}).get('explanation') or ''
    reasons = []
    for stated, listed, preview in count_slips(explanation):
        reasons.append(
            f'The explanation says there are {stated} but lists {listed} '
            f'({preview}) — recount, and check the answer that depends on it.')
    for ordinal, claimed, listed in ordinal_slips(explanation):
        reasons.append(
            f'The explanation says the {ordinal} value is {claimed}, but the '
            f'{ordinal} value in its own list is {listed} — check the answer.')
    for expr, stated, actual in arithmetic_slips(explanation):
        reasons.append(
            f'The explanation\'s arithmetic does not add up: {expr} = {stated} '
            f'(it makes {actual}) — check the answer.')
    return reasons


def flag_explanation_problems(questions):
    """Route every question whose explanation contradicts itself to review.

    Sets ``needs_review`` with the contradiction as ``review_reason`` (appended
    to any reason already there). Returns how many questions were flagged.
    """
    flagged = 0
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        reasons = explanation_problems(q)
        if not reasons:
            continue
        q['needs_review'] = True
        existing = (q.get('review_reason') or '').strip()
        q['review_reason'] = ' '.join(([existing] if existing else []) + reasons)
        flagged += 1
    return flagged
