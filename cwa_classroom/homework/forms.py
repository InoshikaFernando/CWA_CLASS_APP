from django import forms
from django.utils import timezone
from .models import Homework


class HomeworkCreateForm(forms.ModelForm):
    class Meta:
        model = Homework
        fields = ['title', 'homework_type', 'topics', 'num_questions', 'due_date', 'max_attempts']
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
            'max_attempts': forms.NumberInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                'min': 1,
                'placeholder': 'Leave blank for unlimited',
            }),
        }

    def clean_due_date(self):
        due_date = self.cleaned_data.get('due_date')
        if due_date and due_date <= timezone.now():
            raise forms.ValidationError('Due date must be in the future.')
        return due_date

    def clean_num_questions(self):
        n = self.cleaned_data.get('num_questions')
        if n and n < 1:
            raise forms.ValidationError('Must assign at least 1 question.')
        return n
