from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid
from brainbuzz.managers import CodingExercisesManager


def calculate_coding_points(
    passed_tests,
    total_tests,
    time_taken_seconds,
    quality_score: float = 1.0,
    k: float = 2.0,
) -> float:
    """Calculate attempt points for a single submission.

    Formula:
        base   = (passed / total) × 100 × (K / (K + time_per_test))
        result = base × quality_score

    Components
    ----------
    accuracy      Primary driver.  A partial pass scores proportionally.
    speed bonus   Diminishing-returns multiplier.  K=2 means the bonus
                  halves when the average server-measured round-trip time
                  per test case reaches 2 s.  Typical Piston runtimes are
                  0.05–0.5 s, so an O(n²) solution (e.g. 1–2 s/test) scores
                  noticeably lower than an O(n log n) one (e.g. 0.05 s/test):
                    0.05 s → K/(K+0.05) ≈ 97.6 %  →  ~98 pts
                    1.00 s → K/(K+1.00) ≈ 66.7 %  →  ~67 pts
                    2.00 s → K/(K+2.00)  = 50.0 %  →  ~50 pts
    quality_score Fraction in [0.70, 1.00] produced by analyse_code_quality().
                  A clean, efficient solution earns 1.00; one with deeply
                  nested loops or high cyclomatic complexity earns less.
                  Always ≥ 0.70 so a correct solution never falls below 70 pts
                  for quality reasons alone.

    The caller (api_submit_problem) is responsible for preserving the
    student's best-ever score separately; this function always returns
    the raw score for the current attempt only.
    """
    if not total_tests:
        return 0.0
    percentage = passed_tests / total_tests
    time_per_test = time_taken_seconds / total_tests if total_tests else time_taken_seconds
    base = percentage * 100 * (k / (k + time_per_test))
    return round(base * quality_score, 2)


# ---------------------------------------------------------------------------
# Language & Topic catalogue
# ---------------------------------------------------------------------------

class CodingLanguage(models.Model):
    """Supported coding languages (Python, JavaScript, HTML/CSS, Scratch)."""

    PYTHON = 'python'
    JAVASCRIPT = 'javascript'
    HTML = 'html'
    CSS = 'css'
    SCRATCH = 'scratch'

    LANGUAGE_CHOICES = [
        (PYTHON, 'Python'),
        (JAVASCRIPT, 'JavaScript'),
        (HTML, 'HTML'),
        (CSS, 'CSS'),
        (SCRATCH, 'Scratch'),
    ]

    # Maps slug → Piston API language identifier
    # Note: Piston calls Node.js "node", not "javascript"
    PISTON_LANGUAGE_MAP = {
        PYTHON: 'python',
        JAVASCRIPT: 'javascript',
        HTML: None,       # browser-side iframe sandbox — no Piston call
        CSS: None,        # browser-side iframe sandbox — no Piston call
        SCRATCH: None,    # MIT Scratch VM — no Piston call
    }

    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50, unique=True, choices=LANGUAGE_CHOICES)
    description = models.TextField(blank=True)
    icon_name = models.CharField(max_length=50, blank=True, help_text="Icon identifier used in templates")
    color = models.CharField(max_length=30, blank=True, help_text="Tailwind color class, e.g. 'blue-500'")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    @property
    def piston_language(self):
        """Return the Piston API language identifier, or None if not applicable."""
        return self.PISTON_LANGUAGE_MAP.get(self.slug)

    @property
    def uses_browser_sandbox(self):
        """True for HTML or CSS (including legacy html-css slug) — rendered in a sandboxed iframe."""
        return self.slug in (self.HTML, self.CSS, 'html-css')

    @property
    def uses_scratch_vm(self):
        """True for Scratch — handled by MIT Scratch editor embed."""
        return self.slug == self.SCRATCH


class CodingTopic(models.Model):
    """A topic within a language, e.g. Variables, Loops, Functions."""

    language = models.ForeignKey(CodingLanguage, on_delete=models.CASCADE, related_name='topics')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['language', 'order', 'name']
        unique_together = ('language', 'slug')

    def __str__(self):
        return f"{self.language.name} — {self.name}"


# ---------------------------------------------------------------------------
# Topic Exercises  (structured learning, beginner → advanced)
# ---------------------------------------------------------------------------

