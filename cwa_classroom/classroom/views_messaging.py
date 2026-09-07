"""
Messaging views — compose and schedule email/SMS communications (CPP-348).

Phase 1 (CPP-349): routing + placeholder shell.
Phase 2 (CPP-350): recipient autocomplete API + To/CC/BCC tag fields.
Phase 3 (CPP-351): compose form — subject, body editor, attachments.
Phase 4 (CPP-352): schedule picker — send-now / one-time / weekly / monthly.
Phase 5 (CPP-353): RQ dispatch — dispatch_message task + check_due_messages cron.
Phase 6 (CPP-358): Message history inbox — list, cancel, delete, retry.
"""
import json
from datetime import date, datetime, time as dt_time

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.timezone import localtime
from django.views import View

from accounts.models import Role
from .models import ParentStudent, ScheduledMessage, ScheduledMessageAttachment, School, SchoolStudent, SchoolTeacher
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
    """Redirect /messaging/ → inbox (canonical entry point)."""
    required_roles = _MESSAGING_ROLES

    def get(self, request):
        return redirect('messaging_inbox')


class MessagingComposeView(RoleRequiredMixin, View):
    """Compose page — schedule picker and message persistence (CPP-352)."""
    required_roles = _MESSAGING_ROLES

    def get(self, request):
        school = _get_messaging_school(request.user)
        draft = None
        draft_json = 'null'
        edit_pk = request.GET.get('edit', '').strip()
        if edit_pk and school:
            draft = get_object_or_404(ScheduledMessage, pk=edit_pk, school=school)
            draft_json = json.dumps({
                'pk':              draft.pk,
                'subject':         draft.subject,
                'body_html':       draft.body_html,
                'recipients_to':   draft.recipients_to,
                'recipients_cc':   draft.recipients_cc,
                'recipients_bcc':  draft.recipients_bcc,
                'frequency':       draft.frequency,
                'schedule_date':   localtime(draft.scheduled_at).strftime('%Y-%m-%d') if draft.scheduled_at else '',
                'schedule_time':   draft.send_time.strftime('%H:%M') if draft.send_time else '09:00',
                'weekly_day':      str(draft.send_day) if draft.frequency == 'weekly' and draft.send_day is not None else '1',
                'monthly_day':     str(draft.send_day) if draft.frequency == 'monthly' and draft.send_day is not None else '1',
                'starts_at':       draft.starts_at.isoformat() if draft.starts_at else '',
                'ends_at':         draft.ends_at.isoformat() if draft.ends_at else '',
            })
        is_reschedule = draft is not None and draft.status != ScheduledMessage.STATUS_DRAFT
        existing_attachments = list(draft.attachments.all()) if draft else []
        return render(request, 'messaging/compose.html', {
            'school':               school,
            'user_email':           request.user.email or '',
            'user_name':            request.user.get_full_name() or request.user.username,
            'draft':                draft,
            'draft_json':           draft_json,
            'is_reschedule':        is_reschedule,
            'existing_attachments': existing_attachments,
        })

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

        draft_pk = request.POST.get('draft_pk', '').strip()
        if draft_pk:
            sm = get_object_or_404(ScheduledMessage, pk=draft_pk, school=school)
            _editable = (ScheduledMessage.STATUS_DRAFT, ScheduledMessage.STATUS_SCHEDULED,
                         ScheduledMessage.STATUS_FAILED, ScheduledMessage.STATUS_CANCELLED)
            if sm.status not in _editable:
                messages.error(request, 'This message cannot be edited in its current state.')
                return redirect('messaging_inbox')
            sm.subject        = subject
            sm.body_html      = body_html
            sm.recipients_to  = to_tags
            sm.recipients_cc  = cc_tags
            sm.recipients_bcc = bcc_tags
            sm.frequency      = frequency
            sm.scheduled_at   = scheduled_at
            sm.send_time      = send_time
            sm.send_day       = send_day
            sm.starts_at      = _parse_date(starts_at_str)
            sm.ends_at        = _parse_date(ends_at_str)
            sm.status         = status
            sm.save()
        else:
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

        # Save newly uploaded attachments
        import logging as _logging, os as _os
        _att_log = _logging.getLogger(__name__)
        _ALLOWED_EXTS = {'.pdf', '.docx', '.png', '.jpg', '.jpeg'}
        for f in request.FILES.getlist('attachments'):
            safe_name = _os.path.basename(f.name)
            ext = _os.path.splitext(safe_name)[1].lower()
            if ext not in _ALLOWED_EXTS:
                _att_log.warning('Rejected attachment with disallowed extension %s for msg %s', ext, sm.pk)
                continue
            try:
                ScheduledMessageAttachment.objects.create(
                    message=sm,
                    file=f,
                    filename=safe_name,
                    filesize=f.size,
                )
            except Exception:
                _att_log.exception('Failed to save attachment %s for message %s', safe_name, sm.pk)

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

        return redirect('messaging_inbox')


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


