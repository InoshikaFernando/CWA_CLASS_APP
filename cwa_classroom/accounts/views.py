import logging
import re

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.contrib.auth.views import LoginView, PasswordResetView
from django.db import transaction

from django.utils.text import slugify

from .models import CustomUser, Role, UserRole

logger = logging.getLogger(__name__)


def _check_registration_rate_limit(request):
    """Returns an HttpResponse(429) if rate limited, else None."""
    from django.conf import settings as django_settings
    if getattr(django_settings, 'TESTING', False):
        return None
    from billing.rate_limiting import check_rate_limit
    from audit.services import get_client_ip
    ip = get_client_ip(request) or 'unknown'
    if not check_rate_limit(f'register:{ip}', max_attempts=10, window_seconds=3600):
        return HttpResponse('Too many registration attempts. Please try again later.', status=429)
    return None


class AuditLoginView(LoginView):
    """Login view with audit logging and rate limiting."""

    def post(self, request, *args, **kwargs):
        from billing.rate_limiting import check_rate_limit
        from audit.services import get_client_ip
        ip = get_client_ip(request) or 'unknown'
        if not check_rate_limit(f'login:{ip}', max_attempts=5, window_seconds=900):
            from audit.services import log_event
            log_event(
                category='auth', action='login_rate_limited',
                result='blocked', detail={'ip': ip}, request=request,
            )
            messages.error(request, 'Too many login attempts. Please try again in 15 minutes.')
            return render(request, self.template_name, self.get_context_data())
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        from audit.services import log_event
        from billing.rate_limiting import reset_rate_limit
        from audit.services import get_client_ip
        response = super().form_valid(form)
        log_event(
            user=self.request.user,
            category='auth',
            action='login_success',
            request=self.request,
        )
        # Clear stale active_role from previous session
        self.request.session.pop('active_role', None)
        # Clear rate limit on successful login
        ip = get_client_ip(self.request) or 'unknown'
        reset_rate_limit(f'login:{ip}')
        return response

    def form_invalid(self, form):
        from audit.services import log_event
        username = form.cleaned_data.get('username', '')
        log_event(
            category='auth',
            action='login_failed',
            result='blocked',
            detail={'username': username},
            request=self.request,
        )
        return super().form_invalid(form)


class SwitchRoleView(LoginRequiredMixin, View):
    """POST-only view to switch the user's active role."""

    def post(self, request):
        role = request.POST.get('role', '')
        if not role or not request.user.has_role(role):
            messages.error(request, 'Invalid role.')
            return redirect('home')

        request.session['active_role'] = role

        from audit.services import log_event
        log_event(
            user=request.user, category='auth', action='role_switched',
            detail={'role': role}, request=request,
        )

        # Redirect to the appropriate dashboard for the new role
        dashboard_map = {
            Role.PARENT: 'parent_dashboard',
            Role.ADMIN: 'admin_dashboard',
            Role.INSTITUTE_OWNER: 'admin_dashboard',
            Role.HEAD_OF_INSTITUTE: 'admin_dashboard',
            Role.HEAD_OF_DEPARTMENT: 'hod_overview',
            Role.SENIOR_TEACHER: 'teacher_dashboard',
            Role.TEACHER: 'teacher_dashboard',
            Role.JUNIOR_TEACHER: 'teacher_dashboard',
            Role.STUDENT: 'subjects_hub',
            Role.INDIVIDUAL_STUDENT: 'subjects_hub',
            Role.ACCOUNTANT: 'invoice_list',
        }
        target = dashboard_map.get(role, 'home')
        return redirect(target)


class DiagnosticPasswordResetView(PasswordResetView):
    """Override to add logging for debugging email delivery issues."""

    def post(self, request, *args, **kwargs):
        from billing.rate_limiting import check_rate_limit
        from audit.services import get_client_ip
        ip = get_client_ip(request) or 'unknown'
        if not check_rate_limit(f'password_reset:{ip}', max_attempts=5, window_seconds=900):
            messages.error(request, 'Too many password reset attempts. Please try again in 15 minutes.')
            return render(request, self.template_name, self.get_context_data())
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        email = form.cleaned_data.get('email', '')
        # Check if any users match this email
        users = list(form.get_users(email))
        if users:
            logger.info(
                'Password reset requested for %s — found %d matching user(s)',
                email, len(users),
            )
        else:
            logger.warning(
                'Password reset requested for %s — NO matching users found '
                '(email not registered, account inactive, or unusable password)',
                email,
            )
        try:
            response = super().form_valid(form)
            logger.info('Password reset email sent successfully for %s', email)
            from audit.services import log_event
            log_event(
                category='auth', action='password_reset_requested',
                detail={'email': email, 'users_found': len(users)},
                request=self.request,
            )
            return response
        except Exception:
            logger.exception('Failed to send password reset email for %s', email)
            raise