class TopicLevel(models.Model):
    """A topic at a specific difficulty level (Beginner / Intermediate / Advanced).

    Acts as the join point between CodingTopic and CodingExercise.
    One TopicLevel row is created for every (topic, level) combination that
    has at least one exercise — created on-demand by the seeder and upload tool.
    """

    BEGINNER     = 'beginner'
    INTERMEDIATE = 'intermediate'
    ADVANCED     = 'advanced'

    LEVEL_CHOICES = [
        (BEGINNER,     'Beginner'),
        (INTERMEDIATE, 'Intermediate'),
        (ADVANCED,     'Advanced'),
    ]

    LEVEL_ORDER = {BEGINNER: 1, INTERMEDIATE: 2, ADVANCED: 3}

    topic        = models.ForeignKey(CodingTopic, on_delete=models.CASCADE, related_name='topic_levels')
    level_choice = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    is_active    = models.BooleanField(default=True)
    order        = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ('topic', 'level_choice')
        ordering        = ['topic', 'level_choice']

    def __str__(self):
        return f"{self.topic} [{self.get_level_choice_display()}]"

    @classmethod
    def get_or_create_for(cls, topic, level_choice):
        """Return (TopicLevel, created) for the given topic + level, creating if needed."""
        return cls.objects.get_or_create(topic=topic, level_choice=level_choice)


