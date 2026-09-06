import re
import uuid
from brainbuzz.managers import MathsQuestionsManager

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# Global question images must live under questions/year<N>/<topic>/<filename>
# so the content team can find them by year + topic. School-specific
# questions are exempt — schools can organise their own media however they
# like. Enforced by Question.clean() so admin / ModelForm uploads are
# rejected up-front rather than drifting through the audit.
QUESTION_IMAGE_PATH_RE = re.compile(r'^questions/year[0-9]+/[a-zA-Z0-9_-]+/.+')


# What each question type draws for ITSELF, keyed to the render property the
# take templates read. When that property comes back empty the type puts no
# picture on the page, so an uploaded image is the only thing the student has to
# look at — which is what ``Question.renders_a_figure`` below reports.
#
# A type absent from here never generates a figure at all (a multiple-choice
# question, a short answer): for those an image is the only possible visual.
FIGURE_RENDER_PROPERTIES = {
    'measure': 'measure_figure_svg',
    'read_graph': 'graph_data',
    'draw_on_grid': 'draw_on_grid_data',
    'shape_select': 'shape_select_data',
    'plot_points': 'plane_data',
    'plot_line': 'plane_data',
    'identify_coords': 'plane_data',
    'number_line': 'number_line_data',
    'table_of_values': 'table_data',
    'sketch_graph': 'sketch_data',
}


# A "list every value" answer ("54, 63" / "54 and 63" / "54; 63") split into
# its values. A comma that groups digits ("1,000", "12,345,678") is part of the
# number, not a separator, so it is protected before the split — otherwise
# "1,000" would read as the two values 1 and 000.
_DIGIT_GROUP_COMMA_RE = re.compile(r'(?<=\d),(?=\d{3}\b)')
_ANSWER_LIST_SEP_RE = re.compile(r'\s*(?:,|;|\band\b)\s*', re.IGNORECASE)
_GROUP_COMMA_SENTINEL = '\x00'
_PLAIN_NUMBER_RE = re.compile(r'^-?\d+(?:\.\d+)?$')
# One value of a numeric list, with any bracket it was written inside:
# "(3", "11)", "-2.5)". Used to compare such a list value-by-value.
_LIST_VALUE_BRACKETS = '()[]'

# Width, in characters, of a fill-in-the-blank input. Sized from the longest
# accepted answer and clamped: narrow enough that a one-digit gap reads as a
# gap in the sentence, wide enough that a phrase is not typed through a
# keyhole.
_BLANK_MIN_SIZE = 4
_BLANK_MAX_SIZE = 20


def _split_answer_list(value):
    """Split a list-style answer into its values, preserving digit grouping.

    >>> _split_answer_list('54, 63')
    ['54', '63']
    >>> _split_answer_list('54 and 63')
    ['54', '63']
    >>> _split_answer_list('1,000')
    ['1,000']
    >>> _split_answer_list('54 63')
    ['54', '63']
    >>> _split_answer_list('nine dollars fifty three cents')
    ['nine dollars fifty three cents']
    """
    protected = _DIGIT_GROUP_COMMA_RE.sub(_GROUP_COMMA_SENTINEL, value)
    parts = [
        part.replace(_GROUP_COMMA_SENTINEL, ',').strip()
        for part in _ANSWER_LIST_SEP_RE.split(protected)
        if part.strip()
    ]
    # A student may separate the values with nothing but a space ("54 63").
    # Space is only a separator when every token is a plain number, so word
    # answers ("nine dollars fifty three cents") and mixed numbers ("2 1/4")
    # stay whole — their words must not be treated as reorderable values.
    if len(parts) == 1:
        tokens = parts[0].split()
        if len(tokens) > 1 and all(_PLAIN_NUMBER_RE.match(t) for t in tokens):
            return tokens
    return parts


def generate_class_code():
    """Retained for historical migration compatibility — not used by any model."""
    return uuid.uuid4().hex[:8]


def calculate_points(score, total_questions, time_taken_seconds, k=30):
    """Calculate quiz points balancing accuracy and speed.

    Formula: percentage * 100 * (K / (K + time_per_question))

    - Accuracy is the primary driver
    - Speed gives a bonus with diminishing returns
    - Normalised per question so quiz length doesn't matter
    - K controls speed weight (lower = speed matters more)
    """
    if not total_questions:
        return 0.0
    percentage = score / total_questions
    time_per_q = time_taken_seconds / total_questions
    return round(percentage * 100 * (k / (k + time_per_q)), 2)


