"""
HoI/Admin views for managing parent-student relationships (CPP-70).
"""
from datetime import timedelta

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views import View

from accounts.models import CustomUser, Role, UserRole
from audit.services import log_event
from django.core.paginator import Paginator
from django.db.models import Q

from .models import School, SchoolStudent, ParentStudent, ParentInvite, Guardian, StudentGuardian
from .views import RoleRequiredMixin
from .views_admin import _get_user_school_or_404


def _parent_welcome_filter_state(row):
    """Classify a parent-account row's welcome email into a single state used by
    the ?welcome= filter and the badge (CPP-343).

    Priority is the tracked EmailLog delivery state (genuine proof the email went
    out): 'delivered' | 'sent' | 'bounced' | 'failed'. Only when there is no log
    do we fall back to the welcome_email_sent flag (a legacy account sent before
    delivery tracking existed) — counted as 'sent'. Otherwise 'not_sent'.
    """
    state = row.get('welcome_email_state')
    if state in ('delivered', 'sent', 'bounced', 'failed'):
        return state
    if row.get('welcome_email_sent'):
        return 'sent'
    return 'not_sent'


# ?welcome= value -> the set of filter-states it matches. "Sent" means the email
# genuinely went out (delivered or accepted); bounced/failed are surfaced
# separately so a bounce is never mistaken for a successful send.
_PARENT_WELCOME_FILTERS = {
    'sent': {'delivered', 'sent'},
    'not_sent': {'not_sent'},
    'bounced': {'bounced'},
    'failed': {'failed'},
}


def _send_parent_setup_email(request, parent_user, school, linked_students, plain_password):
    """
    Send a parent account setup email containing their temporary password and a login link.

    Returns True on success, False on failure.
    """
    import logging
    logger = logging.getLogger(__name__)

    if not parent_user.email:
        logger.warning('Cannot send parent setup email: no email for user %s', parent_user.pk)
        return False

    try:
        from django.urls import reverse
        from classroom.email_service import send_templated_email, _get_email_logo_url
        from django.conf import settings

        site_url = getattr(settings, 'SITE_URL', '').rstrip('/')
        login_path = getattr(settings, 'LOGIN_URL', '/accounts/login/')

        ctx = {
            'parent_name': parent_user.get_full_name() or parent_user.username,
            'school_name': school.name,
            'username': parent_user.username,
            'temp_password': plain_password,
            'login_url': f'{site_url}{login_path}',
            'student_names': [s.get_full_name() for s in linked_students],
            'site_url': site_url,
            'email_logo_url': _get_email_logo_url(school),
        }

        return send_templated_email(
            recipient_email=parent_user.email,
            subject=f'You have been added to {school.name} — Your Login Details',
            template_name='email/lifecycle/parent_account_setup.html',
            context=ctx,
            recipient_user=parent_user,
            notification_type='welcome',
            school=school,
            fail_silently=True,
        )
    except Exception:
        logger.exception('Failed to send parent setup email to %s', parent_user.email)
        return False


