"""
Password reset for school members (students, parents, teachers).

Accessible by:
  - HoI / Admin: any member of their school.
  - Teacher / Senior Teacher / Junior Teacher: only students enrolled in a
    class they teach at that school.
  - HoD: students in their class (via ClassTeacher) OR in any class within
    their department.

The actor can:
  - Generate a random password, OR
  - Set a known password (provided in the modal).

The user receives an email with the new password and a soft suggestion to
change it on next login. We do NOT set ``must_change_password = True`` —
the user is not forced to change.
"""
import logging
import secrets
import string

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views import View

from accounts.models import CustomUser, Role
from audit.services import log_event

from .models import School, SchoolStudent, SchoolTeacher, ParentStudent
from .views import RoleRequiredMixin
from .views_admin import _get_user_school_or_404

_ADMIN_ROLES = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]
_TEACHER_ROLES = [
    Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
]
_ALL_RESET_ROLES = _ADMIN_ROLES + _TEACHER_ROLES

logger = logging.getLogger(__name__)


def _get_school_for_password_reset(request_user, school_id, target_user_id):
    """
    Return the School if request_user is authorised to reset target's password.

    Admin / HoI: unrestricted within their school (delegates to existing helper).
    Teacher-level: must teach a class at the school that has the target student.
    HoD also passes if the target student is in any class within their department.
    Raises Http404 on any authorisation failure.
    """
    from django.http import Http404

    if (request_user.is_superuser
            or any(request_user.has_role(r) for r in _ADMIN_ROLES)):
        return _get_user_school_or_404(request_user, school_id)

    school = School.objects.filter(id=school_id, is_active=True).first()
    if not school:
        raise Http404

    from .models import ClassTeacher, ClassStudent

    if ClassTeacher.objects.filter(
        teacher=request_user,
        classroom__school=school,
        classroom__class_students__student_id=target_user_id,
        classroom__class_students__is_active=True,
    ).exists():
        return school

    if request_user.has_role(Role.HEAD_OF_DEPARTMENT):
        if ClassStudent.objects.filter(
            student_id=target_user_id,
            is_active=True,
            classroom__school=school,
            classroom__department__head=request_user,
        ).exists():
            return school

    raise Http404


# Password alphabet excluding confusable characters (0/O, 1/l/I).
_SAFE_ALPHABET = ''.join(
    c for c in string.ascii_letters + string.digits if c not in 'O0Il1'
)


def _generate_random_password(length=12):
    """Generate a 12-char password with at least one lower, upper, and digit."""
    while True:
        pw = ''.join(secrets.choice(_SAFE_ALPHABET) for _ in range(length))
        if (any(c.islower() for c in pw)
                and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)):
            return pw


def _resolve_user_school_role(user, school):
    """
    Return ('student'|'teacher'|'parent', None) if ``user`` is a member of
    ``school`` in any of those capacities; otherwise (None, error_message).
    """
    if SchoolStudent.objects.filter(school=school, student=user, is_active=True).exists():
        return 'student', None
    if SchoolTeacher.objects.filter(school=school, teacher=user, is_active=True).exists():
        return 'teacher', None
    if ParentStudent.objects.filter(school=school, parent=user, is_active=True).exists():
        return 'parent', None
    return None, 'User is not an active member of this school.'


def _send_password_reset_email(user, school, plain_password, actor):
    """
    Send the new-password email. Returns True/False; never raises.
    """
    if not user.email:
        logger.warning(
            'Password reset for user %s skipped: no email address.', user.pk
        )
        return False

    try:
        from classroom.email_service import send_templated_email, _get_email_logo_url
        from django.conf import settings as _settings
        site_url = getattr(_settings, 'SITE_URL', '').rstrip('/')
        login_path = getattr(_settings, 'LOGIN_URL', '/accounts/login/')

        ctx = {
            'recipient_name': user.get_full_name() or user.username,
            'school_name': school.name,
            'username': user.username,
            'temp_password': plain_password,
            'login_url': f'{site_url}{login_path}',
            'site_url': site_url,
            'reset_at': timezone.now(),
            'actor_name': actor.get_full_name() or actor.username,
            'email_logo_url': _get_email_logo_url(school),
        }
        return send_templated_email(
            recipient_email=user.email,
            subject=f'[{school.name}] Your password has been reset',
            template_name='email/transactional/admin_password_reset.html',
            context=ctx,
            recipient_user=user,
            notification_type='password_changed',
            school=school,
            fail_silently=True,
        )
    except Exception:
        logger.exception('Failed to send password-reset email to %s', user.email)
        return False


class AdminPasswordResetModalView(RoleRequiredMixin, View):
    """Return the password-reset modal partial via HTMX."""
    required_roles = _ALL_RESET_ROLES

    def get(self, request, school_id, user_id):
        target = get_object_or_404(CustomUser, id=user_id)
        school = _get_school_for_password_reset(request.user, school_id, user_id)
        next_url = request.GET.get('next', '')
        role_label, err = _resolve_user_school_role(target, school)
        if err:
            messages.error(request, err)
            if next_url and next_url.startswith('/') and '//' not in next_url:
                return redirect(next_url)
            return redirect('admin_school_detail', school_id=school.id)
        return render(request, 'admin_dashboard/partials/password_reset_modal.html', {
            'school': school,
            'target_user': target,
            'role_label': role_label,
            'reset_url': reverse('admin_user_password_reset', args=[school.id, target.id]),
            'next_url': next_url,
        })


