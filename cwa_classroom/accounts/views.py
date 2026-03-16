import logging
import re

from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.contrib.auth.views import PasswordResetView
from django.db import transaction

from django.utils.text import slugify

from .models import CustomUser, Role, UserRole

logger = logging.getLogger(__name__)


class DiagnosticPasswordResetView(PasswordResetView):
    """Override to add logging for debugging email delivery issues."""

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

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('subjects_hub')
        return render(request, 'accounts/register_teacher.html', {'center_mode': True})

    def post(self, request):
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')
        center_name = request.POST.get('center_name', '').strip()

        errors = _validate_registration(username, email, password, confirm)
        if not center_name:
            errors.append('School / centre name is required.')
        if errors:
            return render(request, 'accounts/register_teacher.html', {
                'errors': errors, 'username': username, 'email': email,
                'center_name': center_name, 'center_mode': True,
            })

        try:
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
                School.objects.create(
                    name=center_name,
                    slug=slug,
                    admin=user,
                )

            login(request, user)
            messages.success(request, f'Welcome! Your school "{center_name}" is ready.')
            return redirect('subjects_hub')
        except Exception as e:
            return render(request, 'accounts/register_teacher.html', {
                'errors': [str(e)], 'username': username, 'email': email,
                'center_name': center_name, 'center_mode': True,
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
        from billing.models import Package, DiscountCode, Subscription
        from django.utils import timezone
        from datetime import timedelta

        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')
        package_id = request.POST.get('package_id')
        discount_code_str = request.POST.get('discount_code', '').strip().upper()

        errors = _validate_registration(username, email, password, confirm)

        package = None
        if not package_id:
            errors.append('Please select a package.')
        else:
            package = Package.objects.filter(id=package_id, is_active=True).first()
            if not package:
                errors.append('Invalid package selected.')

        packages = Package.objects.filter(is_active=True).order_by('price')

        if errors:
            return render(request, 'accounts/register_individual_student.html', {
                'errors': errors, 'username': username, 'email': email,
                'packages': packages, 'selected_package_id': package_id,
            })

        # Validate discount code if provided
        discount = None
        if discount_code_str:
            discount = DiscountCode.objects.filter(code=discount_code_str).first()
            if not discount or not discount.is_valid():
                return render(request, 'accounts/register_individual_student.html', {
                    'errors': ['Invalid or expired discount code.'],
                    'username': username, 'email': email,
                    'packages': packages, 'selected_package_id': package_id,
                    'discount_code': discount_code_str,
                })

        try:
            with transaction.atomic():
                # Create user
                user = CustomUser.objects.create_user(
                    username=username, email=email, password=password,
                    package=package,
                )
                role, _ = Role.objects.get_or_create(
                    name=Role.INDIVIDUAL_STUDENT,
                    defaults={'display_name': 'Individual Student'},
                )
                UserRole.objects.create(user=user, role=role)

                # Create subscription record
                trial_end = timezone.now() + timedelta(days=package.trial_days)
                Subscription.objects.create(
                    user=user,
                    package=package,
                    status=Subscription.STATUS_TRIALING,
                    trial_end=trial_end,
                )

                # Handle discount code
                if discount and discount.is_fully_free:
                    discount.uses += 1
                    discount.save()
                    login(request, user)
                    messages.success(request, f'Welcome, {username}! Your free access is active.')
                    return redirect('select_classes')

            login(request, user)

            # Paid package — go to Stripe checkout
            if not package.is_free:
                return redirect('billing_checkout', package_id=package.id)

            messages.success(request, f'Welcome, {username}!')
            return redirect('select_classes')

        except Exception as e:
            return render(request, 'accounts/register_individual_student.html', {
                'errors': [str(e)], 'username': username, 'email': email,
                'packages': packages, 'selected_package_id': package_id,
            })


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
            messages.success(request, f'Joined "{classroom.name}" successfully!')

        elif action == 'leave':
            classroom_id = request.POST.get('classroom_id')
            classroom = get_object_or_404(ClassRoom, id=classroom_id)
            ClassStudent.objects.filter(classroom=classroom, student=request.user).delete()
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
        username = request.GET.get('username', '').strip()
        exclude_id = request.GET.get('exclude_id')
        try:
            exclude_id = int(exclude_id) if exclude_id else None
        except (ValueError, TypeError):
            exclude_id = None
        errors = _validate_username(username, exclude_user_id=exclude_id)
        return JsonResponse({'available': len(errors) == 0, 'errors': errors})