class MessagingRecipientGroupAPIView(RoleRequiredMixin, View):
    """
    GET /admin-dashboard/messaging/api/recipients/group/?role=<student|staff|parent>

    Returns all school contacts of the given role — no query filter.
    Used for "All Students / All Staff / All Parents" bulk-add chips (CPP-361).

    Response: { "results": [{ "id", "name", "email", "role" }] }
    """
    required_roles = _MESSAGING_ROLES

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        if not request.user.is_superuser:
            has_any = any(request.user.has_role(r) for r in self.required_roles)
            if not has_any:
                return JsonResponse({'error': 'Permission denied'}, status=403)
        return View.dispatch(self, request, *args, **kwargs)

    def get(self, request):
        role = request.GET.get('role', '')
        if role not in ('student', 'staff', 'parent'):
            return JsonResponse({'error': 'Invalid role. Use: student, staff, parent'}, status=400)

        school = _get_messaging_school(request.user)
        if not school:
            return JsonResponse({'results': []})

        results = []
        seen = set()

        if role == 'staff':
            qs = (SchoolTeacher.objects
                  .filter(school=school, is_active=True)
                  .filter(teacher__email__isnull=False)
                  .exclude(teacher__email='')
                  .select_related('teacher')
                  .order_by('teacher__first_name', 'teacher__last_name'))
            for st in qs:
                email = st.teacher.email
                if email not in seen:
                    seen.add(email)
                    results.append(_recipient_result(st.teacher, 'staff'))

        elif role == 'student':
            qs = (SchoolStudent.objects
                  .filter(school=school, is_active=True)
                  .filter(student__email__isnull=False)
                  .exclude(student__email='')
                  .select_related('student')
                  .order_by('student__first_name', 'student__last_name'))
            for ss in qs:
                email = ss.student.email
                if email not in seen:
                    seen.add(email)
                    results.append(_recipient_result(ss.student, 'student'))

        elif role == 'parent':
            qs = (ParentStudent.objects
                  .filter(school=school, is_active=True)
                  .filter(parent__email__isnull=False)
                  .exclude(parent__email='')
                  .select_related('parent')
                  .order_by('parent__first_name', 'parent__last_name')
                  .distinct())
            for ps in qs:
                email = ps.parent.email
                if email not in seen:
                    seen.add(email)
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
    """Dispatch or schedule a ScheduledMessage after creation (non-draft only).

    'now'  → dispatch_message() immediately (enqueues into EmailQueue).
    other  → compute next_run_at and save; dispatch_due_sync / send_due_messages
             cron will pick it up when the time arrives.
    No RQ worker or Redis required — uses the existing EmailQueue infrastructure.
    """
    import logging
    from classroom.tasks_messaging import compute_next_run_at, dispatch_message

    _log = logging.getLogger(__name__)

    if sm.frequency == 'now':
        dispatch_message(sm.pk)
        return

    next_run = compute_next_run_at(sm)
    if next_run:
        sm.next_run_at = next_run
        sm.save(update_fields=['next_run_at', 'updated_at'])
    else:
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


# ---------------------------------------------------------------------------
# Message Detail (read view)
# ---------------------------------------------------------------------------