class CodingExercise(models.Model):
    """A single coding exercise within a topic at a given level.

    The topic and difficulty level are stored via the ``topic_level`` FK to
    :class:`TopicLevel` rather than as separate flat fields.  Use the
    ``topic`` and ``level`` properties for read access; use ORM traversal
    (``topic_level__topic``, ``topic_level__level_choice``) for filtering.

    ``question_type`` defaults to ``write_code`` so all existing exercises
    behave exactly as before.  MCQ/TF/short-answer exercises expose answer
    options via the related ``CodingAnswer`` model.
    """

    # Level constants and choices mirrored from TopicLevel for backwards compat.
    BEGINNER     = TopicLevel.BEGINNER
    INTERMEDIATE = TopicLevel.INTERMEDIATE
    ADVANCED     = TopicLevel.ADVANCED
    LEVEL_CHOICES = TopicLevel.LEVEL_CHOICES
    LEVEL_ORDER   = TopicLevel.LEVEL_ORDER

    # Question type — write_code is the historical default (non-breaking).
    WRITE_CODE        = 'write_code'
    MULTIPLE_CHOICE   = 'multiple_choice'
    TRUE_FALSE        = 'true_false'
    SHORT_ANSWER      = 'short_answer'
    FILL_BLANK        = 'fill_blank'

    QUESTION_TYPE_CHOICES = [
        (WRITE_CODE,      'Write Code'),
        (MULTIPLE_CHOICE, 'Multiple Choice'),
        (TRUE_FALSE,      'True / False'),
        (SHORT_ANSWER,    'Short Answer'),
        (FILL_BLANK,      'Fill in the Blank'),
    ]

    topic_level       = models.ForeignKey(TopicLevel, on_delete=models.CASCADE, related_name='exercises')
    title             = models.CharField(max_length=200)
    description       = models.TextField(help_text="Instructions shown to the student")
    starter_code      = models.TextField(blank=True, help_text="Pre-filled code shown in the editor when the student opens the exercise")
    solution_code     = models.TextField(blank=True, help_text="Reference solution — shown only to teachers, never to students")
    expected_output   = models.TextField(blank=True, help_text="Expected stdout for simple output-matching exercises (leave blank for free-form exercises)")
    hints             = models.TextField(blank=True, help_text="Optional hint text shown on request")
    order             = models.PositiveSmallIntegerField(default=0)
    is_active         = models.BooleanField(default=True)
    uses_browser_sandbox = models.BooleanField(
        default=False,
        help_text=(
            "Override execution environment for this exercise. "
            "When True, the editor renders an iframe sandbox instead of sending code to Piston. "
            "Use for DOM/HTML-in-JS exercises that belong to a non-browser language topic (e.g. JavaScript DOM Basics)."
        ),
    )
    question_type = models.CharField(
        max_length=20,
        choices=QUESTION_TYPE_CHOICES,
        default=WRITE_CODE,
        help_text=(
            "write_code (default) keeps existing behaviour. "
            "Other types expose MCQ/TF/short-answer options via CodingAnswer and "
            "allow the exercise to be used in BrainBuzz sessions."
        ),
    )
    correct_short_answer = models.TextField(
        null=True,
        blank=True,
        help_text="Required for short_answer and fill_blank question types. Unused for other types.",
    )
    school = models.ForeignKey(
        'classroom.School',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='coding_exercises',
        help_text='Null = global/shared exercise. Set = private to this school only.',
    )
    department = models.ForeignKey(
        'classroom.Department',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='coding_exercises',
        help_text='Null = not department-scoped. Set = visible to this department only.',
    )
    classroom = models.ForeignKey(
        'classroom.ClassRoom',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='coding_exercises',
        help_text='Null = not class-scoped. Set = visible to this class only.',
    )
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    # Custom manager for visibility filtering
    objects = CodingExercisesManager()

    class Meta:
        ordering = ['topic_level__topic', 'topic_level__level_choice', 'order']

    def __str__(self):
        return f"{self.topic_level} — {self.title}"

    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}
        qt = self.question_type

        if qt == self.WRITE_CODE:
            has_code = bool(
                (self.starter_code or '').strip()
                or (self.expected_output or '').strip()
                or self.uses_browser_sandbox
            )
            if not has_code:
                errors['starter_code'] = (
                    "write_code exercises require starter_code, expected_output, "
                    "or uses_browser_sandbox."
                )
            if (self.correct_short_answer or '').strip():
                errors['correct_short_answer'] = (
                    "correct_short_answer is only for short_answer and fill_blank types."
                )

        elif qt in (self.SHORT_ANSWER, self.FILL_BLANK):
            if not (self.correct_short_answer or '').strip():
                errors['correct_short_answer'] = (
                    f"{self.get_question_type_display()} requires a non-empty correct_short_answer."
                )

        if self.pk:
            answer_qs   = self.answers.all()
            n_answers   = answer_qs.count()
            n_correct   = answer_qs.filter(is_correct=True).count()

            if qt in (self.WRITE_CODE, self.SHORT_ANSWER, self.FILL_BLANK):
                if n_answers > 0:
                    errors['question_type'] = (
                        f"{self.get_question_type_display()} exercises must not have answer choices."
                    )

            elif qt == self.MULTIPLE_CHOICE:
                if n_answers < 2:
                    errors.setdefault('question_type', (
                        "Multiple-choice exercises require at least 2 answer choices."
                    ))
                if n_correct == 0:
                    errors['question_type'] = (
                        "Multiple-choice exercises require exactly one correct answer (found 0)."
                    )
                elif n_correct > 1:
                    errors['question_type'] = (
                        f"Multiple-choice exercises require exactly one correct answer (found {n_correct})."
                    )

            elif qt == self.TRUE_FALSE:
                if n_answers != 2:
                    errors['question_type'] = (
                        f"True/False exercises require exactly 2 answer choices (found {n_answers})."
                    )
                elif n_correct != 1:
                    errors['question_type'] = (
                        f"True/False exercises require exactly 1 correct answer (found {n_correct})."
                    )

        if errors:
            raise ValidationError(errors)

    # ------------------------------------------------------------------
    # Convenience properties — read-only shorthand for templates / code
    # ------------------------------------------------------------------

    @property
    def topic(self):
        """Shorthand for ``self.topic_level.topic``."""
        return self.topic_level.topic

    @property
    def level(self):
        """Shorthand for ``self.topic_level.level_choice``."""
        return self.topic_level.level_choice

    def get_level_display(self):
        """Mimic Django's auto-generated get_FOO_display() for backwards compat."""
        return self.topic_level.get_level_choice_display()

    @property
    def level_order(self):
        return self.LEVEL_ORDER.get(self.level, 0)


class CodingAnswer(models.Model):
    """Answer option for a CodingExercise with question_type != write_code.

    Mirrors maths.Answer so the BrainBuzz pipeline can treat both subjects
    uniformly.  Exercises with question_type == write_code ignore this table.
    """

    exercise    = models.ForeignKey(
        CodingExercise,
        on_delete=models.CASCADE,
        related_name='answers',
        db_column='coding_exercise_id',  # actual DB column name from prior branch
    )
    answer_text = models.TextField()
    is_correct  = models.BooleanField(default=False)
    order       = models.PositiveSmallIntegerField(default=0)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['exercise', 'order']

    def __str__(self):
        correct = ' ✓' if self.is_correct else ''
        return f"{self.exercise.title} — {self.answer_text[:60]}{correct}"