# ---------------------------------------------------------------------------
# Head of Institute Registration
# ---------------------------------------------------------------------------

class TeacherSignupView(View):
    """Legacy URL — redirects to the center registration flow."""
    def get(self, request):
        return redirect('register_teacher_center')

    def post(self, request):
        return redirect('register_teacher_center')


class TeacherCenterRegisterView(View):
    """Register as Head of Institute — creates a user, school, and assigns HoI role."""

    def _get_plans(self):
        from billing.models import InstitutePlan
        return InstitutePlan.objects.filter(is_active=True).order_by('order', 'price')

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('subjects_hub')
        return render(request, 'accounts/register_teacher.html', {
            'center_mode': True, 'plans': self._get_plans(),
        })

    def post(self, request):
        rate_limited = _check_registration_rate_limit(request)
        if rate_limited:
            return rate_limited

        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')
        center_name = request.POST.get('center_name', '').strip()
        plan_id = request.POST.get('plan_id', '').strip()
        discount_code_str = request.POST.get('discount_code', '').strip().upper()

        # Company / address fields (Step 2)
        abn = request.POST.get('abn', '').strip()
        phone = request.POST.get('phone', '').strip()
        street_address = request.POST.get('street_address', '').strip()
        city = request.POST.get('city', '').strip()
        state_region = request.POST.get('state_region', '').strip()
        postal_code = request.POST.get('postal_code', '').strip()
        country = request.POST.get('country', '').strip()

        errors = _validate_registration(username, email, password, confirm)
        if not center_name:
            errors.append('School / centre name is required.')

        from billing.models import InstitutePlan, InstituteDiscountCode, SchoolSubscription
        plan = None
        if plan_id:
            plan = InstitutePlan.objects.filter(id=plan_id, is_active=True).first()
        if not plan:
            errors.append('Please select a plan.')

        # Validate discount code (optional)
        discount_obj = None
        if discount_code_str:
            discount_obj = InstituteDiscountCode.objects.filter(
                code__iexact=discount_code_str,
            ).first()
            if not discount_obj:
                errors.append('Invalid discount code.')
            elif not discount_obj.is_valid():
                errors.append('This discount code has expired or reached its usage limit.')

        if errors:
            return render(request, 'accounts/register_teacher.html', {
                'errors': errors, 'username': username, 'email': email,
                'center_name': center_name, 'center_mode': True,
                'plans': self._get_plans(), 'selected_plan_id': plan_id,
                'discount_code': discount_code_str,
                'abn': abn, 'phone': phone, 'street_address': street_address,
                'city': city, 'state_region': state_region,
                'postal_code': postal_code, 'country': country,
            })

        try:
            from datetime import timedelta
            from django.utils import timezone
            from classroom.models import School

            with transaction.atomic():
                # 1. Create user
                user = CustomUser.objects.create_user(
                    username=username, email=email, password=password,
                )

                # 2. Assign Head of Institute role
                role, _ = Role.objects.get_or_create(
                    name=Role.HEAD_OF_INSTITUTE,
                    defaults={'display_name': 'Head of Institute'},
                )
                UserRole.objects.create(user=user, role=role)

                # 3. Create school with this user as admin
                slug = slugify(center_name)
                base_slug = slug or 'school'
                counter = 1
                while School.objects.filter(slug=slug).exists():
                    slug = f'{base_slug}-{counter}'
                    counter += 1
                school = School.objects.create(
                    name=center_name,
                    slug=slug,
                    admin=user,
                    abn=abn,
                    phone=phone,
                    street_address=street_address,
                    city=city,
                    state_region=state_region,
                    postal_code=postal_code,
                    country=country,
                )

                # 4. Create school subscription
                # If 100% discount code → active immediately, otherwise trial
                is_free = discount_obj and discount_obj.is_fully_free
                if is_free:
                    status = SchoolSubscription.STATUS_ACTIVE
                    trial_end = None
                    has_used_trial = False
                else:
                    status = SchoolSubscription.STATUS_TRIALING
                    trial_days = plan.trial_days if plan else 14
                    trial_end = timezone.now() + timedelta(days=trial_days)
                    has_used_trial = True

                sub = SchoolSubscription.objects.create(
                    school=school,
                    plan=plan,
                    discount_code=discount_obj,
                    status=status,
                    trial_end=trial_end,
                    has_used_trial=has_used_trial,
                    invoice_year_start=timezone.now().date(),
                )

                # Increment discount code usage
                if discount_obj:
                    discount_obj.uses += 1
                    discount_obj.save(update_fields=['uses'])

            login(request, user)

            from audit.services import log_event
            log_event(
                user=user, school=school, category='auth',
                action='hoi_registered',
                detail={
                    'center_name': center_name, 'plan': plan.name if plan else None,
                    'discount_code': discount_code_str or None,
                },
                request=request,
            )

            # If plan has a Stripe price and not fully free → redirect to Stripe Checkout
            if plan and plan.stripe_price_id and not is_free:
                try:
                    from billing.stripe_service import create_institute_checkout_session
                    stripe_coupon = discount_obj.stripe_coupon_id if discount_obj and discount_obj.stripe_coupon_id else None
                    session = create_institute_checkout_session(
                        school, plan, request,
                        trial_period_days=plan.trial_days if plan.trial_days else 14,
                        stripe_coupon_id=stripe_coupon,
                    )
                    return redirect(session.url)
                except Exception:
                    # Stripe not configured or failed — fall through to dashboard
                    pass

            messages.success(request, f'Welcome! Your school "{center_name}" is ready.')
            return redirect('subjects_hub')
        except Exception as e:
            return render(request, 'accounts/register_teacher.html', {
                'errors': [str(e)], 'username': username, 'email': email,
                'center_name': center_name, 'center_mode': True,
                'plans': self._get_plans(), 'selected_plan_id': plan_id,
                'discount_code': discount_code_str,
                'abn': abn, 'phone': phone, 'street_address': street_address,
                'city': city, 'state_region': state_region,
                'postal_code': postal_code, 'country': country,
            })