class MessagingDetailView(RoleRequiredMixin, View):
    """Read-only detail view for a single ScheduledMessage — Gmail-style."""
    required_roles = _MESSAGING_ROLES

    def get(self, request, pk):
        school = _get_messaging_school(request.user)
        msg = get_object_or_404(ScheduledMessage, pk=pk, school=school)
        _inbox = '/admin-dashboard/messaging/inbox/'
        referer = request.META.get('HTTP_REFERER', '')
        # Only allow same-origin relative-path referers to prevent open-redirect.
        if referer.startswith(request.build_absolute_uri('/')) and '/admin-dashboard/' in referer:
            back_url = referer
        else:
            back_url = _inbox
        return render(request, 'messaging/detail.html', {
            'school': school,
            'msg': msg,
            'back_url': back_url,
        })


# ---------------------------------------------------------------------------
# CPP-358: Message History Inbox
# ---------------------------------------------------------------------------

_INBOX_PAGE_SIZE = 10

_TAB_STATUS_MAP = {
    'draft':     ScheduledMessage.STATUS_DRAFT,
    'scheduled': ScheduledMessage.STATUS_SCHEDULED,
    'sent':      ScheduledMessage.STATUS_SENT,
    'failed':    ScheduledMessage.STATUS_FAILED,
    'cancelled': ScheduledMessage.STATUS_CANCELLED,
}


def _recipient_summary(msg):
    """Return (first_name, total_count) from To/CC/BCC recipient lists."""
    all_r = (msg.recipients_to or []) + (msg.recipients_cc or []) + (msg.recipients_bcc or [])
    total = len(all_r)
    first = all_r[0].get('name', '') if all_r and isinstance(all_r[0], dict) else ''
    return first, total


def _fmt_dt(dt):
    return localtime(dt).strftime('%d %b %Y, %H:%M') if dt else ''


def _serialise_msg(m):
    return {
        'pk':            m.pk,
        'subject':       m.subject,
        'body_html':     m.body_html,
        'status':        m.status,
        'frequency':     m.frequency,
        'recipients_to':  m.recipients_to  or [],
        'recipients_cc':  m.recipients_cc  or [],
        'recipients_bcc': m.recipients_bcc or [],
        'created_by':    (m.created_by.get_full_name() or m.created_by.username) if m.created_by else '',
        'created_at':    _fmt_dt(m.created_at),
        'last_run_at':   _fmt_dt(m.last_run_at),
        'scheduled_at':  _fmt_dt(m.scheduled_at),
        'next_run_at':   _fmt_dt(m.next_run_at),
        'attachments':   [{'filename': a.filename, 'url': a.file.url, 'filesize': a.filesize} for a in m.attachments.all()],
    }


class MessagingInboxView(RoleRequiredMixin, View):
    """Message history list — All / Draft / Scheduled / Sent / Failed tabs (CPP-358)."""
    required_roles = _MESSAGING_ROLES

    def get(self, request):
        school = _get_messaging_school(request.user)
        if not school:
            return render(request, 'messaging/inbox.html', {
                'page_obj': None, 'school': None,
                'tab': 'all', 'q': '',
                'tabs': ['all'] + list(_TAB_STATUS_MAP.keys()),
                'total': 0,
            })

        tab = request.GET.get('tab', 'all')
        q   = request.GET.get('q', '').strip()

        qs = ScheduledMessage.objects.filter(school=school).select_related('created_by').prefetch_related('attachments')

        if tab in _TAB_STATUS_MAP:
            qs = qs.filter(status=_TAB_STATUS_MAP[tab])

        if q:
            qs = qs.filter(subject__icontains=q)

        # Dispatch any overdue scheduled messages synchronously (no worker needed)
        try:
            from classroom.tasks_messaging import dispatch_due_sync
            dispatch_due_sync()
        except Exception:
            import logging
            logging.getLogger(__name__).exception('MessagingInboxView: dispatch_due_sync failed')

        paginator = Paginator(qs.order_by('-created_at'), _INBOX_PAGE_SIZE)
        page_obj  = paginator.get_page(request.GET.get('page', 1))

        # Annotate each message with recipient summary for display
        page_items = list(page_obj)
        for msg in page_items:
            msg.first_recipient, msg.recipient_count = _recipient_summary(msg)

        # Counts per status (unfiltered by search/tab) for tab badges
        from django.db.models import Count as _Count
        raw_counts = (
            ScheduledMessage.objects.filter(school=school)
            .values('status').annotate(n=_Count('id'))
        )
        status_counts = {row['status']: row['n'] for row in raw_counts}

        return render(request, 'messaging/inbox.html', {
            'school':        school,
            'page_obj':      page_obj,
            'tab':           tab,
            'q':             q,
            'tabs':          ['all'] + list(_TAB_STATUS_MAP.keys()),
            'total':         paginator.count,
            'msgs_data':     [_serialise_msg(m) for m in page_items],
            'status_counts': status_counts,
        })