# ---------------------------------------------------------------------------
# Problem Solving  (algorithm / logic problems, difficulty 1–8)
# ---------------------------------------------------------------------------

class CodingProblem(models.Model):
    """An algorithm or logic problem students solve by writing their own code.

    Problems are language-agnostic: the student picks the language when they
    submit.  The optional ``language`` FK is kept for legacy compatibility and
    for problems that are intentionally language-specific, but new problems
    should leave it null.
    """

    ALGORITHM = 'algorithm'
    LOGIC = 'logic'
    DATA_STRUCTURES = 'data_structures'
    DYNAMIC_PROGRAMMING = 'dynamic_programming'
    GRAPH_THEORY = 'graph_theory'
    STRING_MANIPULATION = 'string_manipulation'
    MATHEMATICS = 'mathematics'
    SORTING_SEARCHING = 'sorting_searching'

    CATEGORY_CHOICES = [
        (ALGORITHM,            'Algorithm'),
        (LOGIC,                'Logic'),
        (DATA_STRUCTURES,      'Data Structures'),
        (DYNAMIC_PROGRAMMING,  'Dynamic Programming'),
        (GRAPH_THEORY,         'Graph Theory'),
        (STRING_MANIPULATION,  'String Manipulation'),
        (MATHEMATICS,          'Mathematics'),
        (SORTING_SEARCHING,    'Sorting & Searching'),
    ]

    # Optional: kept for legacy / language-specific problems only.
    language = models.ForeignKey(
        CodingLanguage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='problems',
        help_text="Leave blank for language-agnostic problems (students choose on submit).",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(
        help_text="Full problem statement shown to the student, including input/output format",
    )
    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default=ALGORITHM,
        help_text="Problem category used for filtering and grouping",
    )
    constraints = models.TextField(
        blank=True,
        help_text="Constraints on input size, value ranges, etc. (e.g. '1 ≤ n ≤ 10⁶')",
    )
    time_limit_seconds = models.PositiveSmallIntegerField(
        default=5,
        help_text="Maximum wall-clock execution time allowed per test case (seconds)",
    )
    memory_limit_mb = models.PositiveSmallIntegerField(
        default=256,
        help_text="Maximum memory allowed per test case (megabytes)",
    )
    starter_code = models.TextField(blank=True, help_text="Skeleton code to give students a starting point")
    solution_code = models.TextField(blank=True, help_text="Reference solution — never exposed to students")
    forbidden_code_patterns = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of forbidden source-code substrings for this problem, e.g. "
            "['sorted(', '.sort('] for Bubble Sort. A submission containing any "
            "forbidden pattern fails immediately with zero points."
        ),
    )
    difficulty = models.PositiveSmallIntegerField(
        default=1,
        help_text="Difficulty level 1 (easiest) to 8 (hardest)",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['difficulty', 'title']

    def __str__(self):
        lang = f"{self.language.name} — " if self.language_id else ""
        return f"{lang}Level {self.difficulty}: {self.title}"

    @property
    def visible_test_cases(self):
        return self.test_cases.filter(is_visible=True)

    @property
    def hidden_test_cases(self):
        return self.test_cases.filter(is_visible=False)

    @property
    def total_test_cases(self):
        return self.test_cases.count()


class ProblemTestCase(models.Model):
    """A single test case for a CodingProblem.

    Visible test cases (is_visible=True) are shown in full to the student as
    sample cases.  Hidden test cases are run server-side; the student only sees
    a pass/fail count.  Boundary/edge-value tests should be marked with both
    ``is_visible=False`` and ``is_boundary_test=True``.

    Each problem must have at least 2 visible test cases.
    """

    problem = models.ForeignKey(CodingProblem, on_delete=models.CASCADE, related_name='test_cases')
    input_data = models.TextField(
        blank=True,
        help_text="stdin passed to the student's program (leave blank if no input needed)",
    )
    expected_output = models.TextField(
        help_text="Expected stdout (stripped of trailing whitespace during comparison)",
    )
    is_visible = models.BooleanField(
        default=True,
        help_text="True = shown to student as a sample case. False = hidden boundary/edge case.",
    )
    is_boundary_test = models.BooleanField(
        default=False,
        help_text="True for boundary / edge-value test cases (e.g. empty input, max constraints).",
    )
    description = models.CharField(
        max_length=200,
        blank=True,
        help_text="Short label, e.g. 'Empty list input' or 'Maximum constraint'",
    )
    display_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Controls the order test cases are displayed / run",
    )

    class Meta:
        ordering = ['problem', 'display_order', 'id']

    def __str__(self):
        visibility = "Visible" if self.is_visible else "Hidden"
        boundary = " [boundary]" if self.is_boundary_test else ""
        return f"{self.problem.title} — Test {self.display_order} ({visibility}{boundary})"


