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
from .models import School, ParentStudent, ParentInvite
from .views import RoleRequiredMixin


class ParentInviteCreateView(RoleRequiredMixin, View):
    """Create and send a parent invite for a specific student."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, student_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
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
        school = get_object_or_404(School, id=school_id, admin=request.user)
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

        messages.success(
            request,
            f'Invite sent to {parent_email} for {student.first_name} {student.last_name}.',
        )
        return redirect('invite_parent', school_id=school.id, student_id=student.id)


class ParentInviteListView(RoleRequiredMixin, View):
    """List all parent invites for a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
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
        school = get_object_or_404(School, id=school_id, admin=request.user)
        invite = get_object_or_404(
            ParentInvite, id=invite_id, school=school, status='pending',
        )
        invite.status = 'revoked'
        invite.save(update_fields=['status'])
        messages.success(request, f'Invite to {invite.parent_email} has been revoked.')
        return redirect('parent_invite_list', school_id=school.id)


class StudentParentLinksView(RoleRequiredMixin, View):
    """View/manage parent links for a specific student."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, student_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
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
        school = get_object_or_404(School, id=school_id, admin=request.user)
        link = get_object_or_404(
            ParentStudent, id=link_id, school=school, student_id=student_id,
        )
        link.is_active = False
        link.save(update_fields=['is_active'])
        messages.success(
            request,
            f'Unlinked {link.parent.first_name} {link.parent.last_name} from '
            f'{link.student.first_name} {link.student.last_name}.',
        )
        return redirect('student_parent_links', school_id=school.id, student_id=student_id)
