"""Forms for the question-automation schedule (CPP-399)."""

from django import forms

from classroom.models import AcademicYear, Term

from .models import QuestionSchedule, ScheduleWeek

_INPUT = ('w-full border border-gray-300 rounded-lg px-3 py-2 text-sm '
          'focus:outline-none focus:ring-2 focus:ring-blue-500')


class QuestionScheduleForm(forms.ModelForm):
    """Create/edit a schedule.

    The period is entered one of three ways — academic year, term, or explicit
    dates — but ``start_date``/``end_date`` are always what gets stored, so the
    week builder and every query read one shape. ``clean()`` is where that
    resolution happens.
    """

    class Meta:
        model = QuestionSchedule
        fields = [
            'name', 'scope', 'academic_year', 'term', 'start_date', 'end_date',
            'release_weekday', 'release_time', 'due_days', 'lead_days',
            'num_questions', 'question_type', 'max_attempts',
            'avoid_repeat_weeks', 'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': _INPUT, 'placeholder': 'e.g. Term 2 Maths plan',
            }),
            'scope': forms.Select(attrs={'class': _INPUT, 'id': 'id_scope'}),
            'academic_year': forms.Select(attrs={'class': _INPUT}),
            'term': forms.Select(attrs={'class': _INPUT}),
            'start_date': forms.DateInput(attrs={'class': _INPUT, 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': _INPUT, 'type': 'date'}),
            'release_weekday': forms.Select(attrs={'class': _INPUT}),
            'release_time': forms.TimeInput(attrs={'class': _INPUT, 'type': 'time'}),
            'due_days': forms.NumberInput(attrs={'class': _INPUT, 'min': 1, 'max': 60}),
            'lead_days': forms.NumberInput(attrs={'class': _INPUT, 'min': 0, 'max': 30}),
            'num_questions': forms.NumberInput(attrs={'class': _INPUT, 'min': 1, 'max': 100}),
            'question_type': forms.Select(attrs={'class': _INPUT}),
            'max_attempts': forms.NumberInput(attrs={'class': _INPUT, 'min': 1}),
            'avoid_repeat_weeks': forms.NumberInput(attrs={'class': _INPUT, 'min': 0, 'max': 52}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded text-blue-600'}),
        }

    def __init__(self, *args, classroom=None, plugin=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.classroom = classroom
        school = getattr(classroom, 'school', None)

        # Only offer the class's own school's calendar. Without this a teacher
        # could pin a plan to another school's term dates.
        year_qs = AcademicYear.objects.filter(school=school) if school else AcademicYear.objects.none()
        term_qs = Term.objects.filter(school=school) if school else Term.objects.none()
        self.fields['academic_year'].queryset = year_qs
        self.fields['term'].queryset = term_qs
        self.fields['academic_year'].required = False
        self.fields['term'].required = False
        # Resolved in clean() for year/term scopes, so they must not be
        # required at the field level.
        self.fields['start_date'].required = False
        self.fields['end_date'].required = False

        choices = plugin.homework_question_type_choices() if plugin else []
        self.fields['question_type'].widget = forms.Select(
            attrs={'class': _INPUT},
            choices=[('', 'Any type')] + list(choices),
        )
        self.fields['question_type'].required = False

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get('scope')
        year = cleaned.get('academic_year')
        term = cleaned.get('term')
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')

        if scope == QuestionSchedule.SCOPE_YEAR:
            if not year:
                self.add_error('academic_year', 'Choose an academic year.')
            else:
                start, end = year.start_date, year.end_date
        elif scope == QuestionSchedule.SCOPE_TERM:
            if not term:
                self.add_error('term', 'Choose a term.')
            else:
                start, end = term.start_date, term.end_date
        else:
            if not start:
                self.add_error('start_date', 'Enter a start date.')
            if not end:
                self.add_error('end_date', 'Enter an end date.')

        if start and end:
            if end < start:
                self.add_error('end_date', 'The end date must be on or after the start date.')
            cleaned['start_date'] = start
            cleaned['end_date'] = end
        return cleaned

    def clean_name(self):
        """Enforce the (class, subject, name) unique key with a readable message.

        The model constraint would otherwise surface as an IntegrityError on
        save — a 500 rather than a form error the teacher can act on.
        """
        name = (self.cleaned_data.get('name') or '').strip()
        if not name or self.classroom is None:
            return name
        subject_slug = getattr(self.instance, 'subject_slug', '') or 'mathematics'
        clash = QuestionSchedule.objects.filter(
            classroom=self.classroom, subject_slug=subject_slug, name=name,
        ).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(
                'This class already has a schedule with that name for this subject.'
            )
        return name


class ScheduleWeekForm(forms.ModelForm):
    """Edit one week of a plan. Topic ids arrive as a repeated POST field."""

    class Meta:
        model = ScheduleWeek
        fields = ['num_questions', 'notes', 'is_active']
        widgets = {
            'num_questions': forms.NumberInput(attrs={
                'class': _INPUT, 'min': 1, 'max': 100,
                'placeholder': 'Use plan default',
            }),
            'notes': forms.TextInput(attrs={
                'class': _INPUT, 'placeholder': 'Optional note for this week',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded text-blue-600'}),
        }