# ---------------------------------------------------------------------------
# School Student Registration (simple — no package)
# ---------------------------------------------------------------------------

class SchoolStudentRegisterView(View):
    """Register as a school student — no package or subscription needed."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('subjects_hub')
        return render(request, 'accounts/register_school_student.html')

    def post(self, request):
        rate_limited = _check_registration_rate_limit(request)
        if rate_limited:
            return rate_limited

        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')
        username = request.POST.get('username', '').strip()

        errors = []
        if not first_name:
            errors.append('First name is required.')
        if not last_name:
            errors.append('Last name is required.')
        if not email or '@' not in email:
            errors.append('A valid email address is required.')
        elif CustomUser.objects.filter(email=email).exists():
            errors.append('An account with this email already exists.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if password != confirm:
            errors.append('Passwords do not match.')

        # Username: use provided or auto-generate from email
        if username:
            errors.extend(_validate_username(username))
        elif email and '@' in email:
            username = _generate_username_suggestion(email)

        if errors:
            return render(request, 'accounts/register_school_student.html', {
                'errors': errors,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'username': username,
            })

        try:
            with transaction.atomic():
                user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )
                student_role, _ = Role.objects.get_or_create(
                    name=Role.STUDENT,
                    defaults={'display_name': 'Student'},
                )
                UserRole.objects.create(user=user, role=student_role)

            login(request, user)

            from audit.services import log_event
            log_event(
                user=user, school=None, category='auth',
                action='school_student_registered',
                detail={'username': username, 'email': email},
                request=request,
            )

            messages.success(request, f'Welcome, {first_name}! You can now join a class using a class code.')
            return redirect('student_join_class')

        except Exception as e:
            return render(request, 'accounts/register_school_student.html', {
                'errors': [str(e)],
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
            })


# ---------------------------------------------------------------------------
# Individual Student Registration (3-step)
# ---------------------------------------------------------------------------

class IndividualStudentRegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('subjects_hub')
        from billing.models import Package
        packages = Package.objects.filter(is_active=True).order_by('price')
        return render(request, 'accounts/register_individual_student.html', {'packages': packages})

    def post(self, request):
        rate_limited = _check_registration_rate_limit(request)
        if rate_limited:
            return rate_limited

        from billing.models import Package, DiscountCode, Subscription
        from django.utils import timezone
        from datetime import timedelta

        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')
        package_id = request.POST.get('package_id')
        discount_code_str = request.POST.get('discount_code', '').strip().upper()

        # Personal / address fields (Step 2)
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        date_of_birth = request.POST.get('date_of_birth', '').strip()
        phone = request.POST.get('phone', '').strip()
        street_address = request.POST.get('street_address', '').strip()
        city = request.POST.get('city', '').strip()
        postal_code = request.POST.get('postal_code', '').strip()
        country = request.POST.get('country', '').strip()

        errors = _validate_registration(username, email, password, confirm)

        package = None
        if not package_id:
            errors.append('Please select a package.')
        else:
            package = Package.objects.filter(id=package_id, is_active=True).first()
            if not package:
                errors.append('Invalid package selected.')

        packages = Package.objects.filter(is_active=True).order_by('price')

        ctx = {
            'username': username, 'email': email,
            'packages': packages, 'selected_package_id': package_id,
            'discount_code': discount_code_str,
            'first_name': first_name, 'last_name': last_name,
            'date_of_birth': date_of_birth, 'phone': phone,
            'street_address': street_address, 'city': city,
            'postal_code': postal_code, 'country': country,
        }

        if errors:
            ctx['errors'] = errors
            return render(request, 'accounts/register_individual_student.html', ctx)

        # Validate discount code if provided
        discount = None
        if discount_code_str:
            discount = DiscountCode.objects.filter(code=discount_code_str).first()
            if not discount or not discount.is_valid():
                ctx['errors'] = ['Invalid or expired discount code.']
                return render(request, 'accounts/register_individual_student.html', ctx)

        try:
            with transaction.atomic():
                user = CustomUser.objects.create_user(
                    username=username, email=email, password=password,
                    package=package,
                    first_name=first_name, last_name=last_name,
                    phone=phone, street_address=street_address,
                    city=city, postal_code=postal_code, country=country,
                )
                if date_of_birth:
                    user.date_of_birth = date_of_birth
                    user.save(update_fields=['date_of_birth'])

                role, _ = Role.objects.get_or_create(
                    name=Role.INDIVIDUAL_STUDENT,
                    defaults={'display_name': 'Individual Student'},
                )
                UserRole.objects.create(user=user, role=role)

                # Create subscription record – all packages start as a trial
                trial_end = timezone.now() + timedelta(days=package.trial_days)
                Subscription.objects.create(
                    user=user, package=package,
                    status=Subscription.STATUS_TRIALING,
                    trial_end=trial_end,
                )

                # Handle discount code
                if discount:
                    discount.uses += 1
                    discount.save(update_fields=['uses'])

                    if discount.is_fully_free:
                        sub = user.subscription
                        sub.status = Subscription.STATUS_ACTIVE
                        sub.trial_end = None
                        sub.save(update_fields=['status', 'trial_end'])

            login(request, user, backend='accounts.backends.EmailOrUsernameBackend')

            from audit.services import log_event
            log_event(
                user=user, school=None, category='auth',
                action='individual_student_registered',
                detail={
                    'username': username, 'email': email,
                    'package': package.name if package else None,
                    'discount_code': discount_code_str or None,
                },
                request=request,
            )

            # Paid package with Stripe price → redirect to Stripe Checkout
            if not package.is_free and package.stripe_price_id and not (discount and discount.is_fully_free):
                try:
                    from billing.stripe_service import create_individual_checkout_session
                    stripe_coupon = getattr(discount, 'stripe_coupon_id', None) if discount else None
                    session = create_individual_checkout_session(
                        user, package, request,
                        stripe_coupon_id=stripe_coupon if stripe_coupon else None,
                    )
                    return redirect(session.url)
                except Exception:
                    pass

            messages.success(request, f'Welcome, {username}!')
            return redirect('select_classes')

        except Exception as e:
            ctx['errors'] = [str(e)]
            return render(request, 'accounts/register_individual_student.html', ctx)


class TrialExpiredView(View):
    def get(self, request):
        from billing.models import Package
        packages = Package.objects.filter(is_active=True, price__gt=0).order_by('price')
        return render(request, 'accounts/trial_expired.html', {'packages': packages})


class AccountBlockedView(View):
    """Landing page shown when a user's account is blocked or school is suspended."""
    def get(self, request):
        return render(request, 'accounts/account_blocked.html')


