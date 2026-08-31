"""Prime factorisation, in one place.

``prime_factorization`` questions are graded from ``Question.target_number`` —
every token the student types must be prime and the product must equal the
target — so the factor list itself is only ever needed to *say* what the answer
was: on a result page, in a teacher's answer key, and as the Answer row the
importers store so ``correct_answer_display()`` has something to show.

It used to be worked out in three places (the worksheet grader, the ladder
renderer on the model, an inline loop in the plugin), so this is the canonical
one; the PDF importers use it and ``worksheets.views`` delegates to it.

Pure and framework-agnostic (no Django import), like the other grading helpers.
"""


def prime_factors(n):
    """The prime factors of ``n``, ascending, with repeats: 60 → [2, 2, 3, 5].

    Returns ``[]`` for anything that is not an integer of at least 2 — 1 and 0
    have no factorisation, and a non-integer is a content defect rather than a
    number to guess at. Never raises.
    """
    if isinstance(n, bool):
        return []
    try:
        whole = int(n)
    except (TypeError, ValueError):
        return []
    # int() truncates, so 2.5 would silently factorise as 2 — a number that is
    # not whole has no prime factorisation and must not be guessed at.
    try:
        if whole != float(n):
            return []
    except (TypeError, ValueError):
        return []
    n = whole
    if n < 2:
        return []
    factors = []
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors.append(d)
            n //= d
        d += 1 if d == 2 else 2
    if n > 1:
        factors.append(n)
    return factors


def prime_factorization_answer(n):
    """The canonical written answer for ``n``, e.g. ``"2 x 2 x 3 x 5"``.

    Uses the same ``x`` separator the graders split on (they also accept ``×``,
    ``*``, ``,`` and whitespace), so what a student is shown they should have
    written is a string that would itself mark correct. Returns ``''`` when
    there is no factorisation to give.
    """
    factors = prime_factors(n)
    return ' x '.join(str(f) for f in factors) if factors else ''
