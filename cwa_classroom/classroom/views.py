import logging

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import transaction

from accounts.models import CustomUser, Role, UserRole
from .models import (
    ClassRoom, Subject, Topic, Level, ClassTeacher, ClassStudent,
    SubjectApp, ContactMessage, CONTACT_SUBJECT_CHOICES,
)

logger = logging.getLogger(__name__)


class RoleRequiredMixin(LoginRequiredMixin):
    required_role = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.required_role and not request.user.has_role(self.required_role):
            messages.error(request, "You don't have permission to access that page.")
            return redirect('subjects_hub')
        return super().dispatch(request, *args, **kwargs)


def _get_individual_student_levels(user):
    basic_facts_levels = Level.objects.filter(level_number__gte=100)
    try:
        sub = user.subscription
        if sub.is_active_or_trialing:
            classrooms = ClassRoom.objects.filter(students=user, is_active=True)
            enrolled_levels = Level.objects.filter(classrooms__in=classrooms).distinct()
            return (enrolled_levels | basic_facts_levels).distinct()
    except Exception:
        pass
    return basic_facts_levels


class HomeView(LoginRequiredMixin, View):
    def get(self, request):
        # Superusers / staff with no Role → go straight to admin
        if request.user.is_superuser or request.user.is_staff:
            role = request.user.primary_role
            if role is None:
                return redirect('/admin/')

        role = request.user.primary_role

        if role == Role.ADMIN or role is None and request.user.is_superuser:
            return redirect('/admin/')
        if role == Role.HEAD_OF_DEPARTMENT:
            return redirect('hod_overview')
        if role == Role.ACCOUNTANT:
            return redirect('accounting_dashboard')

        if role == Role.TEACHER:
            classes = ClassRoom.objects.filter(
                teachers=request.user, is_active=True
            ).prefetch_related('students', 'teachers', 'levels')
            return render(request, 'teacher/home.html', {'classes': classes})

        if role in (Role.STUDENT, Role.INDIVIDUAL_STUDENT):
            if role == Role.STUDENT:
                classrooms = ClassRoom.objects.filter(students=request.user, is_active=True)
                accessible_levels = Level.objects.filter(classrooms__in=classrooms).distinct()
            else:
                accessible_levels = _get_individual_student_levels(request.user)

            year_data = []
            for year in range(1, 9):
                try:
                    level = Level.objects.get(level_number=year)
                    topics = Topic.objects.filter(levels=level, is_active=True).select_related('subject')
                    year_data.append({
                        'level': level,
                        'topics': topics,
                        'accessible': level in accessible_levels,
                    })
                except Level.DoesNotExist:
                    pass

            return render(request, 'student/home.html', {
                'year_data': year_data,
                'accessible_levels': accessible_levels,
            })

        # No role at all
        return render(request, 'accounts/no_role.html')


class StudentDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        if not (request.user.is_student or request.user.is_individual_student):
            return redirect('subjects_hub')
        from progress.models import StudentFinalAnswer, BasicFactsResult
        final_answers = StudentFinalAnswer.objects.filter(
            student=request.user
        ).select_related('topic', 'level').order_by('topic__name', 'level__level_number')
        bf_results = BasicFactsResult.objects.filter(
            student=request.user
        ).order_by('subtopic', 'level_number')
        return render(request, 'student/dashboard.html', {
            'final_answers': final_answers,
            'bf_results': bf_results,
        })


class TopicsView(LoginRequiredMixin, View):
    def get(self, request):
        subjects = Subject.objects.filter(is_active=True).prefetch_related('topics')
        return render(request, 'teacher/topics.html', {'subjects': subjects})


class TopicLevelsView(LoginRequiredMixin, View):
    def get(self, request, topic_id):
        topic = get_object_or_404(Topic, id=topic_id)
        levels = topic.levels.all().order_by('level_number')
        return render(request, 'teacher/topic_levels.html', {'topic': topic, 'levels': levels})


class LevelDetailView(LoginRequiredMixin, View):
    def get(self, request, level_number):
        level = get_object_or_404(Level, level_number=level_number)
        topics = Topic.objects.filter(levels=level, is_active=True)
        return render(request, 'teacher/level_detail.html', {'level': level, 'topics': topics})


class CreateClassView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request):
        levels = Level.objects.filter(level_number__lte=8).order_by('level_number')
        return render(request, 'teacher/create_class.html', {'levels': levels})

    def post(self, request):
        name = request.POST.get('name', '').strip()
        level_ids = request.POST.getlist('levels')
        if not name:
            messages.error(request, 'Class name is required.')
            return redirect('create_class')
        with transaction.atomic():
            classroom = ClassRoom.objects.create(name=name, created_by=request.user)
            if level_ids:
                classroom.levels.set(Level.objects.filter(id__in=level_ids))
            ClassTeacher.objects.create(classroom=classroom, teacher=request.user)
        messages.success(request, f'Class "{name}" created. Code: {classroom.code}')
        return redirect('subjects_hub')


