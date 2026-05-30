"""
HoI/Admin password reset for school members (students, parents, teachers).

The HoI can:
  - Generate a random password, OR
  - Set a known password (provided in the modal).

The user receives an email with the new password and a soft suggestion to
change it on next login. We do NOT set ``must_change_password = True`` —
the user is not forced to change.

Authorization: HoI must have admin/HoI access to the school AND the target
user must be linked to that school as a student, teacher, or parent.
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

logger = logging.getLogger(__name__)


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
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, user_id):
        school = _get_user_school_or_404(request.user, school_id)
        target = get_object_or_404(CustomUser, id=user_id)
        role_label, err = _resolve_user_school_role(target, school)
        if err:
            messages.error(request, err)
            return redirect('admin_school_detail', school_id=school.id)
        return render(request, 'admin_dashboard/partials/password_reset_modal.html', {
            'school': school,
            'target_user': target,
            'role_label': role_label,
            'reset_url': reverse('admin_user_password_reset', args=[school.id, target.id]),
        })


class AdminPasswordResetView(RoleRequiredMixin, View):
    """Reset a user's password (random or HoI-supplied) and email them the new value."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, user_id):
        school = _get_user_school_or_404(request.user, school_id)
        target = get_object_or_404(CustomUser, id=user_id)
        role_label, err = _resolve_user_school_role(target, school)
        if err:
            messages.error(request, err)
            return redirect('admin_school_detail', school_id=school.id)

        # HoI cannot reset a superuser via this UI.
        if target.is_superuser:
            messages.error(request, 'Superuser passwords cannot be reset from this screen.')
            return redirect(self._return_url(school, role_label))

        mode = request.POST.get('mode', 'random').strip()
        if mode == 'known':
            new_password = request.POST.get('new_password', '')
            confirm = request.POST.get('confirm_password', '')
            if len(new_password) < 8:
                messages.error(request, 'Password must be at least 8 characters.')
                return redirect(self._return_url(school, role_label))
            if new_password != confirm:
                messages.error(request, 'Passwords do not match.')
                return redirect(self._return_url(school, role_label))
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
        return redirect(self._return_url(school, role_label))

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

        # Generate a new password for institute accounts but only persist
        # after the email is confirmed sent — avoids locking the user out
        # with an unknown password if the email fails.
        is_institute = target.creation_method == 'institute'
        new_password = _generate_random_password() if is_institute else None

        email_sent = _send_resend_welcome_email(target, school, new_password)

        # Only change the password if the email was actually delivered.
        if email_sent and new_password:
            target.set_password(new_password)
            target.must_change_password = True
            target.save(update_fields=['password', 'must_change_password'])

        log_event(
            user=request.user, school=school, category='communication',
            action='welcome_email_resent',
            detail={
                'target_user_id': target.id,
                'target_user': target.get_full_name() or target.username,
                'target_role': role_label,
                'creation_method': target.creation_method,
                'email_sent': email_sent,
                'password_reset': email_sent and new_password is not None,
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
