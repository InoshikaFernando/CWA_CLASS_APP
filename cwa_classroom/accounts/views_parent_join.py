"""
Parent self-join registration view (CPP-70).
Allows parents to register and submit link requests for teacher approval.
"""
import re
from django.contrib import messages
from django.contrib.auth import login
from django.core.cache import cache
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, redirect
from django.views import View

from accounts.models import CustomUser, Role, UserRole
from classroom.models import SchoolStudent, ParentStudent, ParentLinkRequest


class ParentSelfJoinView(View):
    """Register as a parent and submit link requests for teacher approval."""
    template_name = 'accounts/register_parent_join.html'

    RELATIONSHIP_CHOICES = [
        ('mother', 'Mother'),
        ('father', 'Father'),
        ('guardian', 'Guardian'),
        ('other', 'Other'),
    ]

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('parent_dashboard')
        return render(request, self.template_name, {
            'relationship_choices': self.RELATIONSHIP_CHOICES,
        })

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('parent_dashboard')

        # Rate limiting: 10/hour per IP
        ip = self._get_client_ip(request)
        cache_key = f'parent_join_rate:{ip}'
        attempts = cache.get(cache_key, 0)
        if attempts >= 10:
            messages.error(request, 'Too many registration attempts. Please try again later.')
            return render(request, self.template_name, {
                'relationship_choices': self.RELATIONSHIP_CHOICES,
            })

        errors = {}
        form_data = {}

        # Extract form fields
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        form_data = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'username': username,
        }

        # Collect student IDs and relationships from dynamic fields
        student_ids = []
        relationships = []
        for i in range(5):  # max 5
            sid = request.POST.get(f'student_id_{i}', '').strip()
            rel = request.POST.get(f'relationship_{i}', 'guardian').strip()
            if sid:
                student_ids.append(sid)
                relationships.append(rel)

        form_data['student_entries'] = list(zip(student_ids, relationships))

        accept_terms = request.POST.get('accept_terms')

        # --- Validation ---

        if not first_name:
            errors['first_name'] = 'First name is required.'
        if not last_name:
            errors['last_name'] = 'Last name is required.'
        if not accept_terms:
            errors['accept_terms'] = 'You must accept the Terms and Conditions and Privacy Policy.'

        # Email validation
        if not email:
            errors['email'] = 'Email is required.'
        else:
            try:
                validate_email(email)
            except ValidationError:
                errors['email'] = 'Please enter a valid email address.'

        if email and not errors.get('email'):
            if CustomUser.objects.filter(email=email).exists():
                errors['email'] = (
                    'An account with this email already exists. '
                    'Please log in instead.'
                )

        # Username: auto-generate from email if blank
        if not username:
            username = email.split('@')[0] if email else ''
            # Sanitize: keep only alphanumeric
            username = re.sub(r'[^a-zA-Z0-9]', '', username)
            form_data['username'] = username

        if username:
            if not re.match(r'^[a-zA-Z0-9]+$', username):
                errors['username'] = 'Username must contain only letters and numbers.'
            elif CustomUser.objects.filter(username=username).exists():
                # Try appending numbers to make unique
                base = username
                for suffix in range(1, 100):
                    candidate = f'{base}{suffix}'
                    if not CustomUser.objects.filter(username=candidate).exists():
                        username = candidate
                        form_data['username'] = username
                        break
                else:
                    errors['username'] = 'Username is taken. Please choose another.'

        # Password validation
        if not password:
            errors['password'] = 'Password is required.'
        elif len(password) < 8:
            errors['password'] = 'Password must be at least 8 characters.'
        elif password != confirm_password:
            errors['confirm_password'] = 'Passwords do not match.'

        # Student IDs
        if not student_ids:
            errors['student_ids'] = 'At least one Student ID is required.'

        # Validate each student ID
        valid_school_students = []
        student_errors = []
        for idx, sid in enumerate(student_ids):
            school_student = SchoolStudent.objects.filter(
                student_id_code=sid, is_active=True,
            ).select_related('school', 'student').first()

            if not school_student:
                student_errors.append(f'Student ID "{sid}" was not found.')
                continue

            # Check max 2 parents per student per school (active links only)
            parent_count = ParentStudent.objects.filter(
                student=school_student.student,
                school=school_student.school,
                is_active=True,
            ).count()
            if parent_count >= 2:
                student_errors.append(
                    f'Student "{school_student.student.first_name}" already has '
                    f'the maximum number of parent accounts linked.'
                )
                continue

            valid_school_students.append((school_student, relationships[idx]))

        if student_errors:
            errors['student_ids'] = ' '.join(student_errors)

        if not valid_school_students and not errors.get('student_ids'):
            errors['student_ids'] = 'No valid Student IDs provided.'

        # If any errors, re-render
        if errors:
            return render(request, self.template_name, {
                'errors': errors,
                'form_data': form_data,
                'relationship_choices': self.RELATIONSHIP_CHOICES,
            })

        # --- Create account and pending link requests ---
        try:
            with transaction.atomic():
                from django.utils import timezone
                user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )
                user.terms_accepted_at = timezone.now()
                user.save(update_fields=['terms_accepted_at'])

                # Assign PARENT role
                parent_role, _created = Role.objects.get_or_create(
                    name=Role.PARENT,
                    defaults={'display_name': 'Parent', 'description': 'Parent/guardian role'},
                )
                UserRole.objects.create(user=user, role=parent_role)

                # Create pending link requests (not immediate ParentStudent links)
                notified_schools = set()
                for school_student, relationship in valid_school_students:
                    ParentLinkRequest.objects.create(
                        parent=user,
                        school_student=school_student,
                        relationship=relationship,
                        status=ParentLinkRequest.STATUS_PENDING,
                    )

                    # Notify teachers/admin for each school (once per school)
                    if school_student.school_id not in notified_schools:
                        notified_schools.add(school_student.school_id)
                        self._notify_school(school_student.school, user)

            # Increment rate limit counter
            cache.set(cache_key, attempts + 1, 3600)

            # Log user in
            login(request, user)

            from audit.services import log_event
            linked_students = [
                {'student_id': ss.student_id_code, 'school': ss.school.name, 'relationship': rel}
                for ss, rel in valid_school_students
            ]
            log_event(
                user=user,
                school=valid_school_students[0][0].school if valid_school_students else None,
                category='auth',
                action='parent_joined',
                detail={'username': username, 'email': email, 'linked_students': linked_students},
                request=request,
            )

            messages.success(
                request,
                'Your parent account has been created. Your request to link to your '
                'child(ren) has been sent to the school for approval. You will be '
                'notified once approved.'
            )
            return redirect('parent_dashboard')

        except Exception:
            messages.error(request, 'An error occurred while creating your account. Please try again.')
            return render(request, self.template_name, {
                'errors': errors,
                'form_data': form_data,
                'relationship_choices': self.RELATIONSHIP_CHOICES,
            })

    def _notify_school(self, school, parent_user):
        """Notify school admin and teachers that a parent has requested to link."""
        from classroom.notifications import create_notification
        from classroom.models import SchoolTeacher

        parent_name = parent_user.get_full_name() or parent_user.username
        message = (
            f'{parent_name} has requested to link as a parent/guardian to a student '
            f'at {school.name}. Please review and approve or reject the request.'
        )
        link = '/teacher/parent-link-requests/'

        notified_ids = set()

        # Notify school admin (HoI)
        if school.admin_id:
            create_notification(
                user=school.admin,
                message=message,
                notification_type='parent_link_request',
                link=link,
            )
            notified_ids.add(school.admin_id)

        # Notify active school teachers
        for membership in SchoolTeacher.objects.filter(
            school=school, is_active=True,
        ).select_related('teacher'):
            if membership.teacher_id not in notified_ids:
                create_notification(
                    user=membership.teacher,
                    message=message,
                    notification_type='parent_link_request',
                    link=link,
                )
                notified_ids.add(membership.teacher_id)

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '0.0.0.0')
