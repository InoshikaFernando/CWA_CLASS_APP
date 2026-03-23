from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid


def generate_class_code():
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


class Topic(models.Model):
    name = models.CharField(max_length=120)

    def __str__(self):
        return self.name


class Level(models.Model):
    topics = models.ManyToManyField(Topic, related_name="levels", blank=True)
    level_number = models.PositiveIntegerField(unique=True)
    title = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("level_number",)

    def __str__(self):
        return f"Year {self.level_number}"

    @property
    def display_name(self):
        return self.title or f"Year {self.level_number}"

    @property
    def topic_names(self):
        return ", ".join([topic.name for topic in self.topics.all()])


class ClassRoom(models.Model):
    name = models.CharField(max_length=150)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="maths_classes")
    code = models.CharField(max_length=8, unique=True, default=generate_class_code)
    levels = models.ManyToManyField(Level, blank=True, related_name="classrooms")

    def __str__(self):
        return f"{self.name} ({self.code})"


class Enrollment(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="maths_enrollments")
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name="enrollments")
    date_enrolled = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("student", "classroom")

    def __str__(self):
        return f"{self.student} → {self.classroom}"


class Question(models.Model):
    # question_type constants for use in views
    MULTIPLE_CHOICE = 'multiple_choice'
    TRUE_FALSE = 'true_false'
    SHORT_ANSWER = 'short_answer'
    FILL_BLANK = 'fill_blank'
    CALCULATION = 'calculation'

    QUESTION_TYPES = [
        ('multiple_choice', 'Multiple Choice'),
        ('true_false', 'True/False'),
        ('short_answer', 'Short Answer'),
        ('fill_blank', 'Fill in the Blank'),
        ('calculation', 'Calculation'),
    ]

    DIFFICULTY_CHOICES = [
        (1, 'Easy'),
        (2, 'Medium'),
        (3, 'Hard'),
    ]

    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="questions")
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name="questions", help_text="Topic this question belongs to (e.g., BODMAS/PEMDAS, Measurements, Fractions)")
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['level', 'difficulty', 'created_at']

    def __str__(self):
        return f"{self.level} - {self.question_text[:50]}..."


class Answer(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    answer_text = models.TextField()
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
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="basic_facts_results", null=True, blank=True)
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
        current_week = now_local.isocalendar()[1]

        if self.last_reset_week != current_week:
            self.weekly_total_seconds = 0
            self.last_reset_week = current_week
            self.save(update_fields=['weekly_total_seconds', 'last_reset_week'])


class TopicLevelStatistics(models.Model):
    """Store average and standard deviation (sigma) for each topic-level combination"""
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="topic_statistics")
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="level_statistics")
    average_points = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Average points across all students")
    sigma = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Standard deviation (sigma)")
    student_count = models.PositiveIntegerField(default=0, help_text="Number of students who have completed this topic-level")
    last_updated = models.DateTimeField(auto_now=True, help_text="Last time statistics were calculated")

    class Meta:
        unique_together = ("level", "topic")
        ordering = ['level__level_number', 'topic__name']
        indexes = [
            models.Index(fields=['level', 'topic']),
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
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name="final_answers")
    level = models.ForeignKey(Level, on_delete=models.SET_NULL, null=True, blank=True, related_name="final_answers")
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
    last_updated_time = models.DateTimeField(auto_now=True, help_text="Last time this record was updated")

    class Meta:
        ordering = ['-completed_at']
        indexes = [
            models.Index(fields=['student', 'topic', 'level']),
            models.Index(fields=['student', 'topic', 'level', 'attempt_number']),
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
