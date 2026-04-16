"""
HoI/Admin views for managing parent-student relationships (CPP-70).
"""
from datetime import timedelta

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views import View

from accounts.models import Role, UserRole
from audit.services import log_event
from django.core.paginator import Paginator
from django.db.models import Q

from .models import School, SchoolStudent, ParentStudent, ParentInvite, Guardian, StudentGuardian
from .views import RoleRequiredMixin
from .views_admin import _get_user_school_or_404


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

        paginator = Paginator(parents, 25)
        page = paginator.get_page(request.GET.get('page'))

        ctx = {
            'school': school,
            'parents': page,
            'page': page,
            'search': search,
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
    """Save parent-student link edits."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, link_id):
        school = _get_user_school_or_404(request.user, school_id)
        link = get_object_or_404(
            ParentStudent, id=link_id, school=school, is_active=True,
        )
        relationship = request.POST.get('relationship', '').strip()
        if relationship:
            link.relationship = relationship
        is_primary = request.POST.get('is_primary_contact') == 'on'
        link.is_primary_contact = is_primary
        link.save(update_fields=['relationship', 'is_primary_contact'])

        log_event(
            user=request.user, school=school, category='data_change',
            action='parent_link_edited',
            detail={'link_id': link.id, 'parent': link.parent.get_full_name()},
            request=request,
        )
        messages.success(request, f'{link.parent.get_full_name()} updated.')
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
        return render(request, 'admin_dashboard/add_parent.html', {
            'school': school,
            'students': self._school_students(school),
            'relationship_choices': ParentStudent.RELATIONSHIP_CHOICES,
        })

    def post(self, request, school_id):
        import secrets
        from accounts.models import CustomUser

        school = _get_user_school_or_404(request.user, school_id)
        email = request.POST.get('email', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        relationship = request.POST.get('relationship', 'guardian').strip()
        student_ids = request.POST.getlist('student_ids')

        if not email or '@' not in email:
            messages.error(request, 'Please enter a valid email address.')
            return render(request, 'admin_dashboard/add_parent.html', {
                'school': school,
                'students': self._school_students(school),
                'relationship_choices': ParentStudent.RELATIONSHIP_CHOICES,
                'form_data': request.POST,
            })

        # Check if a user with this email already exists
        existing = CustomUser.objects.filter(email=email).first()
        if existing:
            messages.warning(
                request,
                f'Found existing account: {existing.get_full_name()} ({existing.email}). '
                'Use "Link Existing Parent" below to connect them to students.',
            )
            return render(request, 'admin_dashboard/add_parent.html', {
                'school': school,
                'students': self._school_students(school),
                'relationship_choices': ParentStudent.RELATIONSHIP_CHOICES,
                'existing_parent': existing,
                'form_data': request.POST,
            })

        if not first_name or not last_name:
            messages.error(request, 'First name and last name are required.')
            return render(request, 'admin_dashboard/add_parent.html', {
                'school': school,
                'students': self._school_students(school),
                'relationship_choices': ParentStudent.RELATIONSHIP_CHOICES,
                'form_data': request.POST,
            })

        # Build unique username from email prefix
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while CustomUser.objects.filter(username=username).exists():
            username = f'{base_username}{counter}'
            counter += 1

        # Generate a temporary password — included in the invitation email
        temp_password = secrets.token_urlsafe(10)
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

        # Assign parent role
        parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT,
            defaults={'display_name': 'Parent', 'description': 'Parent/guardian role'},
        )
        UserRole.objects.get_or_create(user=parent_user, role=parent_role)

        # Link to selected students
        linked_students = []
        for sid in student_ids:
            try:
                ss = SchoolStudent.objects.get(school=school, student_id=int(sid), is_active=True)
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
            except (SchoolStudent.DoesNotExist, ValueError):
                pass

        # Send invitation email with temporary credentials
        email_sent = _send_parent_setup_email(
            request=request,
            parent_user=parent_user,
            school=school,
            linked_students=linked_students,
            plain_password=temp_password,
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


class ParentAccountSearchView(RoleRequiredMixin, View):
    """HTMX: search for existing user accounts to link as parents."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        q = request.GET.get('q', '').strip()
        results = []
        if len(q) >= 2:
            from accounts.models import CustomUser
            results = list(
                CustomUser.objects.filter(
                    Q(email__icontains=q)
                    | Q(first_name__icontains=q)
                    | Q(last_name__icontains=q)
                    | Q(username__icontains=q)
                ).exclude(is_superuser=True)[:15]
            )
        return render(request, 'admin_dashboard/partials/parent_account_search_results.html', {
            'results': results,
            'school': school,
            'q': q,
        })
