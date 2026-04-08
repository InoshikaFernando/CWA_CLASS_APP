"""
HoI/Admin views for managing parent-student relationships (CPP-70).
"""
from datetime import timedelta

from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
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


class ManageParentsRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's parent management page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        from .views_admin import _get_user_school
        school = _get_user_school(request.user)
        if school:
            return redirect('admin_school_parents', school_id=school.id)
        messages.info(request, 'Create a school first before managing parents.')
        return redirect('admin_school_create')


class SchoolParentListView(RoleRequiredMixin, View):
    """List all parents (ParentStudent accounts + Guardian contacts) for a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def _get_school(self, request, school_id):
        from .views_admin import _get_user_school_or_404
        return _get_user_school_or_404(request.user, school_id)

    def get(self, request, school_id):
        school = self._get_school(request, school_id)
        search = request.GET.get('q', '').strip()

        # Build unified parent list
        parents = []

        # 1. ParentStudent links (account-based parents)
        ps_qs = ParentStudent.objects.filter(
            school=school, is_active=True,
        ).select_related('parent', 'student')
        if search:
            ps_qs = ps_qs.filter(
                Q(parent__first_name__icontains=search) |
                Q(parent__last_name__icontains=search) |
                Q(parent__email__icontains=search)
            )
        for link in ps_qs:
            parents.append({
                'id': f'ps_{link.id}',
                'type': 'Account',
                'first_name': link.parent.first_name,
                'last_name': link.parent.last_name,
                'email': link.parent.email,
                'phone': getattr(link.parent, 'phone', ''),
                'relationship': link.get_relationship_display(),
                'children': link.student.get_full_name(),
                'obj_type': 'parent_student',
                'obj_id': link.id,
            })

        # 2. Guardian contacts
        g_qs = Guardian.objects.filter(school=school)
        if search:
            g_qs = g_qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search)
            )
        for g in g_qs:
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

            # Send notification email
            try:
                send_mail(
                    subject=f'You have been linked to {student.first_name}\'s account at {school.name}',
                    message=(
                        f'Hello {existing_user.first_name},\n\n'
                        f'You have been linked as a parent/guardian to '
                        f'{student.first_name} {student.last_name} at {school.name}.\n\n'
                        f'You can now log in to view your child\'s progress.\n\n'
                        f'Regards,\n{school.name}'
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[parent_email],
                    fail_silently=True,
                )
            except Exception:
                pass

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

        # Send email (best-effort)
        try:
            from .email_service import send_transactional_email
            from django.urls import reverse
            registration_url = request.build_absolute_uri(
                reverse('register_parent', args=[invite.token])
            )
            send_transactional_email(
                to_email=parent_email,
                subject=f'You are invited to view {student.first_name}\'s records at {school.name}',
                template='email/transactional/parent_invite.html',
                context={
                    'school_name': school.name,
                    'student_name': f'{student.first_name} {student.last_name}',
                    'registration_url': registration_url,
                    'expires_at': invite.expires_at,
                },
            )
        except Exception:
            pass  # Email failure shouldn't block invite creation

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
