from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import transaction

from .models import CustomUser, Role, UserRole


# ---------------------------------------------------------------------------
# Teacher Registration
# ---------------------------------------------------------------------------

class TeacherSignupView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('home')
        return render(request, 'accounts/register_teacher.html')

    def post(self, request):
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')

        errors = _validate_registration(username, email, password, confirm)
        if errors:
            return render(request, 'accounts/register_teacher.html', {
                'errors': errors, 'username': username, 'email': email,
            })

        try:
            with transaction.atomic():
                user = CustomUser.objects.create_user(username=username, email=email, password=password)
                role, _ = Role.objects.get_or_create(name=Role.TEACHER, defaults={'display_name': 'Teacher'})
                UserRole.objects.create(user=user, role=role)
            login(request, user)
            messages.success(request, f'Welcome, {username}! Your teacher account is ready.')
            return redirect('home')
        except Exception as e:
            return render(request, 'accounts/register_teacher.html', {
                'errors': [str(e)], 'username': username, 'email': email,
            })


class TeacherCenterRegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('home')
        return render(request, 'accounts/register_teacher.html', {'center_mode': True})

    def post(self, request):
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')
        center_name = request.POST.get('center_name', '').strip()

        errors = _validate_registration(username, email, password, confirm)
        if not center_name:
            errors.append('Center/school name is required.')
        if errors:
            return render(request, 'accounts/register_teacher.html', {
                'errors': errors, 'username': username, 'email': email,
                'center_name': center_name, 'center_mode': True,
            })

        try:
            with transaction.atomic():
                user = CustomUser.objects.create_user(username=username, email=email, password=password)
                role, _ = Role.objects.get_or_create(name=Role.TEACHER, defaults={'display_name': 'Teacher'})
                UserRole.objects.create(user=user, role=role)
            login(request, user)
            messages.success(request, f'Welcome! Your teacher account for {center_name} is ready.')
            return redirect('home')
        except Exception as e:
            return render(request, 'accounts/register_teacher.html', {
                'errors': [str(e)], 'username': username, 'email': email,
                'center_name': center_name, 'center_mode': True,
            })


# ---------------------------------------------------------------------------
# Individual Student Registration (3-step)
# ---------------------------------------------------------------------------

class IndividualStudentRegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('home')
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
            return redirect('home')
        from classroom.models import ClassRoom
        from billing.models import PromoCode

        enrolled_classrooms = ClassRoom.objects.filter(
            students=request.user, is_active=True
        ).prefetch_related('levels')

        class_limit = _effective_class_limit(request.user)
        enrolled_count = enrolled_classrooms.count()
        redeemed_promos = PromoCode.objects.filter(redeemed_by=request.user, is_active=True)

        return render(request, 'accounts/select_classes.html', {
            'enrolled_classrooms': enrolled_classrooms,
            'class_limit': class_limit,
            'enrolled_count': enrolled_count,
            'redeemed_promos': redeemed_promos,
        })

    def post(self, request):
        if not request.user.is_individual_student:
            return redirect('home')
        from classroom.models import ClassRoom, ClassStudent
        from billing.models import PromoCode

        action = request.POST.get('action')

        if action == 'join':
            code = request.POST.get('class_code', '').strip().upper()
            if not code:
                messages.error(request, 'Please enter a class code.')
                return redirect('select_classes')

            try:
                classroom = ClassRoom.objects.get(code=code, is_active=True)
            except ClassRoom.DoesNotExist:
                messages.error(request, f'No active class found with code "{code}". Check with your teacher.')
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
            return redirect('home')
        from billing.models import Package
        packages = Package.objects.filter(is_active=True).order_by('price')
        return render(request, 'accounts/change_package.html', {
            'packages': packages,
            'current_package': request.user.package,
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_registration(username, email, password, confirm):
    errors = []
    if not username:
        errors.append('Username is required.')
    elif CustomUser.objects.filter(username=username).exists():
        errors.append(f'Username "{username}" is already taken.')
    if not email or '@' not in email:
        errors.append('A valid email address is required.')
    elif CustomUser.objects.filter(email=email).exists():
        errors.append('An account with this email already exists.')
    if len(password) < 8:
        errors.append('Password must be at least 8 characters.')
    if password != confirm:
        errors.append('Passwords do not match.')
    return errors