class ClassDetailView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
        return render(request, 'teacher/class_detail.html', {
            'classroom': classroom,
            'students': classroom.students.all(),
            'teachers': classroom.teachers.all(),
        })


class AssignStudentsView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
        all_students = CustomUser.objects.filter(roles__name=Role.STUDENT)
        return render(request, 'teacher/assign_students.html', {
            'classroom': classroom,
            'all_students': all_students,
            'enrolled': classroom.students.all(),
        })

    def post(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
        student_ids = request.POST.getlist('students')
        added = 0
        for sid in student_ids:
            student = get_object_or_404(CustomUser, id=sid)
            _, created = ClassStudent.objects.get_or_create(classroom=classroom, student=student)
            if created:
                added += 1
        messages.success(request, f'{added} student(s) added.')
        return redirect('class_detail', class_id=class_id)


class AssignTeachersView(LoginRequiredMixin, View):
    def get(self, request, class_id):
        if not (request.user.is_teacher or request.user.is_head_of_department):
            return redirect('subjects_hub')
        classroom = get_object_or_404(ClassRoom, id=class_id)
        return render(request, 'teacher/assign_teachers.html', {
            'classroom': classroom,
            'all_teachers': CustomUser.objects.filter(roles__name=Role.TEACHER),
        })

    def post(self, request, class_id):
        if not (request.user.is_teacher or request.user.is_head_of_department):
            return redirect('subjects_hub')
        classroom = get_object_or_404(ClassRoom, id=class_id)
        added = 0
        for tid in request.POST.getlist('teachers'):
            teacher = get_object_or_404(CustomUser, id=tid)
            _, created = ClassTeacher.objects.get_or_create(classroom=classroom, teacher=teacher)
            if created:
                added += 1
        messages.success(request, f'{added} teacher(s) assigned.')
        return redirect('class_detail', class_id=class_id)


class ClassProgressView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
        students = classroom.students.all()
        levels = classroom.levels.all()
        return render(request, 'teacher/class_progress.html', {
            'classroom': classroom, 'students': students, 'levels': levels,
        })


class ClassProgressListView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request):
        classes = ClassRoom.objects.filter(teachers=request.user, is_active=True)
        return render(request, 'teacher/class_progress_list.html', {'classes': classes})


class ManageTeachersView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request):
        classes = ClassRoom.objects.filter(teachers=request.user, is_active=True)
        return render(request, 'teacher/manage_teachers.html', {'classes': classes})


class BulkStudentRegistrationView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request):
        return render(request, 'teacher/bulk_register.html')

    def post(self, request):
        raw = request.POST.get('students_data', '').strip()
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        student_role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
        results = {'created': 0, 'errors': []}
        for i, line in enumerate(lines, 1):
            parts = line.split(',')
            if len(parts) != 3:
                results['errors'].append(f'Line {i}: must be username,email,password')
                continue
            username, email, password = [p.strip() for p in parts]
            if not username: results['errors'].append(f'Line {i}: username empty'); continue
            if '@' not in email: results['errors'].append(f'Line {i}: invalid email'); continue
            if len(password) < 8: results['errors'].append(f'Line {i}: password too short'); continue
            try:
                with transaction.atomic():
                    user = CustomUser.objects.create_user(username=username, email=email, password=password)
                    UserRole.objects.create(user=user, role=student_role, assigned_by=request.user)
                results['created'] += 1
            except Exception as e:
                results['errors'].append(f'Line {i} ({username}): {e}')
        if results['created']:
            messages.success(request, f"{results['created']} student(s) registered.")
        return render(request, 'teacher/bulk_register.html', {'results': results})


