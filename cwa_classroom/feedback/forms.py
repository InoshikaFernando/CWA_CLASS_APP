from django import forms

from .models import Feedback


class FeedbackForm(forms.ModelForm):
    """Capture form shown in the global 'Send Feedback' modal.

    Category and description are required; title is optional. The remaining
    fields (submitter, role, school, page_url, assignee) are populated by the
    view from the request context.
    """

    class Meta:
        model = Feedback
        fields = ['category', 'title', 'description']
        widgets = {
            'category': forms.Select(attrs={
                'class': 'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm '
                         'focus:outline-none focus:ring-2 focus:ring-accent/40',
            }),
            'title': forms.TextInput(attrs={
                'class': 'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm '
                         'focus:outline-none focus:ring-2 focus:ring-accent/40',
                'placeholder': 'Short summary (optional)',
                'maxlength': 200,
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm '
                         'focus:outline-none focus:ring-2 focus:ring-accent/40',
                'rows': 4,
                'placeholder': 'Tell us what happened or what you would like…',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Force an explicit choice rather than defaulting to the first option.
        self.fields['category'].required = True
        self.fields['description'].required = True
        self.fields['category'].choices = (
            [('', 'Choose a category…')] + list(Feedback.CATEGORY_CHOICES)
        )