# ---------------------------------------------------------------------------
# Student Submissions
# ---------------------------------------------------------------------------

class StudentExerciseSubmission(models.Model):
    """Records each time a student runs/submits code for a topic exercise."""

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='coding_exercise_submissions')
    exercise = models.ForeignKey(CodingExercise, on_delete=models.CASCADE, related_name='submissions')
    code_submitted = models.TextField()
    output_received = models.TextField(blank=True, help_text="stdout returned by the code executor")
    stderr_received = models.TextField(blank=True, help_text="stderr returned by the code executor")
    is_completed = models.BooleanField(default=False, help_text="True once the student marks the exercise as done or output matches expected")
    time_taken_seconds = models.PositiveIntegerField(default=0, help_text="Time spent on this submission in seconds")
    submitted_at = models.DateTimeField(auto_now_add=True)

    # Scratch / Blockly exercises store the workspace state as serialised XML
    # so the student's block program can be restored on next visit.
    # Empty for Python/JS/HTML/CSS exercises.
    blocks_xml = models.TextField(
        blank=True,
        help_text="Blockly workspace XML for Scratch block exercises (empty for text-based languages)",
    )

    class Meta:
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['student', 'exercise'], name='coding_ses_stu_ex_idx'),
        ]

    def __str__(self):
        status = "Completed" if self.is_completed else "In progress"
        return f"{self.student} — {self.exercise.title} ({status})"

    @classmethod
    def is_exercise_completed(cls, student, exercise):
        """Check whether a student has successfully completed an exercise."""
        return cls.objects.filter(student=student, exercise=exercise, is_completed=True).exists()


