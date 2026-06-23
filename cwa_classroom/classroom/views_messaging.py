"""
Messaging views — compose and schedule email/SMS communications (CPP-348).

Phase 1 (CPP-349): routing + placeholder shell.
Phase 2 (CPP-350): recipient autocomplete API + To/CC/BCC tag fields.
Phase 3 (CPP-351): compose form — subject, body editor, attachments.
Phase 4 (CPP-352): schedule picker — send-now / one-time / weekly / monthly.
Send dispatch logic comes in CPP-353.
"""
import json
from datetime import date, datetime, time as dt_time

import django_rq
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from accounts.models import Role
from .models import ParentStudent, ScheduledMessage, School, SchoolStudent, SchoolTeacher
from .views import RoleRequiredMixin, _get_user_school_ids

_MESSAGING_ROLES = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

_RECIPIENT_SEARCH_LIMIT_MAX = 15
_RECIPIENT_SEARCH_LIMIT_DEFAULT = 8


def _get_messaging_school(user):
    """Return the first active school this user can send messages from.

    ADMIN users are resolved via the school.admin FK.
    HEAD_OF_INSTITUTE users are resolved via their SchoolTeacher row.
    INSTITUTE_OWNER users must also be the school.admin FK to be resolved;
    there is no separate SchoolTeacher role for institute owners.
    """
    school_ids = _get_user_school_ids(user)
    return School.objects.filter(id__in=school_ids, is_active=True).first()


class MessagingDashboardView(RoleRequiredMixin, View):
    """Redirect /messaging/ → compose page (canonical entry point)."""
    required_roles = _MESSAGING_ROLES

    def get(self, request):
        return redirect('messaging_compose')


class MessagingComposeView(RoleRequiredMixin, View):
    """Compose page — schedule picker and message persistence (CPP-352)."""
    required_roles = _MESSAGING_ROLES

    def get(self, request):
        school = _get_messaging_school(request.user)
        return render(request, 'messaging/compose.html', {'school': school})

    def post(self, request):
        school = _get_messaging_school(request.user)
        if not school:
            messages.error(request, 'No school found for your account.')
            return redirect('messaging_compose')

        action = request.POST.get('action', 'send')

        try:
            to_tags  = json.loads(request.POST.get('recipients_to', '[]') or '[]')
            cc_tags  = json.loads(request.POST.get('recipients_cc', '[]') or '[]')
            bcc_tags = json.loads(request.POST.get('recipients_bcc', '[]') or '[]')
        except (json.JSONDecodeError, ValueError):
            messages.error(request, 'Invalid recipient data — please try again.')
            return redirect('messaging_compose')

        subject   = request.POST.get('subject', '').strip()
        body_html = request.POST.get('body', '').strip()

        frequency = request.POST.get('frequency', 'now')
        if frequency not in ('now', 'once', 'weekly', 'monthly'):
            frequency = 'now'

        status = (ScheduledMessage.STATUS_DRAFT if action == 'draft'
                  else ScheduledMessage.STATUS_SCHEDULED)

        # ── Parse schedule fields ─────────────────────────────────────────────
        schedule_date_str = request.POST.get('schedule_date', '').strip()
        schedule_time_str = request.POST.get('schedule_time', '').strip()
        weekly_day_str    = request.POST.get('weekly_day', '').strip()
        monthly_day_str   = request.POST.get('monthly_day', '').strip()
        starts_at_str     = request.POST.get('starts_at', '').strip()
        ends_at_str       = request.POST.get('ends_at', '').strip()

        scheduled_at = None
        if frequency == 'once' and schedule_date_str and schedule_time_str:
            try:
                naive = datetime.strptime(f'{schedule_date_str} {schedule_time_str}', '%Y-%m-%d %H:%M')
                scheduled_at = timezone.make_aware(naive)
            except ValueError:
                pass

        send_time = None
        if frequency in ('weekly', 'monthly', 'once') and schedule_time_str:
            try:
                h, m = map(int, schedule_time_str.split(':'))
                send_time = dt_time(h, m)
            except (ValueError, AttributeError):
                pass

        send_day = None
        if frequency == 'weekly' and weekly_day_str:
            try:
                send_day = int(weekly_day_str)
            except ValueError:
                pass
        elif frequency == 'monthly' and monthly_day_str:
            try:
                send_day = int(monthly_day_str)
            except ValueError:
                pass

        sm = ScheduledMessage.objects.create(
            school=school,
            created_by=request.user,
            subject=subject,
            body_html=body_html,
            recipients_to=to_tags,
            recipients_cc=cc_tags,
            recipients_bcc=bcc_tags,
            frequency=frequency,
            scheduled_at=scheduled_at,
            send_time=send_time,
            send_day=send_day,
            starts_at=_parse_date(starts_at_str),
            ends_at=_parse_date(ends_at_str),
            status=status,
        )

        if action != 'draft':
            try:
                _enqueue_or_schedule(sm)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    'Failed to enqueue/schedule message %s', sm.pk
                )
                sm.status = ScheduledMessage.STATUS_FAILED
                sm.save(update_fields=['status', 'updated_at'])
                messages.error(request, 'Message could not be queued — please try again.')
                return redirect('messaging_compose')

        if action == 'draft':
            messages.success(request, 'Draft saved.')
        elif frequency == 'now':
            messages.success(request, 'Message queued for sending.')
        else:
            messages.success(request, 'Message scheduled.')

        return redirect('messaging_compose')