class Question(models.Model):
    # question_type constants for use in views
    MULTIPLE_CHOICE = 'multiple_choice'
    TRUE_FALSE = 'true_false'
    SHORT_ANSWER = 'short_answer'
    FILL_BLANK = 'fill_blank'
    CALCULATION = 'calculation'
    EXTENDED_ANSWER = 'extended_answer'
    LONG_DIVISION = 'long_division'
    PRIME_FACTORIZATION = 'prime_factorization'
    COLUMN_OPERATION = 'column_operation'
    MEASURE = 'measure'
    DRAW_ON_GRID = 'draw_on_grid'
    SHAPE_SELECT = 'shape_select'
    PLOT_POINTS = 'plot_points'
    PLOT_LINE = 'plot_line'
    IDENTIFY_COORDS = 'identify_coords'
    READ_GRAPH = 'read_graph'
    NUMBER_LINE = 'number_line'
    TABLE_OF_VALUES = 'table_of_values'
    SKETCH_GRAPH = 'sketch_graph'

    QUESTION_TYPES = [
        ('multiple_choice', 'Multiple Choice'),
        ('true_false', 'True/False'),
        ('short_answer', 'Short Answer'),
        ('fill_blank', 'Fill in the Blank'),
        ('calculation', 'Calculation'),
        ('extended_answer', 'Extended Answer (written proof/explanation)'),
        ('long_division', 'Long Division'),
        ('prime_factorization', 'Prime Factorization'),
        ('column_operation', 'Column Arithmetic'),
        ('measure', 'Measure (angle/scale, tolerance-graded)'),
        ('draw_on_grid', 'Draw on Grid (symmetry / reflection / plot)'),
        ('shape_select', 'Shape Select (find & colour shapes)'),
        ('plot_points', 'Plot Points (Cartesian plane)'),
        ('plot_line', 'Plot a Line / Shape (Cartesian plane)'),
        ('identify_coords', 'Identify Coordinates (type the point)'),
        ('read_graph', 'Read a Graph (read off a value)'),
        ('number_line', 'Number Line (mark or read a value)'),
        ('table_of_values', 'Table of Values (fill in the x/y table)'),
        ('sketch_graph', 'Sketch a Graph (state vertex / intercepts / axis of symmetry)'),
    ]

    # Validation mode — how student answers are graded
    VALIDATION_AUTO = 'auto'
    VALIDATION_AI = 'ai_graded'
    VALIDATION_HUMAN = 'human_graded'

    VALIDATION_TYPES = [
        ('auto', 'Auto (system checks exact answer)'),
        ('ai_graded', 'AI Graded (Claude evaluates reasoning)'),
        ('human_graded', 'Human Graded (teacher reviews manually)'),
    ]

    DIFFICULTY_CHOICES = [
        (1, 'Easy'),
        (2, 'Medium'),
        (3, 'Hard'),
    ]

    level = models.ForeignKey('classroom.Level', on_delete=models.CASCADE, related_name="maths_questions_by_level")
    topic = models.ForeignKey('classroom.Topic', on_delete=models.SET_NULL, null=True, blank=True, related_name="maths_questions", help_text="Topic this question belongs to (e.g., BODMAS/PEMDAS, Measurements, Fractions)")
    school = models.ForeignKey(
        'classroom.School', on_delete=models.CASCADE,
        null=True, blank=True, related_name='questions',
        help_text='Null = global/shared question. Set = private to this school only.',
    )
    department = models.ForeignKey(
        'classroom.Department', on_delete=models.CASCADE,
        null=True, blank=True, related_name='questions',
        help_text='Null = not department-scoped. Set = visible to this department only.',
    )
    classroom = models.ForeignKey(
        'classroom.ClassRoom', on_delete=models.CASCADE,
        null=True, blank=True, related_name='maths_questions',
        help_text='Null = not class-scoped. Set = visible to this class only.',
    )
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES, default='multiple_choice')
    difficulty = models.PositiveIntegerField(default=1, help_text="1=Easy, 2=Medium, 3=Hard")
    points = models.PositiveIntegerField(default=1)
    explanation = models.TextField(blank=True, help_text="Explanation for the correct answer")
    image = models.ImageField(upload_to='questions/', blank=True, null=True, help_text="Upload an image for this question")
    video = models.FileField(upload_to='questions/videos/', blank=True, null=True, help_text="Upload a video for this question")

    # Grading configuration — applies when question_type = extended_answer
    validation_type = models.CharField(
        max_length=20, choices=VALIDATION_TYPES, default='auto',
        help_text='How student answers are validated. Extended answers use ai_graded or human_graded.',
    )
    grading_rubric = models.TextField(
        blank=True,
        help_text=(
            'Marking guide for AI or teacher graders. '
            'For extended_answer questions: describe what a correct answer must include, '
            'common mistakes to look for, and partial-credit criteria.'
        ),
    )

    # How a typed (short_answer / calculation) answer is matched.
    ANSWER_FORMAT_TEXT = 'text'
    ANSWER_FORMAT_ALGEBRA = 'algebra'
    ANSWER_FORMAT_EQUATION = 'equation'
    ANSWER_FORMAT_SET = 'set'
    ANSWER_FORMAT_PATTERN = 'pattern'
    ANSWER_FORMAT_CHOICES = [
        ('text', 'Text — exact match (case/space-insensitive)'),
        ('algebra', 'Algebra — simplified polynomial (e.g. expand & simplify)'),
        ('equation', 'Equation — algebraic equivalence (accepts vertex / factored / expanded form)'),
        ('set', 'Set — list every value, any order (e.g. "what are the multiples of 9 between 50 and 70?")'),
        ('pattern', 'Pattern — student invents their own number pattern (no stored answer)'),
    ]
    answer_format = models.CharField(
        max_length=10, choices=ANSWER_FORMAT_CHOICES, default='text',
        help_text=(
            'For short_answer / calculation questions. "Algebra" grades the answer as a '
            'fully simplified, expanded polynomial — e.g. (2x+3)(x-5) must be entered as '
            '"2x^2 - 7x - 15". "Equation" grades by algebraic equivalence — for '
            '"write the equation" questions any spelling of the same curve is accepted '
            '(y=2(x-1)^2-2 == y=2x^2-4x). Term order and spacing are always ignored. '
            '"Set" is for "list every value" questions — store the values as one '
            'comma-separated answer ("54, 63"); the student must give them all, in any '
            'order. Leave as "Text" when the order of the values is part of the answer '
            '(e.g. "write these numbers in order"). "Pattern" is for "create your own '
            'number pattern" questions, which have no single right answer and so store '
            'no Answer row at all: the typed numbers are graded against what the '
            'question asks for (same step each time, right operation, right count). '
            'Without it such a question marks every student wrong.'
        ),
    )

    # Long-division and prime-factorisation question data
    dividend = models.PositiveIntegerField(null=True, blank=True, help_text="Long-division: number being divided")
    divisor = models.PositiveIntegerField(null=True, blank=True, help_text="Long-division: number dividing")
    target_number = models.PositiveIntegerField(null=True, blank=True, help_text="Prime-factorization: number to factorise")

    # Column-arithmetic question data (vertical/stacked addition, subtraction, multiplication)
    operands = models.JSONField(null=True, blank=True, help_text="Column arithmetic: list of numbers top-to-bottom, e.g. [90, 82]")
    operator = models.CharField(max_length=1, blank=True, default='', help_text="Column arithmetic operator: '+', '-' or '*'")

    # Measure question data (read an angle/scale and type the value; graded within a tolerance band).
    # Generic on purpose — serves "measure the angle", "read the scale", "estimate the length", etc.
    numeric_answer = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True,
        help_text="Measure: the true value to be measured (e.g. 135 for a 135° angle).",
    )
    answer_tolerance = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True,
        help_text="Measure: accepted ± band. 135 ± 2 marks 133–137 correct. NULL or 0 = exact match.",
    )
    answer_unit = models.CharField(
        max_length=10, blank=True, default='',
        help_text="Measure: unit shown in the answer box, e.g. '°', 'cm', 'g'.",
    )

    # Draw-on-grid question data: a single JSON document describing the dot grid,
    # the shape, the interaction mode, and the correct target set. Coordinates are
    # integer grid indices (not pixels) so the figure is scale-independent. See
    # docs/specs/CPP-330_interactive_geometry_questions.md §3.4 for the schema:
    #   {"grid": {"cols", "rows"}, "shape": {...},
    #    "mode": "segments"|"points"|"shape_complete",
    #    "target": {"segments"|"points"|"expected_extra_segments": [...]},
    #    "allow_extra": bool}
    # Schema validation lives in Question.clean() (CPP-338).
    grid_spec = models.JSONField(
        null=True, blank=True,
        help_text="draw_on_grid only. Dot grid + shape + correct target set (grid-index coords).",
    )

    # Shape-select question data: a self-contained scene of 2D shapes plus the
    # target type the student must find and colour ("colour all the triangles").
    # The correct-answer set is DERIVED (shapes whose type == target_type), so it
    # can never drift from the figure. Schema validation lives in
    # Question.clean(); scenes are produced by maths.shape_select_gen. Shape:
    #   {"target_type": "triangle", "viewbox": [w, h],
    #    "shapes": [{"id", "type", "cx", "cy", "size", "rot"}, ...]}
    shape_spec = models.JSONField(
        null=True, blank=True,
        help_text="shape_select only. Scene of shapes + the target type to find (set-comparison graded).",
    )

    # Cartesian-plane question data: a SIGNED coordinate plane (four quadrants,
    # negatives allowed) shared by plot_points / plot_line / identify_coords.
    # Coordinates are signed integers; grading is set-comparison (plot_points/
    # plot_line) or typed-string parsing (identify_coords). Schema validation
    # lives in Question.clean() (validate_plane_spec). Shape:
    #   {"bounds": {"xmin", "xmax", "ymin", "ymax"}, "mode": "points"|"segments",
    #    "given_points": [[x,y], [x,y,"A"], ...], "target": {"points"|"segments": [...]},
    #    "allow_extra": bool}
    # given_points are drawn for the student to READ; a third element names the
    # point ("A"), which a question phrased in terms of A and B needs to be
    # answerable at all. For identify_coords they must not repeat target.points
    # unless the question really is "write the coordinates of this plotted dot" —
    # otherwise the drawing gives the answer away.
    plane_spec = models.JSONField(
        null=True, blank=True,
        help_text="plot_points / plot_line / identify_coords only. Signed coordinate plane (set-comparison graded).",
    )

    # Read-a-graph question data: a render-only line-graph definition (axes,
    # labels, units, series). The ANSWER reuses numeric_answer / answer_tolerance
    # / answer_unit (the measure fields) — read_graph adds no grading code. When a
    # graph_spec is absent (PDF-extracted), the figure falls back to the uploaded
    # image. Schema validation lives in Question.clean() (validate_graph_spec).
    #   {"title", "x_axis": {"label","unit","min","max","step"}, "y_axis": {...},
    #    "series": [{"points": [[x,y], ...]}]}
    graph_spec = models.JSONField(
        null=True, blank=True,
        help_text="read_graph only. Render-only line-graph (axes/series); answer uses the measure numeric fields.",
    )

    # Number-line question data: a single JSON document describing the scale
    # (min/max/step), the interaction mode, and the correct target set. Two modes:
    #   - "mark": the app draws the blank scale and the student taps tick positions
    #     to place marker(s); graded by set comparison against target.
    #   - "read": the app draws marker(s) at given positions (an arrow on the line)
    #     and the student types the value(s); graded numerically within tolerance.
    # All positions are numbers on the line's own scale (not pixels), so the figure
    # is scale-independent. Schema validation lives in Question.clean().
    #   {"min": -3, "max": 7, "step": 1, "mode": "mark"|"read",
    #    "target": [numbers], "given": [numbers], "tolerance": 0}
    number_line_spec = models.JSONField(
        null=True, blank=True,
        help_text="number_line only. Scale + mode + correct target set (mark: set-comparison; read: numeric tolerance).",
    )

    # Table-of-values question data: a table of headers + rows where each cell is
    # either a shown value the student reads (``given``, e.g. the x column) or a
    # blank the student fills (``answer``, e.g. the y column computed from a rule).
    # Graded all-or-nothing by numeric tolerance (every answer cell must match).
    # Schema validation lives in Question.clean() (validate_table_spec). Shape:
    #   {"headers": ["x", "y"],
    #    "rows": [[{"given": "-3"}, {"answer": "7"}], ...],
    #    "tolerance": 0}
    table_spec = models.JSONField(
        null=True, blank=True,
        help_text="table_of_values only. Headers + rows of given/answer cells (numeric-tolerance graded).",
    )

    # Sketch-a-graph question data: the blank plane the worksheet printed, the
    # key features the stem asks the student to show (vertex, intercepts, axis
    # of symmetry) with the value each is marked against, and — optionally — the
    # curve's coefficients so the result page can draw the sketch that was
    # wanted. Feature values are decimals, not grid indices: the vertex of
    # y = x² + x − 2 is (−0.5, −2.25). Graded feature by feature within a
    # tolerance (partial credit). Schema validation lives in Question.clean()
    # (validate_sketch_spec). Shape:
    #   {"equation": "y = x^2 + x - 2",
    #    "bounds": {"xmin": -6, "xmax": 6, "ymin": -4, "ymax": 8},
    #    "curve": {"type": "quadratic", "a": 1, "b": 1, "c": -2},
    #    "features": [{"kind": "vertex", "points": [[-0.5, -2.25]]},
    #                 {"kind": "x_intercept", "points": [[-2, 0], [1, 0]]},
    #                 {"kind": "y_intercept", "points": [[0, -2]]},
    #                 {"kind": "axis_of_symmetry", "value": -0.5}],
    #    "tolerance": 0.01}
    sketch_spec = models.JSONField(
        null=True, blank=True,
        help_text=(
            "sketch_graph only. The plane to draw plus the key features "
            "(vertex / intercepts / axis of symmetry) the answer is marked "
            "against, feature by feature."
        ),
    )

    # Fill-in-the-blank question data: the accepted answers for each blank, in
    # the order the blanks appear in question_text. The blanks themselves are
    # marked IN the text as runs of underscores ("... to the age of ___."), so
    # the sentence stays readable everywhere it is printed and the spec only
    # carries what is missing from it. Graded all-or-nothing, every blank folded
    # like a short answer (maths.blank_grading.grade_fill_blank). Schema
    # validation lives in Question.clean() (validate_blank_spec), which also
    # cross-checks the count against the text. Shape:
    #   {"blanks": [{"answers": ["15"]}, {"answers": ["live", "survive"]}]}
    # Null on a fill_blank question is the legacy shape — one plain text box for
    # the whole answer — which still works and still grades.
    blank_spec = models.JSONField(
        null=True, blank=True,
        help_text=(
            'fill_blank only. Accepted answers per blank, positional. Mark each '
            'blank in the question text with "___".'
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Custom manager for visibility filtering
    objects = MathsQuestionsManager()

    @property
    def needs_grading(self):
        """True if this question requires AI or human grading (not instant auto-check)."""
        return self.validation_type in (self.VALIDATION_AI, self.VALIDATION_HUMAN)

    # ------------------------------------------------------------------
    # AI-graded or not — one definition, in one place
    # ------------------------------------------------------------------
    #
    # A question costs a model call to mark when it is either an
    # ``extended_answer`` (written prose, no stored answer to match against) or
    # explicitly marked ``validation_type='ai_graded'``. That pair of conditions
    # is what separates the bank into the two halves the product is sold as:
    # the AI-graded questions, and everything the app can mark for itself.
    #
    # It used to be written out by hand wherever it was needed — as a ``Q`` in
    # ``quiz.views.gradable_for``, as an ``if`` elsewhere — so the two halves
    # could drift apart and a question could be hidden from a quiz while still
    # being sent to the grader. Both forms now come from here.

    @classmethod
    def ai_graded_q(cls):
        """The ``Q`` that selects the AI-graded half of the bank."""
        return (models.Q(question_type=cls.EXTENDED_ANSWER)
                | models.Q(validation_type=cls.VALIDATION_AI))

    @property
    def is_ai_graded(self):
        """True if marking this question needs a model call.

        The row-level twin of :meth:`ai_graded_q` — the same rule, so a
        question filtered out of a queryset can never be one this returns
        ``False`` for.
        """
        return (self.question_type == self.EXTENDED_ANSWER
                or self.validation_type == self.VALIDATION_AI)

    def grade_text_answer_parts(self, text_answer):
        """Grade a multi-part typed answer part by part, or return ``None``.

        A fill-in-the-blank sentence and a table of values ask for several
        values, so marking them all-or-nothing throws away most of what the
        student showed: nine of ten money-chart cells right scored zero and the
        feedback could not say which cell was wrong. This returns a
        :class:`~maths.partial_credit.PartialGrade` for those types — one part
        per gap/cell, each with what was typed, what was wanted and whether it
        matched — so a surface can award ``points × fraction`` and name every
        wrong part.

        ``None`` means "not part-graded": a single-answer question type, or a
        multi-part one whose spec or payload could not be lined up (see the
        ``*_parts`` graders). Callers fall back to the boolean
        :meth:`grade_text_answer`, which is what they did before partial credit
        existed, so ``None`` is always safe.

        Routed here, beside :meth:`grade_text_answer`, so the quiz, the
        worksheet and the homework surfaces award identical credit for
        identical work rather than each deciding for itself.
        """
        if self.question_type == self.FILL_BLANK and self.blank_spec:
            from maths.blank_grading import grade_fill_blank_parts
            return grade_fill_blank_parts(
                self.blank_spec, text_answer, self.answer_format)

        if self.question_type == self.TABLE_OF_VALUES and self.table_spec:
            from maths.geometry_grading import grade_table_parts
            return grade_table_parts(self.table_spec, text_answer)

        if self.question_type == self.SKETCH_GRAPH and self.sketch_spec:
            from maths.geometry_grading import grade_sketch_parts
            return grade_sketch_parts(self.sketch_spec, text_answer)

        return None

    def grade_text_answer(self, text_answer):
        """Grade a typed short_answer / calculation answer against the stored
        correct answers (the Answer rows with is_correct=True).

        Routing is driven by ``answer_format``:
          - 'text'    → case/space-insensitive exact match (legacy behaviour).
          - 'algebra' → simplified-polynomial match (see maths.algebra_grading);
                        any of the correct answers may be the canonical form, and
                        each may itself list ``|`` separated acceptable forms.
          - 'pattern' → the student invents the answer, so it is graded against
                        the question's requirements (see maths.pattern_grading).

        Centralised here so every delivery surface (worksheets, the maths plugin)
        grades identically. Returns a bool.
        """
        if not text_answer:
            return False

        # A fill-in-the-blank sentence posts one value per blank as JSON, not a
        # single answer, and its accepted answers live in blank_spec rather than
        # in Answer rows — so it must come before the no-stored-answer guard
        # below. Routing it here (rather than in each view) is what makes the
        # quiz, worksheet and homework surfaces grade it identically; a
        # fill_blank question with no spec falls through to the plain text
        # matching it has always used.
        if self.question_type == self.FILL_BLANK and self.blank_spec:
            from maths.blank_grading import grade_fill_blank
            # answer_format goes with it, so a converted algebra question keeps
            # grading by algebraic equivalence rather than string equality.
            return grade_fill_blank(
                self.blank_spec, text_answer, self.answer_format)

        # A "create your own pattern" question stores no correct answer — there
        # isn't one — so this MUST come before the no-stored-answer guard below,
        # which would otherwise mark every answer wrong.
        if self.answer_format == self.ANSWER_FORMAT_PATTERN:
            from maths.pattern_grading import grade_pattern
            return grade_pattern(self.question_text, text_answer).is_correct

        correct = [
            a.answer_text for a in self.answers.filter(is_correct=True)
            if a.answer_text
        ]
        if not correct:
            return False

        if self.answer_format == self.ANSWER_FORMAT_ALGEBRA:
            from maths.algebra_grading import is_algebraic_answer_correct
            return any(is_algebraic_answer_correct(text_answer, c) for c in correct)

        if self.answer_format == self.ANSWER_FORMAT_EQUATION:
            # "Write the equation" — accept any algebraically equivalent form
            # (vertex / factored / expanded) of the same curve.
            from maths.algebra_grading import is_equation_answer_correct
            return any(is_equation_answer_correct(text_answer, c) for c in correct)

        # Exact match, but exponent-, inequality- and degree-insensitive so the
        # keypad buttons are usable on ordinary maths answers: the x² button
        # (cm^2 == cm² == cm2), a typed inequality however the student spells the
        # operator (x ≥ 2 == x>=2 == x=>2), and the ° button so an angle grades
        # the same with or without it (50 == 50°), and the ÷ button so a
        # quotient grades the same typed either way (n ÷ 4 == n/4). All of it
        # lives in maths.algebra_grading.fold_answer, which one blank of a
        # fill-in-the-blank sentence is folded by too, so a gap in a sentence is
        # graded exactly as forgivingly as a whole answer.
        from maths.algebra_grading import (
            fold_answer as _fold,
            is_reordered_expression_correct,
            option_label_set,
        )

        def _positional_values(value):
            """The ordered values when *value* is a list of plain numbers.

            None for anything else — a word list ("red, green"), an assignment
            list ("x = 4, y = 2") — which keeps those on the whitespace-and-
            comma-insensitive comparison above.

            Needed because that comparison deletes the comma, which loses where
            one value ends and the next begins: "(3,11)" and "(31,1)" both fold
            to "(311)", so a transposed coordinate graded as correct (CPP-378).
            Comparing value-by-value keeps the boundary. Brackets are stripped
            per value, so "(3,11)" also accepts the bare "3,11" a student types
            without them — which is how several coordinate questions are already
            authored, with a paren-less second Answer row.
            """
            parts = _split_answer_list(value)
            if len(parts) < 2:
                return None
            values = []
            for part in parts:
                part = _fold(part).strip(_LIST_VALUE_BRACKETS)
                if not _PLAIN_NUMBER_RE.match(part):
                    return None
                values.append(part)
            return values

        user = _fold(text_answer)
        user_values = _positional_values(text_answer)
        for c in correct:
            # Two numeric lists are compared value-by-value; anything else
            # falls through to the flat comparison, so a student who types the
            # answer as one blob still grades exactly as before.
            if user_values is not None:
                stored_values = _positional_values(c)
                if stored_values is not None:
                    if user_values == stored_values:
                        return True
                    continue
            if user == _fold(c):
                return True

        # "Write an expression for the total cost" is authored as a plain text
        # answer, so a literal match marked "110 + 12p" wrong against a stored
        # "12p + 110" — the same expression with its terms commuted. Compare the
        # two as polynomials when both are written as a simple expression; the
        # student's answer is still graded strictly, so un-combined like terms
        # and un-expanded brackets stay wrong (see is_reordered_expression_correct).
        if any(is_reordered_expression_correct(text_answer, c) for c in correct):
            return True

        # "Work out the number pattern rule and complete the pattern: 30, ___,
        # 60, 75, ___, ___. What is the rule?" asks for two things and stores
        # one — its answer rows are "+15", "add 15", "+ 15". A student who did
        # exactly what the question asked, and typed the missing numbers beside
        # the rule, matched none of them and was marked wrong under a correct
        # answer that already said add 15. The answer is checked against the
        # sequence printed in the QUESTION rather than against the stored
        # string, so the extra numbers have to BE the missing ones — see
        # maths.pattern_grading.completes_printed_pattern.
        from maths.pattern_grading import completes_printed_pattern
        if completes_printed_pattern(self.question_text, correct, text_answer):
            return True

        # A "list every value" answer is a *set*: the student must give every
        # value, but the order they list them in must not decide the mark —
        # "63, 54" is the same answer as "54, 63" (CPP-376). The fold above
        # concatenates a list into one string ("5463"), which only matches the
        # stored order, so the values are compared as a set instead.
        #
        # This is opt-in per question (answer_format='set') rather than inferred
        # from the presence of a comma, because a comma-separated answer is not
        # always a set — "write these numbers in order" stores "3, 5, 7" and
        # must stay order-sensitive (CPP-374).
        if self.answer_format == self.ANSWER_FORMAT_SET:
            user_values = sorted(_fold(p) for p in _split_answer_list(text_answer))
            for c in correct:
                if user_values == sorted(_fold(p) for p in _split_answer_list(c)):
                    return True
            # Content that entered one value per Answer row rather than one
            # comma-separated row: the required set is every ticked row.
            if len(correct) > 1:
                return user_values == sorted(_fold(c) for c in correct)
            return False

        # "Select all that apply" questions are authored as a typed answer that
        # lists the option labels ("D and E"). The student picks the same options
        # but types them in their own order / with their own separator ("E,D"),
        # so those are compared as a set of labels rather than as a string
        # (CPP-374). option_label_set returns None for anything that isn't a
        # list of single letters, which keeps ordered answers order-sensitive.
        user_labels = option_label_set(text_answer)
        if user_labels is None:
            return False
        return any(user_labels == option_label_set(c) for c in correct)

    def rebuild_blank_spec(self, *, positional_rows=True):
        """Derive this question's ``blank_spec`` from its text + Answer rows.

        Returns ``(applied, reason)``. ``applied`` is True when a spec was built
        and assigned to ``self.blank_spec`` (the caller saves); False leaves the
        field untouched and ``reason`` says, in words a person can act on, what
        stopped it — an unmappable question is reported, never guessed at, because
        a blank filled from the wrong value marks a correct student wrong and
        nobody would know.

        The one place the derivation happens, so the AI importer, the teacher
        form and the ``convert_fill_blanks`` command all build the same spec from
        the same question. Mapping rules live in
        :func:`maths.blank_grading.derive_blank_spec`.

        Non-destructive: the Answer rows are left exactly as they are. They are
        still what BrainBuzz snapshots and what an export carries, and keeping
        them is what makes a conversion reversible — clearing ``blank_spec``
        returns the question to its single-box form with its answer intact.
        """
        from maths.blank_grading import derive_blank_spec

        correct = [
            a.answer_text for a in self.answers.filter(is_correct=True).order_by('order', 'id')
            if a.answer_text
        ]
        spec, reason = derive_blank_spec(
            self.question_text, correct, positional_rows=positional_rows)
        if spec is None:
            return False, reason
        self.blank_spec = spec
        return True, ''

    # Types whose answer is typed into a box, and so could instead be typed into
    # the gaps of a sentence. A choice question whose stem happens to contain a
    # gap is still a question you pick an option for, and an extended answer is
    # prose a person or a rubric judges — neither is ever promoted.
    BLANK_PROMOTABLE_TYPES = ('short_answer', 'calculation', 'fill_blank')

    def apply_blank_format(self, *, positional_rows=True):
        """Make this a fill-in-the-blank question if its text has gaps.

        The single entry point every path that writes a question calls — the AI
        importer, the spreadsheet/ZIP upload, the teacher form and the
        ``convert_fill_blanks`` command — so a question with "___" in it comes
        out the same shape no matter how it arrived. Call it AFTER the answer
        rows are written: the spec is derived from them.

        Returns ``(changed, reason)``. ``changed`` says whether this question
        was modified (the caller saves); ``reason`` is set only when the
        question HAS gaps and could not be built into a spec, so a caller can
        report it. The two silent outcomes — not a typed question, or no gaps —
        return no reason, because neither is a problem to tell anyone about.

        Also the repair path: a question whose gaps or answers were edited out
        from under its spec has the stale spec cleared, rather than keeping one
        that no longer describes the sentence.

        ``positional_rows`` is passed through to
        :func:`~maths.blank_grading.derive_blank_spec`. It stays True here — the
        paths that call this saved rows against the documented convention (one
        value per gap, in order) — and ``convert_fill_blanks`` passes False for
        legacy content, where N rows are no evidence of one row per gap.
        """
        from maths.blank_grading import count_blanks

        if self.question_type not in self.BLANK_PROMOTABLE_TYPES:
            # A spec here would never be read, so it is a leftover from a type
            # switch rather than a stored preference.
            if self.blank_spec is not None:
                self.blank_spec = None
                return True, ''
            return False, ''

        if not count_blanks(self.question_text):
            if self.blank_spec is not None:
                self.blank_spec = None
                return True, ''
            return False, ''

        previous = self.blank_spec
        applied, reason = self.rebuild_blank_spec(positional_rows=positional_rows)
        if applied:
            was = self.question_type
            self.question_type = self.FILL_BLANK
            return (self.blank_spec != previous or was != self.FILL_BLANK), ''

        # Gaps, but nothing that maps onto them. The question stays a working
        # single box; any spec that no longer describes it is dropped, because a
        # stale spec grades against the wrong gaps.
        if previous is not None:
            self.blank_spec = None
            return True, reason
        return False, reason

    def display_text_answer(self, text_answer):
        """A stored typed answer as it should be *shown* back to a student.

        The multi-box answers differ from what was stored: they post one value
        per gap/feature as JSON, which is unreadable in a review list, so
        ``{"blanks":["15","live"]}`` is shown as ``"15, live"`` and
        ``{"features":{"vertex":"(-0.5, -2.25)"}}`` as
        ``"Vertex (turning point): (-0.5, -2.25)"``. Every other
        answer is returned unchanged, so a review payload can be built by
        calling this on whatever the student typed without first asking what
        type the question was.
        """
        if self.question_type == self.FILL_BLANK and self.blank_spec:
            from maths.blank_grading import describe_blank_answer
            return describe_blank_answer(text_answer)
        if self.question_type == self.SKETCH_GRAPH and self.sketch_spec:
            from maths.geometry_grading import describe_sketch_answer
            return describe_sketch_answer(text_answer, self.sketch_spec)
        return text_answer

    def correct_answer_display(self):
        """The correct answer as it should be *shown* to a student.

        Every correct Answer row, not just the first — a question whose answer
        is a list of values may store one value per row, and showing only
        ``.first()`` tells the student "54" when the answer is "54 and 63"
        (CPP-376). Separate rows are alternatives, so they are joined with
        " or "; a single row is shown verbatim, commas and all. A "create your
        own pattern" question has no stored answer at all, so a worked example
        of what the question asked for stands in. Returns '' when there is
        neither.
        """
        # A fill-in-the-blank sentence keeps its answers in blank_spec, one set
        # per gap, so reading the Answer rows would show the student nothing (or,
        # on a converted question, the pre-conversion row rather than the gaps).
        if self.question_type == self.FILL_BLANK and self.blank_spec:
            from maths.blank_grading import describe_blank_spec
            shown = describe_blank_spec(self.blank_spec)
            if shown:
                return shown

        # A sketch's answers live in sketch_spec, one per feature, for the same
        # reason — reading the Answer rows would show the student nothing at all.
        if self.question_type == self.SKETCH_GRAPH and self.sketch_spec:
            from maths.geometry_grading import describe_sketch_spec
            shown = describe_sketch_spec(self.sketch_spec)
            if shown:
                return shown

        texts = [
            a.answer_text.strip()
            for a in self.answers.filter(is_correct=True)
            if a.answer_text and a.answer_text.strip()
        ]
        if texts:
            return ' or '.join(texts)

        # "Create your own pattern" questions have no stored answer because
        # there is no single right one. Showing the student a blank where the
        # answer should be says nothing, so show a worked example of the thing
        # the question asked for instead.
        if self.answer_format == self.ANSWER_FORMAT_PATTERN:
            from maths.pattern_grading import example_answer, parse_pattern_request
            request = parse_pattern_request(self.question_text)
            return f'Any pattern that fits — for example {example_answer(request)}'
        return ''

    class Meta:
        ordering = ['level', 'difficulty', 'created_at']

    def __str__(self):
        return f"{self.level} - {self.question_text[:50]}..."

    def clean(self):
        super().clean()
        # Global questions (school IS NULL) must follow the canonical
        # questions/year<N>/<topic>/ image-path convention. School-scoped
        # questions are unconstrained.
        if self.school_id is None and self.image:
            path = str(self.image)
            if not QUESTION_IMAGE_PATH_RE.match(path):
                raise ValidationError({
                    'image': (
                        'Image path must follow '
                        'questions/year<N>/<topic>/<filename> for global '
                        'questions. Got: ' + repr(path)
                    )
                })

        # Measure questions are graded by numeric tolerance, not answer options.
        if self.question_type == self.MEASURE:
            if self.numeric_answer is None:
                raise ValidationError({
                    'numeric_answer': (
                        'Measure questions require a numeric answer '
                        '(the true value the student must measure).'
                    )
                })
            # Guard on pk: answers can only exist for a saved question.
            if self.pk and self.answers.exists():
                raise ValidationError({
                    'question_type': (
                        'Measure questions are graded by numeric tolerance '
                        'and must not have answer options.'
                    )
                })

        # Draw-on-grid questions are graded by set comparison of grid marks.
        if self.question_type == self.DRAW_ON_GRID:
            if not self.grid_spec:
                raise ValidationError({
                    'grid_spec': 'Draw-on-grid questions require a grid_spec.'
                })
            from maths.geometry_grading import validate_grid_spec
            try:
                validate_grid_spec(self.grid_spec)
            except ValueError as exc:
                raise ValidationError({'grid_spec': str(exc)})
            if self.pk and self.answers.exists():
                raise ValidationError({
                    'question_type': (
                        'Draw-on-grid questions are graded by the drawn marks '
                        'and must not have answer options.'
                    )
                })

        # Shape-select questions are graded by set comparison of coloured shapes.
        if self.question_type == self.SHAPE_SELECT:
            if not self.shape_spec:
                raise ValidationError({
                    'shape_spec': 'Shape-select questions require a shape_spec.'
                })
            from maths.geometry_grading import validate_shape_spec
            try:
                validate_shape_spec(self.shape_spec)
            except ValueError as exc:
                raise ValidationError({'shape_spec': str(exc)})
            if self.pk and self.answers.exists():
                raise ValidationError({
                    'question_type': (
                        'Shape-select questions are graded by the coloured shapes '
                        'and must not have answer options.'
                    )
                })

        # Cartesian-plane questions are graded by set comparison (plot) or by
        # parsing the typed coordinates (identify) — both need a plane_spec.
        if self.question_type in (self.PLOT_POINTS, self.PLOT_LINE, self.IDENTIFY_COORDS):
            if not self.plane_spec:
                raise ValidationError({
                    'plane_spec': 'Cartesian-plane questions require a plane_spec.'
                })
            from maths.geometry_grading import validate_plane_spec
            try:
                validate_plane_spec(self.plane_spec)
            except ValueError as exc:
                raise ValidationError({'plane_spec': str(exc)})
            if self.pk and self.answers.exists():
                raise ValidationError({
                    'question_type': (
                        'Cartesian-plane questions are graded by the plotted/typed '
                        'coordinates and must not have answer options.'
                    )
                })

        # Read-a-graph questions are tolerance-graded numeric answers (reuse the
        # measure fields); a graph_spec, when present, must be a valid figure.
        if self.question_type == self.READ_GRAPH:
            if self.numeric_answer is None:
                raise ValidationError({
                    'numeric_answer': (
                        'Read-a-graph questions require a numeric answer '
                        '(the value the student reads off the graph).'
                    )
                })
            if self.graph_spec:
                from maths.geometry_grading import validate_graph_spec
                try:
                    validate_graph_spec(self.graph_spec)
                except ValueError as exc:
                    raise ValidationError({'graph_spec': str(exc)})
            if self.pk and self.answers.exists():
                raise ValidationError({
                    'question_type': (
                        'Read-a-graph questions are graded by numeric tolerance '
                        'and must not have answer options.'
                    )
                })

        # Number-line questions are graded by set comparison of the marked
        # positions (mark mode) or by numeric tolerance on the typed value
        # (read mode) — both need a valid number_line_spec, never answer options.
        if self.question_type == self.NUMBER_LINE:
            if not self.number_line_spec:
                raise ValidationError({
                    'number_line_spec': 'Number-line questions require a number_line_spec.'
                })
            from maths.geometry_grading import validate_number_line_spec
            try:
                validate_number_line_spec(self.number_line_spec)
            except ValueError as exc:
                raise ValidationError({'number_line_spec': str(exc)})
            if self.pk and self.answers.exists():
                raise ValidationError({
                    'question_type': (
                        'Number-line questions are graded by the marked/typed '
                        'values and must not have answer options.'
                    )
                })

        # Table-of-values questions are graded by numeric tolerance on the filled
        # cells (the correct values live in the spec), never answer options.
        if self.question_type == self.TABLE_OF_VALUES:
            if not self.table_spec:
                raise ValidationError({
                    'table_spec': 'Table-of-values questions require a table_spec.'
                })
            from maths.geometry_grading import validate_table_spec
            try:
                validate_table_spec(self.table_spec)
            except ValueError as exc:
                raise ValidationError({'table_spec': str(exc)})
            if self.pk and self.answers.exists():
                raise ValidationError({
                    'question_type': (
                        'Table-of-values questions are graded by the filled cells '
                        'and must not have answer options.'
                    )
                })

        # Sketch-a-graph questions are graded on the FEATURES the stem names —
        # the vertex, the intercepts, the axis of symmetry — each typed into its
        # own box and marked within a tolerance. The values live in the spec, so
        # never answer options.
        if self.question_type == self.SKETCH_GRAPH:
            if not self.sketch_spec:
                raise ValidationError({
                    'sketch_spec': 'Sketch-a-graph questions require a sketch_spec.'
                })
            from maths.geometry_grading import validate_sketch_spec
            try:
                validate_sketch_spec(self.sketch_spec)
            except ValueError as exc:
                raise ValidationError({'sketch_spec': str(exc)})
            if self.pk and self.answers.exists():
                raise ValidationError({
                    'question_type': (
                        'Sketch-a-graph questions are graded by the typed key '
                        'features and must not have answer options.'
                    )
                })

        # Fill-in-the-blank questions are graded from blank_spec — one set of
        # accepted answers per blank, positional. The spec is optional (a
        # fill_blank with none is the legacy single-box shape), but a spec that
        # IS set must line up with the underscores in the question text: a
        # count mismatch mis-grades every attempt, silently.
        if self.question_type == self.FILL_BLANK and self.blank_spec:
            from maths.blank_grading import validate_blank_spec
            try:
                validate_blank_spec(self.blank_spec, self.question_text)
            except ValueError as exc:
                raise ValidationError({'blank_spec': str(exc)})

        # A blank_spec on any other type would never be read — the grader routes
        # on question_type — so it is a mis-set field, not a stored preference.
        if self.blank_spec and self.question_type != self.FILL_BLANK:
            raise ValidationError({
                'blank_spec': (
                    'blank_spec only applies to fill_blank questions. This one '
                    f'is {self.question_type!r}.'
                )
            })

    @property
    def long_division_step_count(self):
        """Number of subtraction blocks needed to long-divide dividend by divisor."""
        if not (self.dividend and self.divisor):
            return 0
        acc = 0
        count = 0
        for d in str(self.dividend):
            acc = acc * 10 + int(d)
            if acc >= self.divisor:
                acc -= (acc // self.divisor) * self.divisor
                count += 1
        return count

    @property
    def long_division_answer(self):
        """Canonical answer for a long-division question: "Q" when it divides evenly,
        otherwise "Q r R" (e.g. "56 r 4"). None if dividend/divisor aren't set."""
        if not (self.dividend and self.divisor):
            return None
        quotient, remainder = divmod(self.dividend, self.divisor)
        return str(quotient) if remainder == 0 else f"{quotient} r {remainder}"

    @property
    def is_degree_measure(self):
        """True for a ``measure`` question whose unit is degrees (vs a length).

        Centralises the unit sniff used by both the generated figure and the
        interactive tool, so "what counts as an angle" is defined once.
        """
        if self.question_type != self.MEASURE:
            return False
        unit = (self.answer_unit or '').strip().lower()
        return '°' in unit or unit in ('deg', 'degree', 'degrees')

    @property
    def measure_tool(self):
        """Which on-screen instrument the digital surfaces overlay on a
        ``measure`` figure: a ``protractor`` for angles, else a ``ruler``.
        Drives ``data-measure-tool`` in the shared partial (measure_tool.js)."""
        return 'protractor' if self.is_degree_measure else 'ruler'

    @property
    def measure_figure_svg(self):
        """Inline SVG of the angle to measure, generated from ``numeric_answer``.

        Only angle questions (degree unit) get a generated figure — drawing an
        angle for a length/mass "measure" question (unit cm, g, …) would be
        misleading, so those render no figure (the author supplies an image or
        describes the scale in the question text). Returns '' when there's
        nothing to draw, so templates can render it unconditionally. Bridges the
        pure ``maths.svg_geometry`` helper into templates without per-view
        context plumbing — the same way the long-division / prime-factorisation
        render helpers live on the model.
        """
        if not self.is_degree_measure or self.numeric_answer is None:
            return ''
        from maths.svg_geometry import angle_svg
        return angle_svg(self.numeric_answer)

    @property
    def draw_on_grid_data(self):
        """SVG-ready render data for a draw_on_grid question, or None.

        Maps the ``grid_spec`` (grid-index coords) to pixel coordinates the
        take-item template draws: the dot lattice (each dot carries its grid
        index for the click-to-draw JS), the shape polygon, and the canvas
        size. Returns None when there's nothing renderable, so templates guard
        with a single check. Kept on the model — like the long-division /
        prime-factorisation render helpers — so no per-view plumbing is needed.
        """
        if self.question_type != self.DRAW_ON_GRID or not self.grid_spec:
            return None
        grid = self.grid_spec.get('grid') or {}
        cols, rows = grid.get('cols'), grid.get('rows')
        if not (isinstance(cols, int) and isinstance(rows, int) and cols > 0 and rows > 0):
            return None
        pad, step = 20, 36

        def px(x):
            return pad + x * step

        dots = [
            {'gx': x, 'gy': y, 'px': px(x), 'py': px(y)}
            for y in range(rows) for x in range(cols)
        ]
        shape = self.grid_spec.get('shape')
        shape_points = shape.get('points', []) if isinstance(shape, dict) else []
        # Defensive: only well-formed integer [x, y] points reach the SVG, so a
        # spec that bypassed validate_grid_spec can't 500 the take-item render.
        polygon = ' '.join(
            f'{px(p[0])},{px(p[1])}'
            for p in shape_points
            if isinstance(p, (list, tuple)) and len(p) == 2
            and all(isinstance(c, int) for c in p)
        )
        return {
            'cols': cols, 'rows': rows, 'pad': pad, 'step': step,
            'width': pad * 2 + (cols - 1) * step,
            'height': pad * 2 + (rows - 1) * step,
            'dots': dots, 'polygon': polygon,
        }

    @property
    def shape_select_data(self):
        """SVG-ready render data for a shape_select question, or None.

        Bridges the pure ``maths.svg_geometry.shape_select_svg`` builder into the
        take-item template (no per-view context plumbing — same pattern as
        ``draw_on_grid_data`` / ``measure_figure_svg``). Returns None when
        there's nothing renderable, so templates guard with a single check.
        """
        if self.question_type != self.SHAPE_SELECT or not self.shape_spec:
            return None
        from maths.svg_geometry import shape_select_svg
        svg = shape_select_svg(self.shape_spec)
        if not svg:
            return None
        vb = self.shape_spec.get('viewbox') or [680, 400]
        try:
            width, height = int(vb[0]), int(vb[1])
        except (TypeError, ValueError, IndexError):
            width, height = 680, 400
        return {
            'width': width, 'height': height, 'svg': svg,
            'target_type': self.shape_spec.get('target_type', ''),
        }

    @property
    def plane_data(self):
        """SVG-ready render data for a Cartesian-plane question, or None.

        Maps the ``plane_spec`` (signed integer coords) to pixel coordinates the
        take-item template draws: the axes/ticks SVG, the tappable lattice points
        (each carrying its signed coord for the click-to-plot JS), any
        pre-plotted ``given_points``, and the canvas size. Returns None when
        there's nothing renderable, so templates guard with a single check.
        Mirrors ``draw_on_grid_data`` / ``shape_select_data`` — render data on the
        model, no per-view plumbing.
        """
        if self.question_type not in (
            self.PLOT_POINTS, self.PLOT_LINE, self.IDENTIFY_COORDS
        ) or not self.plane_spec:
            return None
        from maths.geometry_grading import _plane_bounds
        from maths.svg_geometry import cartesian_plane_svg
        bounds = _plane_bounds(self.plane_spec)
        if bounds is None:
            return None
        xmin, xmax, ymin, ymax = bounds
        pad, step = 28, 32

        def px(x):
            return pad + (x - xmin) * step

        def py(y):
            # y grows upward on a Cartesian plane, downward in SVG.
            return pad + (ymax - y) * step

        cols = xmax - xmin + 1
        rows = ymax - ymin + 1
        width = pad * 2 + (cols - 1) * step
        height = pad * 2 + (rows - 1) * step
        # Tappable lattice points (interactive plot types only — identify_coords
        # is read-only and renders no hit-targets).
        interactive = self.question_type in (self.PLOT_POINTS, self.PLOT_LINE)
        dots = []
        if interactive:
            dots = [
                {'gx': x, 'gy': y, 'px': px(x), 'py': py(y)}
                for y in range(ymin, ymax + 1) for x in range(xmin, xmax + 1)
            ]
        # Given points may be named ([x, y, "A"]) — the label is drawn beside the
        # dot so a question that talks about "the line AB" is readable. A
        # malformed entry is skipped rather than raised on: clean() rejects one
        # at the source, and a render helper must not 500 a whole homework page.
        from maths.geometry_grading import given_point_parts
        given = []
        for p in (self.plane_spec.get('given_points') or []):
            try:
                gx, gy, label = given_point_parts(p)
            except ValueError:
                continue
            if not all(isinstance(c, int) and not isinstance(c, bool)
                       for c in (gx, gy)):
                continue
            given.append({'gx': gx, 'gy': gy, 'px': px(gx), 'py': py(gy),
                          'label': label,
                          # Nudge the label clear of the dot and of the axes.
                          'lx': px(gx) + 8, 'ly': py(gy) - 8})
        return {
            'svg': cartesian_plane_svg(self.plane_spec, pad=pad, step=step),
            'width': width, 'height': height, 'pad': pad, 'step': step,
            'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax,
            'mode': self.plane_spec.get('mode') or 'points',
            'dots': dots, 'given': given, 'interactive': interactive,
            # Opt-in: render a smooth curve through the plotted points (plot_points
            # only — a "join the dots into a parabola" visual aid; grading unchanged).
            'curve': bool(self.plane_spec.get('curve')),
        }

    @property
    def graph_data(self):
        """SVG-ready render data for a read_graph question, or None.

        Bridges the pure ``maths.svg_geometry.line_graph_svg`` builder into the
        take-item template. Returns None when there's no ``graph_spec`` to render
        (the template then falls back to ``question.image``), so a PDF-extracted
        read_graph still shows its figure. Mirrors ``measure_figure_svg``.
        """
        if self.question_type != self.READ_GRAPH or not self.graph_spec:
            return None
        from maths.svg_geometry import line_graph_svg
        svg = line_graph_svg(self.graph_spec)
        if not svg:
            return None
        return {'svg': svg}

    @property
    def number_line_data(self):
        """SVG-ready render data for a number_line question, or None.

        Maps the ``number_line_spec`` (values on the line's own scale) to pixel
        coordinates the take-item template draws: the axis backdrop SVG (line,
        ticks, labels, and — in read mode — the given arrows), the tappable tick
        positions (mark mode) each carrying its value for the click-to-mark JS,
        and the canvas size. Returns None when there's nothing renderable, so
        templates guard with a single check. Mirrors ``plane_data`` — render data
        on the model, no per-view plumbing.
        """
        if self.question_type != self.NUMBER_LINE or not self.number_line_spec:
            return None
        from maths.geometry_grading import number_line_ticks, _num_key
        from maths.svg_geometry import number_line_svg
        ticks = number_line_ticks(self.number_line_spec)
        if ticks is None:
            return None
        spec = self.number_line_spec
        pad, tick_px = 28, 44
        top = 34  # baseline y for the number line

        def px(i):
            return pad + i * tick_px

        width = pad * 2 + (len(ticks) - 1) * tick_px
        height = 78
        mode = spec.get('mode') or 'mark'
        # Tappable tick positions (mark mode only — read mode is answered by typing).
        dots = []
        if mode == 'mark':
            dots = [{'value': v, 'px': px(i), 'py': top}
                    for i, v in enumerate(ticks)]
        # Index by the canonical tick key so a spec value stored as 6.0 still maps
        # to the tick at 6 (same normalisation validate_number_line_spec uses).
        index_of = {_num_key(v): i for i, v in enumerate(ticks)}
        # Values already marked with an arrow (read mode reads these).
        given = [{'value': v, 'px': px(index_of[_num_key(v)]), 'py': top}
                 for v in (spec.get('given') or []) if _num_key(v) in index_of]
        # Correct answer marks — shown on the teacher answer-key (worksheets).
        targets = spec.get('target')
        if targets is None:
            targets = spec.get('given') or []
        answer = [{'value': v, 'px': px(index_of[_num_key(v)]), 'py': top}
                  for v in targets if _num_key(v) in index_of]
        return {
            'svg': number_line_svg(self.number_line_spec, pad=pad, tick_px=tick_px, top=top),
            'width': width, 'height': height, 'pad': pad, 'tick_px': tick_px, 'top': top,
            'mode': mode, 'dots': dots, 'given': given, 'answer': answer,
            'target_values': [t['value'] for t in answer],
            'tolerance': spec.get('tolerance') or 0,
        }

    @property
    def table_data(self):
        """Render-ready data for a table_of_values question, or None.

        Maps ``table_spec`` to the rows the take-item template draws: each cell is
        either a shown value (``given``) or a blank input carrying its ``r,c`` key
        for the serialise-to-JSON JS. The ``answer`` value is kept on blank cells
        so the worksheets answer-key surface can show the correct value — the
        student take template renders only the empty input and never prints it.
        Returns None when there's nothing renderable, so templates guard with a
        single check. Mirrors ``plane_data`` / ``number_line_data`` — render data
        on the model, no per-view plumbing.
        """
        if self.question_type != self.TABLE_OF_VALUES or not self.table_spec:
            return None
        from maths.geometry_grading import _table_cell_kind
        headers = self.table_spec.get('headers')
        rows = self.table_spec.get('rows')
        if not isinstance(headers, list) or not isinstance(rows, list):
            return None
        out_rows = []
        for r, row in enumerate(rows):
            if not isinstance(row, list):
                return None
            out_cells = []
            for c, cell in enumerate(row):
                kind = _table_cell_kind(cell)
                if kind is None:
                    return None
                role, value = kind
                if role == 'given':
                    out_cells.append({'given': True, 'value': value})
                else:
                    out_cells.append({'given': False, 'rc': f'{r},{c}', 'answer': value})
            out_rows.append(out_cells)
        return {'headers': headers, 'rows': out_rows}

    @property
    def sketch_data(self):
        """Render-ready data for a sketch_graph question, or None.

        Two halves, and only one of them is ever shown to a student mid-attempt:

        * ``svg`` / ``width`` / ``height`` — the BLANK plane the worksheet
          printed, so the pupil has the same axes to work the sketch out on.
        * ``dots`` (with ``pad`` / ``step`` / ``xmin`` / ``ymax``) — the lattice
          points of that plane, tappable, so the sketch the stem asks for can
          actually be drawn: the student plots points and the widget joins them
          into a curve. Empty when the question cannot be sketched (no curve to
          mark a drawing against, or too few of its points inside the plane),
          which leaves the plane exactly as it was — paper to work on.
        * ``features`` — one box per feature the stem asks for, each with the
          label it is called by and a placeholder showing the form to type. The
          correct value is deliberately NOT here; it lives in the spec and never
          reaches the take page.
        * ``answer_svg`` / ``answer_features`` — the curve, the axis of symmetry
          and the labelled key points: the sketch that was wanted. Feedback
          only. The take template must not render them, exactly as ``table_data``
          keeps its answers off the student's screen.

        Returns None when there's nothing renderable, so templates guard with a
        single check. Mirrors ``plane_data`` / ``table_data`` — render data on
        the model, no per-view plumbing.
        """
        if self.question_type != self.SKETCH_GRAPH or not self.sketch_spec:
            return None
        from maths.geometry_grading import (
            SKETCH_FEATURE_LABELS, _plane_bounds, sketch_curve,
            sketch_drawing_part, sketch_feature_expected,
        )
        from maths.svg_geometry import cartesian_plane_svg, sketch_answer_svg

        bounds = _plane_bounds(self.sketch_spec)
        if bounds is None:
            return None
        xmin, xmax, ymin, ymax = bounds
        pad, step = 28, 32
        width = pad * 2 + (xmax - xmin) * step
        height = pad * 2 + (ymax - ymin) * step

        def px(x):
            return pad + (x - xmin) * step

        def py(y):
            # y grows upward on a Cartesian plane, downward in SVG.
            return pad + (ymax - y) * step

        # The plane is only made tappable when a drawn sketch can be marked —
        # the same test the grader applies, asked once here so the widget never
        # invites a student to plot points that could not count.
        curve = sketch_curve(self.sketch_spec)
        drawable = sketch_drawing_part(self.sketch_spec, [], curve) is not None
        dots = [
            {'gx': x, 'gy': y, 'px': px(x), 'py': py(y)}
            for y in range(ymin, ymax + 1) for x in range(xmin, xmax + 1)
        ] if drawable else []

        features, answer_features = [], []
        for feature in (self.sketch_spec.get('features') or []):
            if not isinstance(feature, dict):
                continue
            kind = feature.get('kind')
            if kind not in SKETCH_FEATURE_LABELS:
                continue
            label = SKETCH_FEATURE_LABELS[kind]
            if kind == 'axis_of_symmetry':
                placeholder, hint = 'x = 2', 'Write the equation, e.g. x = 2.'
            elif kind == 'x_intercept':
                placeholder = '(-2, 0), (1, 0)'
                hint = 'Give every intercept, separated by a comma.'
            else:
                placeholder, hint = '(0, -2)', 'Write the coordinates as (x, y).'
            features.append({'kind': kind, 'label': label,
                             'placeholder': placeholder, 'hint': hint})
            answer_features.append({'kind': kind, 'label': label,
                                    'expected': sketch_feature_expected(feature)})

        if not features:
            return None
        return {
            'equation': (self.sketch_spec.get('equation') or '').strip(),
            'svg': cartesian_plane_svg(self.sketch_spec, pad=pad, step=step),
            'answer_svg': sketch_answer_svg(self.sketch_spec, pad=pad, step=step),
            'width': width, 'height': height,
            'pad': pad, 'step': step, 'xmin': xmin, 'ymax': ymax,
            'dots': dots, 'drawable': drawable,
            'features': features, 'answer_features': answer_features,
        }

    @property
    def renders_a_figure(self):
        """Does a student taking this question see a picture of any kind?

        True for an uploaded image or video, and for the types that draw their
        own figure once the spec behind it is set — the angle a ``measure``
        question generates from ``numeric_answer``, the plane a ``plot_points``
        question draws from ``plane_spec``, and so on. Reads the same render
        properties the take templates read, so "is there anything on the page
        to look at" is answered once here rather than re-derived per template
        and per audit (``maths.answer_verification.verify_question_figure``).

        False does NOT mean the question is broken: most questions need no
        figure. It means an image is the only visual this question could have,
        and it has none — which IS a fault when the stem points at a figure or
        the type is one whose answer is read off one (CPP-406).
        """
        if self.image or self.video:
            return True
        prop = FIGURE_RENDER_PROPERTIES.get(self.question_type)
        return bool(getattr(self, prop)) if prop else False

    @property
    def blank_data(self):
        """Render-ready data for a fill_blank question, or None.

        Interleaves the literal text around the blanks with the blanks
        themselves, so a template can lay the sentence back out with an input
        sitting in each gap::

            {'count': 2,
             'parts': [{'text': 'Out of 100 000 births, ... to the age of '},
                       {'index': 0, 'size': 4, 'answer': '15'},
                       {'text': '. From that age, ... expected to '},
                       {'index': 1, 'size': 8, 'answer': 'live or survive'},
                       {'text': ' for another 67.0 years.'}]}

        Each part has exactly one of ``text`` (literal) or ``index`` (a blank).
        ``size`` is the input's width in characters, from the longest accepted
        answer, so a one-digit gap isn't a full-width box and a wordy one still
        fits. ``answer`` is kept on blank parts so the worksheets answer-key
        surface can print the correct value — the student take template renders
        only the empty input and never prints it, exactly as ``table_data``
        does.

        Returns None when there's nothing renderable (no spec, or a spec out of
        step with the text), so templates guard with a single check and fall
        back to the plain single-box input rather than rendering a broken
        sentence. Mirrors ``table_data`` / ``number_line_data`` — render data on
        the model, no per-view plumbing.
        """
        if self.question_type != self.FILL_BLANK or not self.blank_spec:
            return None
        from maths.blank_grading import blank_answers, split_on_blanks

        answers = blank_answers(self.blank_spec)
        if not answers:
            return None
        segments = split_on_blanks(self.question_text)
        # A spec that no longer matches its sentence cannot be laid out — some
        # gap would have no input, or some input no gap. clean() rejects that,
        # but content edited around the validator must degrade to the plain box
        # rather than render a sentence that is missing an answer.
        if len(segments) != len(answers) + 1:
            return None

        parts = []
        for i, segment in enumerate(segments):
            if segment:
                parts.append({'text': segment})
            if i < len(answers):
                longest = max(len(a) for a in answers[i])
                parts.append({
                    'index': i,
                    'size': max(_BLANK_MIN_SIZE, min(longest, _BLANK_MAX_SIZE)),
                    'answer': ' or '.join(answers[i]),
                })
        return {'count': len(answers), 'parts': parts}

    @property
    def pattern_field_data(self):
        """Render-ready boxes for a "create your own pattern" question, or None.

            {'count': 6, 'indexes': [0, 1, 2, 3, 4, 5],
             'needs_rule': True, 'fixed': True}

        One box per number the question asks for, plus a box for the rule —
        the shape of the answer, which a single text box left the student to
        guess at. What they compose is the same sentence a student would have
        typed, so nothing downstream of the widget has to know it exists.

        None for every other question, so a template guards with one check and
        falls back to the plain box. Mirrors ``blank_data`` / ``table_data``:
        render data on the model, no per-view plumbing.
        """
        if self.answer_format != self.ANSWER_FORMAT_PATTERN:
            return None
        from maths.pattern_grading import pattern_fields

        fields = pattern_fields(self.question_text)
        return {
            'count': fields.count,
            'indexes': fields.indexes,
            'needs_rule': fields.needs_rule,
            'fixed': fields.fixed,
        }

    @property
    def prime_factorization_rows(self):
        """Rows for the ladder rendering. First row shows target_number, last row shows 1.
        Intermediate rows are blank inputs the student fills in.
        Each row has prime_input (left cell type) and number-side fields:
          show_number=True → display the value
          number_input=True → render an input cell
        """
        n = self.target_number
        if not n or n < 2:
            return []
        primes_count = 0
        m = n
        p = 2
        while m > 1:
            if m % p == 0:
                m //= p
                primes_count += 1
            else:
                p = 3 if p == 2 else p + 2
        rows = [{'show_number': True, 'number': n, 'number_input': False, 'prime_input': True}]
        for i in range(primes_count - 1):
            rows.append({'show_number': False, 'number': None, 'number_input': True, 'prime_input': True})
        rows.append({'show_number': True, 'number': 1, 'number_input': False, 'prime_input': False})
        return rows

    @property
    def column_result(self):
        """Computed answer for a column-arithmetic question, or None if not applicable."""
        ops = self.operands or []
        if not ops or not self.operator:
            return None
        try:
            nums = [int(o) for o in ops]
        except (TypeError, ValueError):
            return None
        if not nums:
            return None
        if self.operator == '+':
            return sum(nums)
        if self.operator == '-':
            result = nums[0]
            for n in nums[1:]:
                result -= n
            return result
        if self.operator in ('*', '×', 'x'):
            result = 1
            for n in nums:
                result *= n
            return result
        return None

    @property
    def column_arithmetic(self):
        """Render structure for the column-arithmetic widget.

        Returns a dict with:
          width    — number of digit columns (max of widest operand and the result)
          rows     — list of right-aligned digit-string lists (one per operand), blanks left-padded
          operator — display symbol: '+', '−' or '×'
          cols     — range(width) for template iteration
          partials — (long multiplication only) list of scratch working rows, one per
                     non-zero multiplier digit; each is {'shift', 'boxes', 'spacers'}.
                     Absent for +, −, single-significant-digit × and 3+ operands.
        Returns None if this isn't a valid column-arithmetic question.
        """
        ops = self.operands or []
        result = self.column_result
        if not ops or not self.operator or result is None:
            return None
        try:
            nums = [int(o) for o in ops]
        except (TypeError, ValueError):
            return None
        width = max([len(str(abs(n))) for n in nums] + [len(str(abs(result)))])

        def pad(n):
            s = str(abs(n))
            return [''] * (width - len(s)) + list(s)

        symbol = {'+': '+', '-': '−', '*': '×', '×': '×', 'x': '×'}.get(self.operator, self.operator)
        data = {
            'width': width,
            'rows': [pad(n) for n in nums],
            'operator': symbol,
            'cols': range(width),
        }

        # Long-multiplication partial-product working rows.
        # Only for a genuine multi-digit multiplier: × with exactly two operands
        # where the multiplier (bottom number) has ≥ 2 non-zero digits. A single
        # significant digit (×4, ×10, ×100, ×60) needs no partials — the simple
        # single-answer-row layout is kept. Zero digits are skipped (no row); the
        # next non-zero digit shifts by its full place value (23×101 → 2 rows).
        if self.operator in ('*', '×', 'x') and len(nums) == 2:
            multiplier_digits = str(abs(nums[1]))
            if sum(1 for d in multiplier_digits if d != '0') >= 2:
                partials = []
                for shift, digit in enumerate(reversed(multiplier_digits)):
                    if digit == '0':
                        continue  # nothing to write for a zero digit
                    partials.append({
                        'shift': shift,                  # place-value offset, 0 = units
                        'boxes': range(width - shift),   # scratch cells (value right-aligned here)
                        'spacers': range(shift),         # empty cells on the right (the shift)
                    })
                data['partials'] = partials

        return data

    @property
    def column_inline(self):
        """Single-line form of the problem, e.g. "90 − 82".

        Renderers that don't draw the stacked grid (mixed quiz, homework,
        worksheet preview) show this so the numbers are still visible — the
        grid renderer presents the operands visually instead.
        """
        ca = self.column_arithmetic
        if not ca:
            return ''
        return f" {ca['operator']} ".join(str(int(o)) for o in self.operands)


class Answer(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    answer_text = models.TextField(blank=True)
    answer_image = models.ImageField(upload_to='answers/', blank=True, null=True, help_text="Image answer for MCQ")
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0, help_text="Order for multiple choice options")

    class Meta:
        ordering = ['question', 'order', 'id']

    def __str__(self):
        return f"{self.question} - {self.answer_text[:30]}..."


class StudentAnswer(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="maths_student_answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="student_answers")
    selected_answer = models.ForeignKey(Answer, on_delete=models.CASCADE, null=True, blank=True)
    text_answer = models.TextField(blank=True, help_text="For short answer questions")
    ordered_answer_ids = models.JSONField(null=True, blank=True, help_text="For drag-drop questions")
    is_correct = models.BooleanField(default=False)
    points_earned = models.PositiveIntegerField(default=0)
    answered_at = models.DateTimeField(auto_now_add=True)
    session_id = models.CharField(max_length=100, blank=True, default="", help_text="Session identifier for tracking attempts")
    attempt_id = models.UUIDField(default=uuid.uuid4, help_text="Groups all answers from one quiz session")
    time_taken_seconds = models.PositiveIntegerField(default=0, help_text="Time taken for this attempt in seconds")

    class Meta:
        unique_together = ("student", "question", "attempt_id")
        ordering = ['-answered_at']

    def __str__(self):
        return f"{self.student} - {self.question} - {'Correct' if self.is_correct else 'Incorrect'}"


class BasicFactsResult(models.Model):
    """Store Basic Facts quiz attempts in database for persistent tracking"""
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="maths_basic_facts_results")
    level = models.ForeignKey('classroom.Level', on_delete=models.CASCADE, related_name="maths_basic_facts_results", null=True, blank=True)
    # subtopic + level_number used by the quiz-engine rows (progress app style)
    subtopic = models.CharField(max_length=20, blank=True, default="", help_text="e.g. Addition, Subtraction, Multiplication, Division, PlaceValue")
    level_number = models.PositiveIntegerField(null=True, blank=True, help_text="Numeric level within the subtopic (1-10)")
    session_id = models.CharField(max_length=100, help_text="Session identifier for tracking attempts")
    score = models.PositiveIntegerField(help_text="Number of correct answers")
    total_points = models.PositiveIntegerField(help_text="Total possible points")
    time_taken_seconds = models.PositiveIntegerField(help_text="Time taken for this attempt in seconds")
    points = models.DecimalField(max_digits=10, decimal_places=2, help_text="Calculated points based on score, time, and percentage")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-completed_at']
        indexes = [
            models.Index(fields=['student', 'level']),
            models.Index(fields=['student', 'level', 'session_id']),
            models.Index(fields=['student', 'subtopic', 'level_number']),
        ]

    # questions_data stores generated question details + student answers for results review
    questions_data = models.JSONField(
        default=list, blank=True,
        help_text="Stores generated questions + student answers for review.",
    )

    def __str__(self):
        return f"{self.student} - {self.subtopic} L{self.level_number} - {self.points} points ({self.completed_at})"

    @property
    def percentage(self):
        """Percentage score (0-100)."""
        if not self.total_points:
            return 0
        return round((self.score / self.total_points) * 100)

    @property
    def total_questions(self):
        """Alias for total_points (same value — each question = 1 point in Basic Facts)."""
        return self.total_points

    @classmethod
    def get_best_result(cls, student, subtopic, level_number):
        """Get the best (highest points) result for a student-subtopic-level combination."""
        return cls.objects.filter(
            student=student, subtopic=subtopic, level_number=level_number
        ).order_by('-points').first()

    @classmethod
    def prune_old_attempts(cls, instance):
        """Keep only the most recent attempts for this student/subtopic/level."""
        from classroom.attempt_retention import prune_to_last_n
        return prune_to_last_n(cls, {
            'student_id': instance.student_id,
            'subtopic': instance.subtopic,
            'level_number': instance.level_number,
        })


class TimeLog(models.Model):
    """Track daily and weekly time spent by students on the app"""
    student = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="maths_time_log")
    daily_total_seconds = models.PositiveIntegerField(default=0, help_text="Total seconds spent today")
    weekly_total_seconds = models.PositiveIntegerField(default=0, help_text="Total seconds spent this week")
    last_reset_date = models.DateField(auto_now=True, help_text="Last date when daily time was reset")
    last_reset_week = models.IntegerField(default=0, help_text="ISO week number of last weekly reset")
    last_activity = models.DateTimeField(auto_now=True, help_text="Last time activity was recorded")

    class Meta:
        ordering = ['-last_activity']

    def __str__(self):
        return f"{self.student.username} - Daily: {self.daily_total_seconds}s, Weekly: {self.weekly_total_seconds}s"

    # ── Backward-compatible aliases (for progress app templates/views) ────────
    @property
    def daily_seconds(self):
        return self.daily_total_seconds

    @property
    def weekly_seconds(self):
        return self.weekly_total_seconds

    @property
    def last_updated(self):
        return self.last_activity

    @property
    def last_daily_reset(self):
        return self.last_reset_date

    def reset_daily_if_needed(self):
        """Reset daily time if it's past midnight (local time)"""
        from django.utils import timezone
        from django.utils.timezone import localtime
        now_local = localtime(timezone.now())
        today = now_local.date()
        if self.last_reset_date < today:
            self.daily_total_seconds = 0
            self.last_reset_date = today
            self.save(update_fields=['daily_total_seconds', 'last_reset_date'])

    def reset_weekly_if_needed(self):
        """Reset weekly time if it's past Sunday midnight (Monday 00:00) in local time"""
        from django.utils import timezone
        from django.utils.timezone import localtime
        now_local = localtime(timezone.now())
        iso = now_local.isocalendar()
        current_week = iso[0] * 100 + iso[1]  # e.g. 202615 — encodes year+week to avoid year-rollover bug

        if self.last_reset_week != current_week:
            self.weekly_total_seconds = 0
            self.last_reset_week = current_week
            self.save(update_fields=['weekly_total_seconds', 'last_reset_week'])


class TopicLevelStatistics(models.Model):
    """Store average and standard deviation (sigma) for each topic-level combination"""
    level = models.ForeignKey('classroom.Level', on_delete=models.CASCADE, related_name="maths_topic_statistics")
    topic = models.ForeignKey('classroom.Topic', on_delete=models.CASCADE, related_name="maths_level_statistics")
    average_points = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Average points across all students")
    sigma = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Standard deviation (sigma)")
    student_count = models.PositiveIntegerField(default=0, help_text="Number of students who have completed this topic-level")
    last_updated = models.DateTimeField(auto_now=True, help_text="Last time statistics were calculated")

    class Meta:
        unique_together = ("level", "topic")
        ordering = ['level__level_number', 'topic__name']
        indexes = [
            models.Index(fields=['level', 'topic'], name='maths_tls_level_topic_idx'),
        ]

    def __str__(self):
        return f"{self.level} - {self.topic}: avg={self.average_points}, σ={self.sigma} (n={self.student_count})"

    @classmethod
    def recalculate(cls, topic, level):
        """Recompute mean/sigma from best StudentFinalAnswer per student."""
        from django.db.models import Max
        best_per_student = (
            StudentFinalAnswer.objects.filter(topic=topic, level=level)
            .values('student')
            .annotate(best_points=Max('points'))
        )
        points_list = [row['best_points'] for row in best_per_student if row['best_points'] is not None]
        n = len(points_list)
        if n == 0:
            cls.objects.filter(topic=topic, level=level).delete()
            return
        mean = sum(points_list) / n
        variance = sum((p - mean) ** 2 for p in points_list) / n if n > 1 else 0
        sigma = variance ** 0.5
        cls.objects.update_or_create(
            topic=topic, level=level,
            defaults={
                'average_points': round(mean, 2),
                'sigma': round(sigma, 2),
                'student_count': n,
            },
        )

    def get_colour_band(self, points):
        """Return Tailwind CSS classes based on student points vs platform average.
        If fewer than 2 students, treat as Average.
        """
        if self.student_count < 2:
            return 'bg-green-200 text-green-900'
        avg = float(self.average_points)
        s = float(self.sigma)
        if s == 0:
            return 'bg-green-200 text-green-900'
        if points > avg + 2 * s:
            return 'bg-green-800 text-white'
        if points > avg + s:
            return 'bg-green-500 text-white'
        if points > avg - s:
            return 'bg-green-200 text-green-900'
        if points > avg - 2 * s:
            return 'bg-yellow-200 text-yellow-900'
        if points > avg - 3 * s:
            return 'bg-orange-200 text-orange-900'
        return 'bg-red-200 text-red-900'

    def get_color_class(self, student_points):
        """
        Determine color class based on student's points relative to average and sigma
        Returns: 'dark-green', 'green', 'light-green', 'yellow', 'orange', 'red'
        """
        if self.sigma == 0 or self.student_count < 2:
            return 'light-green'

        avg = float(self.average_points)
        sigma = float(self.sigma)
        points = float(student_points)

        diff = points - avg

        if diff > 2 * sigma:
            return 'dark-green'
        elif diff > sigma:
            return 'green'
        elif diff > -sigma:
            return 'light-green'
        elif diff > -2 * sigma:
            return 'yellow'
        elif diff > -3 * sigma:
            return 'orange'
        else:
            return 'red'


class StudentFinalAnswer(models.Model):
    """
    Store aggregated results for each quiz attempt.
    One record per attempt (session_id) with attempt_number that increments for each new attempt of the same topic-level.
    """
    QUIZ_TYPE_TOPIC = 'topic'
    QUIZ_TYPE_MIXED = 'mixed'
    QUIZ_TYPE_TIMES_TABLE = 'times_table'
    QUIZ_TYPE_CHOICES = [
        ('topic', 'Topic Quiz'),
        ('mixed', 'Mixed Quiz'),
        ('times_table', 'Times Table'),
    ]

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="maths_final_answers")
    # session_id defaults to a fresh UUID for each new attempt (quiz engine does not need to supply it)
    session_id = models.CharField(max_length=100, default=uuid.uuid4, blank=True, help_text="Session identifier for this attempt")
    topic = models.ForeignKey('classroom.Topic', on_delete=models.SET_NULL, null=True, blank=True, related_name="maths_final_answers")
    level = models.ForeignKey('classroom.Level', on_delete=models.SET_NULL, null=True, blank=True, related_name="maths_final_answers")
    quiz_type = models.CharField(max_length=20, choices=QUIZ_TYPE_CHOICES, default='topic', blank=True)
    operation = models.CharField(max_length=20, default='', blank=True, help_text="Operation for times-table quizzes: 'multiplication' or 'division'")
    table_number = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Times-table number (1-12). Only set for quiz_type='times_table'.")
    attempt_number = models.PositiveIntegerField(default=1, help_text="Attempt number for this student-topic-level combination")
    score = models.PositiveSmallIntegerField(default=0, help_text="Number of correct answers")
    total_questions = models.PositiveSmallIntegerField(default=0, help_text="Total questions in this attempt")
    points = models.FloatField(default=0.0, help_text="Calculated points based on score and time")
    time_taken_seconds = models.PositiveIntegerField(default=0, help_text="Time taken for this attempt in seconds")
    completed_at = models.DateTimeField(default=timezone.now, help_text="When this result was completed")
    # Legacy field retained from consolidation migration — new code uses 'points'
    points_earned = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Legacy: points from consolidation migration")
    shuffled = models.BooleanField(default=False, help_text="Whether the questions were presented in random order")
    # Full per-question review payload (question text + student's answer + the
    # correct answer + correctness) so an attempt can be reviewed later by the
    # student, teacher or parent — mirrors BasicFactsResult.questions_data.
    questions_data = models.JSONField(
        default=list, blank=True,
        help_text="Stores the questions + student answers for later review.",
    )
    last_updated_time = models.DateTimeField(auto_now=True, help_text="Last time this record was updated")

    class Meta:
        ordering = ['-completed_at']
        indexes = [
            models.Index(fields=['student', 'topic', 'level'], name='maths_sfa_topic_level_idx'),
            models.Index(fields=['student', 'topic', 'level', 'attempt_number'], name='maths_sfa_topic_level_att_idx'),
        ]

    def __str__(self):
        return f"{self.student} - {self.level} {self.topic} - Attempt {self.attempt_number}: {self.points} points"

    @property
    def percentage(self):
        """Percentage score (0-100) based on score/total_questions."""
        if not self.total_questions:
            return 0
        return round((self.score / self.total_questions) * 100)

    @classmethod
    def get_next_attempt_number(cls, student, topic, level):
        """
        Get the next attempt number for a student-topic-level combination.
        Uses atomic transaction to prevent race conditions.
        """
        from django.db import transaction
        from django.db.models import Max

        max_retries = 5
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    result = cls.objects.filter(
                        student=student,
                        topic=topic,
                        level=level
                    ).aggregate(max_attempt=Max('attempt_number'))

                    max_attempt = result['max_attempt']
                    if max_attempt is not None:
                        return max_attempt + 1
                    return 1
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                import time
                time.sleep(0.01 * (2 ** attempt))
                continue

        return 1

    @classmethod
    def get_best_result(cls, student, topic, level):
        """Get the best (highest points) result for a student-topic-level combination."""
        return cls.objects.filter(
            student=student,
            topic=topic,
            level=level
        ).order_by('-points').first()

    @classmethod
    def get_latest_attempt(cls, student, topic, level):
        """Get the latest attempt for a student-topic-level combination."""
        return cls.objects.filter(
            student=student,
            topic=topic,
            level=level
        ).order_by('-completed_at').first()

    @classmethod
    def attempt_series_filter(cls, instance):
        """Filter kwargs identifying the attempt *series* an instance belongs to.

        Topic / mixed quizzes are grouped by (student, topic, level); times
        tables by (student, table_number, operation). Including every key keeps
        the three quiz types in separate series so pruning one never touches
        another.
        """
        return {
            'student_id': instance.student_id,
            'topic_id': instance.topic_id,
            'level_id': instance.level_id,
            'quiz_type': instance.quiz_type,
            'table_number': instance.table_number,
            'operation': instance.operation,
            # Shuffled vs ordered times-tables are tracked as distinct series
            # for best/record purposes, so keep their histories separate too.
            'shuffled': instance.shuffled,
        }

    @classmethod
    def prune_old_attempts(cls, instance):
        """Keep only the most recent attempts for ``instance``'s series."""
        from classroom.attempt_retention import prune_to_last_n
        return prune_to_last_n(cls, cls.attempt_series_filter(instance))


class QuestionHealthSnapshot(models.Model):
    """A point-in-time measurement of how sound the question bank is.

    Written by ``manage.py record_question_health`` (cron) and read by the
    super-admin dashboard, mirroring the OpsSnapshot → ops dashboard pattern.

    Snapshots exist so question health can be seen as a *trend*: a single audit
    run tells you today's count, but only a series tells you whether editing is
    outpacing breakage. Rows are small and written at most daily, so they are
    kept rather than pruned.

    "Blocking" issues can mark a student wrong for correct work (CPP-377);
    "advisory" ones cannot, and are tracked separately so a presentation nit
    never dilutes the headline number.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Scope of this run — blank means the whole bank.
    level_number = models.PositiveSmallIntegerField(null=True, blank=True)
    topic = models.ForeignKey(
        'classroom.Topic', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='health_snapshots',
    )

    # Population
    total_questions = models.PositiveIntegerField(default=0)
    choice_questions = models.PositiveIntegerField(default=0)
    typed_questions = models.PositiveIntegerField(
        default=0,
        help_text='Short-answer / calculation questions scanned (CPP-378). '
                  'Previously unmeasured, so health read better than it was.')

    # Coverage — how much of the bank the audit could actually judge.
    arithmetic_verified = models.PositiveIntegerField(
        default=0, help_text='Questions whose own maths was evaluated and checked.')
    unverifiable = models.PositiveIntegerField(
        default=0, help_text='Word problems etc. that need a human.')

    # Findings
    questions_blocking = models.PositiveIntegerField(
        default=0, help_text='Questions with an issue that can mismark a student.')
    questions_advisory = models.PositiveIntegerField(
        default=0, help_text='Questions with only non-mismarking issues.')

    # Per-code counts, so the dashboard can show what is actually wrong.
    # Keyed by the issue codes in maths.answer_verification.
    issue_counts = models.JSONField(
        default=dict, blank=True,
        help_text="e.g. {'EQUIVALENT-OPTION': 14, 'WRONG-ANSWER-KEY': 2}")

    # Enough detail to jump straight to the offending questions.
    flagged_questions = models.JSONField(
        default=list, blank=True,
        help_text="[{'id': 6017, 'codes': ['EQUIVALENT-OPTION'], 'text': '...'}]")

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'question health snapshot'

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} — {self.questions_blocking} blocking'

    @property
    def health_percent(self):
        """Share of *audited* questions with no blocking issue, 0-100.

        Audited means choice + typed: questions_blocking counts both since
        CPP-378, so dividing by the choice count alone reported a bank with two
        broken typed answers and no choice questions as 100% healthy.
        """
        audited = self.choice_questions + self.typed_questions
        if not audited:
            return 100
        sound = max(0, audited - self.questions_blocking)
        return round(sound / audited * 100, 1)

    @property
    def coverage_percent(self):
        """Share of choice questions whose maths could be machine-checked.

        Deliberately separate from health: a 100% healthy bank that could only
        be verified 16% deep is not the same claim, and collapsing the two
        would overstate what is actually known.
        """
        if not self.choice_questions:
            return 0
        return round(self.arithmetic_verified / self.choice_questions * 100, 1)

    @property
    def status(self):
        if self.questions_blocking:
            return 'crit'
        if self.questions_advisory:
            return 'warn'
        return 'ok'


class QuestionAIReview(models.Model):
    """One semantic review of one question by an independent model (CPP-380).

    The deterministic audits prove things about the data — a distractor equal to
    the answer, an answer key that fails its own arithmetic. They cannot judge
    whether a question is *sensible*: ambiguous wording, an answer that does not
    follow from the stem, information missing from a word problem.

    This is the record of a model having looked. It is deliberately a *review*,
    not a verdict on truth: two models agreeing is a second opinion, and the
    row exists to route a human's attention, never to bless content. Nothing in
    this app edits question text on the strength of it.

    The row is the single source of truth for review state — there is no
    denormalised flag on Question to drift out of sync. ``question_updated_at``
    snapshots the content version reviewed, so an edit after review makes the
    review stale rather than silently vouching for text nobody checked.
    """

    VERDICT_OK = 'ok'
    VERDICT_FLAGGED = 'flagged'
    VERDICT_ERROR = 'error'
    VERDICT_CHOICES = [
        (VERDICT_OK, 'Reviewed — no objection'),
        (VERDICT_FLAGGED, 'Flagged for human review'),
        (VERDICT_ERROR, 'Review failed'),
    ]

    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name='ai_reviews')
    reviewed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    verdict = models.CharField(max_length=10, choices=VERDICT_CHOICES)
    reason = models.TextField(
        blank=True, default='',
        help_text='Short human-readable explanation, shown to whoever triages.')

    # Which content version this review applies to. Compared against
    # Question.updated_at to detect a review made stale by a later edit.
    question_updated_at = models.DateTimeField(null=True, blank=True)

    # Two-tier review: a cheap model looks at everything, and only what it
    # doubts is escalated. Recorded so the escalation rate — the thing that
    # actually drives cost — is measurable after the fact.
    first_pass_model = models.CharField(max_length=100, blank=True, default='')
    adjudicator_model = models.CharField(max_length=100, blank=True, default='')
    escalated = models.BooleanField(default=False)

    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    # Null when the model's rate is not configured — tokens are always known,
    # cost is not, and guessing it would make the budget ceiling a lie.
    cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ['-reviewed_at']
        indexes = [models.Index(fields=['question', '-reviewed_at'])]
        verbose_name = 'question AI review'

    def __str__(self):
        return f'Q{self.question_id} — {self.get_verdict_display()}'

    @property
    def is_stale(self):
        """True if the question was edited after this review was made."""
        if not self.question_updated_at or not self.question.updated_at:
            return False
        return self.question.updated_at > self.question_updated_at