class ManageParentsRedirectView(RoleRequiredMixin, View):
    """School picker for parent management; redirects directly if only one school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        from .views_admin import _get_user_schools
        schools = list(_get_user_schools(request.user))
        if len(schools) == 1:
            return redirect('admin_school_parents', school_id=schools[0].id)
        if not schools:
            messages.info(request, 'Create a school first before managing parents.')
            return redirect('admin_school_create')
        return render(request, 'admin_dashboard/school_picker.html', {
            'schools': schools,
            'section': 'parents',
            'title': 'Select a School — Parents',
            'dest_url_name': 'admin_school_parents',
        })


class SchoolParentListView(RoleRequiredMixin, View):
    """List all parents (ParentStudent accounts + Guardian contacts) for a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def _get_school(self, request, school_id):
        from .views_admin import _get_user_school_or_404
        return _get_user_school_or_404(request.user, school_id)

    def get(self, request, school_id):
        school = self._get_school(request, school_id)
        search = request.GET.get('q', '').strip()

        # Build unified parent list — one row per real person.
        # A person may appear as a ParentStudent (login account) and/or a
        # Guardian (contact record). We aggregate ParentStudent rows by
        # parent_id so a parent with N children is one row, and suppress
        # any Guardian whose (school, email) already matches an account row.
        parents = []
        account_emails = set()  # lowercased emails emitted from ParentStudent

        # 1. ParentStudent links, aggregated by parent
        ps_qs = ParentStudent.objects.filter(
            school=school, is_active=True,
        ).select_related('parent', 'student')
        if search:
            ps_qs = ps_qs.filter(
                Q(parent__first_name__icontains=search) |
                Q(parent__last_name__icontains=search) |
                Q(parent__email__icontains=search)
            )

        ps_by_parent = {}
        for link in ps_qs:
            bucket = ps_by_parent.setdefault(link.parent_id, {
                'parent': link.parent,
                'links': [],
                'children': [],
            })
            bucket['links'].append(link)
            bucket['children'].append(link.student.get_full_name())

        for parent_id, bucket in ps_by_parent.items():
            parent_user = bucket['parent']
            first_link = bucket['links'][0]
            if parent_user.email:
                account_emails.add(parent_user.email.lower())
            parents.append({
                'id': f'ps_{first_link.id}',
                'type': 'Account',
                'first_name': parent_user.first_name,
                'last_name': parent_user.last_name,
                'email': parent_user.email,
                'phone': getattr(parent_user, 'phone', ''),
                'relationship': first_link.get_relationship_display(),
                'children': ', '.join(bucket['children']),
                'obj_type': 'parent_student',
                'obj_id': first_link.id,
                'parent_id': parent_user.id,
                'welcome_email_sent': parent_user.welcome_email_sent,
            })

        # 2. Guardian contacts — skip any whose email matches an account row
        g_qs = Guardian.objects.filter(school=school)
        if search:
            g_qs = g_qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search)
            )
        for g in g_qs:
            if g.email and g.email.lower() in account_emails:
                continue
            children_names = ', '.join(
                sg.student.get_full_name()
                for sg in g.guardian_students.select_related('student').all()
            )
            parents.append({
                'id': f'g_{g.id}',
                'type': 'Contact',
                'first_name': g.first_name,
                'last_name': g.last_name,
                'email': g.email,
                'phone': g.phone,
                'relationship': g.get_relationship_display(),
                'children': children_names or '—',
                'obj_type': 'guardian',
                'obj_id': g.id,
            })

        parents.sort(key=lambda p: (p['last_name'].lower(), p['first_name'].lower()))

        # Welcome-email delivery status for ALL parent accounts (CPP-343),
        # computed before paging so the ?welcome= filter can act on every row.
        # The state is driven by the latest welcome EmailLog (genuine evidence
        # the email went out), falling back to the welcome_email_sent flag only
        # for legacy accounts that predate delivery tracking.
        from .email_service import get_welcome_email_states
        states = get_welcome_email_states(
            [p['parent_id'] for p in parents if p.get('parent_id')]
        )
        for p in parents:
            if p.get('parent_id'):
                p['welcome_email_state'] = states.get(p['parent_id'])
                p['welcome_filter_state'] = _parent_welcome_filter_state(p)

        # Optional filter: sent | not_sent | bounced | failed. Guardian contacts
        # have no account/welcome email, so any welcome filter excludes them.
        welcome_filter = request.GET.get('welcome', '')
        if welcome_filter in _PARENT_WELCOME_FILTERS:
            wanted = _PARENT_WELCOME_FILTERS[welcome_filter]
            parents = [
                p for p in parents if p.get('welcome_filter_state') in wanted
            ]
        else:
            welcome_filter = ''

        paginator = Paginator(parents, 25)
        page = paginator.get_page(request.GET.get('page'))

        ctx = {
            'school': school,
            'parents': page,
            'page': page,
            'search': search,
            'welcome_filter': welcome_filter,
        }
        if request.headers.get('HX-Request'):
            return render(request, 'admin_dashboard/partials/parents_table.html', ctx)
        return render(request, 'admin_dashboard/school_parents.html', ctx)


class GuardianEditModalView(RoleRequiredMixin, View):
    """Return the guardian edit modal partial via HTMX."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, guardian_id):
        school = _get_user_school_or_404(request.user, school_id)
        guardian = get_object_or_404(Guardian, id=guardian_id, school=school)
        children = StudentGuardian.objects.filter(
            guardian=guardian,
        ).select_related('student')
        return render(request, 'admin_dashboard/partials/parent_edit_modal.html', {
            'school': school,
            'guardian': guardian,
            'children': children,
            'edit_type': 'guardian',
        })


class GuardianUpdateView(RoleRequiredMixin, View):
    """Save guardian edits."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, guardian_id):
        school = _get_user_school_or_404(request.user, school_id)
        guardian = get_object_or_404(Guardian, id=guardian_id, school=school)

        guardian.first_name = request.POST.get('first_name', guardian.first_name).strip()
        guardian.last_name = request.POST.get('last_name', guardian.last_name).strip()
        email = request.POST.get('email', '').strip()
        if email and '@' in email:
            guardian.email = email
        guardian.phone = request.POST.get('phone', guardian.phone).strip()
        relationship = request.POST.get('relationship', '').strip()
        if relationship:
            guardian.relationship = relationship
        guardian.address = request.POST.get('address', guardian.address).strip()
        guardian.city = request.POST.get('city', guardian.city).strip()
        guardian.country = request.POST.get('country', guardian.country).strip()
        guardian.save()

        log_event(
            user=request.user, school=school, category='data_change',
            action='guardian_edited',
            detail={'guardian_id': guardian.id, 'guardian_name': f'{guardian.first_name} {guardian.last_name}'},
            request=request,
        )
        messages.success(request, f'{guardian.first_name} {guardian.last_name} updated.')
        return redirect('admin_school_parents', school_id=school.id)