class AdminPasswordResetView(RoleRequiredMixin, View):
    """Reset a user's password (random or HoI-supplied) and email them the new value."""
    required_roles = _ALL_RESET_ROLES

    def post(self, request, school_id, user_id):
        # Extract next_url early so ALL redirect paths (errors included) can
        # return teacher-level callers to the page they came from.
        next_url = request.POST.get('next', '').strip()
        safe_next = (
            next_url
            if next_url and next_url.startswith('/') and '//' not in next_url
            else None
        )

        target = get_object_or_404(CustomUser, id=user_id)
        school = _get_school_for_password_reset(request.user, school_id, user_id)
        role_label, err = _resolve_user_school_role(target, school)
        if err:
            messages.error(request, err)
            if safe_next:
                return redirect(safe_next)
            return redirect('admin_school_detail', school_id=school.id)

        # HoI cannot reset a superuser via this UI.
        if target.is_superuser:
            messages.error(request, 'Superuser passwords cannot be reset from this screen.')
            return redirect(safe_next or self._return_url(school, role_label))

        mode = request.POST.get('mode', 'random').strip()
        if mode == 'known':
            new_password = request.POST.get('new_password', '')
            confirm = request.POST.get('confirm_password', '')
            if len(new_password) < 8:
                messages.error(request, 'Password must be at least 8 characters.')
                return redirect(safe_next or self._return_url(school, role_label))
            if new_password != confirm:
                messages.error(request, 'Passwords do not match.')
                return redirect(safe_next or self._return_url(school, role_label))
        else:
            new_password = _generate_random_password()

        target.set_password(new_password)
        # Suggest, don't force, a change on next login.
        target.must_change_password = False
        target.save(update_fields=['password', 'must_change_password'])

        email_sent = _send_password_reset_email(
            user=target, school=school, plain_password=new_password, actor=request.user,
        )

        log_event(
            user=request.user, school=school, category='auth',
            action='admin_password_reset',
            detail={
                'target_user_id': target.id,
                'target_user': target.get_full_name() or target.username,
                'target_role': role_label,
                'mode': mode,
                'email_sent': email_sent,
            },
            request=request,
        )

        if email_sent:
            messages.success(
                request,
                f'Password reset for {target.get_full_name() or target.username}. '
                f'New password emailed to {target.email}.',
            )
        else:
            messages.warning(
                request,
                f'Password reset for {target.get_full_name() or target.username}, '
                f'but the email could not be sent. Share the new password manually: {new_password}',
            )

        return redirect(safe_next or self._return_url(school, role_label))

    @staticmethod
    def _return_url(school, role_label):
        if role_label == 'student':
            return reverse('admin_school_students', args=[school.id])
        if role_label == 'teacher':
            return reverse('admin_school_teachers', args=[school.id])
        if role_label == 'parent':
            return reverse('admin_school_parents', args=[school.id])
        return reverse('admin_school_detail', args=[school.id])


def _send_resend_welcome_email(user, school, plain_password):
    """Delegate to resend_welcome_notification. Returns True/False, never raises."""
    try:
        from notifications.services import resend_welcome_notification
        return resend_welcome_notification(user=user, plain_password=plain_password, school=school)
    except Exception:
        logger.exception('Unexpected error during welcome resend for %s', user.email)
        return False


def _resend_welcome_to_user(user, school):
    """Resend the welcome email to a single user, regenerating credentials.

    For institute-created accounts a fresh temporary password is generated,
    stored on the account, and ``must_change_password`` is forced True so the
    user is re-gated through the first-login flow. Self-registered accounts get
    a password-free welcome resend (the existing single-user behaviour).

    Users with no email are skipped. Never raises.

    Returns a dict: ``{'sent': bool, 'password_reset': bool, 'skipped': bool}``.
    """
    if not user.email:
        return {'sent': False, 'password_reset': False, 'skipped': True}

    new_password = None
    if user.creation_method == CustomUser.CREATION_INSTITUTE:
        new_password = _generate_random_password()
        user.set_password(new_password)
        user.must_change_password = True
        user.save(update_fields=['password', 'must_change_password'])

    sent = _send_resend_welcome_email(user, school, new_password)
    return {
        'sent': sent,
        'password_reset': new_password is not None,
        'skipped': False,
    }