class RecipientSearchAPIView(RoleRequiredMixin, View):
    """
    GET /admin-dashboard/messaging/api/recipients/?q=<query>&limit=<n>

    Returns up to `limit` (default 8, max 15) school contacts whose name or
    email contains `q` (minimum 2 chars). Searches staff, students, and parents
    scoped to the requesting user's school. Users without an email are excluded.

    Response: { "results": [{ "id", "name", "email", "role" }] }
    """
    required_roles = _MESSAGING_ROLES

    def dispatch(self, request, *args, **kwargs):
        # Return JSON errors instead of HTML redirects so fetch() callers can
        # detect auth failures rather than silently swallowing a redirect.
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        if not request.user.is_superuser:
            has_any = any(request.user.has_role(r) for r in self.required_roles)
            if not has_any:
                return JsonResponse({'error': 'Permission denied'}, status=403)
        return View.dispatch(self, request, *args, **kwargs)

    def get(self, request):
        school = _get_messaging_school(request.user)
        if not school:
            return JsonResponse({'results': []})

        q = request.GET.get('q', '').strip()
        if len(q) < 2:
            return JsonResponse({'results': []})

        try:
            limit = min(int(request.GET.get('limit', _RECIPIENT_SEARCH_LIMIT_DEFAULT)), _RECIPIENT_SEARCH_LIMIT_MAX)
        except (ValueError, TypeError):
            limit = _RECIPIENT_SEARCH_LIMIT_DEFAULT

        results = []
        seen_emails = set()

        staff_q = (
            Q(teacher__first_name__icontains=q)
            | Q(teacher__last_name__icontains=q)
            | Q(teacher__email__icontains=q)
        )
        for st in (
            SchoolTeacher.objects
            .filter(school=school, is_active=True)
            .filter(staff_q)
            .filter(teacher__email__isnull=False)
            .exclude(teacher__email='')
            .select_related('teacher')
            .order_by('teacher__first_name', 'teacher__last_name')[:limit]
        ):
            email = st.teacher.email
            if email not in seen_emails:
                seen_emails.add(email)
                results.append(_recipient_result(st.teacher, 'staff'))

        remaining = limit - len(results)
        if remaining > 0:
            student_q = (
                Q(student__first_name__icontains=q)
                | Q(student__last_name__icontains=q)
                | Q(student__email__icontains=q)
            )
            for ss in (
                SchoolStudent.objects
                .filter(school=school, is_active=True)
                .filter(student_q)
                .filter(student__email__isnull=False)
                .exclude(student__email='')
                .select_related('student')
                .order_by('student__first_name', 'student__last_name')[:remaining]
            ):
                email = ss.student.email
                if email not in seen_emails:
                    seen_emails.add(email)
                    results.append(_recipient_result(ss.student, 'student'))

        remaining = limit - len(results)
        if remaining > 0:
            parent_q = (
                Q(parent__first_name__icontains=q)
                | Q(parent__last_name__icontains=q)
                | Q(parent__email__icontains=q)
            )
            for ps in (
                ParentStudent.objects
                .filter(school=school, is_active=True)
                .filter(parent_q)
                .filter(parent__email__isnull=False)
                .exclude(parent__email='')
                .select_related('parent')
                .order_by('parent__first_name', 'parent__last_name')
                .distinct()[:remaining]
            ):
                email = ps.parent.email
                if email not in seen_emails:
                    seen_emails.add(email)
                    results.append(_recipient_result(ps.parent, 'parent'))

        return JsonResponse({'results': results})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _display_name(user):
    full = f'{user.first_name} {user.last_name}'.strip()
    return full or user.username


def _parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _recipient_result(user, role):
    return {'id': user.id, 'name': _display_name(user), 'email': user.email, 'role': role}


def _enqueue_or_schedule(sm):
    """Compute next_run_at and enqueue immediately for 'now' messages.

    Called after ScheduledMessage creation (non-draft only).
    tasks_messaging is imported lazily to avoid circular-import issues.
    Raises on RQ connection errors so the caller (post()) can handle them.
    """
    import logging
    from classroom.tasks_messaging import compute_next_run_at, dispatch_message

    _log = logging.getLogger(__name__)

    if sm.frequency == 'now':
        django_rq.get_queue('default').enqueue(
            dispatch_message, sm.pk, job_id=f'dispatch-msg-{sm.pk}'
        )
        return

    next_run = compute_next_run_at(sm)
    if next_run:
        sm.next_run_at = next_run
        sm.save(update_fields=['next_run_at', 'updated_at'])
    else:
        # Required schedule fields missing or all candidate dates outside range.
        _log.warning(
            '_enqueue_or_schedule: compute_next_run_at returned None for msg %s '
            '(freq=%s, send_day=%s, send_time=%s)',
            sm.pk, sm.frequency, sm.send_day, sm.send_time,
        )
        sm.status = ScheduledMessage.STATUS_FAILED
        sm.save(update_fields=['status', 'updated_at'])
        raise ValueError(
            f'Cannot compute next run time for message {sm.pk} '
            f'(frequency={sm.frequency}). Check send_day and send_time.'
        )