class ParentLinkEditModalView(RoleRequiredMixin, View):
    """Return the parent-student link edit modal partial via HTMX."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, link_id):
        school = _get_user_school_or_404(request.user, school_id)
        link = get_object_or_404(
            ParentStudent, id=link_id, school=school, is_active=True,
        )
        # Get all children linked to this parent in this school
        children = ParentStudent.objects.filter(
            parent=link.parent, school=school, is_active=True,
        ).select_related('student')
        return render(request, 'admin_dashboard/partials/parent_edit_modal.html', {
            'school': school,
            'parent_link': link,
            'children': children,
            'edit_type': 'parent_student',
        })


class ParentLinkUpdateView(RoleRequiredMixin, View):
    """Save parent-student link edits, plus the underlying parent account fields."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, link_id):
        from accounts.models import CustomUser
        import logging
        logger = logging.getLogger(__name__)

        school = _get_user_school_or_404(request.user, school_id)
        link = get_object_or_404(
            ParentStudent, id=link_id, school=school, is_active=True,
        )

        # --- ParentStudent link fields ---
        relationship = request.POST.get('relationship', '').strip()
        if relationship:
            link.relationship = relationship
        is_primary = request.POST.get('is_primary_contact') == 'on'
        link.is_primary_contact = is_primary
        link.save(update_fields=['relationship', 'is_primary_contact'])

        # --- Underlying CustomUser (parent account) fields ---
        parent = link.parent
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        new_email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()

        old_email = parent.email or ''
        user_dirty = False

        if first_name and first_name != parent.first_name:
            parent.first_name = first_name
            user_dirty = True
        if last_name and last_name != parent.last_name:
            parent.last_name = last_name
            user_dirty = True
        if phone != (parent.phone or ''):
            parent.phone = phone
            user_dirty = True

        email_changed = False
        if new_email and new_email != old_email:
            if '@' not in new_email:
                messages.error(request, 'Email must contain "@".')
                return redirect('admin_school_parents', school_id=school.id)
            if CustomUser.objects.filter(email__iexact=new_email).exclude(pk=parent.pk).exists():
                messages.error(request, f'Another account already uses {new_email}.')
                return redirect('admin_school_parents', school_id=school.id)
            parent.email = new_email
            user_dirty = True
            email_changed = True

        if user_dirty:
            parent.save(update_fields=['first_name', 'last_name', 'email', 'phone'])

        # Notify the parent if their email address was changed by an admin.
        if email_changed:
            try:
                from notifications.services import send_email_changed_notification
                # Notify the new address (matches self-service pattern)
                send_email_changed_notification(parent, new_email=new_email, school=school)
                # Best-effort heads-up to the previous address so the user notices.
                if old_email:
                    try:
                        from classroom.email_service import send_templated_email, _get_email_logo_url
                        send_templated_email(
                            recipient_email=old_email,
                            subject=f'[{school.name}] Your account email was changed by an administrator',
                            template_name='email/lifecycle/email_changed.html',
                            context={
                                'recipient_name': parent.get_full_name() or parent.username,
                                'school_name': school.name,
                                'new_email': new_email,
                                'change_datetime': timezone.now(),
                                'email_logo_url': _get_email_logo_url(school),
                            },
                            recipient_user=parent,
                            notification_type='email_changed',
                            school=school,
                            fail_silently=True,
                        )
                    except Exception:
                        logger.exception('Failed to notify old email %s of address change', old_email)
            except Exception:
                logger.exception('Failed to send email-changed notification for parent %s', parent.pk)

        log_event(
            user=request.user, school=school, category='data_change',
            action='parent_link_edited',
            detail={
                'link_id': link.id,
                'parent_id': parent.id,
                'parent': parent.get_full_name(),
                'email_changed': email_changed,
            },
            request=request,
        )
        messages.success(request, f'{parent.get_full_name()} updated.')
        return redirect('admin_school_parents', school_id=school.id)


