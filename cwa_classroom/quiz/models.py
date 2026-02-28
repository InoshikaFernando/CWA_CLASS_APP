from django.db import models
from django.conf import settings


class Question(models.Model):
    MULTIPLE_CHOICE = 'multiple_choice'
    TRUE_FALSE = 'true_false'
    SHORT_ANSWER = 'short_answer'
    FILL_BLANK = 'fill_blank'
    CALCULATION = 'calculation'
    DRAG_DROP = 'drag_drop'

    QUESTION_TYPES = [
        (MULTIPLE_CHOICE, 'Multiple Choice'),
        (TRUE_FALSE, 'True / False'),
        (SHORT_ANSWER, 'Short Answer'),
        (FILL_BLANK, 'Fill in the Blank'),
        (CALCULATION, 'Calculation'),
        (DRAG_DROP, 'Drag & Drop'),
    ]

    DIFFICULTY_EASY = 1
    DIFFICULTY_MEDIUM = 2
    DIFFICULTY_HARD = 3

    DIFFICULTY_CHOICES = [
        (DIFFICULTY_EASY, 'Easy'),
        (DIFFICULTY_MEDIUM, 'Medium'),
        (DIFFICULTY_HARD, 'Hard'),
    ]

    topic = models.ForeignKey(
        'classroom.Topic',
        on_delete=models.CASCADE,
        related_name='questions',
    )
    level = models.ForeignKey(
        'classroom.Level',
        on_delete=models.CASCADE,
        related_name='questions',
    )
    question_text = models.TextField()
    question_type = models.CharField(
        max_length=20,
        choices=QUESTION_TYPES,
        default=MULTIPLE_CHOICE,
    )
    difficulty = models.PositiveSmallIntegerField(
        choices=DIFFICULTY_CHOICES,
        default=DIFFICULTY_EASY,
    )
    points = models.PositiveSmallIntegerField(default=1)
    explanation = models.TextField(blank=True)
    image = models.ImageField(upload_to='questions/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='created_questions',
    )

    class Meta:
        ordering = ['topic', 'level', 'difficulty']

    def __str__(self):
        return f'[{self.get_question_type_display()}] {self.question_text[:60]}'

    def is_valid_for_quiz(self):
        """Check question has the minimum answers required for its type."""
        answers = self.answers.all()
        if not answers.exists():
            return False
        if not answers.filter(is_correct=True).exists():
            return False
        if self.question_type == self.MULTIPLE_CHOICE:
            if not answers.filter(is_correct=False).exists():
                return False
        return True


class Answer(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    text = models.TextField()
    is_correct = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ['display_order']

    def __str__(self):
        return f'{"✓" if self.is_correct else "✗"} {self.text[:50]}'
