from django.conf import settings
from django.db import models
from django.utils import timezone


class Language(models.Model):
    SCRIPT_LATIN = 'latin'
    SCRIPT_SINHALA = 'sinhala'
    SCRIPT_TAMIL = 'tamil'
    SCRIPT_DEVANAGARI = 'devanagari'
    SCRIPT_ARABIC = 'arabic'
    SCRIPT_CJK = 'cjk'
    SCRIPT_CHOICES = [
        (SCRIPT_LATIN, 'Latin'),
        (SCRIPT_SINHALA, 'Sinhala'),
        (SCRIPT_TAMIL, 'Tamil'),
        (SCRIPT_DEVANAGARI, 'Devanagari'),
        (SCRIPT_ARABIC, 'Arabic'),
        (SCRIPT_CJK, 'CJK'),
    ]

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10, unique=True)
    script_type = models.CharField(max_length=20, choices=SCRIPT_CHOICES, default=SCRIPT_LATIN)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class LanguageTopic(models.Model):
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='topics')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['language', 'order', 'name']

    def __str__(self):
        return f'{self.language.name} — {self.name}'


class LanguageTopicLevel(models.Model):
    BEGINNER = 'beginner'
    INTERMEDIATE = 'intermediate'
    ADVANCED = 'advanced'
    LEVEL_CHOICES = [
        (BEGINNER, 'Beginner'),
        (INTERMEDIATE, 'Intermediate'),
        (ADVANCED, 'Advanced'),
    ]

    topic = models.ForeignKey(LanguageTopic, on_delete=models.CASCADE, related_name='levels')
    level_choice = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=BEGINNER)

    class Meta:
        unique_together = ('topic', 'level_choice')
        ordering = ['topic', 'level_choice']

    @property
    def name(self):
        return f'{self.topic.name} — {self.get_level_choice_display()}'

    def __str__(self):
        return f'{self.topic} [{self.get_level_choice_display()}]'


class LanguageExercise(models.Model):
    LETTER_WRITING = 'letter_writing'
    PHONICS_MCQ = 'phonics_mcq'
    SPELLING_MCQ = 'spelling_mcq'
    SPELLING_TYPE = 'spelling_type'
    CROSSWORD = 'crossword'
    GRAMMAR_FILL_BLANK = 'grammar_fill_blank'
    SENTENCE_ORDER = 'sentence_order'
    ADVANCED_CROSSWORD = 'advanced_crossword'
    EXERCISE_TYPES = [
        (LETTER_WRITING, 'Letter Writing'),
        (PHONICS_MCQ, 'Phonics MCQ'),
        (SPELLING_MCQ, 'Spelling MCQ'),
        (SPELLING_TYPE, 'Spelling — Type Answer'),
        (CROSSWORD, 'Crossword'),
        (GRAMMAR_FILL_BLANK, 'Grammar Fill-in-the-Blank'),
        (SENTENCE_ORDER, 'Sentence Ordering'),
        (ADVANCED_CROSSWORD, 'Advanced Crossword'),
    ]

    topic_level = models.ForeignKey(
        LanguageTopicLevel, on_delete=models.CASCADE, related_name='exercises'
    )
    exercise_type = models.CharField(max_length=30, choices=EXERCISE_TYPES)
    prompt = models.TextField()
    media_url = models.URLField(blank=True)
    audio_file = models.FileField(upload_to='languages/audio/', blank=True)
    puzzle_data = models.JSONField(default=dict, blank=True)
    points = models.PositiveSmallIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['topic_level', 'order']

    def __str__(self):
        return f'[{self.get_exercise_type_display()}] {self.prompt[:60]}'


class LanguageAnswer(models.Model):
    exercise = models.ForeignKey(
        LanguageExercise, on_delete=models.CASCADE, related_name='answers'
    )
    answer_text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['exercise', 'display_order']

    def __str__(self):
        return f'{self.answer_text} ({"✓" if self.is_correct else "✗"})'


class LanguageStudentAnswer(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='language_answers'
    )
    exercise = models.ForeignKey(
        LanguageExercise, on_delete=models.CASCADE, related_name='student_answers'
    )
    selected_answer = models.ForeignKey(
        LanguageAnswer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='student_answers',
    )
    text_answer = models.CharField(max_length=500, blank=True)
    stroke_data = models.JSONField(default=dict, blank=True)
    score = models.FloatField(default=0.0)
    is_correct = models.BooleanField(default=False)
    points_earned = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'exercise')
        ordering = ['-answered_at']

    def __str__(self):
        return f'{self.student.username} → {self.exercise} ({"✓" if self.is_correct else "✗"})'


class LanguageProgress(models.Model):
    """Per-student, per-level progress row. Created lazily on first answer."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='language_progress',
    )
    topic_level = models.ForeignKey(
        LanguageTopicLevel, on_delete=models.CASCADE,
        related_name='student_progress',
    )
    exercises_completed = models.PositiveIntegerField(default=0)  # count with score >= 80
    exercises_total = models.PositiveIntegerField(default=0)
    best_score_avg = models.FloatField(default=0.0)
    is_unlocked = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('student', 'topic_level')

    def __str__(self):
        status = 'done' if self.completed_at else ('unlocked' if self.is_unlocked else 'locked')
        return f'{self.student.username} | {self.topic_level} [{status}]'