class ParentInviteCreateView(RoleRequiredMixin, View):
    """Create and send a parent invite for a specific student."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, student_id):
        school = _get_user_school_or_404(request.user, school_id)
        from accounts.models import CustomUser
        student = get_object_or_404(CustomUser, id=student_id)

        existing_links = ParentStudent.objects.filter(
            student=student, school=school, is_active=True,
        ).select_related('parent')

        pending_invites = ParentInvite.objects.filter(
            student=student, school=school, status='pending',
        )

        return render(request, 'admin_dashboard/invite_parent.html', {
            'school': school,
            'student': student,
            'existing_links': existing_links,
            'pending_invites': pending_invites,
            'can_invite': existing_links.count() < 2,
        })

    def post(self, request, school_id, student_id):
        school = _get_user_school_or_404(request.user, school_id)
        from accounts.models import CustomUser
        student = get_object_or_404(CustomUser, id=student_id)

        # Check max 2 parents
        active_count = ParentStudent.objects.filter(
            student=student, school=school, is_active=True,
        ).count()
        if active_count >= 2:
            messages.error(request, f'{student.first_name} already has 2 parent accounts linked.')
            return redirect('invite_parent', school_id=school.id, student_id=student.id)

        parent_email = request.POST.get('parent_email', '').strip()
        relationship = request.POST.get('relationship', '').strip()

        if not parent_email or '@' not in parent_email:
            messages.error(request, 'Please enter a valid email address.')
            return redirect('invite_parent', school_id=school.id, student_id=student.id)

        # Check for duplicate pending invite
        if ParentInvite.objects.filter(
            student=student, school=school, parent_email=parent_email, status='pending',
        ).exists():
            messages.warning(request, f'A pending invite already exists for {parent_email}.')
            return redirect('invite_parent', school_id=school.id, student_id=student.id)

        # Smart invite: if the email belongs to an existing user, link immediately
        from accounts.models import CustomUser
        existing_user = CustomUser.objects.filter(email=parent_email).first()
        if existing_user:
            # Check max 2 parent links per student per school
            if active_count >= 2:
                messages.error(request, f'{student.first_name} already has 2 parent accounts linked.')
                return redirect('invite_parent', school_id=school.id, student_id=student.id)

            # Check no duplicate ParentStudent for this user+student+school
            if ParentStudent.objects.filter(
                parent=existing_user, student=student, school=school,
            ).exists():
                messages.warning(request, f'{parent_email} is already linked to {student.first_name}.')
                return redirect('invite_parent', school_id=school.id, student_id=student.id)

            # Add PARENT role if not already assigned
            parent_role, _created = Role.objects.get_or_create(
                name=Role.PARENT,
                defaults={'display_name': 'Parent', 'description': 'Parent/guardian role'},
            )
            UserRole.objects.get_or_create(user=existing_user, role=parent_role)

            # Create ParentStudent link
            ParentStudent.objects.create(
                parent=existing_user,
                student=student,
                school=school,
                relationship=relationship,
                is_primary_contact=(active_count == 0),
                created_by=request.user,
            )

            # Create ParentInvite with status='accepted' for audit trail
            ParentInvite.objects.create(
                school=school,
                student=student,
                parent_email=parent_email,
                relationship=relationship,
                invited_by=request.user,
                expires_at=timezone.now() + timedelta(days=7),
                status='accepted',
                accepted_at=timezone.now(),
                accepted_by=existing_user,
            )

            # Notify the existing user that they've been linked
            try:
                from .email_service import send_templated_email, _get_email_logo_url
                from django.conf import settings as _settings
                site_url = getattr(_settings, 'SITE_URL', '').rstrip('/')
                login_path = getattr(_settings, 'LOGIN_URL', '/accounts/login/')
                send_templated_email(
                    recipient_email=parent_email,
                    subject=f'You have been linked to {student.first_name}\'s account at {school.name}',
                    template_name='email/transactional/parent_invite.html',
                    context={
                        'school_name': school.name,
                        'student_name': f'{student.first_name} {student.last_name}',
                        'registration_url': f'{site_url}{login_path}',
                        'expires_at': None,
                        'already_has_account': True,
                        'email_logo_url': _get_email_logo_url(school),
                    },
                    recipient_user=existing_user,
                    notification_type='parent_invite',
                    school=school,
                    fail_silently=True,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    'Failed to send parent link notification to %s', parent_email
                )

            log_event(
                user=request.user, school=school, category='data_change',
                action='parent_invited',
                detail={'parent_email': parent_email, 'student_id': student.id,
                        'student': f'{student.first_name} {student.last_name}',
                        'auto_linked': True},
                request=request,
            )
            messages.success(
                request,
                f'{parent_email} already has an account and has been linked to '
                f'{student.first_name} {student.last_name} automatically.',
            )
            return redirect('invite_parent', school_id=school.id, student_id=student.id)

        invite = ParentInvite.objects.create(
            school=school,
            student=student,
            parent_email=parent_email,
            relationship=relationship,
            invited_by=request.user,
            expires_at=timezone.now() + timedelta(days=7),
        )

        # Send invite email with registration link (best-effort)
        try:
            from .email_service import send_templated_email, _get_email_logo_url
            from django.urls import reverse
            from django.conf import settings as _settings
            registration_url = request.build_absolute_uri(
                reverse('register_parent', args=[invite.token])
            )
            send_templated_email(
                recipient_email=parent_email,
                subject=f'You are invited to view {student.first_name}\'s records at {school.name}',
                template_name='email/transactional/parent_invite.html',
                context={
                    'school_name': school.name,
                    'student_name': f'{student.first_name} {student.last_name}',
                    'registration_url': registration_url,
                    'expires_at': invite.expires_at,
                    'email_logo_url': _get_email_logo_url(school),
                },
                notification_type='parent_invite',
                school=school,
                fail_silently=True,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'Failed to send parent invite email to %s for student %s',
                parent_email, student.pk,
            )

        log_event(
            user=request.user, school=school, category='data_change',
            action='parent_invited',
            detail={'invite_id': invite.id, 'parent_email': parent_email,
                    'student_id': student.id,
                    'student': f'{student.first_name} {student.last_name}'},
            request=request,
        )
        messages.success(
            request,
            f'Invite sent to {parent_email} for {student.first_name} {student.last_name}.',
        )
        return redirect('invite_parent', school_id=school.id, student_id=student.id)


class ParentInviteListView(RoleRequiredMixin, View):
    """List all parent invites for a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        invites = (
            ParentInvite.objects.filter(school=school)
            .select_related('student', 'invited_by')
            .order_by('-created_at')
        )

        return render(request, 'admin_dashboard/parent_invites.html', {
            'school': school,
            'invites': invites,
        })