# ---------------------------------------------------------------------------
# Parent Registration (invite-based)
# ---------------------------------------------------------------------------

class ParentRegisterView(View):
    """Register as a parent using an invite token. Creates user + PARENT role + ParentStudent link."""

    def get(self, request, token):
        from classroom.models import ParentInvite
        invite = get_object_or_404(ParentInvite, token=token)

        if not invite.is_valid:
            from django.utils import timezone as tz
            if invite.status == 'pending' and invite.expires_at <= tz.now():
                effective_status = 'expired'
            else:
                effective_status = invite.status
            status_msg = {
                'accepted': 'This invite has already been used.',
                'expired': 'This invite has expired. Please contact the school for a new one.',
                'revoked': 'This invite has been revoked. Please contact the school.',
            }.get(effective_status, 'This invite is no longer valid.')
            return render(request, 'accounts/parent_invite_invalid.html', {
                'message': status_msg,
            })

        # If already logged in, redirect to accept-invite flow
        if request.user.is_authenticated:
            return redirect('accept_parent_invite', token=token)

        return render(request, 'accounts/register_parent.html', {
            'invite': invite,
            'email': invite.parent_email,
        })

    def post(self, request, token):
        from django.utils import timezone
        from classroom.models import ParentInvite, ParentStudent

        invite = get_object_or_404(ParentInvite, token=token)
        if not invite.is_valid:
            messages.error(request, 'This invite is no longer valid.')
            return redirect('login')

        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip() or invite.parent_email
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')
        username = request.POST.get('username', '').strip()

        errors = []
        if not first_name:
            errors.append('First name is required.')
        if not last_name:
            errors.append('Last name is required.')
        if not email or '@' not in email:
            errors.append('A valid email address is required.')
        elif CustomUser.objects.filter(email=email).exists():
            errors.append('An account with this email already exists. Please log in and accept the invite.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if password != confirm:
            errors.append('Passwords do not match.')

        if username:
            errors.extend(_validate_username(username))
        elif email and '@' in email:
            username = _generate_username_suggestion(email)

        if errors:
            return render(request, 'accounts/register_parent.html', {
                'invite': invite,
                'errors': errors,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'username': username,
            })

        try:
            with transaction.atomic():
                user = CustomUser.objects.create_user(
                    username=username, email=email, password=password,
                    first_name=first_name, last_name=last_name,
                )
                parent_role, _ = Role.objects.get_or_create(
                    name=Role.PARENT,
                    defaults={'display_name': 'Parent'},
                )
                UserRole.objects.create(user=user, role=parent_role)

                ParentStudent.objects.create(
                    parent=user, student=invite.student,
                    school=invite.school,
                    relationship=invite.relationship,
                    created_by=invite.invited_by,
                )

                invite.status = 'accepted'
                invite.accepted_at = timezone.now()
                invite.accepted_by = user
                invite.save(update_fields=['status', 'accepted_at', 'accepted_by'])

            login(request, user)

            from audit.services import log_event
            log_event(
                user=user, school=invite.school, category='auth',
                action='parent_registered',
                detail={
                    'invite_token': str(token),
                    'student': f'{invite.student.first_name} {invite.student.last_name}',
                    'relationship': invite.relationship,
                },
                request=request,
            )

            messages.success(
                request,
                f'Welcome, {first_name}! You are now linked to '
                f'{invite.student.first_name} {invite.student.last_name}.',
            )
            return redirect('parent_dashboard')

        except Exception as e:
            return render(request, 'accounts/register_parent.html', {
                'invite': invite,
                'errors': [str(e)],
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
            })


class ParentAcceptInviteView(LoginRequiredMixin, View):
    """Accept a parent invite for an existing logged-in user."""

    def get(self, request, token):
        from classroom.models import ParentInvite
        invite = get_object_or_404(ParentInvite, token=token)

        if not invite.is_valid:
            messages.error(request, 'This invite is no longer valid.')
            return redirect('subjects_hub')

        return render(request, 'accounts/accept_parent_invite.html', {
            'invite': invite,
        })

    def post(self, request, token):
        from django.utils import timezone
        from classroom.models import ParentInvite, ParentStudent

        invite = get_object_or_404(ParentInvite, token=token)
        if not invite.is_valid:
            messages.error(request, 'This invite is no longer valid.')
            return redirect('subjects_hub')

        try:
            with transaction.atomic():
                # Add PARENT role if user doesn't have it
                if not request.user.is_parent:
                    parent_role, _ = Role.objects.get_or_create(
                        name=Role.PARENT,
                        defaults={'display_name': 'Parent'},
                    )
                    UserRole.objects.create(user=request.user, role=parent_role)

                ParentStudent.objects.create(
                    parent=request.user, student=invite.student,
                    school=invite.school,
                    relationship=invite.relationship,
                    created_by=invite.invited_by,
                )

                invite.status = 'accepted'
                invite.accepted_at = timezone.now()
                invite.accepted_by = request.user
                invite.save(update_fields=['status', 'accepted_at', 'accepted_by'])

            from audit.services import log_event
            log_event(
                user=request.user, school=invite.school, category='auth',
                action='parent_invite_accepted',
                detail={
                    'invite_token': str(token),
                    'student': f'{invite.student.first_name} {invite.student.last_name}',
                    'relationship': invite.relationship,
                },
                request=request,
            )

            messages.success(
                request,
                f'You are now linked to '
                f'{invite.student.first_name} {invite.student.last_name}.',
            )
            return redirect('parent_dashboard')

        except Exception as e:
            messages.error(request, str(e))
            return redirect('subjects_hub')


# ---------------------------------------------------------------------------
# Profile Completion (first login after HoI creates student)
# ---------------------------------------------------------------------------

class CompleteProfileView(LoginRequiredMixin, View):
    """Force new students/teachers to change password, complete profile,
    and subscribe (school students need $19.90/mo subscription)."""

    def _get_student_package(self):
        """Get the default student subscription package."""
        from billing.models import Package
        return Package.objects.filter(is_active=True, price__gt=0).order_by('price').first()

    def get(self, request):
        if not request.user.must_change_password and request.user.profile_completed:
            return redirect('subjects_hub')
        return render(request, 'accounts/complete_profile.html', {
            'student_package': self._get_student_package() if request.user.is_student else None,
        })

    def post(self, request):
        user = request.user
        errors = []

        # Password change (required on first login)
        if user.must_change_password:
            new_pw = request.POST.get('new_password', '')
            confirm_pw = request.POST.get('confirm_password', '')
            if len(new_pw) < 8:
                errors.append('Password must be at least 8 characters.')
            elif new_pw != confirm_pw:
                errors.append('Passwords do not match.')

        # Profile fields
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        dob = request.POST.get('date_of_birth', '').strip()
        country = request.POST.get('country', '').strip()
        region = request.POST.get('region', '').strip()
        phone = request.POST.get('phone', '').strip()
        street_address = request.POST.get('street_address', '').strip()
        city = request.POST.get('city', '').strip()
        postal_code = request.POST.get('postal_code', '').strip()

        # Discount code for school students
        discount_code_str = request.POST.get('discount_code', '').strip().upper()

        if not first_name:
            errors.append('First name is required.')
        if not last_name:
            errors.append('Last name is required.')

        # Validate discount code if provided
        from billing.models import InstituteDiscountCode
        discount_obj = None
        if discount_code_str:
            discount_obj = InstituteDiscountCode.objects.filter(
                code__iexact=discount_code_str,
            ).first()
            if not discount_obj:
                errors.append('Invalid discount code.')
            elif not discount_obj.is_valid():
                errors.append('This discount code has expired or reached its usage limit.')

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'accounts/complete_profile.html', {
                'student_package': self._get_student_package() if user.is_student else None,
            })

        # Save profile
        user.first_name = first_name
        user.last_name = last_name
        if dob:
            user.date_of_birth = dob
        user.country = country
        user.region = region
        user.phone = phone
        user.street_address = street_address
        user.city = city
        user.postal_code = postal_code
        user.profile_completed = True

        if user.must_change_password:
            user.set_password(request.POST.get('new_password', ''))
            user.must_change_password = False

        user.save()
        update_session_auth_hash(request, user)

        from audit.services import log_event
        log_event(
            user=user, school=None, category='auth',
            action='profile_completed',
            detail={'first_name': first_name, 'last_name': last_name},
            request=request,
        )

        # Increment discount code usage
        if discount_obj:
            discount_obj.uses += 1
            discount_obj.save(update_fields=['uses'])

        # School students need their own subscription
        if user.is_student:
            from billing.models import Package, Subscription
            from django.utils import timezone
            from datetime import timedelta

            package = self._get_student_package()
            if package:
                # Create subscription
                is_free = discount_obj and discount_obj.is_fully_free
                if is_free:
                    Subscription.objects.get_or_create(
                        user=user,
                        defaults={
                            'package': package,
                            'status': Subscription.STATUS_ACTIVE,
                        },
                    )
                    user.package = package
                    user.save(update_fields=['package'])
                    messages.success(request, 'Profile completed! Free access activated.')
                    return redirect('subjects_hub')
                else:
                    trial_end = timezone.now() + timedelta(days=package.trial_days)
                    Subscription.objects.get_or_create(
                        user=user,
                        defaults={
                            'package': package,
                            'status': Subscription.STATUS_TRIALING,
                            'trial_end': trial_end,
                        },
                    )
                    user.package = package
                    user.save(update_fields=['package'])

                    # Redirect to Stripe Checkout for card details
                    if package.stripe_price_id:
                        try:
                            from billing.stripe_service import create_student_checkout_session
                            stripe_coupon = discount_obj.stripe_coupon_id if discount_obj and discount_obj.stripe_coupon_id else None
                            session = create_student_checkout_session(
                                user, package, request,
                                stripe_coupon_id=stripe_coupon,
                            )
                            return redirect(session.url)
                        except Exception as e:
                            import logging
                            logging.getLogger(__name__).error(
                                f'Stripe checkout session creation failed for user {user.id}: {e}'
                            )
                            messages.warning(request, 'Could not redirect to payment page. Please visit Billing to set up payment.')
                    else:
                        import logging
                        logging.getLogger(__name__).warning(
                            f'Package {package.id} ({package.name}) has no stripe_price_id — skipping Stripe redirect'
                        )

        messages.success(request, 'Profile completed successfully! Welcome aboard.')
        return redirect('subjects_hub')


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class ProfileView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'accounts/profile.html')

    def post(self, request):
        action = request.POST.get('action')

        if action == 'update_profile':
            # Update username if changed
            new_username = request.POST.get('username', '').strip()
            if new_username and new_username != request.user.username:
                errors = _validate_username(new_username, exclude_user_id=request.user.id)
                if errors:
                    for err in errors:
                        messages.error(request, err)
                    return redirect('profile')
                request.user.username = new_username

            request.user.first_name = request.POST.get('first_name', '').strip()
            request.user.last_name = request.POST.get('last_name', '').strip()
            request.user.email = request.POST.get('email', '').strip()
            dob = request.POST.get('date_of_birth', '').strip()
            if dob:
                request.user.date_of_birth = dob
            request.user.country = request.POST.get('country', '').strip()
            request.user.region = request.POST.get('region', '').strip()
            request.user.save()
            from audit.services import log_event
            log_event(
                user=request.user, school=None, category='data_change',
                action='profile_updated',
                detail={'first_name': request.user.first_name, 'last_name': request.user.last_name},
                request=request,
            )
            messages.success(request, 'Profile updated.')

        elif action == 'change_password':
            current = request.POST.get('current_password', '')
            new_pw = request.POST.get('new_password', '')
            confirm = request.POST.get('confirm_password', '')

            if not request.user.check_password(current):
                messages.error(request, 'Current password is incorrect.')
            elif len(new_pw) < 8:
                messages.error(request, 'New password must be at least 8 characters.')
            elif new_pw != confirm:
                messages.error(request, 'Passwords do not match.')
            else:
                request.user.set_password(new_pw)
                request.user.save()
                update_session_auth_hash(request, request.user)
                from audit.services import log_event
                log_event(
                    user=request.user, school=None, category='auth',
                    action='password_changed',
                    detail={}, request=request,
                )
                messages.success(request, 'Password changed successfully.')

        return redirect('profile')


