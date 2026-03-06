import uuid
from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Level(models.Model):
    """
    level_number 1-8  → Year 1-8 curriculum levels
    level_number >= 100 → Basic Facts levels (always accessible)
    """
    level_number = models.PositiveIntegerField(unique=True)
    display_name = models.CharField(max_length=50)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['level_number']

    def __str__(self):
        return self.display_name

    @property
    def is_basic_facts_level(self):
        return self.level_number >= 100

    @property
    def year_number(self):
        if self.level_number <= 8:
            return self.level_number
        return None


class Topic(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='topics')
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='subtopics',
        help_text='Leave blank for top-level topics; set for subtopics.',
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    levels = models.ManyToManyField(Level, related_name='topics', blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']
        unique_together = ('subject', 'slug')

    def __str__(self):
        return f'{self.subject.name} — {self.name}'


class ClassRoom(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=8, unique=True, editable=False)
    subject = models.ForeignKey(
        'Subject',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='classrooms',
    )
    levels = models.ManyToManyField(Level, related_name='classrooms', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_classes',
    )
    teachers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='ClassTeacher',
        related_name='teaching_classes',
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='ClassStudent',
        related_name='enrolled_classes',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.code})'

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)

    def get_accessible_levels(self):
        return self.levels.all()


class ClassTeacher(models.Model):
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name='class_teachers')
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='class_teacher_entries',
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('classroom', 'teacher')

    def __str__(self):
        return f'{self.teacher.username} → {self.classroom.name}'


class ClassStudent(models.Model):
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name='class_students')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='class_student_entries',
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('classroom', 'student')

    def __str__(self):
        return f'{self.student.username} → {self.classroom.name}'


class StudentLevelEnrollment(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='level_enrollments',
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    level = models.ForeignKey(Level, on_delete=models.CASCADE)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'subject', 'level')

    def __str__(self):
        return f'{self.student.username} → {self.subject.name} {self.level.display_name}'


# ---------------------------------------------------------------------------
# Subject Hub models (public landing page & subject hub feature)
# ---------------------------------------------------------------------------

class SubjectApp(models.Model):
    """
    Represents a top-level subject application shown on the Subjects Hub.
    Separate from the existing classroom.Subject model, which represents
    internal curriculum subjects. SubjectApp represents external (or future
    internal) subject applications that users can launch from the hub.
    """
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    icon_name = models.CharField(
        max_length=50, blank=True,
        help_text='Heroicon name (e.g. "calculator") or emoji',
    )
    external_url = models.URLField(
        blank=True, null=True,
        help_text='Full URL to the external subject app. null = not yet available.',
    )
    is_active = models.BooleanField(default=False)
    is_coming_soon = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=7, default='#16a34a')
    subject = models.ForeignKey(
        'Subject', null=True, blank=True, on_delete=models.SET_NULL,
        help_text='Optional link to internal classroom.Subject for future use.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Subject App'
        verbose_name_plural = 'Subject Apps'

    def __str__(self):
        return self.name

    def clean(self):
        if self.is_active and self.is_coming_soon:
            raise ValidationError(
                'A subject cannot be both active and coming soon.'
            )
        if self.is_active and not self.external_url:
            raise ValidationError(
                'Active subjects must have an external_url.'
            )


CONTACT_SUBJECT_CHOICES = [
    ('general', 'General Inquiry'),
    ('support', 'Technical Support'),
    ('billing', 'Billing'),
    ('partnership', 'Partnership'),
    ('other', 'Other'),
]


class ContactMessage(models.Model):
    """Stores contact form submissions from the public Contact Us page."""
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=50, choices=CONTACT_SUBJECT_CHOICES)
    message = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Contact Message'
        verbose_name_plural = 'Contact Messages'

    def __str__(self):
        return f'{self.name} — {self.get_subject_display()} ({self.created_at:%Y-%m-%d})'