class ParentInviteRevokeView(RoleRequiredMixin, View):
    """Revoke a pending parent invite."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, invite_id):
        school = _get_user_school_or_404(request.user, school_id)
        invite = get_object_or_404(
            ParentInvite, id=invite_id, school=school, status='pending',
        )
        invite.status = 'revoked'
        invite.save(update_fields=['status'])
        log_event(
            user=request.user, school=school, category='data_change',
            action='parent_invite_revoked',
            detail={'invite_id': invite.id, 'parent_email': invite.parent_email},
            request=request,
        )
        messages.success(request, f'Invite to {invite.parent_email} has been revoked.')
        return redirect('parent_invite_list', school_id=school.id)


class StudentParentLinksView(RoleRequiredMixin, View):
    """View/manage parent links for a specific student."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, student_id):
        school = _get_user_school_or_404(request.user, school_id)
        from accounts.models import CustomUser
        student = get_object_or_404(CustomUser, id=student_id)

        links = ParentStudent.objects.filter(
            student=student, school=school,
        ).select_related('parent').order_by('-is_active', '-created_at')

        return render(request, 'admin_dashboard/student_parents.html', {
            'school': school,
            'student': student,
            'links': links,
        })


class ParentStudentUnlinkView(RoleRequiredMixin, View):
    """Deactivate a parent-student link."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, student_id, link_id):
        school = _get_user_school_or_404(request.user, school_id)
        link = get_object_or_404(
            ParentStudent, id=link_id, school=school, student_id=student_id,
        )
        link.is_active = False
        link.save(update_fields=['is_active'])
        log_event(
            user=request.user, school=school, category='data_change',
            action='parent_student_unlinked',
            detail={'link_id': link.id,
                    'parent_id': link.parent_id,
                    'parent': f'{link.parent.first_name} {link.parent.last_name}',
                    'student_id': link.student_id,
                    'student': f'{link.student.first_name} {link.student.last_name}'},
            request=request,
        )
        messages.success(
            request,
            f'Unlinked {link.parent.first_name} {link.parent.last_name} from '
            f'{link.student.first_name} {link.student.last_name}.',
        )
        return redirect('student_parent_links', school_id=school.id, student_id=student_id)


# ---------------------------------------------------------------------------
# Add new parent / link existing parent (school-level)
# ---------------------------------------------------------------------------

class AddParentView(RoleRequiredMixin, View):
    """Create a new parent account and link them to students in this school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def _school_students(self, school):
        return (
            SchoolStudent.objects.filter(school=school, is_active=True)
            .select_related('student')
            .order_by('student__last_name', 'student__first_name')
        )

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        from classroom.models import ClassRoom
        classes = (
            ClassRoom.objects.filter(school=school, is_active=True)
            .select_related('subject', 'department')
            .order_by('name')
        )
        return render(request, 'admin_dashboard/add_parent.html', {
            'school': school,
            'students': self._school_students(school),
            'relationship_choices': ParentStudent.RELATIONSHIP_CHOICES,
            'default_relationship': 'guardian',
            'classes': classes,
        })

    def _render_form(self, request, school, extra=None):
        from classroom.models import ClassRoom
        ctx = {
            'school': school,
            'students': self._school_students(school),
            'relationship_choices': ParentStudent.RELATIONSHIP_CHOICES,
            'default_relationship': 'guardian',
            'classes': ClassRoom.objects.filter(school=school, is_active=True)
                       .select_related('subject', 'department').order_by('name'),
        }
        if extra:
            ctx.update(extra)
        return render(request, 'admin_dashboard/add_parent.html', ctx)

    def post(self, request, school_id):
        import secrets
        from django.db import transaction
        from accounts.models import CustomUser
        from accounts.models import Role as _Role, UserRole as _UserRole
        from classroom.models import ClassStudent, ClassRoom, SchoolStudent as _SS

        school = _get_user_school_or_404(request.user, school_id)
        email = request.POST.get('email', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        relationship = request.POST.get('relationship', 'guardian').strip()
        student_ids = list(request.POST.getlist('student_ids'))

        if not email or '@' not in email:
            messages.error(request, 'Please enter a valid email address.')
            return self._render_form(request, school, {'form_data': request.POST})

        # Check if a user with this email already exists
        existing = CustomUser.objects.filter(email=email).first()
        if existing:
            messages.warning(
                request,
                f'Found existing account: {existing.get_full_name()} ({existing.email}). '
                'Use "Link Existing Parent" below to connect them to students.',
            )
            return self._render_form(request, school, {
                'existing_parent': existing,
                'form_data': request.POST,
            })

        if not first_name or not last_name:
            messages.error(request, 'First name and last name are required.')
            return self._render_form(request, school, {'form_data': request.POST})

        # Validate inline student fields if requested
        inline_action = request.POST.get('inline_student_action', '').strip()
        inline_student_fields = None
        inline_link_student_id = None
        if inline_action == 'link':
            sid = request.POST.get('inline_student_id', '').strip()
            if not (sid and sid.isdigit()):
                messages.error(request, 'Please select a student to link.')
                return self._render_form(request, school, {'form_data': request.POST})
            if not SchoolStudent.objects.filter(school=school, student_id=int(sid), is_active=True).exists():
                messages.error(request, 'Selected student not found in this school.')
                return self._render_form(request, school, {'form_data': request.POST})
            inline_link_student_id = int(sid)
        if inline_action == 'new':
            s_first = request.POST.get('inline_student_first_name', '').strip()
            s_last = request.POST.get('inline_student_last_name', '').strip()
            s_email = request.POST.get('inline_student_email', '').strip()
            s_password = request.POST.get('inline_student_password', '').strip()
            s_class_ids = request.POST.getlist('inline_student_class_ids')
            inline_errors = []
            if not s_first:
                inline_errors.append('Student first name is required.')
            if not s_last:
                inline_errors.append('Student last name is required.')
            if not s_email or '@' not in s_email:
                inline_errors.append('A valid student email is required.')
            elif CustomUser.objects.filter(email=s_email).exists():
                inline_errors.append('A user with this student email already exists.')
            if len(s_password) < 8:
                inline_errors.append('Student password must be at least 8 characters.')
            if inline_errors:
                for err in inline_errors:
                    messages.error(request, err)
                return self._render_form(request, school, {'form_data': request.POST})
            # Billing limit
            from billing.entitlements import check_student_limit
            allowed, current, limit = check_student_limit(school)
            if not allowed:
                messages.error(
                    request,
                    f'Student limit reached ({limit}). Upgrade to add more students.',
                )
                return self._render_form(request, school, {'form_data': request.POST})
            inline_student_fields = {
                'first_name': s_first, 'last_name': s_last,
                'email': s_email, 'password': s_password,
                'class_ids': s_class_ids,
            }

        # Build unique username from email prefix
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while CustomUser.objects.filter(username=username).exists():
            username = f'{base_username}{counter}'
            counter += 1

        # Generate a temporary password — included in the invitation email
        temp_password = secrets.token_urlsafe(10)
        inline_student_user = None

        with transaction.atomic():
            parent_user = CustomUser.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=temp_password,
                phone=phone,
            )
            parent_user.must_change_password = True
            parent_user.creation_method = 'institute'
            parent_user.profile_completed = True
            parent_user.save(update_fields=['must_change_password', 'creation_method', 'profile_completed'])

            parent_role, _ = _Role.objects.get_or_create(
                name=_Role.PARENT,
                defaults={'display_name': 'Parent', 'description': 'Parent/guardian role'},
            )
            _UserRole.objects.get_or_create(user=parent_user, role=parent_role)

            # Inline student creation
            if inline_student_fields:
                sf = inline_student_fields
                s_uname_base = sf['email'].split('@')[0]
                s_uname = s_uname_base
                s_ctr = 1
                while CustomUser.objects.filter(username=s_uname).exists():
                    s_uname = f'{s_uname_base}{s_ctr}'
                    s_ctr += 1
                inline_student_user = CustomUser.objects.create_user(
                    username=s_uname,
                    email=sf['email'],
                    first_name=sf['first_name'],
                    last_name=sf['last_name'],
                    password=sf['password'],
                )
                inline_student_user.must_change_password = True
                inline_student_user.profile_completed = False
                inline_student_user.save(update_fields=['must_change_password', 'profile_completed'])
                student_role, _ = _Role.objects.get_or_create(
                    name=_Role.STUDENT, defaults={'display_name': 'Student'},
                )
                _UserRole.objects.create(
                    user=inline_student_user, role=student_role, assigned_by=request.user,
                )
                _SS.objects.create(school=school, student=inline_student_user)
                # Class enrollment
                allowed_cls_ids = set(
                    ClassRoom.objects.filter(school=school, is_active=True)
                    .values_list('id', flat=True)
                )
                skipped_classes = 0
                for cid_str in sf['class_ids']:
                    if cid_str.isdigit() and int(cid_str) in allowed_cls_ids:
                        cs, _ = ClassStudent.objects.get_or_create(
                            classroom_id=int(cid_str), student=inline_student_user,
                        )
                        if not cs.is_active:
                            cs.is_active = True
                            cs.save(update_fields=['is_active'])
                    elif cid_str.isdigit():
                        skipped_classes += 1
                if skipped_classes:
                    messages.warning(
                        request,
                        f'Student created but {skipped_classes} class assignment(s) could not be '
                        'applied (class not found or inactive). Enrol from the Classes page.',
                    )
                # Add to student_ids for linking below
                student_ids.append(str(inline_student_user.id))

            # Link-existing-student path (inline_action='link')
            if inline_link_student_id:
                student_ids.append(str(inline_link_student_id))

            # Link to selected students (existing + inline)
            linked_students = []
            for sid in student_ids:
                try:
                    ss = _SS.objects.get(school=school, student_id=int(sid), is_active=True)
                    existing_count = ParentStudent.objects.filter(
                        student=ss.student, school=school, is_active=True,
                    ).count()
                    if existing_count < 2:
                        ParentStudent.objects.create(
                            parent=parent_user,
                            student=ss.student,
                            school=school,
                            relationship=relationship,
                            is_primary_contact=(existing_count == 0),
                            created_by=request.user,
                        )
                        linked_students.append(ss.student)
                except (_SS.DoesNotExist, ValueError):
                    pass

        # Send invitation email with temporary credentials
        email_sent = _send_parent_setup_email(
            request=request,
            parent_user=parent_user,
            school=school,
            linked_students=linked_students,
            plain_password=temp_password,
        )

        # Send student welcome email for inline-created student
        if inline_student_user:
            from classroom.email_utils import send_staff_welcome_email
            send_staff_welcome_email(
                user=inline_student_user,
                plain_password=inline_student_fields['password'],
                role_display='Student',
                school=school,
            )
            log_event(
                user=request.user, school=school, category='data_change',
                action='student_added', detail={
                    'student_username': inline_student_user.username,
                    'student_name': inline_student_user.get_full_name(),
                    'added_via': 'inline_parent_add',
                },
                request=request,
            )

        log_event(
            user=request.user, school=school, category='data_change',
            action='parent_created_direct',
            detail={
                'parent_id': parent_user.id,
                'parent_name': parent_user.get_full_name(),
                'parent_email': email,
                'students_linked': len(linked_students),
                'invite_email_sent': email_sent,
                'inline_student_created': inline_student_user is not None,
            },
            request=request,
        )
        if email_sent:
            messages.success(
                request,
                f'Parent account created for {first_name} {last_name} and linked to '
                f'{len(linked_students)} student(s). An invitation email has been sent to {email}.',
            )
        else:
            messages.warning(
                request,
                f'Parent account created for {first_name} {last_name} and linked to '
                f'{len(linked_students)} student(s), but the invitation email could not be sent. '
                f'Use the "Resend Invite" button to try again.',
            )
        return redirect('admin_school_parents', school_id=school.id)