class StudentProblemSubmission(models.Model):
    """Records each attempt a student makes on an algorithm problem.

    One record per submission. Multiple submissions are allowed; attempt_number
    increments per student-problem combination, mirroring StudentFinalAnswer in maths.
    """

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='coding_problem_submissions')
    problem = models.ForeignKey(CodingProblem, on_delete=models.CASCADE, related_name='submissions')
    session_id = models.CharField(max_length=100, default=uuid.uuid4, blank=True, help_text="Unique identifier for this submission session")
    attempt_number = models.PositiveIntegerField(default=1, help_text="Attempt number for this student-problem combination")
    code_submitted = models.TextField()

    # Test result summary
    passed_all_tests = models.BooleanField(default=False, help_text="True only when every test case (visible + hidden) passes")
    visible_passed = models.PositiveSmallIntegerField(default=0, help_text="Number of visible test cases passed")
    visible_total = models.PositiveSmallIntegerField(default=0)
    hidden_passed = models.PositiveSmallIntegerField(default=0, help_text="Number of hidden test cases passed")
    hidden_total = models.PositiveSmallIntegerField(default=0)

    # Detailed per-test results (shown for visible tests only)
    test_results = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of dicts: {test_case_id, is_visible, passed, actual_output, expected_output}. "
            "actual_output is only stored for visible test cases."
        ),
    )

    # Scoring (mirrors maths pattern)
    points = models.FloatField(default=0.0, help_text="Points awarded based on tests passed and time taken")
    time_taken_seconds = models.PositiveIntegerField(default=0, help_text="Time from opening problem to submission")
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['student', 'problem'], name='coding_sps_stu_prob_idx'),
            models.Index(fields=['student', 'problem', 'attempt_number'], name='coding_sps_stu_prob_att_idx'),
        ]

    def __str__(self):
        status = "PASS" if self.passed_all_tests else "FAIL"
        return f"{self.student} — {self.problem.title} Attempt {self.attempt_number} [{status}]"

    @property
    def total_passed(self):
        return self.visible_passed + self.hidden_passed

    @property
    def total_tests(self):
        return self.visible_total + self.hidden_total

    @property
    def percentage(self):
        if not self.total_tests:
            return 0
        return round((self.total_passed / self.total_tests) * 100)

    @classmethod
    def get_next_attempt_number(cls, student, problem):
        """Return the next sequential attempt number for a student-problem pair.

        Uses atomic transaction to prevent race conditions, mirroring
        StudentFinalAnswer.get_next_attempt_number() in maths.
        """
        from django.db import transaction
        from django.db.models import Max

        max_retries = 5
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    result = cls.objects.filter(
                        student=student,
                        problem=problem,
                    ).aggregate(max_attempt=Max('attempt_number'))
                    max_attempt = result['max_attempt']
                    return (max_attempt + 1) if max_attempt is not None else 1
            except Exception:
                if attempt == max_retries - 1:
                    raise
                import time
                time.sleep(0.01 * (2 ** attempt))
        return 1

    @classmethod
    def get_best_result(cls, student, problem):
        """Return the highest-scoring submission for a student-problem pair."""
        return cls.objects.filter(student=student, problem=problem).order_by('-points').first()

    @classmethod
    def get_best_points(cls, student, problem):
        """Return the highest points ever scored by this student on this problem.

        Used to ensure re-submissions of a correct solution never reduce the
        student's awarded score.  Returns 0.0 if no passing submission exists.
        """
        from django.db.models import Max
        result = cls.objects.filter(
            student=student,
            problem=problem,
            passed_all_tests=True,
        ).aggregate(best=Max('points'))
        return result['best'] or 0.0

    @classmethod
    def has_solved(cls, student, problem):
        """True if the student has at least one passing submission."""
        return cls.objects.filter(student=student, problem=problem, passed_all_tests=True).exists()


# ---------------------------------------------------------------------------
# Problem Solving — structured submission + per-test-case results
# ---------------------------------------------------------------------------

class ProblemSubmission(models.Model):
    """One student attempt on a CodingProblem.

    Complements StudentProblemSubmission (which is used for scoring/history)
    by providing a clean, spec-compliant record per the Problem Solving data model:
    explicit status enum, per-language tracking, and normalised result rows via
    ProblemSubmissionResult rather than a JSON blob.
    """

    PENDING = 'pending'
    PASSED  = 'passed'
    FAILED  = 'failed'

    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (PASSED,  'Passed'),
        (FAILED,  'Failed'),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='problem_submissions',
    )
    problem = models.ForeignKey(
        CodingProblem,
        on_delete=models.CASCADE,
        related_name='problem_submissions',
    )
    language = models.ForeignKey(
        CodingLanguage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='problem_submissions',
        help_text="Language the student chose for this submission",
    )
    submitted_code = models.TextField(help_text="Exact code submitted by the student")
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=PENDING,
        db_index=True,
    )
    test_cases_passed = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of test cases (visible + hidden) that passed",
    )
    total_test_cases = models.PositiveSmallIntegerField(
        default=0,
        help_text="Total number of test cases evaluated",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['student', 'problem'], name='coding_ps_stu_prob_idx'),
            models.Index(fields=['student', 'problem', 'status'], name='coding_ps_stu_prob_st_idx'),
        ]

    def __str__(self):
        lang = self.language.name if self.language_id else 'Unknown'
        return (
            f"{self.student} — {self.problem.title} "
            f"[{lang}] {self.get_status_display()} "
            f"({self.test_cases_passed}/{self.total_test_cases})"
        )

    @property
    def pass_rate(self):
        if not self.total_test_cases:
            return 0
        return round((self.test_cases_passed / self.total_test_cases) * 100)

    @classmethod
    def get_best_submission(cls, student, problem):
        """Return the submission with the highest test_cases_passed for this student/problem."""
        return (
            cls.objects
            .filter(student=student, problem=problem)
            .order_by('-test_cases_passed', '-submitted_at')
            .first()
        )

    @classmethod
    def has_passed(cls, student, problem):
        """True if the student has at least one fully-passing submission."""
        return cls.objects.filter(
            student=student, problem=problem, status=cls.PASSED,
        ).exists()


