from django.db import models
from django.conf import settings
from django.utils import timezone


class Homework(models.Model):
    HOMEWORK_TYPE_CHOICES = [
        ('topic', 'Topic Quiz'),
        ('mixed', 'Mixed Quiz'),
    ]

    classroom = models.ForeignKey(
        'classroom.ClassRoom', on_delete=models.CASCADE, related_name='homework_assignments'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_homework'
    )
    title = models.CharField(max_length=200)
    homework_type = models.CharField(max_length=20, choices=HOMEWORK_TYPE_CHOICES, default='topic')
    topics = models.ManyToManyField('classroom.Topic', related_name='homework_assignments', blank=True)
    num_questions = models.PositiveIntegerField(default=10)
    due_date = models.DateTimeField()
    max_attempts = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Leave blank for unlimited attempts.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.classroom})'

    @property
    def is_past_due(self):
        return timezone.now() > self.due_date

    @property
    def attempts_unlimited(self):
        return self.max_attempts is None


class HomeworkQuestion(models.Model):
    """The fixed set of questions assigned to a homework. Same for all students."""
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name='homework_questions')
    question = models.ForeignKey('maths.Question', on_delete=models.CASCADE, related_name='homework_question_entries')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        unique_together = ('homework', 'question')

    def __str__(self):
        return f'{self.homework} — Q{self.order}'


class HomeworkSubmission(models.Model):
    STATUS_ON_TIME = 'on_time'
    STATUS_LATE = 'late'
    STATUS_NOT_SUBMITTED = 'not_submitted'

    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name='submissions')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='homework_submissions'
    )
    attempt_number = models.PositiveIntegerField(default=1)
    score = models.PositiveSmallIntegerField(default=0)
    total_questions = models.PositiveSmallIntegerField(default=0)
    points = models.FloatField(default=0.0)
    time_taken_seconds = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']
        unique_together = ('homework', 'student', 'attempt_number')

    def __str__(self):
        return f'{self.student} — {self.homework} attempt {self.attempt_number}'

    @property
    def submission_status(self):
        if self.submitted_at <= self.homework.due_date:
            return self.STATUS_ON_TIME
        return self.STATUS_LATE

    @property
    def percentage(self):
        if not self.total_questions:
            return 0
        return round((self.score / self.total_questions) * 100)

    @classmethod
    def get_attempt_count(cls, homework, student):
        return cls.objects.filter(homework=homework, student=student).count()

    @classmethod
    def get_best_submission(cls, homework, student):
        return cls.objects.filter(homework=homework, student=student).order_by('-points').first()

    @classmethod
    def get_next_attempt_number(cls, homework, student):
        from django.db.models import Max
        result = cls.objects.filter(homework=homework, student=student).aggregate(max_att=Max('attempt_number'))
        return (result['max_att'] or 0) + 1


class HomeworkStudentAnswer(models.Model):
    submission = models.ForeignKey(HomeworkSubmission, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey('maths.Question', on_delete=models.CASCADE, related_name='homework_student_answers')
    selected_answer = models.ForeignKey(
        'maths.Answer', on_delete=models.SET_NULL, null=True, blank=True
    )
    text_answer = models.TextField(blank=True)
    is_correct = models.BooleanField(default=False)
    points_earned = models.FloatField(default=0.0)

    class Meta:
        unique_together = ('submission', 'question')

    def __str__(self):
        return f'{self.submission} — {self.question_id} — {"Correct" if self.is_correct else "Wrong"}'