class LinkExistingParentView(RoleRequiredMixin, View):
    """Link an existing parent account to students in this school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def _school_students(self, school):
        return (
            SchoolStudent.objects.filter(school=school, is_active=True)
            .select_related('student')
            .order_by('student__last_name', 'student__first_name')
        )

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        return render(request, 'admin_dashboard/link_parent.html', {
            'school': school,
            'students': self._school_students(school),
            'relationship_choices': ParentStudent.RELATIONSHIP_CHOICES,
        })

    def post(self, request, school_id):
        from accounts.models import CustomUser

        school = _get_user_school_or_404(request.user, school_id)
        parent_id = request.POST.get('parent_id', '').strip()
        relationship = request.POST.get('relationship', 'guardian').strip()
        student_ids = request.POST.getlist('student_ids')

        if not parent_id:
            messages.error(request, 'Please select a parent account.')
            return redirect('admin_school_link_parent', school_id=school.id)

        try:
            parent_user = CustomUser.objects.get(id=int(parent_id))
        except (CustomUser.DoesNotExist, ValueError):
            messages.error(request, 'Parent account not found.')
            return redirect('admin_school_link_parent', school_id=school.id)

        # Ensure the user has the parent role
        parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT,
            defaults={'display_name': 'Parent', 'description': 'Parent/guardian role'},
        )
        UserRole.objects.get_or_create(user=parent_user, role=parent_role)

        linked = 0
        skipped = 0
        for sid in student_ids:
            try:
                ss = SchoolStudent.objects.get(school=school, student_id=int(sid), is_active=True)
                existing_count = ParentStudent.objects.filter(
                    student=ss.student, school=school, is_active=True,
                ).count()
                if ParentStudent.objects.filter(
                    parent=parent_user, student=ss.student, school=school,
                ).exists():
                    skipped += 1
                    continue
                if existing_count >= 2:
                    skipped += 1
                    continue
                ParentStudent.objects.create(
                    parent=parent_user,
                    student=ss.student,
                    school=school,
                    relationship=relationship,
                    is_primary_contact=(existing_count == 0),
                    created_by=request.user,
                )
                linked += 1
            except (SchoolStudent.DoesNotExist, ValueError):
                pass

        log_event(
            user=request.user, school=school, category='data_change',
            action='parent_linked_existing',
            detail={
                'parent_id': parent_user.id,
                'parent_name': parent_user.get_full_name(),
                'students_linked': linked,
                'students_skipped': skipped,
            },
            request=request,
        )
        msg = f'{parent_user.get_full_name()} linked to {linked} student(s).'
        if skipped:
            msg += f' {skipped} skipped (already linked or at 2-parent limit).'
        messages.success(request, msg)
        return redirect('admin_school_parents', school_id=school.id)


class StudentAccountSearchView(RoleRequiredMixin, View):
    """HTMX: search for existing school students to link as children when adding a parent."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        q = request.GET.get('q', '').strip()
        parent_id = request.GET.get('parent_id', '').strip()
        results = []
        if len(q) >= 2:
            qs = SchoolStudent.objects.filter(
                school=school, is_active=True,
            ).filter(
                Q(student__email__icontains=q)
                | Q(student__first_name__icontains=q)
                | Q(student__last_name__icontains=q)
                | Q(student__username__icontains=q)
            ).select_related('student')[:15]
            results = list(qs)
            for ss in results:
                ss.already_linked = False
            if parent_id and parent_id.isdigit():
                pid = int(parent_id)
                if CustomUser.objects.filter(id=pid, roles__name=Role.PARENT).exists():
                    linked_ids = set(
                        ParentStudent.objects.filter(
                            parent_id=pid, school=school,
                        ).values_list('student_id', flat=True)
                    )
                    for ss in results:
                        ss.already_linked = ss.student_id in linked_ids
        return render(request, 'admin_dashboard/partials/student_account_search_results.html', {
            'results': results,
            'school': school,
            'q': q,
        })


class ParentAccountSearchView(RoleRequiredMixin, View):
    """HTMX: search for existing user accounts to link as parents."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        q = request.GET.get('q', '').strip()
        student_id = request.GET.get('student_id', '').strip()
        results = []
        if len(q) >= 2:
            qs = CustomUser.objects.filter(
                roles__name=Role.PARENT,
            ).filter(
                Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(username__icontains=q)
            ).exclude(is_superuser=True).distinct()[:15]
            results = list(qs)
            for user in results:
                user.already_linked = False
            if student_id and student_id.isdigit():
                sid = int(student_id)
                if SchoolStudent.objects.filter(student_id=sid, school=school, is_active=True).exists():
                    linked_ids = set(
                        ParentStudent.objects.filter(
                            student_id=sid, school=school,
                        ).values_list('parent_id', flat=True)
                    )
                    for user in results:
                        user.already_linked = user.id in linked_ids
        return render(request, 'admin_dashboard/partials/parent_account_search_results.html', {
            'results': results,
            'school': school,
            'q': q,
        })