class UploadQuestionsView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request):
        return render(request, 'teacher/upload_questions.html', {
            'topics': Topic.objects.filter(is_active=True).select_related('subject'),
            'levels': Level.objects.filter(level_number__lte=8),
        })

    def post(self, request):
        import json
        from quiz.models import Question, Answer
        json_file = request.FILES.get('json_file')
        if not json_file:
            messages.error(request, 'Please select a JSON file.')
            return redirect('upload_questions')
        try:
            data = json.loads(json_file.read().decode('utf-8'))
        except json.JSONDecodeError as e:
            messages.error(request, f'Invalid JSON: {e}')
            return redirect('upload_questions')
        topic_name = data.get('topic', '').strip()
        year_level = data.get('year_level')
        try:
            topic = Topic.objects.get(name__iexact=topic_name)
            level = Level.objects.get(level_number=year_level)
        except (Topic.DoesNotExist, Level.DoesNotExist) as e:
            messages.error(request, str(e))
            return redirect('upload_questions')
        inserted = updated = failed = 0
        errors = []
        for i, q_data in enumerate(data.get('questions', []), 1):
            question_text = q_data.get('question_text', '').strip()
            question_type = q_data.get('question_type', '').strip()
            answers_data = q_data.get('answers', [])
            if not question_text: errors.append(f'Q{i}: missing question_text'); failed += 1; continue
            if question_type not in dict(Question.QUESTION_TYPES): errors.append(f'Q{i}: bad type'); failed += 1; continue
            if not answers_data: errors.append(f'Q{i}: no answers'); failed += 1; continue
            try:
                with transaction.atomic():
                    existing = Question.objects.filter(question_text=question_text, topic=topic, level=level).first()
                    fields = {'question_type': question_type, 'difficulty': q_data.get('difficulty', 1),
                              'points': q_data.get('points', 1), 'explanation': q_data.get('explanation', ''),
                              'created_by': request.user}
                    if existing:
                        for k, v in fields.items(): setattr(existing, k, v)
                        existing.save(); existing.answers.all().delete(); question = existing; updated += 1
                    else:
                        question = Question.objects.create(question_text=question_text, topic=topic, level=level, **fields)
                        inserted += 1
                    for a in answers_data:
                        Answer.objects.create(question=question, text=a.get('text', ''),
                                              is_correct=a.get('is_correct', False), display_order=a.get('display_order', 1))
            except Exception as e:
                errors.append(f'Q{i}: {e}'); failed += 1
        return render(request, 'teacher/upload_questions.html', {
            'upload_results': {'inserted': inserted, 'updated': updated, 'failed': failed, 'errors': errors},
            'topics': Topic.objects.filter(is_active=True).select_related('subject'),
            'levels': Level.objects.filter(level_number__lte=8),
        })


class QuestionListView(LoginRequiredMixin, View):
    def get(self, request, level_number):
        from quiz.models import Question
        level = get_object_or_404(Level, level_number=level_number)
        questions = Question.objects.filter(level=level).select_related('topic').prefetch_related('answers')
        return render(request, 'teacher/question_list.html', {'level': level, 'questions': questions})


class AddQuestionView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request, level_number):
        from quiz.models import Question
        level = get_object_or_404(Level, level_number=level_number)
        return render(request, 'teacher/question_form.html', {
            'level': level, 'topics': Topic.objects.filter(levels=level, is_active=True),
            'question_types': Question.QUESTION_TYPES, 'difficulty_choices': Question.DIFFICULTY_CHOICES,
        })

    def post(self, request, level_number):
        from quiz.models import Question, Answer
        level = get_object_or_404(Level, level_number=level_number)
        topic = get_object_or_404(Topic, id=request.POST.get('topic'))
        with transaction.atomic():
            question = Question.objects.create(
                topic=topic, level=level,
                question_text=request.POST.get('question_text', '').strip(),
                question_type=request.POST.get('question_type', Question.MULTIPLE_CHOICE),
                difficulty=int(request.POST.get('difficulty', 1)),
                points=int(request.POST.get('points', 1)),
                explanation=request.POST.get('explanation', ''),
                image=request.FILES.get('image'), created_by=request.user,
            )
            for i in range(1, 5):
                text = request.POST.get(f'answer_text_{i}', '').strip()
                if text:
                    Answer.objects.create(question=question, text=text,
                                          is_correct=request.POST.get(f'answer_correct_{i}') == 'true',
                                          display_order=int(request.POST.get(f'answer_order_{i}', i)))
        messages.success(request, 'Question added.')
        return redirect('question_list', level_number=level_number)


