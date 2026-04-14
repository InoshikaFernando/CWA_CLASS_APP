from django.conf import settings
from django.db import models


class Game(models.Model):
    GAME_TYPE_CHOICES = [
        ('maths_crossnumber', 'Maths Cross Number'),
        ('english_crossword', 'English Crossword'),
        ('science_crossword', 'Science Crossword'),
    ]

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=60, unique=True, blank=True, default='')
    game_type = models.CharField(max_length=30, choices=GAME_TYPE_CHOICES)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    generation_threshold = models.FloatField(
        default=0.8,
        help_text="Fraction of published levels completed before a generation notification is sent."
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def input_type(self):
        """digit for cross-number, letter for crosswords."""
        return 'digit' if self.game_type == 'maths_crossnumber' else 'letter'


class Stage(models.Model):
    THEME_CHOICES = [
        ('forest',  'Enchanted Forest'),
        ('ocean',   'Deep Ocean'),
        ('space',   'Outer Space'),
        ('volcano', 'Lava Land'),
        ('crystal', 'Crystal Cave'),
    ]

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='stages')
    name = models.CharField(max_length=100)
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='forest')
    order = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['game', 'order']
        unique_together = ('game', 'order')

    def __str__(self):
        return f"{self.game} — Stage {self.order}: {self.name}"


class Level(models.Model):
    DIFFICULTY_CHOICES = [
        ('easy',   'Easy'),
        ('medium', 'Medium'),
        ('hard',   'Hard'),
    ]
    STATUS_CHOICES = [
        ('draft',     'Draft'),
        ('published', 'Published'),
    ]

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='levels')
    stage = models.ForeignKey(
        Stage, on_delete=models.SET_NULL, null=True, blank=True, related_name='levels'
    )
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=100, blank=True)
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='easy')
    grid_data = models.JSONField(help_text="Grid layout: rows, cols, blocked cells, clue numbers.")
    clues = models.JSONField(help_text="Across and down clues with position and length.")
    answers = models.JSONField(help_text="Expected answers keyed by direction and clue number.")
    passage = models.TextField(
        blank=True, null=True,
        help_text="Optional reading passage (science crosswords)."
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['game', 'stage__order', 'order']

    def __str__(self):
        stage_label = f"Stage {self.stage.order} " if self.stage else ""
        return f"{self.game} — {stage_label}Level {self.order}"


class PlayerProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='game_progress',
        null=True, blank=True,
        help_text="Null for anonymous Level 1 players."
    )
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='player_progress')
    completed = models.BooleanField(default=False)
    score = models.PositiveIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    cell_data = models.JSONField(
        default=dict, blank=True,
        help_text="Partial answers saved as {row_col: value}."
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-completed_at']
        unique_together = ('user', 'level')

    def __str__(self):
        user_label = str(self.user) if self.user else 'Anonymous'
        return f"{user_label} — {self.level} ({'done' if self.completed else 'in progress'})"


class LevelGenerationRequest(models.Model):
    STATUS_CHOICES = [
        ('pending',   'Pending'),
        ('generated', 'Generated'),
        ('reviewed',  'Reviewed'),
        ('published', 'Published'),
    ]

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='generation_requests')
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='level_generation_requests'
    )
    trigger_reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.game} generation request ({self.get_status_display()}) — {self.created_at:%Y-%m-%d}"
