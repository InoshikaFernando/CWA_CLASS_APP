"""Part-by-part credit for questions that ask for more than one value.

A fill-in-the-blank sentence and a table of values are not one answer; they are
several. Marking them all-or-nothing means a child who fills nine of ten cells
in a money chart correctly is told "Not quite right", scores zero, and is given
no idea which cell cost them the mark. That is both untrue — they knew nine
tenths of it — and useless as feedback.

This module is the one definition of what a partly-right answer is worth and
what to say about it::

    grade = grade_fill_blank_parts(spec, payload, answer_format)
    grade.fraction        # 0.9  — nine of ten gaps
    grade.is_correct      # False — full marks only when every part is right
    points_for(1, grade)  # 0.9  — what the question is actually worth here
    grade.as_answer_data()  # the JSON a surface stores for its review pages

Two rules hold everywhere:

* **Full marks means every part.** ``is_correct`` stays the boolean it has
  always been, so counted scores ("7 of 10 questions correct") keep meaning
  what they meant. Partial credit shows up in *points*, never in the count.
* **Every wrong part is named.** ``corrections()`` says what was typed and what
  was wanted, per part, so "explain what went wrong" is answerable from the
  stored row alone — a review page, a teacher's screen and the immediate
  feedback partial all read the same list.

Pure and framework-agnostic (no Django import), like the graders that build
these results, so the model, the views and the AI importer share one meaning.
"""

# Rounding for the points a partly-right answer earns. Two places is what the
# extended-answer grader already stores and what the float fields carry
# comfortably — 9/10 of a 1-point question is 0.9, 2/3 of one is 0.67.
POINTS_DP = 2

# Shown for a gap the student left empty. An empty string in the "you wrote"
# column reads as a rendering bug; "—" reads as a blank they skipped.
EMPTY_DISPLAY = '—'


class Part:
    """One gap/cell of a multi-part answer, graded.

    ``label`` names the part in words the student can find on their screen
    ("Blank 3", "56" for a table row keyed by its given value); ``typed`` is
    what they wrote, ``expected`` what was wanted.
    """

    def __init__(self, label, typed, expected, is_correct):
        self.label = str(label)
        self.typed = str(typed or '').strip()
        self.expected = str(expected or '').strip()
        self.is_correct = bool(is_correct)

    @property
    def typed_display(self):
        """What the student wrote, with an empty gap shown as "—"."""
        return self.typed or EMPTY_DISPLAY

    def as_dict(self):
        return {
            'label': self.label,
            'typed': self.typed,
            'expected': self.expected,
            'is_correct': self.is_correct,
        }

    def __repr__(self):
        return (f'Part({self.label!r}, typed={self.typed!r}, '
                f'expected={self.expected!r}, is_correct={self.is_correct!r})')


class PartialGrade:
    """The outcome of grading a multi-part answer, part by part.

    ``noun`` is what one part is called on this question type ("blank",
    "cell"), used to build feedback a student can act on: "9 of the 10 blanks
    are right".
    """

    def __init__(self, parts, noun='blank'):
        self.parts = list(parts)
        self.noun = noun

    # -- counts ----------------------------------------------------------
    @property
    def total(self):
        return len(self.parts)

    @property
    def correct(self):
        return sum(1 for p in self.parts if p.is_correct)

    @property
    def wrong_parts(self):
        return [p for p in self.parts if not p.is_correct]

    @property
    def fraction(self):
        """Share of parts right, 0.0–1.0. A question with no parts scores 0."""
        if not self.parts:
            return 0.0
        return self.correct / self.total

    @property
    def is_correct(self):
        """Full marks — every part right. Never true for an empty grade."""
        return bool(self.parts) and self.correct == self.total

    def __bool__(self):
        return self.is_correct

    # -- words -----------------------------------------------------------
    def summary(self):
        """"9 of the 10 blanks are right." — the headline of the feedback."""
        if not self.parts:
            return ''
        plural = self.noun if self.total == 1 else f'{self.noun}s'
        return f'{self.correct} of the {self.total} {plural} are right.'

    def corrections(self):
        """One line per wrong part, naming what was typed and what was wanted.

        ``['Blank 3 (7¢): you wrote ".70" — the answer is "0.07".']`` — the
        whole point of partial credit is that the student learns which part
        cost them the mark, so this is built from the same data the score is.
        """
        out = []
        for part in self.wrong_parts:
            typed = f'you wrote "{part.typed}"' if part.typed else 'you left it empty'
            out.append(f'{part.label}: {typed} — the answer is "{part.expected}".')
        return out

    def feedback(self):
        """Summary + corrections as one string, for text-only surfaces."""
        return ' '.join([self.summary()] + self.corrections()).strip()

    # -- storage ---------------------------------------------------------
    def as_answer_data(self):
        """The JSON blob a surface stores on its student-answer row.

        ``score_fraction`` is the key the existing partial-credit display
        already reads (``WorksheetStudentAnswer.ai_score_fraction`` returns it),
        so a part-graded answer lights up the same amber "Partially correct"
        block the AI-graded ones do. ``parts`` is what lets the review page
        rebuild the breakdown without re-grading.
        """
        return {
            'score_fraction': round(self.fraction, 4),
            'parts_correct': self.correct,
            'parts_total': self.total,
            'parts_noun': self.noun,
            'parts': [p.as_dict() for p in self.parts],
            'what_was_correct': self.summary(),
            'what_to_add': ' '.join(self.corrections()),
        }

    def __repr__(self):
        return f'PartialGrade({self.correct}/{self.total} {self.noun}s)'


def points_for(question_points, grade):
    """What *grade* is worth out of *question_points*, rounded to 2dp.

    ``points_for(1, nine_of_ten)`` → ``0.9``. A missing grade (the question
    isn't part-graded, or its spec was unusable) is worth nothing, which is the
    all-or-nothing behaviour these callers had before.
    """
    if grade is None or not grade.total:
        return 0.0
    try:
        total = float(question_points)
    except (TypeError, ValueError):
        total = 0.0
    if grade.is_correct:
        # Never let rounding cost a full-marks answer a fraction of a point.
        return round(total, POINTS_DP)
    return round(total * grade.fraction, POINTS_DP)
