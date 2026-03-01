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

class SelectClassesView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.is_individual_student:
            return redirect('home')
        from classroom.models import Subject, Level, StudentLevelEnrollment

        subjects = Subject.objects.filter(is_active=True).order_by('order', 'name')
        year_levels = Level.objects.filter(level_number__lte=9).order_by('level_number')
        enrollments = StudentLevelEnrollment.objects.filter(student=request.user).values_list('subject_id', 'level_id')
        enrolled_pairs = set(enrollments)

        subjects_data = []
        for subject in subjects:
            subjects_data.append({
                'subject': subject,
                'levels': year_levels,
                'enrolled_level_ids': {lvl_id for subj_id, lvl_id in enrolled_pairs if subj_id == subject.id},
            })

        package = request.user.package
        limit = package.class_limit if package else 0
        enrolled_count = StudentLevelEnrollment.objects.filter(student=request.user).count()

        return render(request, 'accounts/select_classes.html', {
            'subjects_data': subjects_data,
            'class_limit': limit,
            'enrolled_count': enrolled_count,
        })

    def post(self, request):
        if not request.user.is_individual_student:
            return redirect('home')
        from classroom.models import Subject, Level, StudentLevelEnrollment

        action = request.POST.get('action')
        subject_id = request.POST.get('subject_id')
        level_id = request.POST.get('level_id')
        subject = get_object_or_404(Subject, id=subject_id, is_active=True)
        level = get_object_or_404(Level, id=level_id)

        if action == 'join':
            package = request.user.package
            limit = package.class_limit if package else 0
            current_count = StudentLevelEnrollment.objects.filter(student=request.user).count()
            if limit != 0 and current_count >= limit:
                messages.error(request, f'You can only select {limit} year level(s) on your current plan.')
            else:
                StudentLevelEnrollment.objects.get_or_create(
                    student=request.user, subject=subject, level=level
                )
                messages.success(request, f'Enrolled in {subject.name} {level.display_name}.')

        elif action == 'leave':
            StudentLevelEnrollment.objects.filter(
                student=request.user, subject=subject, level=level
            ).delete()
            messages.success(request, f'Removed {subject.name} {level.display_name}.')

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