# ---------------------------------------------------------------------------
# Class selection (IndividualStudent post-registration)
# ---------------------------------------------------------------------------

def _effective_class_limit(user):
    """Returns the effective class limit for a user.
    Checks redeemed promo codes first (0 = unlimited), then falls back to package limit."""
    from billing.models import PromoCode
    promo = PromoCode.objects.filter(redeemed_by=user, is_active=True).order_by('class_limit').first()
    if promo is not None:
        return promo.class_limit  # 0 = unlimited
    return user.package.class_limit if user.package else 1


class SelectClassesView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.is_individual_student:
            return redirect('subjects_hub')
        from classroom.models import ClassRoom, Subject
        from billing.models import PromoCode

        enrolled_classrooms = ClassRoom.objects.filter(
            students=request.user, is_active=True
        ).prefetch_related('levels')

        class_limit = _effective_class_limit(request.user)
        enrolled_count = enrolled_classrooms.count()
        redeemed_promos = PromoCode.objects.filter(redeemed_by=request.user, is_active=True)
        has_unlimited = class_limit == 0

        enrolled_ids = list(enrolled_classrooms.values_list('id', flat=True))

        available_classrooms = None
        subjects_with_rooms = []
        active_subject_slug = ''

        if has_unlimited:
            active_subject_slug = request.GET.get('subject', '')
            qs = (
                ClassRoom.objects.filter(is_active=True)
                .exclude(id__in=enrolled_ids)
                .select_related('subject')
                .prefetch_related('levels')
            )
            if active_subject_slug:
                qs = qs.filter(subject__slug=active_subject_slug)
            available_classrooms = qs

            subjects_with_rooms = list(
                Subject.objects.filter(
                    classrooms__is_active=True,
                    is_active=True,
                ).exclude(
                    classrooms__id__in=enrolled_ids
                ).distinct().order_by('order', 'name')
            )

        return render(request, 'accounts/select_classes.html', {
            'enrolled_classrooms': enrolled_classrooms,
            'available_classrooms': available_classrooms,
            'subjects_with_rooms': subjects_with_rooms,
            'active_subject_slug': active_subject_slug,
            'has_unlimited': has_unlimited,
            'class_limit': class_limit,
            'enrolled_count': enrolled_count,
            'redeemed_promos': redeemed_promos,
        })

    def post(self, request):
        if not request.user.is_individual_student:
            return redirect('subjects_hub')
        from classroom.models import ClassRoom, ClassStudent
        from billing.models import PromoCode

        action = request.POST.get('action')

        if action == 'join':
            # Support joining by ID (unlimited students browsing the list) or by code
            classroom_id = request.POST.get('classroom_id')
            code = request.POST.get('class_code', '').strip().upper()

            if classroom_id:
                classroom = get_object_or_404(ClassRoom, id=classroom_id, is_active=True)
            elif code:
                try:
                    classroom = ClassRoom.objects.get(code=code, is_active=True)
                except ClassRoom.DoesNotExist:
                    messages.error(request, f'No active class found with code "{code}". Check with your teacher.')
                    return redirect('select_classes')
            else:
                messages.error(request, 'Please enter a class code.')
                return redirect('select_classes')

            if ClassStudent.objects.filter(classroom=classroom, student=request.user).exists():
                messages.info(request, f'You are already enrolled in {classroom.name}.')
                return redirect('select_classes')

            class_limit = _effective_class_limit(request.user)
            enrolled_count = ClassRoom.objects.filter(students=request.user, is_active=True).count()
            if class_limit != 0 and enrolled_count >= class_limit:
                messages.error(request, f'Your plan allows up to {class_limit} class{"es" if class_limit != 1 else ""}. Use a promo code or upgrade to join more.')
                return redirect('select_classes')

            ClassStudent.objects.create(classroom=classroom, student=request.user)
            from audit.services import log_event
            log_event(
                user=request.user, school=None, category='data_change',
                action='class_joined',
                detail={'classroom_id': classroom.id, 'classroom_name': classroom.name},
                request=request,
            )
            messages.success(request, f'Joined "{classroom.name}" successfully!')

        elif action == 'leave':
            classroom_id = request.POST.get('classroom_id')
            classroom = get_object_or_404(ClassRoom, id=classroom_id)
            ClassStudent.objects.filter(classroom=classroom, student=request.user).delete()
            from audit.services import log_event
            log_event(
                user=request.user, school=None, category='data_change',
                action='class_left',
                detail={'classroom_id': classroom.id, 'classroom_name': classroom.name},
                request=request,
            )
            messages.success(request, f'Left "{classroom.name}".')

        elif action == 'redeem':
            code = request.POST.get('promo_code', '').strip().upper()
            if not code:
                messages.error(request, 'Please enter a promo code.')
                return redirect('select_classes')

            try:
                promo = PromoCode.objects.get(code=code)
            except PromoCode.DoesNotExist:
                messages.error(request, f'Promo code "{code}" is not valid.')
                return redirect('select_classes')

            if not promo.is_valid():
                messages.error(request, f'Promo code "{code}" has expired or is no longer active.')
                return redirect('select_classes')

            if promo.redeemed_by.filter(pk=request.user.pk).exists():
                messages.info(request, 'You have already redeemed this promo code.')
                return redirect('select_classes')

            promo.redeemed_by.add(request.user)
            promo.uses += 1
            promo.save(update_fields=['uses'])

            from audit.services import log_event
            log_event(
                user=request.user, school=None, category='data_change',
                action='promo_code_redeemed',
                detail={'code': code, 'class_limit': promo.class_limit},
                request=request,
            )

            limit_text = 'unlimited class access' if promo.class_limit == 0 else f'access to {promo.class_limit} class{"es" if promo.class_limit != 1 else ""}'
            messages.success(request, f'Promo code applied! You now have {limit_text}.')

        return redirect('select_classes')


