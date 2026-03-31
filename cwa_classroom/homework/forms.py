from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import Homework, HomeworkSubmission


class HomeworkForm(forms.ModelForm):
    """Form for creating/editing homework assignments."""

    PUBLISH_IMMEDIATELY = 'publish'
    SAVE_DRAFT = 'draft'
    SCHEDULE = 'schedule'

    PUBLISH_CHOICES = [
        (PUBLISH_IMMEDIATELY, 'Publish immediately'),
        (SAVE_DRAFT, 'Save as draft'),
        (SCHEDULE, 'Schedule for later'),
    ]

    publish_option = forms.ChoiceField(
        choices=PUBLISH_CHOICES,
        initial=PUBLISH_IMMEDIATELY,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Homework
        fields = [
            'title', 'topic', 'description', 'due_date',
            'max_attempts', 'scheduled_publish_at',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g. Fractions Practice - Week 8',
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'rows': 3,
                'placeholder': 'Instructions for students (optional)',
            }),
            'due_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            }),
            'scheduled_publish_at': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            }),
            'max_attempts': forms.Select(
                choices=[
                    (0, 'Unlimited'),
                    (1, '1 attempt'),
                    (2, '2 attempts'),
                    (3, '3 attempts'),
                    (5, '5 attempts'),
                ],
                attrs={
                    'class': 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                },
            ),
        }

    def __init__(self, *args, classroom=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.classroom = classroom
        if classroom:
            from classroom.models import Topic
            # Filter topics to class subject/level
            level_ids = classroom.levels.values_list('id', flat=True)
            self.fields['topic'].queryset = Topic.objects.filter(
                subject=classroom.subject,
                levels__in=level_ids,
                is_active=True,
                parent__isnull=True,  # Top-level topics only
            ).distinct()
        self.fields['topic'].widget.attrs.update({
            'class': 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
        })
        self.fields['topic'].empty_label = 'Select topic...'
        self.fields['scheduled_publish_at'].required = False

    def clean(self):
        cleaned = super().clean()
        publish_option = cleaned.get('publish_option')
        due_date = cleaned.get('due_date')
        scheduled_at = cleaned.get('scheduled_publish_at')
        now = timezone.now()

        if due_date and due_date <= now:
            self.add_error('due_date', 'Due date must be in the future.')

        if publish_option == self.PUBLISH_IMMEDIATELY:
            # Enforce 7-day rule on immediate publish
            if due_date and due_date > now + timedelta(days=7):
                self.add_error(
                    'due_date',
                    'Due date must be within 7 days when publishing immediately.',
                )

        if publish_option == self.SCHEDULE:
            if not scheduled_at:
                self.add_error(
                    'scheduled_publish_at',
                    'Schedule date is required when scheduling.',
                )
            elif scheduled_at <= now:
                self.add_error(
                    'scheduled_publish_at',
                    'Schedule date must be in the future.',
                )
            # Enforce 7-day rule from scheduled publish date
            if due_date and scheduled_at and due_date > scheduled_at + timedelta(days=7):
                self.add_error(
                    'due_date',
                    'Due date must be within 7 days of the scheduled publish date.',
                )

        return cleaned


class HomeworkSubmissionForm(forms.ModelForm):
    """Form for students submitting homework."""

    class Meta:
        model = HomeworkSubmission
        fields = ['content', 'attachment']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500',
                'rows': 6,
                'placeholder': 'Write your answer here...',
            }),
            'attachment': forms.ClearableFileInput(attrs={
                'class': 'w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-emerald-50 file:text-emerald-700 hover:file:bg-emerald-100',
            }),
        }


class GradingForm(forms.Form):
    """Form for teacher grading a submission."""

    score = forms.DecimalField(
        max_digits=6,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'w-24 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': '0',
            'min': '0',
            'step': '0.5',
        }),
    )
    max_score = forms.DecimalField(
        max_digits=6,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'w-24 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': '100',
            'min': '0',
            'step': '0.5',
        }),
    )
    feedback = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'rows': 4,
            'placeholder': 'Feedback for the student...',
        }),
    )

    def clean(self):
        cleaned = super().clean()
        score = cleaned.get('score')
        max_score = cleaned.get('max_score')
        if score is not None and max_score is not None and score > max_score:
            self.add_error('score', 'Score cannot exceed max score.')
        return cleaned