class EditQuestionView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request, question_id):
        from quiz.models import Question
        question = get_object_or_404(Question, id=question_id)
        return render(request, 'teacher/question_form.html', {
            'question': question, 'level': question.level,
            'topics': Topic.objects.filter(levels=question.level, is_active=True),
            'question_types': Question.QUESTION_TYPES, 'difficulty_choices': Question.DIFFICULTY_CHOICES,
        })

    def post(self, request, question_id):
        from quiz.models import Question, Answer
        question = get_object_or_404(Question, id=question_id)
        question.topic = get_object_or_404(Topic, id=request.POST.get('topic'))
        question.question_text = request.POST.get('question_text', '').strip()
        question.question_type = request.POST.get('question_type', Question.MULTIPLE_CHOICE)
        question.difficulty = int(request.POST.get('difficulty', 1))
        question.points = int(request.POST.get('points', 1))
        question.explanation = request.POST.get('explanation', '')
        if request.FILES.get('image'): question.image = request.FILES['image']
        with transaction.atomic():
            question.save(); question.answers.all().delete()
            for i in range(1, 5):
                text = request.POST.get(f'answer_text_{i}', '').strip()
                if text:
                    Answer.objects.create(question=question, text=text,
                                          is_correct=request.POST.get(f'answer_correct_{i}') == 'true',
                                          display_order=int(request.POST.get(f'answer_order_{i}', i)))
        messages.success(request, 'Question updated.')
        return redirect('question_list', level_number=question.level.level_number)


class DeleteQuestionView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def post(self, request, question_id):
        from quiz.models import Question
        question = get_object_or_404(Question, id=question_id)
        level_number = question.level.level_number
        question.delete()
        messages.success(request, 'Question deleted.')
        return redirect('question_list', level_number=level_number)


class HoDOverviewView(RoleRequiredMixin, View):
    required_role = Role.HEAD_OF_DEPARTMENT

    def get(self, request):
        return render(request, 'hod/overview.html', {
            'classes': ClassRoom.objects.filter(is_active=True).prefetch_related('teachers', 'students'),
            'teachers': CustomUser.objects.filter(roles__name=Role.TEACHER),
        })


class HoDManageClassesView(RoleRequiredMixin, View):
    required_role = Role.HEAD_OF_DEPARTMENT

    def get(self, request):
        return render(request, 'hod/manage_classes.html', {
            'classes': ClassRoom.objects.filter(is_active=True).prefetch_related('teachers'),
            'teachers': CustomUser.objects.filter(roles__name=Role.TEACHER),
        })


class HoDWorkloadView(RoleRequiredMixin, View):
    required_role = Role.HEAD_OF_DEPARTMENT

    def get(self, request):
        return render(request, 'hod/workload.html', {
            'teachers': CustomUser.objects.filter(roles__name=Role.TEACHER),
        })


class HoDReportsView(RoleRequiredMixin, View):
    required_role = Role.HEAD_OF_DEPARTMENT

    def get(self, request):
        return render(request, 'hod/reports.html', {
            'levels': Level.objects.filter(level_number__lte=8),
            'topics': Topic.objects.filter(is_active=True),
        })


class AccountingDashboardView(RoleRequiredMixin, View):
    required_role = Role.ACCOUNTANT

    def get(self, request):
        from billing.models import Package, Payment, Subscription
        return render(request, 'accounting/dashboard.html', {
            'packages': Package.objects.filter(is_active=True),
            'recent_payments': Payment.objects.select_related('user', 'package').order_by('-created_at')[:20],
            'active_subs': Subscription.objects.filter(status__in=['active', 'trialing']).count(),
            'trial_subs': Subscription.objects.filter(status='trialing').count(),
            'failed_payments': Payment.objects.filter(status='failed').count(),
        })


class AccountingPackagesView(RoleRequiredMixin, View):
    required_role = Role.ACCOUNTANT

    def get(self, request):
        from billing.models import Package
        return render(request, 'accounting/packages.html', {'packages': Package.objects.all()})


class AccountingUsersView(RoleRequiredMixin, View):
    required_role = Role.ACCOUNTANT

    def get(self, request):
        from django.utils import timezone
        from datetime import timedelta
        thirty_days_ago = timezone.now() - timedelta(days=30)
        return render(request, 'accounting/users.html', {
            'students': CustomUser.objects.filter(roles__name=Role.STUDENT).count(),
            'individual_students': CustomUser.objects.filter(roles__name=Role.INDIVIDUAL_STUDENT).count(),
            'teachers': CustomUser.objects.filter(roles__name=Role.TEACHER).count(),
            'active_users': CustomUser.objects.filter(last_login__gte=thirty_days_ago).count(),
        })


class AccountingExportView(RoleRequiredMixin, View):
    required_role = Role.ACCOUNTANT

    def get(self, request):
        return render(request, 'accounting/export.html')


class AccountingRefundsView(RoleRequiredMixin, View):
    required_role = Role.ACCOUNTANT

    def get(self, request):
        from billing.models import Payment
        return render(request, 'accounting/refunds.html', {
            'payments': Payment.objects.select_related('user', 'package').order_by('-created_at'),
        })


class ProcessRefundView(RoleRequiredMixin, View):
    required_role = Role.ACCOUNTANT

    def post(self, request, payment_id):
        from billing.models import Payment
        payment = get_object_or_404(Payment, id=payment_id)
        payment.status = Payment.STATUS_REFUNDED
        payment.save()
        messages.success(request, f'Refund processed for {payment.user.username}.')
        return redirect('accounting_refunds')