# ---------------------------------------------------------------------------
# Change Package
# ---------------------------------------------------------------------------

class ChangePackageView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.is_individual_student:
            return redirect('subjects_hub')
        from billing.models import Package
        packages = Package.objects.filter(is_active=True).order_by('price')
        return render(request, 'accounts/change_package.html', {
            'packages': packages,
            'current_package': request.user.package,
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_username(username, exclude_user_id=None):
    """Validate username format and uniqueness. Returns list of error strings."""
    errors = []
    if not username:
        errors.append('Username is required.')
        return errors
    if len(username) < 3:
        errors.append('Username must be at least 3 characters.')
    if len(username) > 150:
        errors.append('Username must be 150 characters or fewer.')
    if not re.match(r'^[\w.]+$', username):
        errors.append('Username can only contain letters, numbers, underscores, and dots.')
    qs = CustomUser.objects.filter(username=username)
    if exclude_user_id:
        qs = qs.exclude(id=exclude_user_id)
    if qs.exists():
        errors.append(f'Username "{username}" is already taken.')
    return errors


def _generate_username_suggestion(email):
    """Generate a unique username from an email address."""
    base_username = email.split('@')[0].lower().replace(' ', '.')
    base_username = re.sub(r'[^\w.]', '', base_username)
    if len(base_username) < 3:
        base_username = base_username + 'user'
    username = base_username
    counter = 1
    while CustomUser.objects.filter(username=username).exists():
        username = f'{base_username}{counter}'
        counter += 1
    return username


def _validate_registration(username, email, password, confirm):
    errors = _validate_username(username)
    if not email or '@' not in email:
        errors.append('A valid email address is required.')
    elif CustomUser.objects.filter(email=email).exists():
        errors.append('An account with this email already exists.')
    if len(password) < 8:
        errors.append('Password must be at least 8 characters.')
    if password != confirm:
        errors.append('Passwords do not match.')
    return errors


class CheckUsernameView(View):
    """AJAX endpoint: check if a username is available."""
    def get(self, request):
        from billing.rate_limiting import check_rate_limit
        from audit.services import get_client_ip
        ip = get_client_ip(request) or 'unknown'
        if not check_rate_limit(f'check_username:{ip}', max_attempts=30, window_seconds=60):
            return JsonResponse({'available': False, 'errors': ['Too many requests.']}, status=429)

        username = request.GET.get('username', '').strip()
        exclude_id = request.GET.get('exclude_id')
        try:
            exclude_id = int(exclude_id) if exclude_id else None
        except (ValueError, TypeError):
            exclude_id = None
        errors = _validate_username(username, exclude_user_id=exclude_id)
        return JsonResponse({'available': len(errors) == 0, 'errors': errors})
