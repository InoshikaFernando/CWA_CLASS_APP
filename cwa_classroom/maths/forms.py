from django import forms
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from accounts.models import CustomUser
from .models import Question, Answer


class TeacherSignUpForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ("username", "email", "password1", "password2")


class StudentSignUpForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ("username", "email", "password1", "password2")


class TeacherCenterRegistrationForm(UserCreationForm):
    center_name = forms.CharField(max_length=150, label="Center/School Name")
    email = forms.EmailField(required=True)

    class Meta:
        model = CustomUser
        fields = ("username", "email", "password1", "password2", "center_name")


class IndividualStudentRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = CustomUser
        fields = ("username", "email", "password1", "password2")


class StudentBulkRegistrationForm(forms.Form):
    student_data = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 10, 'cols': 50}),
        help_text="Enter student information in the format: username,email,password (one per line)"
    )

    def clean_student_data(self):
        data = self.cleaned_data['student_data']
        lines = data.strip().split('\n')
        students = []

        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue

            parts = line.split(',')
            if len(parts) != 3:
                raise forms.ValidationError(f"Line {i}: Invalid format. Expected 'username,email,password'")

            username, email, password = [part.strip() for part in parts]

            if not username:
                raise forms.ValidationError(f"Line {i}: Username cannot be empty")

            if '@' not in email:
                raise forms.ValidationError(f"Line {i}: Invalid email format")

            if len(password) < 8:
                raise forms.ValidationError(f"Line {i}: Password must be at least 8 characters")

            students.append({
                'username': username,
                'email': email,
                'password': password
            })

        return students


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ['question_text', 'question_type', 'difficulty', 'points', 'explanation']
        widgets = {
            'question_text': forms.Textarea(attrs={'rows': 4, 'cols': 50}),
            'explanation': forms.Textarea(attrs={'rows': 3, 'cols': 50}),
        }


class AnswerForm(forms.ModelForm):
    class Meta:
        model = Answer
        fields = ['answer_text', 'is_correct', 'order']
        widgets = {
            'answer_text': forms.TextInput(attrs={'size': 40}),
        }


class AnswerFormSet(forms.BaseFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for form in self.forms:
            if not form.instance.pk:
                form.fields['order'].initial = len(self.forms)


AnswerFormSet = forms.formset_factory(AnswerForm, extra=4, formset=AnswerFormSet)


class UserProfileForm(forms.ModelForm):
    """Form for editing user profile information"""
    class Meta:
        model = CustomUser
        fields = ('date_of_birth', 'country', 'region', 'email', 'first_name', 'last_name')
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'country': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter your country'}),
            'region': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter your region/state/province'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'date_of_birth': 'Date of Birth',
            'country': 'Country',
            'region': 'Region/State/Province',
            'email': 'Email Address',
            'first_name': 'First Name',
            'last_name': 'Last Name',
        }


class UserPasswordChangeForm(PasswordChangeForm):
    """Form for changing user password with custom styling"""
    old_password = forms.CharField(
        label="Current Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=True
    )
    new_password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=True,
        help_text="Your password must contain at least 8 characters."
    )
    new_password2 = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=True
    )