# ---------------------------------------------------------------------------
# Public Landing & Subject Hub Views
# ---------------------------------------------------------------------------

class PublicHomeView(View):
    """Public landing page. Redirects authenticated users to the hub."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(reverse('subjects_hub'))
        return render(request, 'public/home.html')


class SubjectsHubView(LoginRequiredMixin, View):
    """
    Authenticated home -- shows greeting + subject cards.
    Redirects HoD and Accountant roles to their existing dashboards.
    """

    def get(self, request):
        user = request.user

        # Redirect HoD and Accountant to their existing dashboards
        if user.roles.filter(name=Role.HEAD_OF_DEPARTMENT).exists():
            return redirect(reverse('hod_overview'))
        if user.roles.filter(name=Role.ACCOUNTANT).exists():
            return redirect(reverse('accounting_dashboard'))

        # Show all visible subjects (active or coming soon)
        subjects = SubjectApp.objects.exclude(
            is_active=False, is_coming_soon=False
        ).order_by('order')

        return render(request, 'hub/home.html', {
            'subjects': subjects,
        })


class SubjectsListView(LoginRequiredMixin, View):
    """Convenience redirect: /subjects/ -> /hub/"""

    def get(self, request):
        return redirect(reverse('subjects_hub'))


class ContactView(View):
    """Public Contact Us page with form submission."""

    def get(self, request):
        sent = request.GET.get('sent') == '1'
        return render(request, 'public/contact.html', {
            'sent': sent,
            'subject_choices': CONTACT_SUBJECT_CHOICES,
        })

    def post(self, request):
        # --- Honeypot check ---
        if request.POST.get('website', '').strip():
            # Bot detected — silently return success
            return redirect('/contact/?sent=1')

        # --- Rate limiting (5 per IP per hour) ---
        ip = _get_client_ip(request)
        rate_limit = getattr(settings, 'CONTACT_RATE_LIMIT_PER_HOUR', 5)
        cache_key = f'contact_ratelimit_{ip}'
        submission_count = cache.get(cache_key, 0)
        if submission_count >= rate_limit:
            messages.error(
                request,
                'Too many submissions. Please try again later.',
            )
            return render(request, 'public/contact.html', {
                'subject_choices': CONTACT_SUBJECT_CHOICES,
            }, status=429)

        # --- Validate form ---
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        subject = request.POST.get('subject', '').strip()
        message_text = request.POST.get('message', '').strip()

        errors = {}
        if not name:
            errors['name'] = 'Name is required.'
        if not email or '@' not in email:
            errors['email'] = 'A valid email address is required.'
        valid_subjects = [c[0] for c in CONTACT_SUBJECT_CHOICES]
        if subject not in valid_subjects:
            errors['subject'] = 'Please select a valid subject.'
        if not message_text:
            errors['message'] = 'Message is required.'
        elif len(message_text) > 2000:
            errors['message'] = 'Message must be under 2000 characters.'

        if errors:
            return render(request, 'public/contact.html', {
                'errors': errors,
                'form_data': {
                    'name': name,
                    'email': email,
                    'subject': subject,
                    'message': message_text,
                },
                'subject_choices': CONTACT_SUBJECT_CHOICES,
            })

        # --- Save ---
        ContactMessage.objects.create(
            name=name,
            email=email,
            subject=subject,
            message=message_text,
            ip_address=ip,
        )

        # --- Update rate limit counter ---
        cache.set(cache_key, submission_count + 1, 3600)

        # --- Send notification email (best-effort) ---
        try:
            admin_email = getattr(
                settings, 'DEFAULT_FROM_EMAIL',
                'noreply@wizardslearninghub.co.nz',
            )
            subject_display = dict(CONTACT_SUBJECT_CHOICES).get(subject, subject)
            send_mail(
                subject=f'[Classroom] New Contact: {subject_display}',
                message=(
                    f'Name: {name}\nEmail: {email}\n'
                    f'Subject: {subject_display}\n\n{message_text}'
                ),
                from_email=admin_email,
                recipient_list=[admin_email],
                fail_silently=True,
            )
        except Exception:
            logger.exception('Failed to send contact form notification email')

        return redirect('/contact/?sent=1')


class JoinClassView(View):
    """Public page showing registration options (Teacher / Individual Student)."""

    def get(self, request):
        return render(request, 'public/join_class.html')


def _get_client_ip(request):
    """Extract client IP from request, considering X-Forwarded-For header."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')