class ProblemSubmissionResult(models.Model):
    """Per-test-case execution result for a single ProblemSubmission.

    One row per (submission, test_case) pair.  Replaces the JSON blob used in
    StudentProblemSubmission.test_results, enabling proper querying and admin
    drill-down.
    """

    submission = models.ForeignKey(
        ProblemSubmission,
        on_delete=models.CASCADE,
        related_name='results',
    )
    test_case = models.ForeignKey(
        ProblemTestCase,
        on_delete=models.CASCADE,
        related_name='submission_results',
    )
    actual_output = models.TextField(
        blank=True,
        help_text="stdout captured from the student's program for this test case",
    )
    is_passed = models.BooleanField(default=False)
    execution_time_ms = models.PositiveIntegerField(
        default=0,
        help_text="Wall-clock execution time in milliseconds as reported by Piston",
    )

    class Meta:
        ordering = ['submission', 'test_case__display_order']
        unique_together = ('submission', 'test_case')
        indexes = [
            models.Index(fields=['submission', 'is_passed'], name='coding_psr_sub_passed_idx'),
        ]

    def __str__(self):
        result = "PASS" if self.is_passed else "FAIL"
        return (
            f"Submission {self.submission_id} / "
            f"Test {self.test_case.display_order} [{result}] "
            f"{self.execution_time_ms}ms"
        )


# ---------------------------------------------------------------------------
# Time Tracking  (mirrors maths.TimeLog)
# ---------------------------------------------------------------------------

class CodingTimeLog(models.Model):
    """Track daily and weekly time a student spends in the Coding app."""

    student = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='coding_time_log')
    daily_total_seconds = models.PositiveIntegerField(default=0)
    weekly_total_seconds = models.PositiveIntegerField(default=0)
    last_reset_date = models.DateField(auto_now=True)
    last_reset_week = models.IntegerField(default=0, help_text="Year-encoded ISO week of last weekly reset (year * 100 + week, e.g. 202615)")
    last_activity = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_activity']

    def __str__(self):
        return f"{self.student.username} — Coding: Daily {self.daily_total_seconds}s / Weekly {self.weekly_total_seconds}s"

    def reset_daily_if_needed(self):
        from django.utils.timezone import localtime
        today = localtime(timezone.now()).date()
        if self.last_reset_date < today:
            self.daily_total_seconds = 0
            self.last_reset_date = today
            self.save(update_fields=['daily_total_seconds', 'last_reset_date'])

    def reset_weekly_if_needed(self):
        from django.utils.timezone import localtime
        iso = localtime(timezone.now()).isocalendar()
        current_week = iso[0] * 100 + iso[1]   # e.g. 202615 — unique per year
        if self.last_reset_week != current_week:
            self.weekly_total_seconds = 0
            self.last_reset_week = current_week
            self.save(update_fields=['weekly_total_seconds', 'last_reset_week'])


# ---------------------------------------------------------------------------
# Performance Statistics  (mirrors maths.TopicLevelStatistics)
# ---------------------------------------------------------------------------

class CodingTopicStatistics(models.Model):
    """Store average and standard deviation of exercise completion per topic-level.

    Used to colour-band student performance on the progress dashboard,
    mirroring TopicLevelStatistics in the maths app.
    """

    topic = models.ForeignKey(CodingTopic, on_delete=models.CASCADE, related_name='statistics')
    level = models.CharField(max_length=20, choices=CodingExercise.LEVEL_CHOICES)
    average_points = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sigma = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Standard deviation")
    student_count = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('topic', 'level')
        ordering = ['topic', 'level']
        indexes = [
            models.Index(fields=['topic', 'level'], name='coding_cts_topic_level_idx'),
        ]

    def __str__(self):
        return f"{self.topic} [{self.level}]: avg={self.average_points}, σ={self.sigma} (n={self.student_count})"

    def get_colour_band(self, points):
        """Return Tailwind CSS classes based on student points vs platform average.
        Mirrors TopicLevelStatistics.get_colour_band() in maths.
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