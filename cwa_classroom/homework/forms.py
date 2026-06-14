from django import forms
from django.utils import timezone
from .models import Homework


class HomeworkCreateForm(forms.ModelForm):
    class Meta:
        model = Homework
        fields = ['title', 'homework_type', 'topics', 'num_questions', 'due_date', 'publish_at', 'max_attempts']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'e.g. Week 3 Fractions Homework',
            }),
            'homework_type': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
            }),
            'topics': forms.CheckboxSelectMultiple(),
            'num_questions': forms.NumberInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                'min': 1, 'max': 50,
            }),
            'due_date': forms.DateTimeInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                'type': 'datetime-local',
            }),
            'publish_at': forms.DateTimeInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                'type': 'datetime-local',
            }),
            'max_attempts': forms.NumberInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                'min': 1,
                'placeholder': 'Leave blank for unlimited',
            }),
        }

    def clean_due_date(self):
        due_date = self.cleaned_data.get('due_date')
        if due_date:
            # datetime-local input returns a naive datetime; make it TZ-aware
            # using the server's current timezone before comparing with now().
            if timezone.is_naive(due_date):
                due_date = timezone.make_aware(due_date)
            if due_date <= timezone.now():
                raise forms.ValidationError('Due date must be in the future.')
        return due_date

    def clean_publish_at(self):
        publish_at = self.cleaned_data.get('publish_at')
        if not publish_at:
            # Blank means "publish immediately" — handled in the view.
            return publish_at
        # datetime-local input returns a naive datetime; make it TZ-aware.
        if timezone.is_naive(publish_at):
            publish_at = timezone.make_aware(publish_at)
        if publish_at <= timezone.now():
            raise forms.ValidationError(
                'Publish date must be in the future. Leave blank to publish now.'
            )
        # due_date is cleaned before publish_at (declared earlier in Meta.fields),
        # so it is already available here when valid.
        due_date = self.cleaned_data.get('due_date')
        if due_date and publish_at >= due_date:
            raise forms.ValidationError('Publish date must be before the due date.')
        return publish_at

    def clean_num_questions(self):
        n = self.cleaned_data.get('num_questions')
        if n and n < 1:
            raise forms.ValidationError('Must assign at least 1 question.')
        return n


class HomeworkEditForm(forms.ModelForm):
    """Edit a homework's schedule and metadata after creation.

    Deliberately omits topics / question selection — those stay fixed once the
    homework's question set is snapshotted. Teachers can reschedule the publish
    time (while still unpublished) and adjust the due date, title, description
    and attempt cap. ``publish_at`` is dropped from the form once the homework
    is already live (see ``__init__``).
    """

    class Meta:
        model = Homework
        fields = ['title', 'description', 'due_date', 'publish_at', 'max_attempts']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                'rows': 3,
                'placeholder': 'Optional notes for students',
            }),
            'due_date': forms.DateTimeInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                'type': 'datetime-local',
            }),
            'publish_at': forms.DateTimeInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                'type': 'datetime-local',
            }),
            'max_attempts': forms.NumberInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                'min': 1,
                'placeholder': 'Leave blank for unlimited',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # datetime-local inputs need the value formatted without seconds/tz.
        for name in ('due_date', 'publish_at'):
            field = self.fields.get(name)
            if field is not None:
                field.input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S']
        # Once published, publish_at is meaningless — drop it so the teacher
        # can't "reschedule" homework students have already been notified about.
        if self.instance and self.instance.pk and self.instance.is_published:
            self.fields.pop('publish_at', None)

    def clean_due_date(self):
        # Keep it tz-aware but do NOT force a future date: a teacher may edit an
        # expired homework's title without being forced to reopen it.
        due_date = self.cleaned_data.get('due_date')
        if due_date and timezone.is_naive(due_date):
            due_date = timezone.make_aware(due_date)
        return due_date

    def clean_publish_at(self):
        publish_at = self.cleaned_data.get('publish_at')
        if not publish_at:
            # Blank on an unpublished homework means "publish now" (view-handled).
            return publish_at
        if timezone.is_naive(publish_at):
            publish_at = timezone.make_aware(publish_at)
        if publish_at <= timezone.now():
            raise forms.ValidationError(
                'Publish date must be in the future. Leave blank to publish now.'
            )
        due_date = self.cleaned_data.get('due_date')
        if due_date and publish_at >= due_date:
            raise forms.ValidationError('Publish date must be before the due date.')
        return publish_at