class MessagingCancelView(RoleRequiredMixin, View):
    """POST /messaging/<pk>/cancel/ — cancel a scheduled message (CPP-358)."""
    required_roles = _MESSAGING_ROLES

    def post(self, request, pk):
        school = _get_messaging_school(request.user)
        if not school:
            messages.error(request, 'No active school found.')
            return redirect('messaging_inbox')
        msg = get_object_or_404(ScheduledMessage, pk=pk, school=school)
        if msg.status == ScheduledMessage.STATUS_SCHEDULED:
            msg.status = ScheduledMessage.STATUS_CANCELLED
            msg.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'Message cancelled.')
        else:
            messages.warning(request, 'Only scheduled messages can be cancelled.')
        return redirect(_inbox_url(request))


class MessagingDeleteView(RoleRequiredMixin, View):
    """POST /messaging/<pk>/delete/ — hard-delete any message (CPP-358)."""
    required_roles = _MESSAGING_ROLES

    def post(self, request, pk):
        school = _get_messaging_school(request.user)
        if not school:
            messages.error(request, 'No active school found.')
            return redirect('messaging_inbox')
        msg = get_object_or_404(ScheduledMessage, pk=pk, school=school)
        subject = msg.subject or 'Message'
        msg.delete()
        messages.success(request, f'"{subject}" deleted.')
        return redirect(_inbox_url(request))


class MessagingRetryView(RoleRequiredMixin, View):
    """POST /messaging/<pk>/retry/ — re-enqueue a failed message (CPP-358)."""
    required_roles = _MESSAGING_ROLES

    def post(self, request, pk):
        school = _get_messaging_school(request.user)
        if not school:
            messages.error(request, 'No active school found.')
            return redirect('messaging_inbox')
        msg = get_object_or_404(ScheduledMessage, pk=pk, school=school)
        if msg.status != ScheduledMessage.STATUS_FAILED:
            messages.warning(request, 'Only failed messages can be retried.')
            return redirect(_inbox_url(request))
        try:
            from classroom.tasks_messaging import dispatch_message
            msg.status = ScheduledMessage.STATUS_SCHEDULED
            msg.save(update_fields=['status', 'updated_at'])
            dispatch_message(msg.pk)
            messages.success(request, 'Message re-queued for sending.')
        except Exception:
            import logging
            logging.getLogger(__name__).exception('MessagingRetryView: failed to re-enqueue %s', pk)
            msg.status = ScheduledMessage.STATUS_FAILED
            msg.save(update_fields=['status', 'updated_at'])
            messages.error(request, 'Could not re-queue message — please try again.')
        return redirect(_inbox_url(request))


def _inbox_url(request):
    """Preserve tab + search params when redirecting back to inbox."""
    from django.urls import reverse as _reverse
    from urllib.parse import quote
    tab = request.POST.get('tab') or request.GET.get('tab', '')
    q   = request.POST.get('q')   or request.GET.get('q', '')
    url = _reverse('messaging_inbox')
    params = []
    if tab:
        params.append(f'tab={quote(tab, safe="")}')
    if q:
        params.append(f'q={quote(q, safe="")}')
    return f'{url}?{"&".join(params)}' if params else url
