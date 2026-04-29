"""Forms for question uploads."""

from django import forms
from django.core.exceptions import ValidationError


class QuestionUploadForm(forms.Form):
    """Form for uploading questions from file."""

    FILE_FORMAT_CHOICES = [
        ('json', 'JSON'),
        ('csv', 'CSV'),
        ('excel', 'Excel (.xlsx)'),
    ]

    SUBJECT_CHOICES = [
        ('maths', 'Mathematics'),
        ('coding', 'Coding'),
    ]

    subject = forms.ChoiceField(
        choices=SUBJECT_CHOICES,
        label='Subject',
        help_text='Which subject area the questions belong to',
        widget=forms.RadioSelect,
    )

    file_format = forms.ChoiceField(
        choices=FILE_FORMAT_CHOICES,
        label='File Format',
        help_text='Format of the file you are uploading',
        widget=forms.RadioSelect,
    )

    file = forms.FileField(
        label='Upload File',
        help_text='Maximum file size: 10MB',
        required=True,
    )

    def clean_file(self):
        """Validate file upload."""
        file = self.cleaned_data.get('file')

        if not file:
            raise ValidationError('File is required')

        # Check file size (10MB max)
        if file.size > 10 * 1024 * 1024:
            raise ValidationError('File size must not exceed 10MB')

        # Check file extension based on format
        file_format = self.cleaned_data.get('file_format', '')
        filename = file.name.lower()

        if file_format == 'json' and not filename.endswith('.json'):
            raise ValidationError('JSON format requires a .json file')

        elif file_format == 'csv' and not filename.endswith('.csv'):
            raise ValidationError('CSV format requires a .csv file')

        elif file_format == 'excel' and not filename.endswith(('.xlsx', '.xls')):
            raise ValidationError('Excel format requires a .xlsx or .xls file')

        return file


class QuestionSelectionForm(forms.Form):
    """Form for selecting questions from database for a session."""

    SUBJECT_CHOICES = [
        ('maths', 'Mathematics'),
        ('coding', 'Coding'),
    ]

    subject = forms.ChoiceField(
        choices=SUBJECT_CHOICES,
        label='Subject',
        help_text='Which subject area',
    )

    topic = forms.CharField(
        label='Topic',
        required=False,
        help_text='Optional: Filter by topic name',
    )

    question_type = forms.ChoiceField(
        label='Question Type',
        required=False,
        initial='',
        help_text='Optional: Filter by question type',
        choices=[
            ('', '--- Any ---'),
            ('multiple_choice', 'Multiple Choice'),
            ('true_false', 'True/False'),
            ('short_answer', 'Short Answer'),
            ('fill_blank', 'Fill in the Blank'),
        ],
    )

    difficulty = forms.ChoiceField(
        label='Difficulty',
        required=False,
        initial='',
        help_text='Optional: Filter by difficulty',
        choices=[
            ('', '--- Any ---'),
            ('1', 'Easy (1)'),
            ('2', 'Medium (2)'),
            ('3', 'Hard (3)'),
        ],
    )

    question_ids = forms.CharField(
        label='Selected Questions',
        required=False,
        widget=forms.HiddenInput(),
        help_text='Comma-separated list of question IDs (populated by JavaScript)',
    )