class ResendWelcomeModalView(RoleRequiredMixin, View):
    """Return the resend-welcome modal partial via HTMX."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, user_id):
        school = _get_user_school_or_404(request.user, school_id)
        target = get_object_or_404(CustomUser, id=user_id)
        role_label, err = _resolve_user_school_role(target, school)
        if err:
            messages.error(request, err)
            return redirect('admin_school_detail', school_id=school.id)
        return render(request, 'admin_dashboard/partials/resend_welcome_modal.html', {
            'school': school,
            'target_user': target,
            'role_label': role_label,
            'resend_url': reverse('admin_user_resend_welcome', args=[school.id, target.id]),
        })


class ResendWelcomeEmailView(RoleRequiredMixin, View):
    """
    Resend the welcome email to a school member.

    Institute accounts: generates a new temporary password, updates the account,
    includes the password in the email, sets must_change_password=True.
    Self-registered accounts: resends the welcome email without a password.
    """
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, user_id):
        school = _get_user_school_or_404(request.user, school_id)
        target = get_object_or_404(CustomUser, id=user_id)
        role_label, err = _resolve_user_school_role(target, school)
        if err:
            messages.error(request, err)
            return redirect('admin_school_detail', school_id=school.id)

        if target.is_superuser:
            messages.error(request, 'Superuser welcome emails cannot be resent from this screen.')
            return redirect(AdminPasswordResetView._return_url(school, role_label))

        outcome = _resend_welcome_to_user(target, school)
        email_sent = outcome['sent']
        new_password = outcome['password_reset']

        log_event(
            user=request.user, school=school, category='communication',
            action='welcome_email_resent',
            detail={
                'target_user_id': target.id,
                'target_user': target.get_full_name() or target.username,
                'target_role': role_label,
                'creation_method': target.creation_method,
                'email_sent': email_sent,
                'password_reset': outcome['password_reset'],
            },
            request=request,
        )

        name = target.get_full_name() or target.username
        if email_sent:
            if new_password:
                messages.success(
                    request,
                    f'Welcome email resent to {name}. A new temporary password was generated and included.',
                )
            else:
                messages.success(request, f'Welcome email resent to {name}.')
        else:
            messages.warning(
                request,
                f'Welcome email for {name} could not be sent. '
                f'Check their email address ({target.email or "none"}) and try again.',
            )

        return redirect(AdminPasswordResetView._return_url(school, role_label))


class BulkResendWelcomeView(RoleRequiredMixin, View):
    """Bulk-resend welcome emails to selected students of a class (CPP-300).

    Roles: Admin / HoI / Institute Owner (any class in their school), plus the
    class's own teachers (only classes they teach). For each selected student
    the welcome email is resent to the STUDENT *and* each active linked parent,
    regenerating temporary credentials for institute accounts. Recipients with
    no email are skipped and reported.

    Tenant isolation: the class is resolved against the requesting user's
    school / taught classes, so a cross-school class id 404s.
    """
    required_roles = _ALL_RESET_ROLES

    def _get_classroom_or_404(self, request, class_id):
        from django.db.models import Q
        from .models import ClassRoom

        user = request.user
        if (user.is_superuser
                or any(user.has_role(r) for r in _ADMIN_ROLES)):
            return get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        # Teacher-level: must teach this class (HoD: or own its department).
        classroom = ClassRoom.objects.filter(
            Q(teachers=user) | Q(department__head=user),
            id=class_id,
        ).distinct().first()
        if not classroom:
            from django.http import Http404
            raise Http404
        return classroom

    def post(self, request, class_id):
        from .models import ClassStudent

        classroom = self._get_classroom_or_404(request, class_id)
        school = classroom.school
        redirect_url = reverse('class_detail', args=[classroom.id])

        selected_ids = request.POST.getlist('student_ids')
        if not selected_ids:
            messages.info(request, 'No students selected — nothing was sent.')
            return redirect(redirect_url)

        # Only students actually enrolled (active) in THIS class are eligible.
        eligible = list(
            ClassStudent.objects.filter(
                classroom=classroom, is_active=True,
                student_id__in=selected_ids,
            ).select_related('student')
        )

        students_sent = 0
        parents_sent = 0
        skipped = 0

        # Collect the unique parents to notify FIRST, so a parent shared by two
        # selected siblings is emailed once (not password-reset twice, which
        # would invalidate the first email's credentials).
        parent_ids = set(
            ParentStudent.objects.filter(
                student__in=[cs.student_id for cs in eligible],
                school=school, is_active=True,
            ).values_list('parent_id', flat=True)
        )

        for cs in eligible:
            outcome = _resend_welcome_to_user(cs.student, school)
            if outcome['sent']:
                students_sent += 1
            elif outcome['skipped']:
                skipped += 1

        for parent in CustomUser.objects.filter(id__in=parent_ids):
            p_outcome = _resend_welcome_to_user(parent, school)
            if p_outcome['sent']:
                parents_sent += 1
            elif p_outcome['skipped']:
                skipped += 1

        log_event(
            user=request.user, school=school, category='communication',
            action='bulk_welcome_resent',
            detail={
                'class_id': classroom.id,
                'selected': len(selected_ids),
                'students_sent': students_sent,
                'parents_sent': parents_sent,
                'skipped': skipped,
            },
            request=request,
        )

        summary = (
            f'Resent welcome to {students_sent} student(s) '
            f'and {parents_sent} parent(s).'
        )
        if skipped:
            summary += f' {skipped} recipient(s) skipped (no email address).'
        messages.success(request, summary)
        return redirect(redirect_url)
