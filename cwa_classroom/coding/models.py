from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid


def calculate_coding_points(passed_tests, total_tests, time_taken_seconds, k=30):
    """Calculate problem points balancing accuracy and speed.

    Mirrors maths.calculate_points() — percentage of passed tests × speed bonus.
    Formula: percentage * 100 * (K / (K + time_per_test))

    - Accuracy (tests passed) is the primary driver
    - Speed gives a diminishing-returns bonus
    - K controls speed weight (lower = speed matters more)
    """
    if not total_tests:
        return 0.0
    percentage = passed_tests / total_tests
    time_per_test = time_taken_seconds / total_tests if total_tests else time_taken_seconds
    return round(percentage * 100 * (k / (k + time_per_test)), 2)


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

class CodingExercise(models.Model):
    """A single coding exercise within a topic at a given level."""

    BEGINNER = 'beginner'
    INTERMEDIATE = 'intermediate'
    ADVANCED = 'advanced'

    LEVEL_CHOICES = [
        (BEGINNER, 'Beginner'),
        (INTERMEDIATE, 'Intermediate'),
        (ADVANCED, 'Advanced'),
    ]

    LEVEL_ORDER = {BEGINNER: 1, INTERMEDIATE: 2, ADVANCED: 3}

    topic = models.ForeignKey(CodingTopic, on_delete=models.CASCADE, related_name='exercises')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=BEGINNER)
    title = models.CharField(max_length=200)
    description = models.TextField(help_text="Instructions shown to the student")
    starter_code = models.TextField(blank=True, help_text="Pre-filled code shown in the editor when the student opens the exercise")
    solution_code = models.TextField(blank=True, help_text="Reference solution — shown only to teachers, never to students")
    expected_output = models.TextField(blank=True, help_text="Expected stdout for simple output-matching exercises (leave blank for free-form exercises)")
    hints = models.TextField(blank=True, help_text="Optional hint text shown on request")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['topic', 'level', 'order']

    def __str__(self):
        return f"{self.topic} [{self.get_level_display()}] — {self.title}"

    @property
    def level_order(self):
        return self.LEVEL_ORDER.get(self.level, 0)


# ---------------------------------------------------------------------------
# Problem Solving  (algorithm / logic problems, difficulty 1–8)
# ---------------------------------------------------------------------------

class CodingProblem(models.Model):
    """An algorithm or logic problem students solve by writing their own code."""

    language = models.ForeignKey(CodingLanguage, on_delete=models.CASCADE, related_name='problems')
    title = models.CharField(max_length=200)
    description = models.TextField(help_text="Full problem statement shown to the student, including input/output format")
    starter_code = models.TextField(blank=True, help_text="Skeleton code to give students a starting point")
    solution_code = models.TextField(blank=True, help_text="Reference solution — never exposed to students")
    difficulty = models.PositiveSmallIntegerField(
        default=1,
        help_text="Difficulty level 1 (easiest) to 8 (hardest)",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['language', 'difficulty', 'title']

    def __str__(self):
        return f"{self.language.name} — Level {self.difficulty}: {self.title}"

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

    Visible test cases (is_visible=True) are shown in full to the student.
    Hidden test cases are evaluated server-side; the student only sees pass/fail count.
    Always include boundary value test cases as hidden cases.
    """

    problem = models.ForeignKey(CodingProblem, on_delete=models.CASCADE, related_name='test_cases')
    input_data = models.TextField(blank=True, help_text="stdin passed to the student's program (leave blank if no input needed)")
    expected_output = models.TextField(help_text="Expected stdout (stripped of trailing whitespace during comparison)")
    is_visible = models.BooleanField(
        default=True,
        help_text="True = shown to student as a sample. False = hidden boundary/edge case.",
    )
    description = models.CharField(max_length=200, blank=True, help_text="Short label, e.g. 'Empty list input'")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['problem', 'order', 'id']

    def __str__(self):
        visibility = "Visible" if self.is_visible else "Hidden"
        return f"{self.problem.title} — Test {self.order} ({visibility})"


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
    def has_solved(cls, student, problem):
        """True if the student has at least one passing submission."""
        return cls.objects.filter(student=student, problem=problem, passed_all_tests=True).exists()


# ---------------------------------------------------------------------------
# Time Tracking  (mirrors maths.TimeLog)
# ---------------------------------------------------------------------------

class CodingTimeLog(models.Model):
    """Track daily and weekly time a student spends in the Coding app."""

    student = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='coding_time_log')
    daily_total_seconds = models.PositiveIntegerField(default=0)
    weekly_total_seconds = models.PositiveIntegerField(default=0)
    last_reset_date = models.DateField(auto_now=True)
    last_reset_week = models.IntegerField(default=0, help_text="ISO week number of last weekly reset")
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
        current_week = localtime(timezone.now()).isocalendar()[1]
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