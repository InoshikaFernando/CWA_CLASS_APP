import logging

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import transaction

from accounts.models import CustomUser, Role, UserRole
from audit.services import log_event
from billing.mixins import ModuleRequiredMixin

def _get_user_school_ids(user):
    """Get school IDs the user can manage (as admin or HoI via SchoolTeacher)."""
    from .models import School, SchoolTeacher
    if user.is_superuser:
        return list(School.objects.filter(is_active=True).values_list('id', flat=True))
    admin_ids = set(School.objects.filter(admin=user, is_active=True).values_list('id', flat=True))
    hoi_ids = set(SchoolTeacher.objects.filter(
        teacher=user, role='head_of_institute', is_active=True,
    ).values_list('school_id', flat=True))
    return list(admin_ids | hoi_ids)
from billing.models import ModuleSubscription
from .models import (
    ClassRoom, Subject, Topic, Level, ClassTeacher, ClassStudent,
    StudentLevelEnrollment, SubjectApp, ContactMessage, CONTACT_SUBJECT_CHOICES,
    School, SchoolTeacher, SchoolStudent, ClassSession, StudentAttendance,
    TeacherAttendance, Department, DepartmentLevel, DepartmentSubject, Enrollment,
    Invoice, InvoicePayment, InvoiceLineItem, SalarySlip, SalarySlipLineItem,
)

logger = logging.getLogger(__name__)


class RoleRequiredMixin(LoginRequiredMixin):
    required_role = None      # Single role string (backward compat)
    required_roles = None     # List of role strings (any match grants access)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        # Superusers bypass role checks
        if not request.user.is_superuser:
            # Check required_roles list first, then fall back to singular required_role
            roles_to_check = self.required_roles or ([self.required_role] if self.required_role else [])
            if roles_to_check:
                has_any = any(request.user.has_role(r) for r in roles_to_check)
                if not has_any:
                    messages.error(request, "You don't have permission to access that page.")
                    return redirect('public_home')

        return super().dispatch(request, *args, **kwargs)


def _get_individual_student_levels(user):
    basic_facts_levels = Level.objects.filter(level_number__gte=100, school__isnull=True)
    try:
        sub = user.subscription
        if sub.is_active_or_trialing:
            enrolled_levels = Level.objects.filter(
                studentlevelenrollment__student=user
            ).distinct()
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

        active_role = request.session.get('active_role')
        if active_role and request.user.has_role(active_role):
            role = active_role
        else:
            role = request.user.primary_role

        if role == Role.ADMIN or role is None and request.user.is_superuser:
            return redirect('admin_dashboard')
        if role == Role.INSTITUTE_OWNER:
            return redirect('hod_overview')
        if role == Role.HEAD_OF_INSTITUTE:
            return redirect('hod_overview')
        if role == Role.HEAD_OF_DEPARTMENT:
            return redirect('hod_overview')
        if role == Role.ACCOUNTANT:
            return redirect('accounting_dashboard')
        if role == Role.PARENT:
            return redirect('parent_dashboard')

        if role in (Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER):
            return redirect('teacher_dashboard')

        if role in (Role.STUDENT, Role.INDIVIDUAL_STUDENT):
            is_individual = role == Role.INDIVIDUAL_STUDENT
            # Both student types: derive accessible levels from enrolled classrooms
            classrooms = ClassRoom.objects.filter(students=request.user, is_active=True)
            accessible_level_ids = set(
                Level.objects.filter(classrooms__in=classrooms).values_list('id', flat=True)
            )
            # Always include basic facts levels
            basic_ids = set(
                Level.objects.filter(level_number__gte=100, school__isnull=True).values_list('id', flat=True)
            )
            accessible_level_ids |= basic_ids
            # Individual students with no classroom: fall back to all year levels
            if is_individual and not classrooms.exists():
                accessible_level_ids |= set(
                    Level.objects.filter(level_number__lte=9).values_list('id', flat=True)
                )

            # Pre-fetch which topics have questions, keyed by (topic_id, level_id)
            # Question.topic and Question.level now reference classroom.Topic/Level directly
            from maths.models import Question
            from django.db.models import Count
            questions_exist = set()
            for row in (Question.objects
                        .values('topic_id', 'level_id')
                        .annotate(cnt=Count('id'))
                        .filter(cnt__gt=0)):
                questions_exist.add((row['topic_id'], row['level_id']))

            year_data = []
            for year in range(1, 10):
                try:
                    level = Level.objects.get(level_number=year)
                except Level.DoesNotExist:
                    continue

                subtopics = (
                    Topic.objects
                    .filter(levels=level, is_active=True, parent__isnull=False)
                    .select_related('parent')
                    .order_by('parent__order', 'order', 'name')
                )
                strand_dict = {}
                for subtopic in subtopics:
                    sid = subtopic.parent_id
                    if sid not in strand_dict:
                        strand_dict[sid] = {'strand': subtopic.parent, 'subtopics': []}
                    has_questions = (subtopic.id, level.id) in questions_exist
                    strand_dict[sid]['subtopics'].append({
                        'topic': subtopic,
                        'topic_id': subtopic.id,
                        'has_questions': has_questions,
                    })
                year_data.append({
                    'level': level,
                    'strand_data': list(strand_dict.values()),
                    'subtopic_count': subtopics.count(),
                    'accessible': level.id in accessible_level_ids,
                })

            return render(request, 'student/home.html', {
                'year_data': year_data,
                'is_individual_student': is_individual,
            })

        # No role at all
        return render(request, 'accounts/no_role.html')


class StudentDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        if not (request.user.is_student or request.user.is_individual_student):
            return redirect('subjects_hub')
        from maths.models import StudentFinalAnswer, BasicFactsResult, TimeLog
        from maths.models import TopicLevelStatistics

        # ── Topic quiz progress grid ──────────────────────────────────────────
        # StudentFinalAnswer.topic and .level now reference classroom.Topic/Level directly
        topic_results = StudentFinalAnswer.objects.filter(
            student=request.user,
            quiz_type__in=[StudentFinalAnswer.QUIZ_TYPE_TOPIC, StudentFinalAnswer.QUIZ_TYPE_MIXED],
        ).select_related('topic', 'level')

        # Key by (level_number, topic_name) to bridge classroom ↔ maths models
        best_map = {}
        attempts_map = {}
        for r in topic_results:
            if r.level and r.topic:
                key = (r.level.level_number, r.topic.name)
                attempts_map[key] = attempts_map.get(key, 0) + 1
                if key not in best_map or r.points > best_map[key].points:
                    best_map[key] = r

        # Pre-fetch platform statistics keyed by (level_number, topic_name)
        stats_map = {
            (s.level.level_number, s.topic.name): s
            for s in TopicLevelStatistics.objects.select_related('level', 'topic').all()
        }

        # ── Filter controls ──────────────────────────────────────────────────
        filter_subject_id = request.GET.get('subject_id')
        filter_class_id = request.GET.get('class_id')

        enrolled_classes = (
            ClassRoom.objects.filter(students=request.user, is_active=True)
            .select_related('subject')
            .order_by('subject__name', 'name')
        )
        enrolled_subjects = (
            Subject.objects.filter(
                classrooms__students=request.user, classrooms__is_active=True,
            ).distinct().order_by('name')
        )

        # Determine which year levels to show based on active filter
        if filter_class_id:
            try:
                active_class = enrolled_classes.get(id=filter_class_id)
                enrolled_level_ids = set(
                    active_class.levels.filter(level_number__lte=8).values_list('id', flat=True)
                )
            except ClassRoom.DoesNotExist:
                enrolled_level_ids = set()
        elif filter_subject_id:
            enrolled_level_ids = set(
                Level.objects.filter(
                    classrooms__students=request.user,
                    classrooms__subject_id=filter_subject_id,
                    classrooms__is_active=True,
                    level_number__lte=8,
                ).values_list('id', flat=True)
            )
        else:
            enrolled_level_ids = set(
                Level.objects.filter(
                    classrooms__in=enrolled_classes, level_number__lte=8,
                ).values_list('id', flat=True)
            )

        # Fall back to all Year 1-8 levels if not in any classroom yet
        if not enrolled_level_ids and not filter_class_id and not filter_subject_id:
            enrolled_level_ids = set(
                Level.objects.filter(level_number__lte=8).values_list('id', flat=True)
            )

        progress_grid = []
        for year in range(1, 10):
            try:
                level = Level.objects.get(level_number=year)
            except Level.DoesNotExist:
                continue
            if level.id not in enrolled_level_ids:
                continue
            # Group topics by strand (only subtopics — topics with a parent)
            all_topics = (
                Topic.objects.filter(levels=level, is_active=True, parent__isnull=False)
                .select_related('parent')
                .order_by('parent__order', 'order', 'name')
            )
            strand_dict = {}
            for topic in all_topics:
                key = topic.parent_id if topic.parent_id else '__flat__'
                if key not in strand_dict:
                    strand_dict[key] = {'strand': topic.parent, 'subtopics': []}
                lv_key = (level.level_number, topic.name)
                best = best_map.get(lv_key)
                stat = stats_map.get(lv_key)
                if best and stat:
                    colour = stat.get_colour_band(best.points)
                    if not colour:
                        colour = 'bg-green-100 text-green-800'
                elif best:
                    colour = 'bg-green-100 text-green-800'
                else:
                    colour = 'bg-gray-100 text-gray-400'
                strand_dict[key]['subtopics'].append({
                    'topic': topic,
                    'topic_id': topic.id,
                    'best': best,
                    'points': round(best.points, 1) if best else None,
                    'colour': colour,
                    'attempts': attempts_map.get((level.level_number, topic.name), 0),
                })
            strand_data = list(strand_dict.values())
            if not strand_data:
                continue
            progress_grid.append({'level': level, 'strand_data': strand_data})

        # ── Basic Facts grid ──────────────────────────────────────────────────
        BF_SUBTOPICS = [
            ('Addition',       'Addition',        100, 106),
            ('Subtraction',    'Subtraction',     107, 113),
            ('Multiplication', 'Multiplication',  114, 120),
            ('Division',       'Division',        121, 127),
            ('PlaceValue',     'Place Value',     128, 132),
        ]
        bf_grid = []
        for subtopic, label, start, end in BF_SUBTOPICS:
            levels_data = []
            for i, num in enumerate(range(start, end + 1), 1):
                best = BasicFactsResult.get_best_result(request.user, subtopic, num)
                levels_data.append({
                    'level_number': num,
                    'display_level': i,
                    'best': best,
                    'colour': _pct_colour(best.percentage if best else None),
                })
            bf_grid.append({'subtopic': subtopic, 'label': label, 'levels': levels_data})

        # ── Number Puzzles progress ──────────────────────────────────────────
        np_grid = []
        try:
            from number_puzzles.models import NumberPuzzleLevel, StudentPuzzleProgress
            np_levels = NumberPuzzleLevel.objects.all()
            np_progress_map = {
                p.level_id: p
                for p in StudentPuzzleProgress.objects.filter(student=request.user)
            }
            for level in np_levels:
                prog = np_progress_map.get(level.id)
                pct = prog.accuracy if prog and prog.total_puzzles_attempted > 0 else None
                np_grid.append({
                    'level': level,
                    'progress': prog,
                    'is_unlocked': prog.is_unlocked if prog else False,
                    'best_score': prog.best_score if prog else 0,
                    'stars': prog.stars if prog else 0,
                    'total_sessions': prog.total_sessions if prog else 0,
                    'accuracy': pct,
                    'colour': _pct_colour(pct),
                })
        except (ImportError, Exception):
            np_grid = []

        # ── Times Tables results ──────────────────────────────────────────────
        tt_results = []
        for table in range(1, 13):
            best_mul = StudentFinalAnswer.objects.filter(
                student=request.user,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                operation='multiplication',
                table_number=table,
            ).order_by('-points').first()
            best_div = StudentFinalAnswer.objects.filter(
                student=request.user,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                operation='division',
                table_number=table,
            ).order_by('-points').first()
            # Legacy: attempts without operation saved (old records)
            if not best_mul and not best_div:
                best_legacy = StudentFinalAnswer.objects.filter(
                    student=request.user,
                    quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                    operation='',
                    table_number=table,
                ).order_by('-points').first()
            else:
                best_legacy = None
            tt_results.append({
                'table': table,
                'mul': best_mul,
                'div': best_div,
                'legacy': best_legacy,
                'mul_colour': _tt_colour(best_mul if best_mul else best_legacy),
                'div_colour': _tt_colour(best_div),
            })

        # ── Recent activity ───────────────────────────────────────────────────
        recent_topic = StudentFinalAnswer.objects.filter(
            student=request.user,
            quiz_type__in=[StudentFinalAnswer.QUIZ_TYPE_TOPIC, StudentFinalAnswer.QUIZ_TYPE_MIXED],
        ).select_related('topic', 'level').order_by('-completed_at')[:5]

        recent_bf = BasicFactsResult.objects.filter(
            student=request.user
        ).order_by('-completed_at')[:5]

        recent_tt = StudentFinalAnswer.objects.filter(
            student=request.user,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
        ).select_related('level').order_by('-completed_at')[:5]

        try:
            from number_puzzles.models import PuzzleSession
            recent_np = PuzzleSession.objects.filter(
                student=request.user, status='completed',
            ).select_related('level').order_by('-completed_at')[:5]
        except (ImportError, Exception):
            recent_np = []

        from maths.views import get_or_create_time_log
        time_log = get_or_create_time_log(request.user)

        return render(request, 'student/dashboard.html', {
            'progress_grid': progress_grid,
            'bf_grid': bf_grid,
            'np_grid': np_grid,
            'tt_results': tt_results,
            'recent_topic': recent_topic,
            'recent_bf': recent_bf,
            'recent_tt': recent_tt,
            'recent_np': recent_np,
            'time_log': time_log,
            'time_daily': _format_seconds(time_log.daily_total_seconds if time_log else 0),
            'time_weekly': _format_seconds(time_log.weekly_total_seconds if time_log else 0),
            # Filter controls
            'enrolled_classes': enrolled_classes,
            'enrolled_subjects': enrolled_subjects,
            'filter_subject_id': int(filter_subject_id) if filter_subject_id else None,
            'filter_class_id': int(filter_class_id) if filter_class_id else None,
        })


def _format_seconds(seconds):
    """Format a seconds count as a human-readable time string.
    < 3600s → 'Xm'   e.g. '27m'
    ≥ 3600s → 'Xh Ym' e.g. '1h 5m'
    """
    seconds = int(seconds or 0)
    if seconds < 3600:
        return f"{seconds // 60}m"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"


def _pct_colour(pct):
    if pct is None:
        return 'bg-gray-100 text-gray-400'
    if pct >= 90:
        return 'bg-green-600 text-white'
    if pct >= 75:
        return 'bg-green-400 text-white'
    if pct >= 60:
        return 'bg-green-200 text-green-900'
    if pct >= 45:
        return 'bg-yellow-200 text-yellow-900'
    if pct >= 30:
        return 'bg-orange-200 text-orange-900'
    return 'bg-red-200 text-red-900'


def _tt_colour(result):
    """
    Colour for a single times-table row (× or ÷).
    Must be 100% correct to get a colour other than red.
      100% + time < 15s  → dark green
      100% + time < 30s  → green
      100% + time < 60s  → light green
      100% + time < 90s  → yellow
      100% + time >= 90s → orange
      any wrong answer   → red
      not attempted      → grey
    """
    if result is None:
        return 'bg-gray-100 text-gray-400'
    if result.percentage < 100:
        return 'bg-red-200 text-red-900'
    t = result.time_taken_seconds
    if t < 15:
        return 'bg-green-800 text-white'
    if t < 30:
        return 'bg-green-600 text-white'
    if t < 60:
        return 'bg-green-200 text-green-900'
    if t < 90:
        return 'bg-yellow-200 text-yellow-900'
    return 'bg-orange-200 text-orange-900'


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
    required_roles = [Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER]

    def _get_departments(self, user):
        """Departments available to this teacher via their school."""
        from .models import DepartmentTeacher
        # Departments where teacher is assigned
        dept_ids = DepartmentTeacher.objects.filter(teacher=user).values_list('department_id', flat=True)
        depts = Department.objects.filter(id__in=dept_ids, is_active=True).select_related('school')
        if depts.exists():
            return depts
        # Fallback: all departments in teacher's school
        school_membership = SchoolTeacher.objects.filter(teacher=user, is_active=True).select_related('school').first()
        if school_membership:
            return Department.objects.filter(school=school_membership.school, is_active=True).select_related('school')
        return Department.objects.none()

    def get(self, request):
        departments = self._get_departments(request.user)
        return render(request, 'teacher/create_class.html', {
            'departments': departments,
        })

    def post(self, request):
        name = request.POST.get('name', '').strip()
        dept_id = request.POST.get('department', '').strip()
        level_ids = request.POST.getlist('levels')
        day = request.POST.get('day', '').strip()
        start_time = request.POST.get('start_time', '').strip() or None
        end_time = request.POST.get('end_time', '').strip() or None
        description = request.POST.get('description', '').strip()

        if not name:
            messages.error(request, 'Class name is required.')
            return redirect('create_class')

        departments = self._get_departments(request.user)
        department = departments.filter(id=dept_id).first() if dept_id else None
        if not department:
            messages.error(request, 'Please select a department.')
            return redirect('create_class')

        # Check class limit before creating
        from billing.entitlements import check_class_limit
        allowed, current, limit = check_class_limit(department.school)
        if not allowed:
            messages.error(
                request,
                f'Your plan allows {limit} classes. '
                f'You currently have {current}. Please upgrade your plan.',
            )
            return redirect('create_class')

        # Validate levels are mapped to the selected department via DepartmentLevel
        from .models import DepartmentLevel
        mapped_level_ids = set(
            DepartmentLevel.objects.filter(
                department=department, level_id__in=level_ids,
            ).values_list('level_id', flat=True)
        )
        valid_levels = Level.objects.filter(id__in=mapped_level_ids)

        # Derive subject from the first selected level
        first_level = valid_levels.select_related('subject').first()
        subject = first_level.subject if first_level else department.primary_subject

        with transaction.atomic():
            classroom = ClassRoom.objects.create(
                name=name,
                school=department.school,
                department=department,
                subject=subject,
                day=day,
                start_time=start_time,
                end_time=end_time,
                description=description,
                created_by=request.user,
            )
            if valid_levels.exists():
                classroom.levels.set(valid_levels)
            ClassTeacher.objects.create(classroom=classroom, teacher=request.user)
        log_event(
            user=request.user, school=department.school, category='data_change',
            action='class_created',
            detail={'class_id': classroom.id, 'class_name': name, 'department': department.name, 'code': classroom.code},
            request=request,
        )
        messages.success(request, f'Class "{name}" created in {department.name}. Code: {classroom.code}')
        return redirect('subjects_hub')


class ClassDetailView(RoleRequiredMixin, View):
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT,
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def get(self, request, class_id):
        from django.utils import timezone
        from django.db.models import Count, Q

        user = request.user
        if user.has_role(Role.ADMIN) or user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            # HoD can view classes in their department OR classes they teach
            classroom = ClassRoom.objects.filter(
                Q(department__head=user) | Q(teachers=user),
                id=class_id,
            ).distinct().first()
            if not classroom:
                raise Http404
        else:
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)

        # Sessions for this class — soonest upcoming first, paginated
        from django.core.paginator import Paginator
        all_sessions = (
            ClassSession.objects.filter(classroom=classroom)
            .annotate(
                present_count=Count('student_attendance', filter=Q(student_attendance__status='present')),
                late_count=Count('student_attendance', filter=Q(student_attendance__status='late')),
                absent_count=Count('student_attendance', filter=Q(student_attendance__status='absent')),
            )
            .order_by('date', 'start_time')
        )
        paginator = Paginator(all_sessions, 15)
        page_number = request.GET.get('page')
        sessions = paginator.get_page(page_number)

        today = timezone.localdate()
        todays_session = ClassSession.objects.filter(classroom=classroom, date=today).first()

        # Show "Start Session" when no session exists today, or if today's was cancelled
        can_start = todays_session is None or todays_session.status == 'cancelled'

        # Fee data for student list
        from .fee_utils import get_effective_fee_for_student, get_fee_source_label, get_effective_fee_for_class
        can_edit_fee = (
            user.has_role(Role.HEAD_OF_DEPARTMENT)
            or user.has_role(Role.HEAD_OF_INSTITUTE)
            or user.has_role(Role.INSTITUTE_OWNER)
            or user.has_role(Role.ADMIN)
        )
        class_effective_fee = get_effective_fee_for_class(classroom)

        student_fee_data = []
        for cs in ClassStudent.objects.filter(classroom=classroom, is_active=True).select_related('student'):
            student_fee_data.append({
                'student': cs.student,
                'class_student': cs,
                'effective_fee': get_effective_fee_for_student(cs),
                'fee_source': get_fee_source_label(cs),
            })

        active_student_ids = ClassStudent.objects.filter(
            classroom=classroom, is_active=True,
        ).values_list('student_id', flat=True)

        return render(request, 'teacher/class_detail.html', {
            'classroom': classroom,
            'students': CustomUser.objects.filter(id__in=active_student_ids),
            'teachers': classroom.teachers.all(),
            'sessions': sessions,
            'todays_session': todays_session,
            'can_start_session': can_start,
            'student_fee_data': student_fee_data,
            'class_effective_fee': class_effective_fee,
            'can_edit_fee': can_edit_fee,
        })


class EditClassView(RoleRequiredMixin, View):
    required_roles = [
        Role.TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def _get_classroom(self, request, class_id):
        from django.db.models import Q
        user = request.user
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            return get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            classroom = ClassRoom.objects.filter(
                Q(department__head=user) | Q(teachers=user),
                id=class_id,
            ).distinct().first()
            if not classroom:
                raise Http404
            return classroom
        else:
            return get_object_or_404(ClassRoom, id=class_id, teachers=request.user)

    def get(self, request, class_id):
        classroom = self._get_classroom(request, class_id)

        # Build levels grouped by subject for multi-subject departments
        subject_groups = []
        if classroom.department:
            dept_subjects = DepartmentSubject.objects.filter(
                department=classroom.department,
            ).select_related('subject').order_by('subject__name')

            dept_levels = (
                DepartmentLevel.objects.filter(department=classroom.department)
                .select_related('level', 'level__subject')
                .exclude(level__level_number__gte=100, level__level_number__lt=200)
                .order_by('order', 'level__level_number')
            )

            for ds in dept_subjects:
                year_levels = []
                custom_levels = []
                for dl in dept_levels:
                    if dl.level.subject_id == ds.subject_id:
                        if dl.level.level_number <= 9:
                            year_levels.append(dl.level)
                        else:
                            custom_levels.append(dl.level)
                subject_groups.append({
                    'subject': ds.subject,
                    'year_levels': year_levels,
                    'custom_levels': custom_levels,
                })
        elif classroom.subject:
            # Fallback: single subject
            year_levels = list(Level.objects.filter(
                subject=classroom.subject, school__isnull=True, level_number__lte=9,
            ).exclude(
                level_number__gte=100, level_number__lt=200,
            ).order_by('level_number'))
            custom_levels = list(Level.objects.filter(
                school=classroom.school,
            ).order_by('level_number')) if classroom.school else []
            subject_groups.append({
                'subject': classroom.subject,
                'year_levels': year_levels,
                'custom_levels': custom_levels,
            })

        # Determine current subject: from classroom.subject or from existing levels
        current_subject_id = classroom.subject_id
        if not current_subject_id:
            first_level = classroom.levels.select_related('subject').first()
            if first_level and first_level.subject_id:
                current_subject_id = first_level.subject_id
        # If still None and only one subject, auto-select it
        if not current_subject_id and len(subject_groups) == 1:
            current_subject_id = subject_groups[0]['subject'].id

        # Fee context
        from .fee_utils import get_parent_fee_for_class
        parent_fee, fee_source = get_parent_fee_for_class(classroom)
        can_edit_fee = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            or request.user.has_role(Role.HEAD_OF_INSTITUTE)
            or request.user.has_role(Role.INSTITUTE_OWNER)
            or request.user.has_role(Role.ADMIN)
        )

        back_url = request.GET.get('next', '')
        return render(request, 'teacher/edit_class.html', {
            'classroom': classroom,
            'subject_groups': subject_groups,
            'selected_levels': list(classroom.levels.values_list('id', flat=True)),
            'current_subject_id': current_subject_id,
            'back_url': back_url,
            'parent_fee': parent_fee,
            'fee_source': fee_source,
            'can_edit_fee': can_edit_fee,
        })

    def post(self, request, class_id):
        classroom = self._get_classroom(request, class_id)
        name = request.POST.get('name', '').strip()
        level_ids = request.POST.getlist('levels')
        day = request.POST.get('day', '').strip()
        start_time = request.POST.get('start_time', '').strip() or None
        end_time = request.POST.get('end_time', '').strip() or None
        description = request.POST.get('description', '').strip()
        next_url = request.POST.get('next', '').strip()

        if not name:
            messages.error(request, 'Class name is required.')
            return redirect('edit_class', class_id=class_id)

        classroom.name = name
        classroom.day = day
        classroom.start_time = start_time
        classroom.end_time = end_time
        classroom.description = description

        # Fee override (HoD+ only)
        can_edit_fee = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            or request.user.has_role(Role.HEAD_OF_INSTITUTE)
            or request.user.has_role(Role.INSTITUTE_OWNER)
            or request.user.has_role(Role.ADMIN)
        )
        if can_edit_fee:
            fee_str = request.POST.get('fee_override', '').strip()
            if fee_str:
                from decimal import Decimal, InvalidOperation
                try:
                    classroom.fee_override = Decimal(fee_str)
                except InvalidOperation:
                    classroom.fee_override = None
            else:
                classroom.fee_override = None

        # Derive subject from selected levels
        selected_levels = Level.objects.filter(id__in=level_ids)
        first_level = selected_levels.first()
        if first_level and first_level.subject:
            classroom.subject = first_level.subject

        classroom.save()
        classroom.levels.set(selected_levels)

        log_event(
            user=request.user, school=classroom.school, category='data_change',
            action='class_edited',
            detail={'class_id': classroom.id, 'class_name': name},
            request=request,
        )
        messages.success(request, f'Class "{name}" updated.')
        if next_url:
            return redirect(next_url)
        return redirect('class_detail', class_id=class_id)


class AssignStudentsView(RoleRequiredMixin, View):
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT,
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def _get_classroom(self, request, class_id):
        from django.db.models import Q
        user = request.user
        if user.has_role(Role.ADMIN) or user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            return get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            classroom = ClassRoom.objects.filter(
                Q(department__head=user) | Q(teachers=user),
                id=class_id,
            ).distinct().first()
            if not classroom:
                raise Http404
            return classroom
        else:
            return get_object_or_404(ClassRoom, id=class_id, teachers=request.user)

    def get(self, request, class_id):
        classroom = self._get_classroom(request, class_id)
        # Show school-scoped students if classroom belongs to a school
        if classroom.school:
            from .models import SchoolStudent
            school_student_ids = SchoolStudent.objects.filter(
                school=classroom.school, is_active=True
            ).values_list('student_id', flat=True)
            all_students = CustomUser.objects.filter(id__in=school_student_ids).order_by('first_name', 'last_name', 'username')
        else:
            all_students = CustomUser.objects.filter(roles__name=Role.STUDENT).order_by('first_name', 'last_name', 'username')
        active_enrolled_ids = ClassStudent.objects.filter(
            classroom=classroom, is_active=True,
        ).values_list('student_id', flat=True)
        return render(request, 'teacher/assign_students.html', {
            'classroom': classroom,
            'all_students': all_students,
            'enrolled': CustomUser.objects.filter(id__in=active_enrolled_ids),
        })

    def post(self, request, class_id):
        classroom = self._get_classroom(request, class_id)
        student_ids = request.POST.getlist('students')

        # Check student limit before adding
        if classroom.school:
            from billing.entitlements import check_student_limit
            allowed, current, limit = check_student_limit(classroom.school)
            if not allowed:
                messages.error(
                    request,
                    f'Your plan allows {limit} students. You currently have {current}. '
                    f'Please upgrade your plan to add more students.'
                )
                return redirect('assign_students', class_id=class_id)

        added = 0
        for sid in student_ids:
            student = get_object_or_404(CustomUser, id=sid)
            cs, created = ClassStudent.objects.get_or_create(classroom=classroom, student=student)
            if not created and not cs.is_active:
                cs.is_active = True
                cs.save(update_fields=['is_active'])
                added += 1
            elif created:
                added += 1
        log_event(
            user=request.user, school=classroom.school, category='data_change',
            action='student_enrolled',
            detail={'class_id': classroom.id, 'class_name': classroom.name, 'students_added': added},
            request=request,
        )
        messages.success(request, f'{added} student(s) added.')
        return redirect('class_detail', class_id=class_id)


class AssignTeachersView(LoginRequiredMixin, View):
    def get(self, request, class_id):
        if not (request.user.is_teacher or request.user.is_head_of_institute or request.user.is_institute_owner):
            return redirect('subjects_hub')
        classroom = get_object_or_404(ClassRoom, id=class_id)
        # Scope to teachers in the same school
        if classroom.school:
            school_teachers = SchoolTeacher.objects.filter(
                school=classroom.school, is_active=True
            ).select_related('teacher')
            all_teachers = []
            for st in school_teachers:
                st.teacher.specialty = st.specialty
                all_teachers.append(st.teacher)
        else:
            all_teachers = list(CustomUser.objects.filter(roles__name=Role.TEACHER))
        assigned_ids = set(classroom.teachers.values_list('id', flat=True))
        return render(request, 'teacher/assign_teachers.html', {
            'classroom': classroom,
            'all_teachers': all_teachers,
            'assigned_ids': assigned_ids,
        })

    def post(self, request, class_id):
        if not (request.user.is_teacher or request.user.is_head_of_institute or request.user.is_institute_owner):
            return redirect('subjects_hub')
        classroom = get_object_or_404(ClassRoom, id=class_id)
        selected_ids = set(request.POST.getlist('teachers'))
        # Add newly selected teachers
        added = 0
        for tid in selected_ids:
            teacher = get_object_or_404(CustomUser, id=tid)
            _, created = ClassTeacher.objects.get_or_create(classroom=classroom, teacher=teacher)
            if created:
                added += 1
        # Remove unchecked teachers
        removed = ClassTeacher.objects.filter(
            classroom=classroom
        ).exclude(teacher_id__in=selected_ids).delete()[0]
        classroom.teachers.set(
            CustomUser.objects.filter(
                id__in=ClassTeacher.objects.filter(classroom=classroom).values_list('teacher_id', flat=True)
            )
        )
        log_event(
            user=request.user, school=classroom.school, category='data_change',
            action='teachers_updated',
            detail={'class_id': classroom.id, 'class_name': classroom.name, 'added': added, 'removed': removed},
            request=request,
        )
        messages.success(request, f'{added} teacher(s) added, {removed} removed.')
        return redirect('class_detail', class_id=class_id)


class ClassAttendanceView(RoleRequiredMixin, ModuleRequiredMixin, View):
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [
        Role.TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def get(self, request, class_id):
        from django.db.models import Q
        user = request.user
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            classroom = ClassRoom.objects.filter(
                Q(department__head=user) | Q(teachers=user),
                id=class_id,
            ).distinct().first()
            if not classroom:
                raise Http404
        else:
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=user)

        # Last 20 non-cancelled sessions, most recent first
        sessions = list(
            ClassSession.objects.filter(
                classroom=classroom,
                status__in=['scheduled', 'completed'],
            ).order_by('-date', '-start_time')[:20]
        )

        active_ids = ClassStudent.objects.filter(
            classroom=classroom, is_active=True,
        ).values_list('student_id', flat=True)
        students = CustomUser.objects.filter(id__in=active_ids).order_by('last_name', 'first_name', 'username')

        # Batch-fetch all attendance records for these sessions
        att_map = {}
        if sessions:
            for rec in StudentAttendance.objects.filter(session__in=sessions):
                att_map[(rec.session_id, rec.student_id)] = rec.status

        # Build per-student rows
        student_data = []
        for student in students:
            present = late = absent = 0
            row_sessions = []
            for session in sessions:
                status = att_map.get((session.id, student.id))
                row_sessions.append(status)
                if status == 'present':
                    present += 1
                elif status == 'late':
                    late += 1
                elif status == 'absent':
                    absent += 1
            total = present + late + absent
            rate = round((present + late) / total * 100) if total else None
            student_data.append({
                'student': student,
                'cells': row_sessions,
                'present': present,
                'late': late,
                'absent': absent,
                'total': total,
                'rate': rate,
            })

        return render(request, 'teacher/class_attendance.html', {
            'classroom': classroom,
            'sessions': sessions,
            'student_data': student_data,
        })


class ClassProgressListView(RoleRequiredMixin, View):
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
        Role.INSTITUTE_OWNER,
    ]

    def get(self, request):
        from django.db.models import Count, Q
        from .views_teacher import _get_teacher_current_school, _get_teacher_classes
        current_school = _get_teacher_current_school(request)
        if current_school:
            classes = _get_teacher_classes(request.user, current_school)
        else:
            classes = ClassRoom.objects.filter(teachers=request.user, is_active=True)
        classes = classes.annotate(
            active_student_count=Count('class_students', filter=Q(class_students__is_active=True)),
        )
        return render(request, 'teacher/class_progress_list.html', {'classes': classes})


class ManageTeachersView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request):
        classes = ClassRoom.objects.filter(
            teachers=request.user, is_active=True
        ).prefetch_related('teachers')
        # Build specialty map from SchoolTeacher for all teachers across classes
        teacher_ids = set()
        for c in classes:
            teacher_ids.update(c.teachers.values_list('id', flat=True))
        specialty_map = {}
        if teacher_ids:
            for st in SchoolTeacher.objects.filter(teacher_id__in=teacher_ids, is_active=True):
                specialty_map[st.teacher_id] = st.specialty
        return render(request, 'teacher/manage_teachers.html', {
            'classes': classes,
            'specialty_map': specialty_map,
        })


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
            log_event(
                user=request.user, school=None, category='data_change',
                action='bulk_students_registered',
                detail={'students_created': results['created'], 'errors': len(results['errors'])},
                request=request,
            )
            messages.success(request, f"{results['created']} student(s) registered.")
        return render(request, 'teacher/bulk_register.html', {'results': results})


IMPORT_ROLES = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]


class StudentCSVUploadView(RoleRequiredMixin, View):
    """Step 1: Upload CSV/XLS and map columns."""
    required_roles = IMPORT_ROLES

    def get(self, request):
        from . import import_services as isvc
        return render(request, 'admin/csv_student_upload.html', {
            'source_presets': isvc.SOURCE_PRESETS,
        })

    def post(self, request):
        from . import import_services as isvc
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, 'Please select a file.')
            return redirect('student_csv_upload')
        if csv_file.size > isvc.MAX_CSV_SIZE:
            messages.error(request, 'File exceeds 10 MB limit.')
            return redirect('student_csv_upload')
        try:
            headers, data_rows = isvc.parse_upload_file(csv_file.read(), csv_file.name)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('student_csv_upload')

        request.session['csv_student_headers'] = headers
        request.session['csv_student_data'] = data_rows

        # Auto-apply preset if selected
        source_preset = request.POST.get('source_preset', '')
        preset_mapping = {}
        if source_preset and source_preset in isvc.SOURCE_PRESETS:
            preset_mapping = isvc.apply_preset(source_preset, headers)

        return render(request, 'admin/csv_student_upload.html', {
            'headers': headers,
            'preview_rows': data_rows[:5],
            'column_fields': isvc.COLUMN_FIELDS,
            'source_presets': isvc.SOURCE_PRESETS,
            'selected_preset': source_preset,
            'preset_mapping': preset_mapping,
            'show_mapping': True,
        })


class StudentCSVPreviewView(RoleRequiredMixin, View):
    """Step 2: Validate columns, then redirect to structure mapping or preview."""
    required_roles = IMPORT_ROLES

    def _get_school(self, request):
        school_id = SchoolTeacher.objects.filter(
            teacher=request.user, is_active=True,
        ).values_list('school_id', flat=True).first()
        if not school_id and request.user.is_superuser:
            school_id = School.objects.first()
            school_id = school_id.id if school_id else None
        return School.objects.get(id=school_id) if school_id else None

    def post(self, request):
        from . import import_services as isvc
        data_rows = request.session.get('csv_student_data')
        if not data_rows:
            messages.error(request, 'No CSV data. Please upload again.')
            return redirect('student_csv_upload')

        school = self._get_school(request)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('student_csv_upload')

        column_mapping = isvc._build_column_mapping(request.POST)
        preview = isvc.validate_and_preview(data_rows, column_mapping, school)

        if preview['errors'] and not preview.get('students_new') and not preview.get('students_existing'):
            for err in preview['errors']:
                messages.error(request, err)
            return redirect('student_csv_upload')

        # Store for subsequent steps
        request.session['csv_student_mapping'] = column_mapping
        request.session['csv_student_school_id'] = school.id

        # Check if school has departments — if so, show structure mapping step
        departments = Department.objects.filter(school=school, is_active=True)
        if departments.exists():
            csv_structure = isvc.extract_csv_structure(data_rows, column_mapping)
            request.session['csv_student_structure'] = csv_structure

            # If user is HoD, auto-select their department
            hod_dept = Department.objects.filter(
                school=school, head=request.user, is_active=True,
            ).first()
            if hod_dept:
                mapping_context = isvc.build_smart_mapping_context(csv_structure, hod_dept)
                return render(request, 'admin/csv_student_structure_mapping.html', {
                    'departments': departments,
                    'selected_department': hod_dept,
                    'csv_structure': csv_structure,
                    'mapping_context': mapping_context,
                    'preview_summary': {
                        'students_new': len(preview['students_new']),
                        'students_existing': len(preview['students_existing']),
                        'guardians_new': len(preview['guardians_new']),
                    },
                    'school': school,
                })

            return render(request, 'admin/csv_student_structure_mapping.html', {
                'departments': departments,
                'csv_structure': csv_structure,
                'preview_summary': {
                    'students_new': len(preview['students_new']),
                    'students_existing': len(preview['students_existing']),
                    'guardians_new': len(preview['guardians_new']),
                },
                'school': school,
            })

        # No departments — go straight to preview
        request.session['csv_student_preview'] = {
            'students_new_count': len(preview['students_new']),
            'students_existing_count': len(preview['students_existing']),
            'departments_new': preview['departments_new'],
            'subjects_new': preview['subjects_new'],
            'classes_new_count': len(preview['classes_new']),
            'classes_existing_count': len(preview['classes_existing']),
            'guardians_new_count': len(preview['guardians_new']),
            'guardians_existing_count': len(preview['guardians_existing']),
        }
        return render(request, 'admin/csv_student_preview.html', {
            'preview': preview,
            'school': school,
        })


class StudentCSVStructureMappingView(RoleRequiredMixin, View):
    """Step 2b: Smart mapping of subjects/levels/classes to a department.

    GET: Load mapping context for the selected department (AJAX-like reload).
    POST: Process mapping choices and proceed to final preview.
    """
    required_roles = IMPORT_ROLES

    def post(self, request):
        from . import import_services as isvc

        data_rows = request.session.get('csv_student_data')
        column_mapping = request.session.get('csv_student_mapping')
        school_id = request.session.get('csv_student_school_id')
        csv_structure = request.session.get('csv_student_structure')

        if not data_rows or not column_mapping or not school_id:
            messages.error(request, 'Session expired. Please upload again.')
            return redirect('student_csv_upload')

        school = School.objects.get(id=school_id)
        department_id = request.POST.get('department_id')

        # If action is "load_mapping" — user selected a department, show mapping UI
        if request.POST.get('action') == 'load_mapping' and department_id:
            department = Department.objects.get(id=department_id, school=school)
            mapping_context = isvc.build_smart_mapping_context(csv_structure, department)
            departments = Department.objects.filter(school=school, is_active=True)

            preview = isvc.validate_and_preview(data_rows, column_mapping, school)

            global_subjects = Subject.objects.filter(
                school__isnull=True, is_active=True,
            ).order_by('order', 'name')
            global_levels = Level.objects.filter(
                school__isnull=True, level_number__lt=100,
            ).order_by('level_number')

            return render(request, 'admin/csv_student_structure_mapping.html', {
                'departments': departments,
                'selected_department': department,
                'csv_structure': csv_structure,
                'mapping_context': mapping_context,
                'preview_summary': {
                    'students_new': len(preview.get('students_new', [])),
                    'students_existing': len(preview.get('students_existing', [])),
                    'guardians_new': len(preview.get('guardians_new', [])),
                },
                'school': school,
                'global_subjects': global_subjects,
                'global_levels': global_levels,
            })

        # Otherwise — user submitted final mapping choices
        if not department_id:
            messages.error(request, 'Please select a department.')
            return redirect('student_csv_upload')

        department = Department.objects.get(id=department_id, school=school)

        # Build structure_mapping from POST data
        structure_mapping = {
            'department_id': department.id,
            'subject_map': {},
            'level_map': {},
            'class_map': {},
            'teacher_map': {},
            'global_subject_map': {},  # csv_subject -> global subject id (optional)
            'global_level_map': {},    # csv_level -> global level id (optional)
            'dummy_subject': False,
            'dummy_level': False,
            'dummy_class': False,
        }

        # Parse subject mappings
        if csv_structure and csv_structure['csv_subjects']:
            for csv_subj in csv_structure['csv_subjects']:
                val = request.POST.get(f'subject_map_{csv_subj}', 'create')
                structure_mapping['subject_map'][csv_subj] = val
                global_val = request.POST.get(f'global_subject_map_{csv_subj}', 'none')
                if global_val and global_val != 'none':
                    structure_mapping['global_subject_map'][csv_subj] = global_val
        elif not csv_structure or not csv_structure['csv_subjects']:
            # No CSV subjects — check if system has subjects
            mapping_ctx = isvc.build_smart_mapping_context(csv_structure or {'csv_subjects': [], 'csv_levels': [], 'csv_classes': [], 'csv_teachers': []}, department)
            if mapping_ctx['subject_scenario'] == 'neither':
                structure_mapping['dummy_subject'] = True

        # Parse level mappings
        if csv_structure and csv_structure['csv_levels']:
            for csv_lvl in csv_structure['csv_levels']:
                val = request.POST.get(f'level_map_{csv_lvl}', 'create')
                structure_mapping['level_map'][csv_lvl] = val
                global_val = request.POST.get(f'global_level_map_{csv_lvl}', 'none')
                if global_val and global_val != 'none':
                    structure_mapping['global_level_map'][csv_lvl] = global_val
        elif not csv_structure or not csv_structure['csv_levels']:
            mapping_ctx = isvc.build_smart_mapping_context(csv_structure or {'csv_subjects': [], 'csv_levels': [], 'csv_classes': [], 'csv_teachers': []}, department)
            if mapping_ctx['level_scenario'] == 'neither':
                structure_mapping['dummy_level'] = True

        # Parse class mappings
        if csv_structure and csv_structure['csv_classes']:
            for csv_cls in csv_structure['csv_classes']:
                val = request.POST.get(f'class_map_{csv_cls}', 'create')
                structure_mapping['class_map'][csv_cls] = val
        elif not csv_structure or not csv_structure['csv_classes']:
            mapping_ctx = isvc.build_smart_mapping_context(csv_structure or {'csv_subjects': [], 'csv_levels': [], 'csv_classes': [], 'csv_teachers': []}, department)
            if mapping_ctx['class_scenario'] == 'neither':
                structure_mapping['dummy_class'] = True

        # Parse teacher mappings
        if csv_structure and csv_structure.get('csv_teachers'):
            for csv_teacher in csv_structure['csv_teachers']:
                val = request.POST.get(f'teacher_map_{csv_teacher}', 'create')
                structure_mapping['teacher_map'][csv_teacher] = val

        # Store structure mapping in session
        request.session['csv_student_structure_mapping'] = structure_mapping

        # Generate final preview
        preview = isvc.validate_and_preview(data_rows, column_mapping, school)
        isvc.apply_structure_mapping(preview, structure_mapping, department)

        request.session['csv_student_preview'] = {
            'students_new_count': len(preview['students_new']),
            'students_existing_count': len(preview['students_existing']),
            'departments_new': preview['departments_new'],
            'subjects_new': preview['subjects_new'],
            'classes_new_count': len(preview['classes_new']),
            'classes_existing_count': len(preview['classes_existing']),
            'guardians_new_count': len(preview['guardians_new']),
            'guardians_existing_count': len(preview['guardians_existing']),
        }

        return render(request, 'admin/csv_student_preview.html', {
            'preview': preview,
            'school': school,
            'target_department': department,
            'structure_mapping': structure_mapping,
        })


class StudentCSVConfirmView(RoleRequiredMixin, View):
    """Step 3: Execute import and show results."""
    required_roles = IMPORT_ROLES

    def post(self, request):
        from . import import_services as isvc
        data_rows = request.session.get('csv_student_data')
        column_mapping = request.session.get('csv_student_mapping')
        school_id = request.session.get('csv_student_school_id')
        if not data_rows or not column_mapping or not school_id:
            messages.error(request, 'Session expired. Please upload again.')
            return redirect('student_csv_upload')

        school = School.objects.get(id=school_id)
        preview = isvc.validate_and_preview(data_rows, column_mapping, school)

        if preview['errors'] and not preview.get('students_new') and not preview.get('students_existing'):
            for err in preview['errors']:
                messages.error(request, err)
            return redirect('student_csv_upload')

        # Check student limit before importing
        from billing.entitlements import check_student_limit, check_class_limit
        new_student_count = len(preview.get('students_new', []))
        if new_student_count > 0:
            allowed, current, limit = check_student_limit(school)
            if limit > 0 and (current + new_student_count) > limit:
                messages.error(
                    request,
                    f'Your plan allows {limit} students. You currently have {current} '
                    f'and are trying to import {new_student_count} new students. '
                    f'Please upgrade your plan or reduce the import size.'
                )
                return redirect('student_csv_upload')

        new_class_count = len(preview.get('classes_new', []))
        if new_class_count > 0:
            allowed, current, limit = check_class_limit(school)
            if limit > 0 and (current + new_class_count) > limit:
                messages.error(
                    request,
                    f'Your plan allows {limit} classes. You currently have {current} '
                    f'and the import would create {new_class_count} new classes. '
                    f'Please upgrade your plan or reduce the import size.'
                )
                return redirect('student_csv_upload')

        # Apply structure mapping if present
        structure_mapping = request.session.get('csv_student_structure_mapping')
        if structure_mapping:
            department = Department.objects.get(id=structure_mapping['department_id'])
            isvc.apply_structure_mapping(preview, structure_mapping, department)

        try:
            results = isvc.execute_import(preview, school, request.user)
        except Exception as e:
            logger.exception('CSV student import failed')
            messages.error(request, f'Import failed: {e}')
            return redirect('student_csv_upload')

        log_event(
            user=request.user, school=school, category='data_change',
            action='student_csv_imported',
            detail={
                'students_created': results['counts']['students_created'],
                'classes_created': results['counts']['classes_created'],
                'students_enrolled': results['counts']['students_enrolled'],
            },
            request=request,
        )

        # Store credentials for download (students + parents combined)
        request.session['csv_student_credentials'] = results['credentials']
        request.session['csv_parent_credentials'] = results.get('parent_credentials', [])

        # Success message for dashboard
        c = results['counts']
        parents_created = c.get('parents_created', 0)
        messages.success(
            request,
            f"Import complete: {c['students_created']} students created, "
            f"{c['classes_created']} classes, {c['students_enrolled']} enrollments"
            + (f", {parents_created} parent accounts created" if parents_created else "") + "."
        )

        # Clear CSV data from session
        for key in ('csv_student_data', 'csv_student_headers', 'csv_student_mapping',
                     'csv_student_school_id', 'csv_student_preview',
                     'csv_student_structure', 'csv_student_structure_mapping'):
            request.session.pop(key, None)

        return render(request, 'admin/csv_student_results.html', {
            'results': results,
            'school': school,
        })


class StudentCSVCredentialsView(RoleRequiredMixin, View):
    """Download generated credentials as CSV."""
    required_roles = IMPORT_ROLES

    def get(self, request):
        import csv as csv_mod
        from django.http import HttpResponse
        credentials = request.session.get('csv_student_credentials', [])
        parent_credentials = request.session.get('csv_parent_credentials', [])
        if not credentials and not parent_credentials:
            messages.error(request, 'No credentials available.')
            return redirect('student_csv_upload')

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="import_credentials.csv"'
        writer = csv_mod.writer(response)
        writer.writerow(['Role', 'Username', 'Email', 'Password', 'First Name', 'Last Name'])
        for c in credentials:
            writer.writerow(['Student', c['username'], c['email'], c['password'],
                             c['first_name'], c['last_name']])
        for c in parent_credentials:
            writer.writerow(['Parent', c['username'], c['email'], c['password'],
                             c['first_name'], c['last_name']])
        return response


class BalanceCSVUploadView(RoleRequiredMixin, View):
    """Step 1: Upload CSV/XLS and map columns for balance import."""
    required_roles = IMPORT_ROLES

    def get(self, request):
        from . import import_services as isvc
        return render(request, 'admin/csv_balance_upload.html', {
            'source_presets': isvc.BALANCE_PRESETS,
        })

    def post(self, request):
        from . import import_services as isvc
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, 'Please select a file.')
            return redirect('balance_csv_upload')
        if csv_file.size > isvc.MAX_CSV_SIZE:
            messages.error(request, 'File exceeds 10 MB limit.')
            return redirect('balance_csv_upload')
        try:
            headers, data_rows = isvc.parse_upload_file(csv_file.read(), csv_file.name)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('balance_csv_upload')

        request.session['csv_balance_headers'] = headers
        request.session['csv_balance_data'] = data_rows

        # Auto-apply preset if selected
        source_preset = request.POST.get('source_preset', '')
        preset_mapping = {}
        if source_preset and source_preset in isvc.BALANCE_PRESETS:
            preset_mapping = isvc.apply_balance_preset(source_preset, headers)

        return render(request, 'admin/csv_balance_upload.html', {
            'headers': headers,
            'preview_rows': data_rows[:5],
            'column_fields': isvc.BALANCE_COLUMN_FIELDS,
            'source_presets': isvc.BALANCE_PRESETS,
            'selected_preset': source_preset,
            'preset_mapping': preset_mapping,
            'show_mapping': True,
        })


class BalanceCSVPreviewView(RoleRequiredMixin, View):
    """Step 2: Validate columns and show balance preview."""
    required_roles = IMPORT_ROLES

    def _get_school(self, request):
        school_id = SchoolTeacher.objects.filter(
            teacher=request.user, is_active=True,
        ).values_list('school_id', flat=True).first()
        if not school_id and request.user.is_superuser:
            school_id = School.objects.first()
            school_id = school_id.id if school_id else None
        return School.objects.get(id=school_id) if school_id else None

    def post(self, request):
        from . import import_services as isvc
        data_rows = request.session.get('csv_balance_data')
        if not data_rows:
            messages.error(request, 'No CSV data. Please upload again.')
            return redirect('balance_csv_upload')

        school = self._get_school(request)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('balance_csv_upload')

        column_mapping = isvc._build_balance_column_mapping(request.POST)
        preview = isvc.validate_balance_preview(data_rows, column_mapping, school)

        if preview['errors']:
            for err in preview['errors']:
                messages.error(request, err)
            return redirect('balance_csv_upload')

        # Store for confirm step — serialize Decimal values
        serializable_matched = []
        for m in preview.get('matched', []):
            item = dict(m)
            item['balance'] = str(item['balance'])
            item['current_balance'] = str(item['current_balance'])
            serializable_matched.append(item)

        request.session['csv_balance_matched'] = serializable_matched
        request.session['csv_balance_school_id'] = school.id

        return render(request, 'admin/csv_balance_preview.html', {
            'preview': preview,
            'school': school,
        })


class BalanceCSVConfirmView(RoleRequiredMixin, View):
    """Step 3: Execute balance import and show results."""
    required_roles = IMPORT_ROLES

    def post(self, request):
        from . import import_services as isvc
        from decimal import Decimal

        matched_items = request.session.get('csv_balance_matched')
        school_id = request.session.get('csv_balance_school_id')
        if not matched_items or not school_id:
            messages.error(request, 'Session expired. Please upload again.')
            return redirect('balance_csv_upload')

        school = School.objects.get(id=school_id)

        # Deserialize Decimal values
        for item in matched_items:
            item['balance'] = Decimal(item['balance'])

        try:
            results = isvc.execute_balance_import(matched_items, school)
        except Exception as e:
            logger.exception('Balance import failed')
            messages.error(request, f'Import failed: {e}')
            return redirect('balance_csv_upload')

        log_event(
            user=request.user, school=school, category='data_change',
            action='balance_csv_imported',
            detail={'balances_updated': results['updated']},
            request=request,
        )

        messages.success(
            request,
            f"Balance import complete: {results['updated']} balances updated."
        )

        # Clear session data
        for key in ('csv_balance_data', 'csv_balance_headers', 'csv_balance_matched',
                     'csv_balance_school_id'):
            request.session.pop(key, None)

        return render(request, 'admin/csv_balance_results.html', {
            'results': results,
            'school': school,
        })


# ── Teacher CSV/XLS Import ──────────────────────────────────

class TeacherCSVUploadView(RoleRequiredMixin, View):
    """Step 1: Upload CSV/XLS and map columns for teacher import."""
    required_roles = IMPORT_ROLES

    def get(self, request):
        from . import import_services as isvc
        return render(request, 'admin/csv_teacher_upload.html', {
            'source_presets': isvc.TEACHER_PRESETS,
        })

    def post(self, request):
        from . import import_services as isvc
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, 'Please select a file.')
            return redirect('teacher_csv_upload')
        if csv_file.size > isvc.MAX_CSV_SIZE:
            messages.error(request, 'File exceeds 10 MB limit.')
            return redirect('teacher_csv_upload')
        try:
            headers, data_rows = isvc.parse_upload_file(csv_file.read(), csv_file.name)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('teacher_csv_upload')

        request.session['csv_teacher_headers'] = headers
        request.session['csv_teacher_data'] = data_rows

        # Auto-apply preset if selected
        source_preset = request.POST.get('source_preset', '')
        preset_mapping = {}
        if source_preset and source_preset in isvc.TEACHER_PRESETS:
            preset_mapping = isvc.apply_teacher_preset(source_preset, headers)

        return render(request, 'admin/csv_teacher_upload.html', {
            'headers': headers,
            'preview_rows': data_rows[:5],
            'column_fields': isvc.TEACHER_COLUMN_FIELDS,
            'source_presets': isvc.TEACHER_PRESETS,
            'selected_preset': source_preset,
            'preset_mapping': preset_mapping,
            'show_mapping': True,
        })


class TeacherCSVPreviewView(RoleRequiredMixin, View):
    """Step 2: Validate columns and show teacher preview."""
    required_roles = IMPORT_ROLES

    def _get_school(self, request):
        school_id = SchoolTeacher.objects.filter(
            teacher=request.user, is_active=True,
        ).values_list('school_id', flat=True).first()
        if not school_id and request.user.is_superuser:
            school_id = School.objects.first()
            school_id = school_id.id if school_id else None
        return School.objects.get(id=school_id) if school_id else None

    def post(self, request):
        from . import import_services as isvc
        data_rows = request.session.get('csv_teacher_data')
        if not data_rows:
            messages.error(request, 'No CSV data. Please upload again.')
            return redirect('teacher_csv_upload')

        school = self._get_school(request)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('teacher_csv_upload')

        column_mapping = isvc._build_teacher_column_mapping(request.POST)
        preview = isvc.validate_teacher_preview(data_rows, column_mapping, school)

        if preview['errors']:
            for err in preview['errors']:
                messages.error(request, err)
            return redirect('teacher_csv_upload')

        request.session['csv_teacher_preview'] = preview
        request.session['csv_teacher_school_id'] = school.id

        return render(request, 'admin/csv_teacher_preview.html', {
            'preview': preview,
            'school': school,
        })


class TeacherCSVConfirmView(RoleRequiredMixin, View):
    """Step 3: Execute teacher import and show results."""
    required_roles = IMPORT_ROLES

    def post(self, request):
        from . import import_services as isvc
        preview = request.session.get('csv_teacher_preview')
        school_id = request.session.get('csv_teacher_school_id')
        if not preview or not school_id:
            messages.error(request, 'Session expired. Please upload again.')
            return redirect('teacher_csv_upload')

        school = School.objects.get(id=school_id)

        try:
            results = isvc.execute_teacher_import(preview, school, request.user)
        except Exception as e:
            logger.exception('Teacher import failed')
            messages.error(request, f'Import failed: {e}')
            return redirect('teacher_csv_upload')

        log_event(
            user=request.user, school=school, category='data_change',
            action='teacher_csv_imported',
            detail={
                'teachers_created': results.get('counts', {}).get('teachers_created', 0),
                'credentials_generated': len(results.get('credentials', [])),
            },
            request=request,
        )

        # Store credentials for download
        request.session['csv_teacher_credentials'] = results['credentials']

        # Clear session data
        for key in ('csv_teacher_data', 'csv_teacher_headers', 'csv_teacher_preview',
                     'csv_teacher_school_id'):
            request.session.pop(key, None)

        return render(request, 'admin/csv_teacher_results.html', {
            'results': results,
            'school': school,
        })


class TeacherCSVCredentialsView(RoleRequiredMixin, View):
    """Download generated teacher credentials as CSV."""
    required_roles = IMPORT_ROLES

    def get(self, request):
        import csv as csv_mod
        from django.http import HttpResponse
        credentials = request.session.get('csv_teacher_credentials', [])
        if not credentials:
            messages.error(request, 'No credentials available.')
            return redirect('teacher_csv_upload')

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="teacher_credentials.csv"'
        writer = csv_mod.writer(response)
        writer.writerow(['Username', 'Email', 'Password', 'First Name', 'Last Name', 'Role'])
        for c in credentials:
            writer.writerow([c['username'], c['email'], c['password'],
                           c['first_name'], c['last_name'], c['role']])
        return response


class ParentCSVUploadView(RoleRequiredMixin, View):
    """Step 1: Upload CSV/XLS and map columns for parent import."""
    required_roles = IMPORT_ROLES

    def get(self, request):
        from . import import_services as isvc
        return render(request, 'admin/csv_parent_upload.html', {
            'source_presets': isvc.PARENT_PRESETS,
        })

    def post(self, request):
        from . import import_services as isvc
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, 'Please select a file.')
            return redirect('parent_csv_upload')
        if csv_file.size > isvc.MAX_CSV_SIZE:
            messages.error(request, 'File exceeds 10 MB limit.')
            return redirect('parent_csv_upload')
        try:
            headers, data_rows = isvc.parse_upload_file(csv_file.read(), csv_file.name)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('parent_csv_upload')

        request.session['csv_parent_headers'] = headers
        request.session['csv_parent_data'] = data_rows

        # Auto-apply preset if selected
        source_preset = request.POST.get('source_preset', '')
        preset_mapping = {}
        if source_preset and source_preset in isvc.PARENT_PRESETS:
            preset_mapping = isvc.apply_parent_preset(source_preset, headers)

        return render(request, 'admin/csv_parent_upload.html', {
            'headers': headers,
            'preview_rows': data_rows[:5],
            'column_fields': isvc.PARENT_COLUMN_FIELDS,
            'source_presets': isvc.PARENT_PRESETS,
            'selected_preset': source_preset,
            'preset_mapping': preset_mapping,
            'show_mapping': True,
        })


class ParentCSVPreviewView(RoleRequiredMixin, View):
    """Step 2: Validate columns and show parent preview."""
    required_roles = IMPORT_ROLES

    def _get_school(self, request):
        school_id = SchoolTeacher.objects.filter(
            teacher=request.user, is_active=True,
        ).values_list('school_id', flat=True).first()
        if not school_id and request.user.is_superuser:
            school_id = School.objects.first()
            school_id = school_id.id if school_id else None
        return School.objects.get(id=school_id) if school_id else None

    def post(self, request):
        from . import import_services as isvc
        data_rows = request.session.get('csv_parent_data')
        if not data_rows:
            messages.error(request, 'No CSV data. Please upload again.')
            return redirect('parent_csv_upload')

        school = self._get_school(request)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('parent_csv_upload')

        column_mapping = isvc._build_parent_column_mapping(request.POST)
        preview = isvc.validate_parent_preview(data_rows, column_mapping, school)

        if preview['errors']:
            for err in preview['errors']:
                messages.error(request, err)
            return redirect('parent_csv_upload')

        request.session['csv_parent_preview'] = preview
        request.session['csv_parent_school_id'] = school.id

        return render(request, 'admin/csv_parent_preview.html', {
            'preview': preview,
            'school': school,
        })


class ParentCSVConfirmView(RoleRequiredMixin, View):
    """Step 3: Execute parent import and show results."""
    required_roles = IMPORT_ROLES

    def post(self, request):
        from . import import_services as isvc
        preview = request.session.get('csv_parent_preview')
        school_id = request.session.get('csv_parent_school_id')
        if not preview or not school_id:
            messages.error(request, 'Session expired. Please upload again.')
            return redirect('parent_csv_upload')

        school = School.objects.get(id=school_id)

        try:
            results = isvc.execute_parent_import(preview, school, request.user)
        except Exception as e:
            logger.exception('Parent import failed')
            messages.error(request, f'Import failed: {e}')
            return redirect('parent_csv_upload')

        log_event(
            user=request.user, school=school, category='data_change',
            action='parent_csv_imported',
            detail={
                'parents_created': results.get('counts', {}).get('parents_created', 0),
                'links_created': results.get('counts', {}).get('links_created', 0),
                'credentials_generated': len(results.get('credentials', [])),
            },
            request=request,
        )

        request.session['csv_parent_credentials'] = results['credentials']

        for key in ('csv_parent_data', 'csv_parent_headers', 'csv_parent_preview',
                     'csv_parent_school_id'):
            request.session.pop(key, None)

        return render(request, 'admin/csv_parent_results.html', {
            'results': results,
            'school': school,
        })


class ParentCSVCredentialsView(RoleRequiredMixin, View):
    """Download generated parent credentials as CSV."""
    required_roles = IMPORT_ROLES

    def get(self, request):
        import csv as csv_mod
        from django.http import HttpResponse
        credentials = request.session.get('csv_parent_credentials', [])
        if not credentials:
            messages.error(request, 'No credentials available.')
            return redirect('parent_csv_upload')

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="parent_credentials.csv"'
        writer = csv_mod.writer(response)
        writer.writerow(['Username', 'Email', 'Password', 'First Name', 'Last Name', 'Children'])
        for c in credentials:
            writer.writerow([c['username'], c['email'], c['password'],
                           c['first_name'], c['last_name'], c.get('children', '')])
        return response


class UploadQuestionsView(RoleRequiredMixin, View):
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def get(self, request):
        school_id, dept_id, classroom_ids = _get_question_scope(request.user)
        ctx = {
            'topics': Topic.objects.filter(is_active=True).select_related('subject'),
            'levels': Level.objects.filter(level_number__lte=8),
        }
        # Teachers must pick a classroom for bulk upload too
        if request.user.is_any_teacher and not (
            request.user.has_role(Role.HEAD_OF_INSTITUTE)
            or request.user.has_role(Role.INSTITUTE_OWNER)
            or request.user.has_role(Role.HEAD_OF_DEPARTMENT)
        ):
            ctx['classrooms'] = ClassRoom.objects.filter(
                id__in=classroom_ids, is_active=True,
            ).order_by('name')
        return render(request, 'teacher/upload_questions.html', ctx)

    def post(self, request):
        import json
        import zipfile
        import re
        from maths.models import Question as MathsQuestion, Answer as MathsAnswer
        from classroom.models import Topic as ClassroomTopic, Level as ClassroomLevel, Subject as ClassroomSubject

        uploaded_file = request.FILES.get('upload_file')
        if not uploaded_file:
            messages.error(request, 'Please select a file.')
            return redirect('upload_questions')

        # Determine if ZIP or plain JSON
        filename = uploaded_file.name.lower()
        extracted_images = {}  # filename -> bytes

        if filename.endswith('.zip'):
            if not zipfile.is_zipfile(uploaded_file):
                messages.error(request, 'Invalid ZIP file.')
                return redirect('upload_questions')
            uploaded_file.seek(0)
            with zipfile.ZipFile(uploaded_file) as zf:
                json_bytes = None
                for name in zf.namelist():
                    basename = name.split('/')[-1]
                    if basename == 'questions.json':
                        json_bytes = zf.read(name)
                    elif re.search(r'\.(png|jpg|jpeg|gif|webp)$', basename, re.I):
                        extracted_images[basename] = zf.read(name)
                if json_bytes is None:
                    messages.error(request, 'ZIP must contain a file named questions.json at its root.')
                    return redirect('upload_questions')
            try:
                data = json.loads(json_bytes.decode('utf-8'))
            except json.JSONDecodeError as e:
                messages.error(request, f'Invalid JSON: {e}')
                return redirect('upload_questions')
        elif filename.endswith('.json'):
            try:
                data = json.loads(uploaded_file.read().decode('utf-8'))
            except json.JSONDecodeError as e:
                messages.error(request, f'Invalid JSON: {e}')
                return redirect('upload_questions')
        else:
            messages.error(request, 'Please upload a .json or .zip file.')
            return redirect('upload_questions')

        topic_name = data.get('topic', '').strip()
        strand_name = data.get('strand', '').strip()
        year_level = data.get('year_level')

        # Ensure the global Mathematics subject exists
        maths_subject, _ = ClassroomSubject.objects.get_or_create(
            slug='mathematics',
            school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )

        # Resolve (or auto-create) the strand
        strand_topic = None
        if strand_name:
            from django.utils.text import slugify as _slugify
            strand_slug = _slugify(strand_name)
            strand_topic, strand_created = ClassroomTopic.objects.get_or_create(
                subject=maths_subject,
                slug=strand_slug,
                defaults={
                    'name': strand_name,
                    'parent': None,
                    'is_active': True,
                    'order': 0,
                },
            )

        # Resolve (or auto-create) the topic
        topic_qs = ClassroomTopic.objects.filter(subject=maths_subject, name__iexact=topic_name)
        if strand_topic is not None:
            topic_qs = topic_qs.filter(parent=strand_topic)
        try:
            maths_topic = topic_qs.get()
        except ClassroomTopic.DoesNotExist:
            from django.utils.text import slugify as _slugify
            base_slug = _slugify(topic_name) or f'topic-{topic_name.lower()}'
            slug = base_slug
            counter = 1
            while ClassroomTopic.objects.filter(subject=maths_subject, slug=slug).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            maths_topic = ClassroomTopic.objects.create(
                subject=maths_subject,
                name=topic_name,
                slug=slug,
                parent=strand_topic,
                is_active=True,
                order=0,
            )
        except ClassroomTopic.MultipleObjectsReturned:
            messages.error(request, f'Multiple topics named "{topic_name}" found — please disambiguate in the database.')
            return redirect('upload_questions')

        try:
            maths_level = ClassroomLevel.objects.get(level_number=year_level)
        except ClassroomLevel.DoesNotExist:
            messages.error(request, f'Year level {year_level} not found.')
            return redirect('upload_questions')

        # Link topic and strand to the level so they appear in the topic browser
        if not maths_topic.levels.filter(pk=maths_level.pk).exists():
            maths_topic.levels.add(maths_level)
        if strand_topic and not strand_topic.levels.filter(pk=maths_level.pk).exists():
            strand_topic.levels.add(maths_level)

        # Build image save directory: questions/year<N>/<topic_slug>/
        topic_slug = re.sub(r'\s+', '_', topic_name.lower())
        image_rel_dir = f'questions/year{year_level}/{topic_slug}'
        if extracted_images:
            from django.conf import settings
            import os
            image_abs_dir = os.path.join(settings.MEDIA_ROOT, image_rel_dir)
            os.makedirs(image_abs_dir, exist_ok=True)
            for img_name, img_bytes in extracted_images.items():
                safe_name = re.sub(r'[^\w.\-]', '_', img_name)
                with open(os.path.join(image_abs_dir, safe_name), 'wb') as f:
                    f.write(img_bytes)

        school_id, dept_id, classroom_ids = _get_question_scope(request.user)

        # For teachers, get the selected classroom
        selected_classroom_id = None
        if request.user.is_any_teacher and not (
            request.user.has_role(Role.HEAD_OF_INSTITUTE)
            or request.user.has_role(Role.INSTITUTE_OWNER)
            or request.user.has_role(Role.HEAD_OF_DEPARTMENT)
        ):
            selected_classroom_id = request.POST.get('classroom')
            if not selected_classroom_id or int(selected_classroom_id) not in classroom_ids:
                messages.error(request, 'Please select a valid classroom.')
                return redirect('upload_questions')
            selected_classroom_id = int(selected_classroom_id)

        inserted = updated = failed = 0
        errors = []
        for i, q_data in enumerate(data.get('questions', []), 1):
            question_text = q_data.get('question_text', '').strip()
            question_type = q_data.get('question_type', '').strip()
            answers_data = q_data.get('answers', [])
            if not question_text: errors.append(f'Q{i}: missing question_text'); failed += 1; continue
            if question_type not in dict(MathsQuestion.QUESTION_TYPES): errors.append(f'Q{i}: bad type'); failed += 1; continue
            if not answers_data: errors.append(f'Q{i}: no answers'); failed += 1; continue

            # Resolve image path if specified
            image_field = ''
            img_filename = q_data.get('image', '').strip()
            if img_filename and img_filename in extracted_images:
                safe_name = re.sub(r'[^\w.\-]', '_', img_filename)
                image_field = f'{image_rel_dir}/{safe_name}'

            try:
                with transaction.atomic():
                    existing = MathsQuestion.objects.filter(
                        question_text=question_text, topic=maths_topic, level=maths_level,
                        school_id=school_id, department_id=dept_id,
                        classroom_id=selected_classroom_id,
                    ).first()
                    fields = {'question_type': question_type, 'difficulty': q_data.get('difficulty', 1),
                              'points': q_data.get('points', 1), 'explanation': q_data.get('explanation', '')}
                    if image_field:
                        fields['image'] = image_field
                    if existing:
                        for k, v in fields.items(): setattr(existing, k, v)
                        existing.save(); existing.answers.all().delete(); question = existing; updated += 1
                    else:
                        question = MathsQuestion.objects.create(
                            question_text=question_text, topic=maths_topic, level=maths_level,
                            school_id=school_id, department_id=dept_id,
                            classroom_id=selected_classroom_id, **fields
                        )
                        inserted += 1
                    for a in answers_data:
                        MathsAnswer.objects.create(
                            question=question,
                            answer_text=a.get('answer_text') or a.get('text', ''),
                            is_correct=a.get('is_correct', False),
                            order=a.get('order') or a.get('display_order', 1),
                        )
            except Exception as e:
                errors.append(f'Q{i}: {e}'); failed += 1
        if inserted or updated:
            log_event(
                user=request.user,
                school=School.objects.filter(id=school_id).first() if school_id else None,
                category='data_change',
                action='questions_uploaded',
                detail={'inserted': inserted, 'updated': updated, 'failed': failed, 'topic': topic_name, 'year_level': year_level},
                request=request,
            )
        return render(request, 'teacher/upload_questions.html', {
            'upload_results': {
                'inserted': inserted, 'updated': updated, 'failed': failed, 'errors': errors,
                'images_saved': len(extracted_images),
                'image_dir': image_rel_dir if extracted_images else '',
            },
            'topics': Topic.objects.filter(is_active=True).select_related('subject'),
            'levels': Level.objects.filter(level_number__lte=8),
        })


def _get_question_scope(user):
    """Return (school_id, department_id, classroom_ids) based on user role.

    Scope hierarchy:
      superuser  → global (all None)
      HoI        → school only
      HoD        → school + department
      Teacher    → school + department + classroom(s)
    """
    from .models import DepartmentTeacher

    if user.is_superuser:
        return None, None, []

    school_teacher = SchoolTeacher.objects.filter(
        teacher=user, is_active=True
    ).select_related('school').first()
    school_id = school_teacher.school_id if school_teacher else None

    if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
        return school_id, None, []

    if user.has_role(Role.HEAD_OF_DEPARTMENT):
        dept = Department.objects.filter(head=user, school_id=school_id).first()
        return school_id, dept.id if dept else None, []

    # Teacher (senior, regular, junior) — get their department + classrooms
    dept_membership = DepartmentTeacher.objects.filter(
        teacher=user, department__school_id=school_id
    ).first()
    dept_id = dept_membership.department_id if dept_membership else None
    classroom_ids = list(
        ClassTeacher.objects.filter(
            teacher=user, classroom__school_id=school_id, classroom__is_active=True,
        ).values_list('classroom_id', flat=True)
    )
    return school_id, dept_id, classroom_ids


def _can_edit_question(user, question):
    """Check if user can edit/delete a question based on scope."""
    if user.is_superuser:
        return True
    school_id, dept_id, classroom_ids = _get_question_scope(user)
    # Global questions — only superuser (handled above)
    if question.school_id is None:
        return False
    # School-scoped — HoI/owner of that school
    if question.department_id is None and question.classroom_id is None:
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            return question.school_id == school_id
        return False
    # Department-scoped — HoD of that department
    if question.classroom_id is None:
        if user.has_role(Role.HEAD_OF_DEPARTMENT):
            return question.department_id == dept_id
        return False
    # Class-scoped — teacher of that class
    return question.classroom_id in classroom_ids


class QuestionListView(LoginRequiredMixin, View):
    def get(self, request, level_number):
        from django.db.models import Q
        from maths.models import Question as MathsQuestion
        level = get_object_or_404(Level, level_number=level_number)

        school_id, dept_id, classroom_ids = _get_question_scope(request.user)

        # Global questions are always visible
        q_filter = Q(level=level) & Q(school__isnull=True)

        if request.user.is_superuser:
            # Superuser sees everything
            q_filter = Q(level=level)
        elif request.user.has_role(Role.HEAD_OF_INSTITUTE) or request.user.has_role(Role.INSTITUTE_OWNER):
            # HoI sees global + all questions in their school (any scope)
            q_filter = Q(level=level) & (
                Q(school__isnull=True) | Q(school_id=school_id)
            )
        elif request.user.has_role(Role.HEAD_OF_DEPARTMENT):
            # HoD sees global + school-scoped + their department's questions (not class-scoped)
            q_filter = Q(level=level) & (
                Q(school__isnull=True)
                | Q(school_id=school_id, department__isnull=True)
                | Q(department_id=dept_id, classroom__isnull=True)
            )
        else:
            # Teacher sees global + school-scoped + department-scoped + their class questions
            q_filter = Q(level=level) & (
                Q(school__isnull=True)
                | Q(school_id=school_id, department__isnull=True)
                | Q(department_id=dept_id, classroom__isnull=True)
                | Q(classroom_id__in=classroom_ids)
            )

        questions = (
            MathsQuestion.objects.filter(q_filter)
            .select_related('topic', 'school', 'department', 'classroom')
            .prefetch_related('answers')
        )
        return render(request, 'teacher/question_list.html', {
            'level': level, 'questions': questions, 'user_can_edit': _can_edit_question,
        })


@login_required
def htmx_topics_for_level(request):
    """HTMX endpoint: return topic <option> tags filtered by level_number."""
    from django.http import HttpResponse
    level_number = request.GET.get('level', '')
    if not level_number:
        return HttpResponse('<option value="">-- Select topic --</option>')
    try:
        level = Level.objects.get(level_number=int(level_number))
    except (Level.DoesNotExist, ValueError):
        return HttpResponse('<option value="">-- Select topic --</option>')

    strands = Topic.objects.filter(levels=level, is_active=True, parent__isnull=True).order_by('name')
    subtopics = Topic.objects.filter(levels=level, is_active=True, parent__isnull=False).order_by('parent__name', 'name')

    html = '<option value="">-- Select topic --</option>'
    for strand in strands:
        children = [t for t in subtopics if t.parent_id == strand.id]
        if children:
            html += f'<optgroup label="{strand.name}">'
            for t in children:
                html += f'<option value="{t.id}">{t.name}</option>'
            html += '</optgroup>'
        else:
            html += f'<option value="{strand.id}">{strand.name}</option>'
    return HttpResponse(html)


class AddQuestionView(RoleRequiredMixin, View):
    """Create a question. Works both standalone (/create-question/) and with pre-selected level (/level/<int>/add-question/)."""
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def _build_context(self, request, level=None):
        from maths.models import Question as MathsQuestion
        school_id, dept_id, classroom_ids = _get_question_scope(request.user)
        ctx = {
            'level': level,
            'question_types': MathsQuestion.QUESTION_TYPES,
            'difficulty_choices': MathsQuestion.DIFFICULTY_CHOICES,
        }

        # Subjects and levels for standalone mode
        from classroom.models import Subject
        ctx['subjects'] = Subject.objects.filter(is_active=True).order_by('name')
        ctx['levels'] = Level.objects.filter(level_number__lte=12).order_by('level_number')

        # Topics — if level is pre-selected, filter by it; otherwise load all
        if level:
            ctx['topics'] = Topic.objects.filter(levels=level, is_active=True).order_by('name')
            # Strands (parent topics) for this level
            ctx['strands'] = Topic.objects.filter(
                levels=level, is_active=True, parent__isnull=True,
            ).order_by('name')
        else:
            ctx['topics'] = Topic.objects.filter(is_active=True).order_by('name')
            ctx['strands'] = Topic.objects.filter(
                is_active=True, parent__isnull=True,
            ).order_by('name')

        # Teachers must pick a classroom
        if request.user.is_any_teacher and not (
            request.user.has_role(Role.HEAD_OF_INSTITUTE)
            or request.user.has_role(Role.INSTITUTE_OWNER)
            or request.user.has_role(Role.HEAD_OF_DEPARTMENT)
        ):
            ctx['classrooms'] = ClassRoom.objects.filter(
                id__in=classroom_ids, is_active=True,
            ).order_by('name')

        # Scope label
        if request.user.is_superuser:
            ctx['scope_label'] = 'Global'
        elif request.user.has_role(Role.HEAD_OF_INSTITUTE) or request.user.has_role(Role.INSTITUTE_OWNER):
            ctx['scope_label'] = 'School'
        elif request.user.has_role(Role.HEAD_OF_DEPARTMENT):
            dept = Department.objects.filter(id=dept_id).first()
            ctx['scope_label'] = f'Department: {dept.name}' if dept else 'Department'
        else:
            ctx['scope_label'] = 'Class'

        # Standalone mode flag
        ctx['standalone'] = level is None
        return ctx

    def get(self, request, level_number=None):
        level = get_object_or_404(Level, level_number=level_number) if level_number else None
        return render(request, 'teacher/question_form.html', self._build_context(request, level))

    def post(self, request, level_number=None):
        from maths.models import Question as MathsQuestion, Answer as MathsAnswer

        # Resolve level — from URL or from form POST
        if level_number:
            level = get_object_or_404(Level, level_number=level_number)
        else:
            level_num = request.POST.get('level')
            if not level_num:
                messages.error(request, 'Please select a year level.')
                return render(request, 'teacher/question_form.html',
                              self._build_context(request))
            level = get_object_or_404(Level, level_number=int(level_num))

        classroom_topic = get_object_or_404(Topic, id=request.POST.get('topic'))
        school_id, dept_id, classroom_ids = _get_question_scope(request.user)

        # For teachers, get the selected classroom
        selected_classroom_id = None
        if request.user.is_any_teacher and not (
            request.user.has_role(Role.HEAD_OF_INSTITUTE)
            or request.user.has_role(Role.INSTITUTE_OWNER)
            or request.user.has_role(Role.HEAD_OF_DEPARTMENT)
        ):
            selected_classroom_id = request.POST.get('classroom')
            if not selected_classroom_id or int(selected_classroom_id) not in classroom_ids:
                messages.error(request, 'Please select a valid classroom.')
                return render(request, 'teacher/question_form.html',
                              self._build_context(request, level))
            selected_classroom_id = int(selected_classroom_id)

        # Auto-link topic to level
        if not classroom_topic.levels.filter(pk=level.pk).exists():
            classroom_topic.levels.add(level)
        if classroom_topic.parent and not classroom_topic.parent.levels.filter(pk=level.pk).exists():
            classroom_topic.parent.levels.add(level)

        with transaction.atomic():
            question = MathsQuestion.objects.create(
                topic=classroom_topic, level=level,
                school_id=school_id,
                department_id=dept_id,
                classroom_id=selected_classroom_id,
                question_text=request.POST.get('question_text', '').strip(),
                question_type=request.POST.get('question_type', MathsQuestion.MULTIPLE_CHOICE),
                difficulty=int(request.POST.get('difficulty', 1)),
                points=int(request.POST.get('points', 1)),
                explanation=request.POST.get('explanation', ''),
                image=request.FILES.get('image'),
                video=request.FILES.get('video'),
            )
            # Dynamic answers — support up to 20
            for i in range(1, 21):
                text = request.POST.get(f'answer_text_{i}', '').strip()
                answer_image = request.FILES.get(f'answer_image_{i}')
                if text or answer_image:
                    MathsAnswer.objects.create(
                        question=question, answer_text=text,
                        answer_image=answer_image,
                        is_correct=request.POST.get(f'answer_correct_{i}') == 'true',
                        order=int(request.POST.get(f'answer_order_{i}', i)),
                    )
        log_event(
            user=request.user,
            school=School.objects.filter(id=school_id).first() if school_id else None,
            category='data_change',
            action='question_created',
            detail={'question_id': question.id, 'level_number': level.level_number},
            request=request,
        )
        messages.success(request, 'Question added.')
        return redirect('question_list', level_number=level.level_number)


class EditQuestionView(RoleRequiredMixin, View):
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def get(self, request, question_id):
        from maths.models import Question as MathsQuestion
        question = get_object_or_404(MathsQuestion, id=question_id)
        if not _can_edit_question(request.user, question):
            messages.error(request, 'You do not have permission to edit this question.')
            return redirect('question_list', level_number=question.level.level_number)
        answers = list(question.answers.order_by('order', 'id'))
        # Pad to 4 answers for the template
        answer_data = []
        for i in range(4):
            if i < len(answers):
                answer_data.append({
                    'text': answers[i].answer_text,
                    'is_correct': answers[i].is_correct,
                })
            else:
                answer_data.append({'text': '', 'is_correct': False})
        return render(request, 'teacher/question_form.html', {
            'question': question, 'level': question.level,
            'topics': Topic.objects.filter(is_active=True).order_by('name'),
            'question_types': MathsQuestion.QUESTION_TYPES,
            'difficulty_choices': MathsQuestion.DIFFICULTY_CHOICES,
            'is_global': question.school is None,
            'answer_data': answer_data,
        })

    def post(self, request, question_id):
        from maths.models import Question as MathsQuestion, Answer as MathsAnswer
        question = get_object_or_404(MathsQuestion, id=question_id)
        if not _can_edit_question(request.user, question):
            messages.error(request, 'You do not have permission to edit this question.')
            return redirect('question_list', level_number=question.level.level_number)
        classroom_topic = get_object_or_404(Topic, id=request.POST.get('topic'))
        question.topic = classroom_topic
        question.question_text = request.POST.get('question_text', '').strip()
        question.question_type = request.POST.get('question_type', MathsQuestion.MULTIPLE_CHOICE)
        question.difficulty = int(request.POST.get('difficulty', 1))
        question.points = int(request.POST.get('points', 1))
        question.explanation = request.POST.get('explanation', '')
        if request.FILES.get('image'): question.image = request.FILES['image']
        with transaction.atomic():
            question.save()
            question.answers.all().delete()
            for i in range(1, 5):
                text = request.POST.get(f'answer_text_{i}', '').strip()
                if text:
                    MathsAnswer.objects.create(
                        question=question, answer_text=text,
                        is_correct=request.POST.get(f'answer_correct_{i}') == 'true',
                        order=int(request.POST.get(f'answer_order_{i}', i)),
                    )
        log_event(
            user=request.user,
            school=question.school,
            category='data_change',
            action='question_edited',
            detail={'question_id': question.id, 'level_number': question.level.level_number},
            request=request,
        )
        messages.success(request, 'Question updated.')
        return redirect('question_list', level_number=question.level.level_number)


class DeleteQuestionView(RoleRequiredMixin, View):
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def post(self, request, question_id):
        from maths.models import Question as MathsQuestion
        question = get_object_or_404(MathsQuestion, id=question_id)
        if not _can_edit_question(request.user, question):
            messages.error(request, 'You do not have permission to delete this question.')
            return redirect('question_list', level_number=question.level.level_number)
        level_number = question.level.level_number
        q_id = question.id
        q_school = question.school
        question.delete()
        log_event(
            user=request.user,
            school=q_school,
            category='data_change',
            action='question_deleted',
            detail={'question_id': q_id, 'level_number': level_number},
            request=request,
        )
        messages.success(request, 'Question deleted.')
        return redirect('question_list', level_number=level_number)


class HoDOverviewView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def _is_hod_only(self, user):
        """Check if user is HoD but not HoI/Owner (department-scoped access)."""
        return (
            user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not user.has_role(Role.HEAD_OF_INSTITUTE)
            and not user.has_role(Role.INSTITUTE_OWNER)
        )

    def get(self, request):
        is_hod_only = self._is_hod_only(request.user)

        from django.db.models import Count, Q
        from django.utils import timezone
        from datetime import timedelta
        from collections import defaultdict

        # ── Next classes: check if user also teaches ──
        # Use the first school's timezone for "today" if available
        _first_school = School.objects.filter(
            id__in=_get_user_school_ids(request.user)
        ).first()
        today = _first_school.get_local_date() if _first_school else timezone.localdate()
        week_ahead = today + timedelta(days=7)

        my_teaching_classes = ClassRoom.objects.filter(
            class_teachers__teacher=request.user,
            is_active=True,
        ).select_related('department', 'subject').prefetch_related('students', 'teachers').annotate(
            student_count=Count('class_students', filter=Q(class_students__is_active=True), distinct=True),
            teacher_count=Count('teachers', distinct=True),
        )

        if my_teaching_classes.exists():
            is_teacher_too = True
            next_classes_scope = my_teaching_classes
            next_classes_label = 'My Next Classes'
        else:
            is_teacher_too = False
            next_classes_label = 'Upcoming Classes'
            next_classes_scope = None  # set after HoD/HoI branch

        if is_hod_only:
            from django.db.models import Q
            # HoD: scope to headed departments + classes they teach
            headed_departments = Department.objects.filter(head=request.user, is_active=True)
            headed_dept_ids = list(headed_departments.values_list('id', flat=True))
            teaching_dept_ids = list(ClassRoom.objects.filter(
                teachers=request.user, is_active=True, department__isnull=False,
            ).values_list('department_id', flat=True).distinct())
            all_dept_ids = list(set(headed_dept_ids) | set(teaching_dept_ids))
            departments = Department.objects.filter(id__in=all_dept_ids, is_active=True)
            teaching_class_ids = list(ClassRoom.objects.filter(
                teachers=request.user, is_active=True,
            ).values_list('id', flat=True))
            classes = ClassRoom.objects.filter(
                Q(department_id__in=headed_dept_ids) | Q(id__in=teaching_class_ids),
                is_active=True,
            ).distinct().select_related('department', 'subject').prefetch_related('teachers', 'students').annotate(
                student_count=Count('class_students', filter=Q(class_students__is_active=True), distinct=True),
                teacher_count=Count('teachers', distinct=True),
            )
            my_school_ids = list(departments.values_list('school_id', flat=True).distinct())
            teachers = CustomUser.objects.filter(
                Q(department_memberships__department_id__in=all_dept_ids)
                | Q(class_teacher_entries__classroom_id__in=teaching_class_ids),
            ).distinct()
            teacher_attendance_qs = TeacherAttendance.objects.filter(
                Q(session__classroom__department_id__in=headed_dept_ids)
                | Q(session__classroom_id__in=teaching_class_ids),
            )
            school_data = []
            for dept in departments:
                dept_classes = [c for c in classes if c.department_id == dept.id]
                school_data.append({
                    'department': dept,
                    'school': dept.school,
                    'teacher_count': dept.department_teachers.count(),
                    'student_count': sum(c.student_count for c in dept_classes),
                    'class_count': len(dept_classes),
                })
        else:
            # HoI/Owner: scope to their schools
            departments = None
            my_schools = School.objects.filter(id__in=_get_user_school_ids(request.user))
            my_school_ids = list(my_schools.values_list('id', flat=True))
            school_data = []
            for s in my_schools:
                teacher_count = SchoolTeacher.objects.filter(school=s, is_active=True).count()
                student_count = ClassRoom.objects.filter(
                    school=s, is_active=True
                ).values_list('students', flat=True).distinct().count()
                dept_count = Department.objects.filter(school=s, is_active=True).count()
                class_count = ClassRoom.objects.filter(school=s, is_active=True).count()
                school_data.append({
                    'school': s,
                    'teacher_count': teacher_count,
                    'student_count': student_count,
                    'department_count': dept_count,
                    'class_count': class_count,
                })
            classes = ClassRoom.objects.filter(
                school_id__in=my_school_ids, is_active=True
            ).select_related('department', 'subject').prefetch_related('teachers', 'students').annotate(
                student_count=Count('class_students', filter=Q(class_students__is_active=True), distinct=True),
                teacher_count=Count('teachers', distinct=True),
            )
            teachers = CustomUser.objects.filter(
                school_memberships__school_id__in=my_school_ids,
                school_memberships__is_active=True,
            ).distinct()
            teacher_attendance_qs = TeacherAttendance.objects.filter(
                session__classroom__school_id__in=my_school_ids,
            )

        total_sessions = teacher_attendance_qs.count()
        present_count = teacher_attendance_qs.filter(status='present').count()
        total_students = ClassStudent.objects.filter(
            classroom__school_id__in=my_school_ids,
            classroom__is_active=True,
            is_active=True,
        ).values('student').distinct().count()

        # For HoD dashboard stats: count across ALL classes they teach + head
        if is_hod_only and my_teaching_classes.exists():
            from django.db.models import Q
            headed_dept_ids = set(Department.objects.filter(
                head=request.user, is_active=True
            ).values_list('id', flat=True))
            all_my_classes = ClassRoom.objects.filter(
                Q(department_id__in=headed_dept_ids) | Q(teachers=request.user),
                is_active=True,
            ).distinct()
            my_classes_count = all_my_classes.count()
            my_students_count = all_my_classes.values_list('students', flat=True).distinct().count()
        else:
            my_classes_count = len(classes) if hasattr(classes, '__len__') else classes.count()
            my_students_count = total_students

        # Pending enrollment requests
        pending_enrollment_count = Enrollment.objects.filter(
            classroom__in=classes, status='pending'
        ).count()

        # Alert data: classes needing attention
        classes_list = list(classes)  # evaluate once for reuse
        classes_no_students = [c for c in classes_list if c.student_count == 0]
        classes_no_teachers = [c for c in classes_list if c.teacher_count == 0]

        # Group classes by department (HoI) or subject (HoD)
        classes_grouped = defaultdict(list)
        if is_hod_only:
            for c in classes_list:
                key = c.subject.name if c.subject else 'No Subject'
                classes_grouped[key].append(c)
            group_label = 'Subject'
        else:
            for c in classes_list:
                key = c.department.name if c.department else 'Unassigned'
                classes_grouped[key].append(c)
            group_label = 'Department'
        classes_grouped = dict(sorted(classes_grouped.items()))

        # ── Next classes: HoI/Owner always sees upcoming school classes ──
        # If the user doesn't personally teach but owns/manages a school,
        # show all upcoming classes for that school instead.
        if next_classes_scope is None and not is_hod_only:
            next_classes_scope = classes
            is_teacher_too = True  # enable the upcoming-classes display block

        upcoming_sessions = []
        next_classes_from_schedule = []

        if is_teacher_too:
            upcoming_sessions = list(ClassSession.objects.filter(
                classroom__in=next_classes_scope,
                date__gte=today,
                date__lte=week_ahead,
                status='scheduled',
            ).select_related(
                'classroom', 'classroom__department', 'classroom__subject',
            ).prefetch_related(
                'classroom__teachers', 'classroom__students',
            ).order_by('date', 'start_time')[:5])

            # Fallback: derive from ClassRoom.day if no sessions exist
            if not upcoming_sessions:
                DAY_MAP = {
                    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                    'friday': 4, 'saturday': 5, 'sunday': 6,
                }
                today_idx = today.weekday()
                now_time = (_first_school.get_local_now() if _first_school else timezone.localtime()).time()

                def _days_until(day_str, start_time=None):
                    target = DAY_MAP.get(day_str, 7)
                    diff = (target - today_idx) % 7
                    if diff == 0:
                        if start_time and start_time > now_time:
                            return 0
                        return 7
                    return diff

                scheduled = sorted(
                    [c for c in next_classes_scope if c.day],
                    key=lambda c: (_days_until(c.day, c.start_time), c.start_time or timezone.datetime.min.time()),
                )
                for c in scheduled[:5]:
                    du = _days_until(c.day, c.start_time)
                    c.next_date = today + timedelta(days=du)
                next_classes_from_schedule = scheduled[:5]

        # ── Report widgets data ────────────────────────────────────
        import json
        from decimal import Decimal
        from django.db.models import Sum, F, DecimalField
        from django.db.models.functions import Coalesce

        now = timezone.now()
        current_month_start = today.replace(day=1)
        if today.month == 12:
            next_month_start = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month_start = today.replace(month=today.month + 1, day=1)

        # ── 1. Monthly Statistics (current month) ─────────────────
        # Active students this month (students in active classes)
        monthly_active_students = total_students

        # Active teachers this month
        monthly_active_teachers = teachers.count()

        # Invoice totals for current month (non-cancelled, scoped to schools)
        month_invoices = Invoice.objects.filter(
            school_id__in=my_school_ids,
            billing_period_start__lt=next_month_start,
            billing_period_end__gte=current_month_start,
        ).exclude(status='cancelled')
        monthly_invoice_total = month_invoices.aggregate(
            total=Coalesce(Sum('amount'), Decimal('0.00'))
        )['total']

        # Student lessons (sessions) this month
        month_sessions_qs = ClassSession.objects.filter(
            classroom__in=classes,
            date__gte=current_month_start,
            date__lt=next_month_start,
            status__in=['completed', 'scheduled'],
        )
        monthly_lesson_count = month_sessions_qs.count()

        # Student hours this month (sum of session durations)
        from django.db.models import ExpressionWrapper, DurationField
        month_completed = month_sessions_qs.filter(status='completed')
        total_minutes = 0
        for s in month_completed.only('start_time', 'end_time'):
            from datetime import datetime as dt
            start = dt.combine(today, s.start_time)
            end = dt.combine(today, s.end_time)
            total_minutes += max((end - start).total_seconds() / 60, 0)
        monthly_student_hours = round(total_minutes / 60, 1)

        # Payments received this month
        monthly_payments = InvoicePayment.objects.filter(
            school_id__in=my_school_ids,
            payment_date__gte=current_month_start,
            payment_date__lt=next_month_start,
            status='confirmed',
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0.00')))['total']

        # ── 2. Revenue by Service (current month) ─────────────────
        revenue_by_class = (
            InvoiceLineItem.objects.filter(
                invoice__school_id__in=my_school_ids,
                invoice__billing_period_start__lt=next_month_start,
                invoice__billing_period_end__gte=current_month_start,
            )
            .exclude(invoice__status='cancelled')
            .values('classroom__name')
            .annotate(total=Sum('line_amount'))
            .order_by('-total')
        )
        revenue_labels = []
        revenue_data = []
        revenue_table = []
        for row in revenue_by_class:
            name = row['classroom__name'] or 'Unknown'
            amount = row['total'] or Decimal('0')
            revenue_labels.append(name)
            revenue_data.append(float(amount))
            revenue_table.append({'name': name, 'amount': amount})
        revenue_total = sum(revenue_data)

        # ── 3. Lesson Profit Snapshot (Jan → current month) ───────
        profit_snapshot = []
        for m in range(1, today.month + 1):
            m_start = today.replace(month=m, day=1)
            if m == 12:
                m_end = today.replace(year=today.year + 1, month=1, day=1)
            else:
                m_end = today.replace(month=m + 1, day=1)

            # Revenue: sum of invoice line items for this month
            m_revenue = (
                InvoiceLineItem.objects.filter(
                    invoice__school_id__in=my_school_ids,
                    invoice__billing_period_start__lt=m_end,
                    invoice__billing_period_end__gte=m_start,
                )
                .exclude(invoice__status='cancelled')
                .aggregate(total=Coalesce(Sum('line_amount'), Decimal('0.00')))['total']
            )

            # Wages: sum of salary slip line items for this month
            m_wages = (
                SalarySlipLineItem.objects.filter(
                    salary_slip__school_id__in=my_school_ids,
                    salary_slip__billing_period_start__lt=m_end,
                    salary_slip__billing_period_end__gte=m_start,
                )
                .exclude(salary_slip__status='cancelled')
                .aggregate(total=Coalesce(Sum('line_amount'), Decimal('0.00')))['total']
            )

            # Hours & count from salary slip line items
            m_salary_agg = (
                SalarySlipLineItem.objects.filter(
                    salary_slip__school_id__in=my_school_ids,
                    salary_slip__billing_period_start__lt=m_end,
                    salary_slip__billing_period_end__gte=m_start,
                )
                .exclude(salary_slip__status='cancelled')
                .aggregate(
                    hours=Coalesce(Sum('total_hours'), Decimal('0.00')),
                    count=Coalesce(Sum('sessions_taught'), 0),
                )
            )

            m_profit = m_revenue - m_wages
            profit_snapshot.append({
                'month': m_start.strftime('%b'),
                'revenue': m_revenue,
                'wages': m_wages,
                'profit': m_profit,
                'hours': m_salary_agg['hours'],
                'count': m_salary_agg['count'],
            })

        # ── 4 & 5. Upcoming birthdays (next 7 days) ──────────────
        birthday_end = today + timedelta(days=7)

        def _birthday_in_range(qs, start, end):
            """Filter users whose birthday falls within a date range (handles year wrap)."""
            results = []
            for user in qs.exclude(date_of_birth__isnull=True):
                dob = user.date_of_birth
                try:
                    this_year_bday = dob.replace(year=start.year)
                except ValueError:
                    # Feb 29 in a non-leap year
                    this_year_bday = dob.replace(year=start.year, month=3, day=1)
                try:
                    next_year_bday = dob.replace(year=start.year + 1)
                except ValueError:
                    next_year_bday = dob.replace(year=start.year + 1, month=3, day=1)
                if start <= this_year_bday <= end:
                    user.upcoming_birthday = this_year_bday
                    user.turning_age = this_year_bday.year - dob.year
                    results.append(user)
                elif start <= next_year_bday <= end:
                    user.upcoming_birthday = next_year_bday
                    user.turning_age = next_year_bday.year - dob.year
                    results.append(user)
            return sorted(results, key=lambda u: u.upcoming_birthday)

        # Students with upcoming birthdays
        all_student_ids = (
            ClassStudent.objects.filter(classroom__in=classes)
            .values_list('student_id', flat=True).distinct()
        )
        student_birthday_qs = CustomUser.objects.filter(id__in=all_student_ids)
        student_birthdays = _birthday_in_range(student_birthday_qs, today, birthday_end)

        # Teachers/employees with upcoming birthdays
        teacher_birthdays = _birthday_in_range(teachers, today, birthday_end)

        # ── Subscription usage (for HoI/Owner) ──
        subscription_usage = None
        if not is_hod_only and my_school_ids:
            from billing.entitlements import get_school_subscription, check_class_limit, check_student_limit, check_invoice_limit
            primary_school = School.objects.filter(id__in=my_school_ids).first()
            if primary_school:
                sub = get_school_subscription(primary_school)
                if sub and sub.plan:
                    _, curr_classes, class_limit = check_class_limit(primary_school)
                    _, curr_students, student_limit = check_student_limit(primary_school)
                    _, inv_used, inv_limit, overage_rate = check_invoice_limit(primary_school)
                    subscription_usage = {
                        'plan': sub.plan,
                        'status': sub.get_status_display(),
                        'trial_days': sub.trial_days_remaining,
                        'classes': curr_classes, 'class_limit': class_limit,
                        'students': curr_students, 'student_limit': student_limit,
                        'invoices': inv_used, 'invoice_limit': inv_limit,
                        'overage_rate': overage_rate,
                    }

        is_hoi = not is_hod_only

        # ── My Earnings (for teachers / HoDs) ──────────────────────
        my_earnings = None
        user_slips = SalarySlip.objects.filter(
            teacher=request.user,
            school_id__in=my_school_ids,
        ).exclude(status='cancelled')

        if user_slips.exists():
            # Current month slip
            current_slip = user_slips.filter(
                billing_period_start__lt=next_month_start,
                billing_period_end__gte=current_month_start,
            ).first()

            current_month_earned = Decimal('0.00')
            current_month_sessions = 0
            current_month_hours = Decimal('0.00')
            current_month_status = None
            current_month_paid = Decimal('0.00')
            current_month_due = Decimal('0.00')

            if current_slip:
                current_month_earned = current_slip.amount or Decimal('0.00')
                agg = current_slip.line_items.aggregate(
                    sessions=Coalesce(Sum('sessions_taught'), 0),
                    hours=Coalesce(Sum('total_hours'), Decimal('0.00')),
                )
                current_month_sessions = agg['sessions']
                current_month_hours = agg['hours']
                current_month_status = current_slip.get_status_display()
                current_month_paid = current_slip.amount_paid
                current_month_due = current_slip.amount_due

            # YTD total
            year_start = today.replace(month=1, day=1)
            ytd_earned = user_slips.filter(
                billing_period_start__gte=year_start,
            ).aggregate(total=Coalesce(Sum('amount'), Decimal('0.00')))['total']

            # Monthly trend (Jan → current month)
            earnings_trend = []
            for m in range(1, today.month + 1):
                m_start = today.replace(month=m, day=1)
                if m == 12:
                    m_end = today.replace(year=today.year + 1, month=1, day=1)
                else:
                    m_end = today.replace(month=m + 1, day=1)
                m_slip = user_slips.filter(
                    billing_period_start__lt=m_end,
                    billing_period_end__gte=m_start,
                ).first()
                if m_slip:
                    m_agg = m_slip.line_items.aggregate(
                        sessions=Coalesce(Sum('sessions_taught'), 0),
                        hours=Coalesce(Sum('total_hours'), Decimal('0.00')),
                    )
                    earnings_trend.append({
                        'month': m_start.strftime('%b'),
                        'earned': m_slip.amount or Decimal('0.00'),
                        'sessions': m_agg['sessions'],
                        'hours': m_agg['hours'],
                        'status': m_slip.get_status_display(),
                    })
                else:
                    earnings_trend.append({
                        'month': m_start.strftime('%b'),
                        'earned': Decimal('0.00'),
                        'sessions': 0,
                        'hours': Decimal('0.00'),
                        'status': '-',
                    })

            my_earnings = {
                'current_month_earned': current_month_earned,
                'current_month_sessions': current_month_sessions,
                'current_month_hours': current_month_hours,
                'current_month_status': current_month_status,
                'current_month_paid': current_month_paid,
                'current_month_due': current_month_due,
                'ytd_earned': ytd_earned,
                'trend': earnings_trend,
            }

        # ── Next Term Alert ───────────────────────────────────────────
        next_term_alert = False
        current_term = None
        school = None  # for the alert link — use first accessible school
        if not is_hod_only and my_school_ids:
            from .models import Term
            school = School.objects.filter(id__in=my_school_ids).first()
            current_term = Term.objects.filter(
                school_id__in=my_school_ids,
                start_date__lte=today,
                end_date__gte=today,
            ).order_by('order').first()
            if current_term:
                days_left = (current_term.end_date - today).days
                if days_left <= 30:
                    has_next = Term.objects.filter(
                        school_id__in=my_school_ids,
                        start_date__gt=current_term.end_date,
                    ).exists()
                    if not has_next:
                        next_term_alert = True

        return render(request, 'hod/overview.html', {
            'is_hoi': is_hoi,
            'school_data': school_data,
            'classes': classes_list,
            'teachers': teachers,
            'total_students': total_students,
            'my_classes_count': my_classes_count,
            'my_students_count': my_students_count,
            'total_sessions': total_sessions,
            'present_count': present_count,
            'is_hod_only': is_hod_only,
            'departments': departments,
            'pending_enrollment_count': pending_enrollment_count,
            'classes_no_students': classes_no_students,
            'classes_no_teachers': classes_no_teachers,
            'next_term_alert': next_term_alert,
            'current_term': current_term,
            'school': school,
            'classes_grouped': classes_grouped,
            'group_label': group_label,
            'upcoming_sessions': upcoming_sessions,
            'next_classes_from_schedule': next_classes_from_schedule,
            'next_classes_label': next_classes_label,
            'is_teacher_too': is_teacher_too,
            'today': today,
            # Report widgets
            'monthly_active_students': monthly_active_students,
            'monthly_active_teachers': monthly_active_teachers,
            'monthly_invoice_total': monthly_invoice_total,
            'monthly_lesson_count': monthly_lesson_count,
            'monthly_student_hours': monthly_student_hours,
            'monthly_payments': monthly_payments,
            'revenue_table': revenue_table,
            'revenue_labels_json': json.dumps(revenue_labels),
            'revenue_data_json': json.dumps(revenue_data),
            'revenue_total': revenue_total,
            'profit_snapshot': profit_snapshot,
            'student_birthdays': student_birthdays,
            'teacher_birthdays': teacher_birthdays,
            'current_month_name': now.strftime('%B %Y'),
            'subscription_usage': subscription_usage,
            'my_earnings': my_earnings,
        })


class HoDManageClassesView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        is_hod_only = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not request.user.has_role(Role.HEAD_OF_INSTITUTE)
            and not request.user.has_role(Role.INSTITUTE_OWNER)
        )

        if is_hod_only:
            # HoD sees departments they head + departments of classes they teach
            headed_depts = Department.objects.filter(head=request.user, is_active=True)
            teaching_dept_ids = ClassRoom.objects.filter(
                teachers=request.user, is_active=True, department__isnull=False,
            ).values_list('department_id', flat=True).distinct()
            all_dept_ids = set(headed_depts.values_list('id', flat=True)) | set(teaching_dept_ids)
            departments = Department.objects.filter(id__in=all_dept_ids, is_active=True)
            dept_ids = list(all_dept_ids)
            school_ids = list(departments.values_list('school_id', flat=True).distinct())
        else:
            school_ids = _get_user_school_ids(request.user)
            departments = Department.objects.filter(school_id__in=school_ids, is_active=True)
            dept_ids = list(departments.values_list('id', flat=True))

        # Department filter from query param
        selected_dept_id = request.GET.get('department')
        if selected_dept_id:
            try:
                selected_dept_id = int(selected_dept_id)
                if selected_dept_id in dept_ids:
                    filter_dept_ids = [selected_dept_id]
                else:
                    filter_dept_ids = dept_ids
            except (ValueError, TypeError):
                filter_dept_ids = dept_ids
                selected_dept_id = None
        else:
            filter_dept_ids = dept_ids
            selected_dept_id = None

        if is_hod_only:
            from django.db.models import Q
            headed_dept_ids = set(headed_depts.values_list('id', flat=True))
            # For headed departments: show ALL classes
            # For other departments: show only classes they teach
            classes = ClassRoom.objects.filter(
                Q(department_id__in=[d for d in filter_dept_ids if d in headed_dept_ids])
                | Q(department_id__in=[d for d in filter_dept_ids if d not in headed_dept_ids], teachers=request.user),
                is_active=True,
            ).distinct().select_related('department').prefetch_related('teachers')
            teachers = CustomUser.objects.filter(
                department_memberships__department_id__in=filter_dept_ids,
            ).distinct()
        else:
            if selected_dept_id:
                classes = ClassRoom.objects.filter(
                    department_id=selected_dept_id, is_active=True
                ).select_related('department').prefetch_related('teachers')
            else:
                classes = ClassRoom.objects.filter(
                    school_id__in=school_ids, is_active=True
                ).select_related('department').prefetch_related('teachers')
            teachers = CustomUser.objects.filter(
                school_memberships__school_id__in=school_ids,
                school_memberships__is_active=True,
            ).distinct()

        # Unassigned classes in the same school(s)
        unassigned_classes = ClassRoom.objects.filter(
            school_id__in=school_ids, is_active=True, department__isnull=True,
        ).prefetch_related('teachers')

        # Build specialty map for all teachers across these schools
        specialty_map = {}
        for st in SchoolTeacher.objects.filter(school_id__in=school_ids, is_active=True):
            specialty_map[st.teacher_id] = st.specialty

        paginator = Paginator(classes, 25)
        page = paginator.get_page(request.GET.get('page'))

        # Deleted classes (HoI only can see and restore)
        deleted_classes = []
        if not is_hod_only:
            deleted_classes = ClassRoom.objects.filter(
                school_id__in=school_ids, is_active=False,
            ).select_related('department').order_by('name')

        return render(request, 'hod/manage_classes.html', {
            'classes': classes,
            'page': page,
            'teachers': teachers,
            'is_hod_only': is_hod_only,
            'departments': departments,
            'selected_dept_id': selected_dept_id,
            'unassigned_classes': unassigned_classes,
            'specialty_map': specialty_map,
            'deleted_classes': deleted_classes,
        })


class HoDDeleteClassView(RoleRequiredMixin, View):
    """Soft-delete a class (set is_active=False)."""
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def post(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, id=class_id)
        classroom.is_active = False
        classroom.save(update_fields=['is_active'])
        log_event(
            user=request.user, school=classroom.school, category='data_change',
            action='hod_class_deleted',
            detail={'class_id': classroom.id, 'class_name': classroom.name},
            request=request,
        )
        messages.success(request, f'Class "{classroom.name}" has been deleted.')
        return redirect('hod_manage_classes')


class HoDRestoreClassView(RoleRequiredMixin, View):
    """Restore a soft-deleted class (HoI only)."""
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, id=class_id, is_active=False)
        classroom.is_active = True
        classroom.save(update_fields=['is_active'])
        log_event(
            user=request.user, school=classroom.school, category='data_change',
            action='hod_class_restored',
            detail={'class_id': classroom.id, 'class_name': classroom.name},
            request=request,
        )
        messages.success(request, f'Class "{classroom.name}" has been restored.')
        return redirect('hod_manage_classes')


class HoDWorkloadView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        is_hod_only = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not request.user.has_role(Role.HEAD_OF_INSTITUTE)
            and not request.user.has_role(Role.INSTITUTE_OWNER)
        )

        if is_hod_only:
            from django.db.models import Q
            headed_dept_ids = list(
                Department.objects.filter(head=request.user, is_active=True).values_list('id', flat=True)
            )
            teaching_class_ids = list(ClassRoom.objects.filter(
                teachers=request.user, is_active=True,
            ).values_list('id', flat=True))
            # Teachers from headed depts + co-teachers in classes HoD teaches
            teacher_ids = list(
                CustomUser.objects.filter(
                    Q(department_memberships__department_id__in=headed_dept_ids)
                    | Q(class_teacher_entries__classroom_id__in=teaching_class_ids),
                ).values_list('id', flat=True).distinct()
            )
            memberships = SchoolTeacher.objects.filter(
                teacher_id__in=teacher_ids, is_active=True,
            ).select_related('teacher')
            teachers = CustomUser.objects.filter(id__in=teacher_ids)
        else:
            my_school_ids = _get_user_school_ids(request.user)
            memberships = SchoolTeacher.objects.filter(
                school_id__in=my_school_ids, is_active=True,
            ).select_related('teacher')
            teachers = CustomUser.objects.filter(
                school_memberships__school_id__in=my_school_ids,
                school_memberships__is_active=True,
            ).distinct()

        senior_teachers = memberships.filter(role='senior_teacher')
        junior_teachers = memberships.filter(role='junior_teacher')

        return render(request, 'hod/workload.html', {
            'teachers': teachers,
            'senior_teachers': senior_teachers,
            'junior_teachers': junior_teachers,
            'is_hod_only': is_hod_only,
        })


class HoDReportsView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        is_hod_only = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not request.user.has_role(Role.HEAD_OF_INSTITUTE)
            and not request.user.has_role(Role.INSTITUTE_OWNER)
        )
        departments = None
        if is_hod_only:
            from django.db.models import Q
            headed_dept_ids = list(Department.objects.filter(head=request.user, is_active=True).values_list('id', flat=True))
            teaching_dept_ids = list(ClassRoom.objects.filter(
                teachers=request.user, is_active=True, department__isnull=False,
            ).values_list('department_id', flat=True).distinct())
            all_dept_ids = set(headed_dept_ids) | set(teaching_dept_ids)
            departments = Department.objects.filter(id__in=all_dept_ids, is_active=True)

        return render(request, 'hod/reports.html', {
            'levels': Level.objects.filter(level_number__lte=8),
            'topics': Topic.objects.filter(is_active=True, parent__isnull=True),
            'attendance_report_url': 'hod_attendance_report',
            'is_hod_only': is_hod_only,
            'departments': departments,
        })


class HoDAttendanceReportView(RoleRequiredMixin, ModuleRequiredMixin, View):
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        from django.db.models import Count, Q

        is_hod_only = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not request.user.has_role(Role.HEAD_OF_INSTITUTE)
            and not request.user.has_role(Role.INSTITUTE_OWNER)
        )

        if is_hod_only:
            from django.db.models import Q
            dept_ids = list(
                Department.objects.filter(head=request.user, is_active=True).values_list('id', flat=True)
            )
            teaching_class_ids = list(
                ClassRoom.objects.filter(teachers=request.user, is_active=True).values_list('id', flat=True)
            )
            class_filter = Q(session__classroom__department_id__in=dept_ids) | Q(session__classroom_id__in=teaching_class_ids)
            teacher_att_qs = TeacherAttendance.objects.filter(class_filter)
            student_att_qs = StudentAttendance.objects.filter(class_filter)
        else:
            my_school_ids = _get_user_school_ids(request.user)
            teacher_att_qs = TeacherAttendance.objects.filter(
                session__classroom__school_id__in=my_school_ids,
            )
            student_att_qs = StudentAttendance.objects.filter(
                session__classroom__school_id__in=my_school_ids,
            )

        teacher_summary = (
            teacher_att_qs
            .values('teacher__id', 'teacher__username', 'teacher__first_name', 'teacher__last_name')
            .annotate(
                total_sessions=Count('id'),
                present_count=Count('id', filter=Q(status='present')),
                absent_count=Count('id', filter=Q(status='absent')),
            )
            .order_by('teacher__last_name', 'teacher__first_name')
        )

        # --- Student attendance summary ---
        student_summary = (
            student_att_qs
            .values('student__id', 'student__username', 'student__first_name', 'student__last_name')
            .annotate(
                total_sessions=Count('id'),
                present_count=Count('id', filter=Q(status='present')),
                absent_count=Count('id', filter=Q(status='absent')),
                late_count=Count('id', filter=Q(status='late')),
            )
            .order_by('student__last_name', 'student__first_name')
        )

        return render(request, 'hod/attendance_report.html', {
            'teacher_summary': teacher_summary,
            'student_summary': student_summary,
        })


class AttendanceDetailView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Return session-level attendance detail for a teacher or student (HTMX partial)."""
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        from django.db.models import Q

        user_type = request.GET.get('type')  # 'teacher' or 'student'
        user_id = request.GET.get('user_id')
        status_filter = request.GET.get('status', 'all')

        if user_type not in ('teacher', 'student') or not user_id:
            return HttpResponse('')

        is_hod_only = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not request.user.has_role(Role.HEAD_OF_INSTITUTE)
            and not request.user.has_role(Role.INSTITUTE_OWNER)
        )

        # Build scope filter: headed dept classes + classes HoD teaches
        if is_hod_only:
            headed_dept_ids = list(
                Department.objects.filter(head=request.user, is_active=True)
                .values_list('id', flat=True)
            )
            teaching_class_ids = list(ClassRoom.objects.filter(
                teachers=request.user, is_active=True,
            ).values_list('id', flat=True))
            scope_filter = Q(session__classroom__department_id__in=headed_dept_ids) | Q(session__classroom_id__in=teaching_class_ids)
        else:
            school_ids = list(
                _get_user_school_ids(request.user)
            )
            scope_filter = Q(session__classroom__school_id__in=school_ids)

        if user_type == 'teacher':
            qs = TeacherAttendance.objects.filter(scope_filter, teacher_id=user_id)

            if status_filter and status_filter != 'all':
                qs = qs.filter(status=status_filter)

            records = qs.select_related('session', 'session__classroom').order_by('-session__date', '-session__start_time')
        else:
            qs = StudentAttendance.objects.filter(scope_filter, student_id=user_id)


            if status_filter and status_filter != 'all':
                qs = qs.filter(status=status_filter)

            records = qs.select_related('session', 'session__classroom').order_by('-session__date', '-session__start_time')

        return render(request, 'hod/attendance_detail_partial.html', {
            'records': records,
            'user_type': user_type,
            'status_filter': status_filter,
        })


class HoDSubjectLevelsView(RoleRequiredMixin, View):
    """Allow HoD/HoI to manage subject levels for their department."""
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def _get_departments_qs(self, user):
        """Return queryset of all departments the user can access."""
        is_hod_only = (
            user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not user.has_role(Role.HEAD_OF_INSTITUTE)
            and not user.has_role(Role.INSTITUTE_OWNER)
        )
        if is_hod_only:
            return Department.objects.filter(head=user, is_active=True)
        else:
            school_ids = _get_user_school_ids(user)
            return Department.objects.filter(school_id__in=school_ids, is_active=True)

    def _get_department(self, user, dept_id=None):
        qs = self._get_departments_qs(user)
        if dept_id:
            return qs.filter(id=dept_id).first()
        return qs.order_by('name').first()

    def _get_all_departments(self, user):
        """Return all departments the user can access (for the picker)."""
        return self._get_departments_qs(user).order_by('name')

    def _next_level_number(self):
        from django.db.models import Max
        max_num = Level.objects.aggregate(m=Max('level_number'))['m'] or 0
        return max(max_num + 1, 300)

    def _get_available_subjects(self, department):
        """Return subjects available to add (global + school-created, not already assigned)."""
        from django.db.models import Q
        assigned_ids = set(
            DepartmentSubject.objects.filter(department=department)
            .values_list('subject_id', flat=True)
        )
        return Subject.objects.filter(
            Q(school__isnull=True) | Q(school=department.school),
            is_active=True,
        ).exclude(id__in=assigned_ids).order_by('order', 'name')

    def get(self, request, dept_id=None):
        department = self._get_department(request.user, dept_id)
        if not department:
            messages.error(request, 'No department found.')
            return redirect('hod_overview')

        dept_subjects = DepartmentSubject.objects.filter(
            department=department,
        ).select_related('subject').order_by('subject__name')

        dept_levels = (
            DepartmentLevel.objects.filter(department=department)
            .select_related('level', 'level__subject')
            .exclude(level__level_number__gte=100, level__level_number__lt=200)
            .order_by('order', 'level__level_number')
        )

        from .fee_utils import get_parent_fee_for_subject, get_parent_fee_for_level

        # Group levels by subject
        subject_groups = []
        for ds in dept_subjects:
            parent_fee, parent_source = get_parent_fee_for_subject(department)
            levels_for_subject = []
            for dl in dept_levels:
                if dl.level.subject_id == ds.subject_id:
                    class_count = ClassRoom.objects.filter(
                        department=department, levels=dl.level, is_active=True,
                    ).count()
                    lvl_parent_fee, lvl_parent_source = get_parent_fee_for_level(dl)
                    levels_for_subject.append({
                        'dept_level': dl, 'level': dl.level, 'class_count': class_count,
                        'parent_fee': lvl_parent_fee,
                        'parent_source': lvl_parent_source,
                    })
            subject_groups.append({
                'subject': ds.subject,
                'dept_subject': ds,
                'levels': levels_for_subject,
                'parent_fee': parent_fee,
                'parent_source': parent_source,
            })

        available_subjects = self._get_available_subjects(department)
        user_departments = self._get_all_departments(request.user)

        # Other departments in this school (for "move subject" dropdown)
        all_departments = Department.objects.filter(
            school=department.school, is_active=True,
        ).exclude(id=department.id).order_by('name')

        return render(request, 'hod/subject_levels.html', {
            'department': department,
            'dept_subjects': dept_subjects,
            'subject_groups': subject_groups,
            'available_subjects': available_subjects,
            'all_departments': all_departments,
            'user_departments': user_departments,
        })

    def _redirect_to_dept(self, department):
        """Redirect back to the subject-levels page for the given department."""
        return redirect('hod_subject_levels_dept', dept_id=department.id)

    def post(self, request, dept_id=None):
        department = self._get_department(request.user, dept_id)
        if not department:
            messages.error(request, 'No department found.')
            return redirect('hod_overview')

        action = request.POST.get('action', 'add_level')

        # ---- Add Subject action ----
        if action == 'add_subject':
            add_subject_id = request.POST.get('add_subject_id', '').strip()
            new_subject_name = request.POST.get('new_subject_name', '').strip()

            if add_subject_id:
                subj = Subject.objects.filter(id=add_subject_id, is_active=True).first()
                if subj:
                    ds, created = DepartmentSubject.objects.get_or_create(
                        department=department, subject=subj,
                        defaults={'order': DepartmentSubject.objects.filter(department=department).count()},
                    )
                    if created:
                        # Auto-map global levels
                        subj_levels = Level.objects.filter(
                            subject=subj, school__isnull=True,
                        ).exclude(level_number__gte=100, level_number__lt=200)
                        for lv in subj_levels:
                            DepartmentLevel.objects.get_or_create(
                                department=department, level=lv,
                                defaults={'order': lv.level_number},
                            )
                        log_event(
                            user=request.user, school=department.school, category='data_change',
                            action='subject_added_to_department',
                            detail={'subject': subj.name, 'department': department.name, 'department_id': department.id},
                            request=request,
                        )
                        messages.success(request, f'Subject "{subj.name}" added to {department.name}.')
                    else:
                        messages.info(request, f'Subject "{subj.name}" is already assigned.')
            elif new_subject_name:
                from django.utils.text import slugify as _slugify
                subj_slug = _slugify(new_subject_name)
                base_slug = subj_slug
                counter = 1
                while Subject.objects.filter(school=department.school, slug=subj_slug).exists():
                    subj_slug = f'{base_slug}-{counter}'
                    counter += 1
                subj = Subject.objects.create(
                    name=new_subject_name, slug=subj_slug, school=department.school, is_active=True,
                )
                DepartmentSubject.objects.create(
                    department=department, subject=subj,
                    order=DepartmentSubject.objects.filter(department=department).count(),
                )
                log_event(
                    user=request.user, school=department.school, category='data_change',
                    action='subject_created',
                    detail={'subject': new_subject_name, 'department': department.name, 'department_id': department.id},
                    request=request,
                )
                messages.success(request, f'Subject "{new_subject_name}" created and added.')
            else:
                messages.error(request, 'Select a subject or enter a new subject name.')

            return self._redirect_to_dept(department)

        # ---- Edit Subject Fee action ----
        if action == 'edit_subject_fee':
            from decimal import Decimal, InvalidOperation
            subject_id = request.POST.get('subject_id', '').strip()
            fee_str = request.POST.get('fee_override', '').strip()
            ds = DepartmentSubject.objects.filter(department=department, subject_id=subject_id).first()
            if ds:
                if fee_str:
                    try:
                        ds.fee_override = Decimal(fee_str)
                    except InvalidOperation:
                        messages.error(request, 'Invalid fee amount.')
                        return self._redirect_to_dept(department)
                else:
                    ds.fee_override = None
                ds.save(update_fields=['fee_override'])
                log_event(
                    user=request.user, school=department.school, category='data_change',
                    action='subject_fee_edited',
                    detail={'subject': ds.subject.name, 'department': department.name, 'fee_override': str(ds.fee_override)},
                    request=request,
                )
                messages.success(request, f'Fee for {ds.subject.name} updated.')
            return self._redirect_to_dept(department)

        # ---- Edit Subject action ----
        if action == 'edit_subject':
            from django.utils.text import slugify as _slugify
            subject_id = request.POST.get('subject_id', '').strip()
            new_name = request.POST.get('subject_name', '').strip()
            new_dept_id = request.POST.get('new_department_id', '').strip()

            ds = DepartmentSubject.objects.filter(department=department, subject_id=subject_id).select_related('subject').first()
            if not ds:
                messages.error(request, 'Subject not found in this department.')
                return self._redirect_to_dept(department)

            subject = ds.subject

            # Update subject name
            if new_name and new_name != subject.name:
                subject.name = new_name
                subject.slug = _slugify(new_name)
                # Ensure slug uniqueness
                base_slug = subject.slug
                counter = 1
                while Subject.objects.filter(school=subject.school, slug=subject.slug).exclude(id=subject.id).exists():
                    subject.slug = f'{base_slug}-{counter}'
                    counter += 1
                subject.save(update_fields=['name', 'slug'])

            # Move subject to a different department
            if new_dept_id and int(new_dept_id) != department.id:
                new_dept = Department.objects.filter(id=new_dept_id, school=department.school, is_active=True).first()
                if new_dept:
                    # Check the subject isn't already in the target department
                    if DepartmentSubject.objects.filter(department=new_dept, subject=subject).exists():
                        messages.error(request, f'Subject "{subject.name}" is already in {new_dept.name}.')
                    else:
                        # Move the DepartmentSubject record
                        ds.department = new_dept
                        ds.save(update_fields=['department'])

                        # Also move associated DepartmentLevel records
                        DepartmentLevel.objects.filter(
                            department=department,
                            level__subject=subject,
                        ).update(department=new_dept)

                        # Update classes under this subject to the new department
                        ClassRoom.objects.filter(
                            department=department,
                            subject=subject,
                            is_active=True,
                        ).update(department=new_dept)

                        log_event(
                            user=request.user, school=department.school, category='data_change',
                            action='subject_moved',
                            detail={'subject': subject.name, 'from_department': department.name, 'to_department': new_dept.name},
                            request=request,
                        )
                        messages.success(request, f'Subject "{subject.name}" moved to {new_dept.name}.')
                        return self._redirect_to_dept(department)
                else:
                    messages.error(request, 'Target department not found.')
                    return self._redirect_to_dept(department)

            log_event(
                user=request.user, school=department.school, category='data_change',
                action='subject_edited',
                detail={'subject': subject.name, 'subject_id': subject.id, 'department': department.name},
                request=request,
            )
            messages.success(request, f'Subject "{subject.name}" updated.')
            return self._redirect_to_dept(department)

        # ---- Edit Level action ----
        if action == 'edit_level':
            from decimal import Decimal, InvalidOperation
            level_id = request.POST.get('level_id', '').strip()
            display_name = request.POST.get('display_name', '').strip()
            description = request.POST.get('description', '').strip()
            fee_str = request.POST.get('fee_override', '').strip()
            if level_id and display_name:
                level = Level.objects.filter(id=level_id).first()
                dl = DepartmentLevel.objects.filter(department=department, level=level).first() if level else None
                if level and dl:
                    level.display_name = display_name
                    level.description = description
                    level.save()
                    # Update fee override on DepartmentLevel
                    if fee_str:
                        try:
                            dl.fee_override = Decimal(fee_str)
                        except InvalidOperation:
                            dl.fee_override = None
                    else:
                        dl.fee_override = None
                    dl.save(update_fields=['fee_override'])
                    log_event(
                        user=request.user, school=department.school, category='data_change',
                        action='level_edited',
                        detail={'level_id': level.id, 'display_name': display_name, 'department': department.name},
                        request=request,
                    )
                    messages.success(request, f'Level "{display_name}" updated.')
                else:
                    messages.error(request, 'Level not found in this department.')
            else:
                messages.error(request, 'Level name is required.')
            return self._redirect_to_dept(department)

        # ---- Add Level action (default) ----
        level_name = request.POST.get('level_name', '').strip()
        level_description = request.POST.get('level_description', '').strip()
        subject_id = request.POST.get('subject_id', '').strip()

        if not level_name:
            messages.error(request, 'Level name is required.')
            return self._redirect_to_dept(department)

        # Resolve subject
        subject = None
        if subject_id:
            subject = Subject.objects.filter(id=subject_id, is_active=True).first()

        if not subject:
            dept_subjects = DepartmentSubject.objects.filter(department=department).select_related('subject')
            if dept_subjects.exists():
                subject = dept_subjects.first().subject
            else:
                # Auto-create subject from department name
                from django.utils.text import slugify as _slugify
                subj_slug = _slugify(department.name)
                base_slug = subj_slug
                counter = 1
                while Subject.objects.filter(school=department.school, slug=subj_slug).exists():
                    subj_slug = f'{base_slug}-{counter}'
                    counter += 1
                subject = Subject.objects.create(
                    name=department.name, slug=subj_slug, school=department.school, is_active=True,
                )
                DepartmentSubject.objects.create(
                    department=department, subject=subject, order=0,
                )

        level_number = self._next_level_number()
        with transaction.atomic():
            level = Level.objects.create(
                level_number=level_number,
                display_name=level_name,
                description=level_description,
                subject=subject,
            )
            DepartmentLevel.objects.get_or_create(
                department=department, level=level,
                defaults={'order': level_number},
            )

        log_event(
            user=request.user, school=department.school, category='data_change',
            action='level_created',
            detail={'level_id': level.id, 'level_name': level_name, 'subject': subject.name, 'department': department.name},
            request=request,
        )
        messages.success(request, f'Level "{level_name}" created under {subject.name}.')
        return self._redirect_to_dept(department)


class HoDSubjectLevelRemoveView(RoleRequiredMixin, View):
    """Allow HoD to remove a level mapping."""
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def post(self, request, dept_id, level_id):
        is_hod_only = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not request.user.has_role(Role.HEAD_OF_INSTITUTE)
            and not request.user.has_role(Role.INSTITUTE_OWNER)
        )
        if is_hod_only:
            department = Department.objects.filter(head=request.user, id=dept_id, is_active=True).first()
        else:
            school_ids = _get_user_school_ids(request.user)
            department = Department.objects.filter(school_id__in=school_ids, id=dept_id, is_active=True).first()

        if department:
            DepartmentLevel.objects.filter(department=department, level_id=level_id).delete()
            log_event(
                user=request.user, school=department.school, category='data_change',
                action='level_removed',
                detail={'level_id': level_id, 'department': department.name, 'department_id': department.id},
                request=request,
            )
            messages.success(request, 'Level removed from department.')
            return redirect('hod_subject_levels_dept', dept_id=department.id)
        return redirect('hod_subject_levels')


class UpdateStudentFeeView(RoleRequiredMixin, View):
    """Inline update of per-student fee override. HoD+ only."""
    required_roles = [
        Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE,
        Role.INSTITUTE_OWNER,
        Role.ADMIN,
    ]

    def post(self, request, class_id, student_id):
        user = request.user
        # Permission: find the classroom and ensure access
        from django.db.models import Q
        if user.has_role(Role.ADMIN) or user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, is_active=True)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            classroom = ClassRoom.objects.filter(
                Q(department__head=user) | Q(teachers=user),
                id=class_id, is_active=True,
            ).distinct().first()
            if not classroom:
                raise Http404
        else:
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=user, is_active=True)

        cs = get_object_or_404(ClassStudent, classroom=classroom, student_id=student_id)
        fee_str = request.POST.get('fee_override', '').strip()
        if fee_str:
            from decimal import Decimal, InvalidOperation
            try:
                cs.fee_override = Decimal(fee_str)
            except InvalidOperation:
                messages.error(request, 'Invalid fee amount.')
                return redirect('class_detail', class_id=class_id)
        else:
            cs.fee_override = None
        cs.save(update_fields=['fee_override'])
        log_event(
            user=request.user, school=classroom.school, category='data_change',
            action='student_fee_updated',
            detail={'class_id': classroom.id, 'student_id': student_id, 'fee_override': str(cs.fee_override)},
            request=request,
        )
        messages.success(request, 'Student fee updated.')
        return redirect('class_detail', class_id=class_id)


class ClassStudentRemoveView(RoleRequiredMixin, View):
    """Soft-remove a student from a class (deactivate, preserve attendance and invoice history)."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT,
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def post(self, request, class_id, student_id):
        from django.db.models import Q
        user = request.user
        if user.has_role(Role.ADMIN) or user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            classroom = ClassRoom.objects.filter(
                Q(department__head=user) | Q(teachers=user),
                id=class_id,
            ).distinct().first()
            if not classroom:
                raise Http404
        else:
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)

        cs = ClassStudent.objects.filter(
            classroom=classroom, student_id=student_id, is_active=True,
        ).select_related('student').first()

        if cs:
            name = cs.student.get_full_name() or cs.student.username
            cs.is_active = False
            cs.save(update_fields=['is_active'])
            # Mark enrollment as removed so the student can re-request later
            Enrollment.objects.filter(
                classroom=classroom, student_id=student_id, status='approved',
            ).update(status='removed')
            log_event(
                user=request.user, school=classroom.school, category='data_change',
                action='class_student_removed',
                detail={'class_id': classroom.id, 'class_name': classroom.name, 'student_id': student_id, 'student_name': name},
                request=request,
            )
            messages.success(request, f'{name} has been removed from {classroom.name}.')
        else:
            messages.warning(request, 'Student not found in this class.')
        return redirect('class_detail', class_id=class_id)


class HoDCreateClassView(RoleRequiredMixin, View):
    """Allow HoI/HoD to create a class under a department."""
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def _get_departments(self, user):
        is_hod_only = (
            user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not user.has_role(Role.HEAD_OF_INSTITUTE)
            and not user.has_role(Role.INSTITUTE_OWNER)
        )
        if is_hod_only:
            return Department.objects.filter(head=user, is_active=True).select_related('school')
        else:
            school_ids = _get_user_school_ids(user)
            return Department.objects.filter(school_id__in=school_ids, is_active=True).select_related('school')

    def get(self, request):
        departments = self._get_departments(request.user)
        selected_dept = request.GET.get('department', '')
        return render(request, 'hod/create_class.html', {
            'departments': departments,
            'selected_dept': selected_dept,
        })

    def post(self, request):
        name = request.POST.get('name', '').strip()
        dept_id = request.POST.get('department', '').strip()
        level_ids = request.POST.getlist('levels')
        day = request.POST.get('day', '').strip()
        start_time = request.POST.get('start_time', '').strip() or None
        end_time = request.POST.get('end_time', '').strip() or None
        description = request.POST.get('description', '').strip()

        if not name:
            messages.error(request, 'Class name is required.')
            return redirect('hod_create_class')

        departments = self._get_departments(request.user)
        department = departments.filter(id=dept_id).first() if dept_id else None

        if not department:
            messages.error(request, 'Please select a valid department.')
            return redirect('hod_create_class')

        # Check class limit before creating
        from billing.entitlements import check_class_limit
        allowed, current, limit = check_class_limit(department.school)
        if not allowed:
            messages.error(
                request,
                f'Your plan allows {limit} classes. '
                f'You currently have {current}. Please upgrade your plan.',
            )
            return redirect('hod_create_class')

        # Validate levels are mapped to the department via DepartmentLevel
        from .models import DepartmentLevel
        mapped_level_ids = set(
            DepartmentLevel.objects.filter(
                department=department, level_id__in=level_ids,
            ).values_list('level_id', flat=True)
        ) if level_ids else set()
        valid_levels = Level.objects.filter(id__in=mapped_level_ids)

        # Derive subject from selected levels
        first_level = valid_levels.select_related('subject').first()
        subject = first_level.subject if first_level else department.primary_subject

        with transaction.atomic():
            classroom = ClassRoom.objects.create(
                name=name,
                school=department.school,
                department=department,
                subject=subject,
                day=day,
                start_time=start_time,
                end_time=end_time,
                description=description,
                created_by=request.user,
            )
            if valid_levels.exists():
                classroom.levels.set(valid_levels)

        log_event(
            user=request.user, school=department.school, category='data_change',
            action='hod_class_created',
            detail={'class_id': classroom.id, 'class_name': name, 'department': department.name, 'code': classroom.code},
            request=request,
        )
        messages.success(
            request,
            f'Class "{name}" created in {department.name}. Code: {classroom.code}'
        )
        return redirect('hod_manage_classes')


class HoDAssignClassView(RoleRequiredMixin, View):
    """Assign an unassigned class to a department."""
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def post(self, request):
        class_id = request.POST.get('class_id')
        dept_id = request.POST.get('department_id')

        if not class_id or not dept_id:
            messages.error(request, 'Class and department are required.')
            return redirect('hod_manage_classes')

        is_hod_only = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not request.user.has_role(Role.HEAD_OF_INSTITUTE)
            and not request.user.has_role(Role.INSTITUTE_OWNER)
        )

        if is_hod_only:
            department = get_object_or_404(
                Department, id=dept_id, head=request.user, is_active=True
            )
        else:
            school_ids = _get_user_school_ids(request.user)
            department = get_object_or_404(
                Department, id=dept_id, school_id__in=school_ids, is_active=True
            )

        classroom = get_object_or_404(
            ClassRoom, id=class_id, school=department.school,
            department__isnull=True, is_active=True,
        )

        classroom.department = department
        classroom.save(update_fields=['department'])

        log_event(
            user=request.user, school=department.school, category='data_change',
            action='hod_class_assigned',
            detail={'class_id': classroom.id, 'class_name': classroom.name, 'department': department.name},
            request=request,
        )
        messages.success(
            request,
            f'"{classroom.name}" assigned to {department.name}.'
        )
        return redirect('hod_manage_classes')


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
        log_event(
            user=request.user, school=None, category='data_change',
            action='refund_processed',
            detail={'payment_id': payment.id, 'username': payment.user.username},
            request=request,
        )
        messages.success(request, f'Refund processed for {payment.user.username}.')
        return redirect('accounting_refunds')


# ---------------------------------------------------------------------------
# Parent Dashboard Stub (replaced by full view in CPP-67)
# ---------------------------------------------------------------------------

class ParentDashboardStubView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def get(self, request):
        from .models import ParentStudent
        children = ParentStudent.objects.filter(
            parent=request.user, is_active=True,
        ).select_related('student', 'school')
        return render(request, 'parent/dashboard_stub.html', {
            'children': children,
        })


# ---------------------------------------------------------------------------
# Public Landing & Subject Hub Views
# ---------------------------------------------------------------------------

class PublicHomeView(View):
    """Public landing page. Redirects authenticated users to their dashboard."""

    def get(self, request):
        if request.user.is_authenticated:
            role = request.user.primary_role
            if role == Role.ADMIN:
                return redirect('admin_dashboard')
            if role in (Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT):
                return redirect('hod_overview')
            if role == Role.ACCOUNTANT:
                return redirect('accounting_dashboard')
            if role == Role.PARENT:
                return redirect('parent_dashboard')
            if role in (Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER):
                return redirect('teacher_dashboard')
            # Students / Individual Students → subjects hub
            return redirect('subjects_hub')
        return render(request, 'public/home.html')


# ---------------------------------------------------------------------------
# Hub helpers — question availability checks
# ---------------------------------------------------------------------------

def _subject_has_questions(subj, school=None):
    """
    Return True if maths questions exist for *subj* that students can access.

    For school students: checks both school-local (school=school) and global
    (school=None) questions — if either exists the card is clickable.
    For individual / global students: checks global questions only.

    Imported lazily to avoid circular import with the maths app.
    """
    from maths.models import Question
    from django.db.models import Q as DQ

    subject_ids = [subj.id]
    if subj.global_subject_id:
        subject_ids.append(subj.global_subject_id)

    qs = Question.objects.filter(level__subject_id__in=subject_ids)
    if school is not None:
        return qs.filter(DQ(school__isnull=True) | DQ(school=school)).exists()
    return qs.filter(school__isnull=True).exists()


def _annotate_apps_with_questions(apps):
    """
    Annotate each SubjectApp in *apps* with a ``has_questions`` bool.

    Checks for global questions (school=None) only — these are the questions
    visible to individual (non-school) students via global subject cards.
    Uses a single DB query for all apps to avoid N+1.
    """
    from maths.models import Question

    app_list = list(apps)
    subject_ids = {app.subject_id for app in app_list if app.subject_id}

    if subject_ids:
        has_q_ids = set(
            Question.objects
            .filter(level__subject_id__in=subject_ids, school__isnull=True)
            .values_list('level__subject_id', flat=True)
            .distinct()
        )
    else:
        has_q_ids = set()

    for app in app_list:
        if app.external_url:
            # Apps with an external URL (e.g. /maths/) are always shown as clickable;
            # the linked app manages its own "no content yet" state.
            app.has_questions = True
        else:
            app.has_questions = bool(app.subject_id and app.subject_id in has_q_ids)

    return app_list


class SubjectsHubView(LoginRequiredMixin, View):
    """
    Authenticated home -- shows greeting + subject cards.
    Redirects non-student roles to their role-specific dashboards.
    Students see school-based subject cards; Individual Students see
    global SubjectApp cards. Both see time stats.
    """

    def get(self, request):
        user = request.user
        active_role = request.session.get('active_role')
        if active_role and user.has_role(active_role):
            role = active_role
        else:
            role = user.primary_role

        # Redirect non-student roles to their dashboards
        if role == Role.ADMIN:
            return redirect('admin_dashboard')
        if role == Role.INSTITUTE_OWNER:
            return redirect('hod_overview')
        if role == Role.HEAD_OF_INSTITUTE:
            return redirect('hod_overview')
        if role == Role.HEAD_OF_DEPARTMENT:
            return redirect('hod_overview')
        if role == Role.ACCOUNTANT:
            return redirect('accounting_dashboard')
        if role == Role.PARENT:
            return redirect('parent_dashboard')
        if role in (Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER):
            return redirect('teacher_dashboard')

        # ----- Student / Individual Student -----

        # SubjectApp cards (only active subjects — hide "coming soon")
        subjects = SubjectApp.objects.filter(
            is_active=True,
        ).order_by('order')

        # Time-of-day greeting
        from django.utils import timezone as tz
        from django.utils.timezone import localtime
        now = tz.now()
        local_now = localtime(now)
        local_hour = local_now.hour
        if local_hour < 12:
            greeting_tod = 'Good morning'
        elif local_hour < 17:
            greeting_tod = 'Good afternoon'
        else:
            greeting_tod = 'Good evening'

        # Time stats
        from maths.views import get_or_create_time_log
        time_log = get_or_create_time_log(user)
        time_daily = _format_seconds(time_log.daily_seconds)
        time_weekly = _format_seconds(time_log.weekly_seconds)

        # ── Upcoming classes (next 5 scheduled sessions) ──
        enrolled_class_ids = list(
            ClassStudent.objects.filter(
                student=user, is_active=True,
            ).values_list('classroom_id', flat=True)
        )
        upcoming_classes = list(
            ClassSession.objects.filter(
                classroom_id__in=enrolled_class_ids,
                status='scheduled',
                date__gte=now.date(),
            ).select_related('classroom')
            .order_by('date', 'start_time')[:5]
        )

        # Fallback: if no sessions exist yet (e.g. CSV-imported classes),
        # derive upcoming dates from ClassRoom.day schedule.
        if not upcoming_classes and enrolled_class_ids:
            from types import SimpleNamespace
            from datetime import timedelta as _td
            _DAY_MAP = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2,
                'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6,
            }
            _today_idx = now.date().weekday()
            _now_time = now.time()

            def _days_until_student(day_str, start_time=None):
                target = _DAY_MAP.get(day_str, 7)
                diff = (target - _today_idx) % 7
                if diff == 0:
                    if start_time and start_time > _now_time:
                        return 0
                    return 7
                return diff

            enrolled_rooms = ClassRoom.objects.filter(
                id__in=enrolled_class_ids, is_active=True, day__isnull=False,
            ).exclude(day='')
            scheduled_rooms = sorted(
                enrolled_rooms,
                key=lambda c: (_days_until_student(c.day, c.start_time),
                               c.start_time or timezone.datetime.min.time()),
            )
            for room in scheduled_rooms[:5]:
                du = _days_until_student(room.day, room.start_time)
                pseudo = SimpleNamespace(
                    classroom=room,
                    date=now.date() + _td(days=du),
                    start_time=room.start_time,
                )
                upcoming_classes.append(pseudo)

        # ── Attendance per class ──
        class_attendance = []
        enrolled_entries = (
            ClassStudent.objects.filter(student=user, is_active=True)
            .select_related('classroom')
            .order_by('classroom__name')
        )
        for entry in enrolled_entries:
            cls = entry.classroom
            completed_count = ClassSession.objects.filter(
                classroom=cls, status='completed',
            ).count()
            if completed_count == 0:
                continue
            present_late = StudentAttendance.objects.filter(
                student=user,
                session__classroom=cls,
                session__status='completed',
                status__in=['present', 'late'],
            ).count()
            pct = round(present_late / completed_count * 100)
            class_attendance.append({
                'classroom': cls,
                'percentage': pct,
                'completed_sessions': completed_count,
            })

        # ── Billing summary ──
        billing_summary = None
        try:
            sub = user.subscription
            if sub:
                billing_summary = {
                    'plan_name': sub.package.name if sub.package else 'Free',
                    'status': sub.get_status_display() if hasattr(sub, 'get_status_display') else sub.status,
                    'is_active': sub.is_active_or_trialing,
                    'trial_days': sub.trial_days_remaining if hasattr(sub, 'trial_days_remaining') else None,
                }
        except Exception:
            pass
        # School-level billing fallback
        if not billing_summary:
            from billing.entitlements import get_school_subscription
            for ss in SchoolStudent.objects.filter(
                student=user, is_active=True,
            ).select_related('school'):
                school_sub = get_school_subscription(ss.school)
                if school_sub:
                    billing_summary = {
                        'plan_name': school_sub.plan.name if school_sub.plan else 'School Plan',
                        'status': school_sub.get_status_display() if hasattr(school_sub, 'get_status_display') else school_sub.status,
                        'is_active': school_sub.is_active_or_trialing,
                        'trial_days': school_sub.trial_days_remaining if hasattr(school_sub, 'trial_days_remaining') else None,
                    }
                    break

        # Common hub context
        hub_extra = {
            'upcoming_classes': upcoming_classes,
            'class_attendance': class_attendance,
            'billing_summary': billing_summary,
        }

        is_school_student = user.has_role(Role.STUDENT)
        schools = []
        active_source = 'global'
        active_school = None
        subject_classes = {}
        department_classes = {}
        enrolled_class_ids = set()
        pending_class_ids = set()

        # ── SCHOOL STUDENT path ──
        if is_school_student:
            school_memberships = SchoolStudent.objects.filter(
                student=user, is_active=True, school__is_active=True,
            ).select_related('school')
            schools = [ss.school for ss in school_memberships]

            if schools:
                # Enrolled class lookup: classroom_id -> classroom
                enrolled_classes = {}
                for cs in ClassStudent.objects.filter(
                    student=user, is_active=True,
                ).select_related('classroom', 'classroom__subject'):
                    enrolled_classes[cs.classroom.subject_id] = cs.classroom

                # Build per-school sections
                # Cache all active SubjectApps and global subject names once
                all_subject_apps = list(SubjectApp.objects.filter(is_active=True).order_by('order'))
                global_subject_name_map = {
                    s.id: s.name.lower()
                    for s in Subject.objects.filter(school__isnull=True, is_active=True)
                }

                def _find_subject_app(subj):
                    """Find best SubjectApp for a subject.

                    Resolution order:
                    1. SubjectApp.subject == this school subject (exact FK)
                    2. SubjectApp.subject == subj.global_subject (FK via global link)
                    3. Name-prefix fallback using global subject name (e.g. "Mathematics" ↔ "Maths")
                    4. Direct name match: subj.name == app.name (case-insensitive)
                    5. Name-prefix fallback using local subject name
                    """
                    for app in all_subject_apps:
                        if app.subject_id == subj.id:
                            return app
                    if subj.global_subject_id:
                        for app in all_subject_apps:
                            if app.subject_id == subj.global_subject_id:
                                return app
                        gs_name = global_subject_name_map.get(subj.global_subject_id, subj.name.lower())
                        if len(gs_name) >= 4:
                            prefix = gs_name[:4]
                            for app in all_subject_apps:
                                if app.name.lower()[:4] == prefix:
                                    return app
                    subj_name_lower = subj.name.lower()
                    for app in all_subject_apps:
                        if app.name.lower() == subj_name_lower:
                            return app
                    if len(subj_name_lower) >= 4:
                        prefix = subj_name_lower[:4]
                        for app in all_subject_apps:
                            if app.name.lower()[:4] == prefix:
                                return app
                    return None

                school_sections = []
                covered_app_ids = set()
                for school in schools:
                    departments = Department.objects.filter(
                        school=school, is_active=True,
                    ).prefetch_related('subjects')
                    subject_cards = []
                    for dept in departments:
                        for subj in dept.subjects.filter(is_active=True):
                            # Only show subjects the student is enrolled in
                            enrolled_cr = enrolled_classes.get(subj.id)
                            if enrolled_cr is None:
                                continue

                            matching_app = _find_subject_app(subj)
                            if matching_app:
                                covered_app_ids.add(matching_app.id)

                            # Determine link:
                            #   • matching app with external_url → link only when questions exist
                            #   • no external_url (session-based subject) → non-clickable (link=None)
                            if matching_app and matching_app.external_url:
                                link = matching_app.external_url if _subject_has_questions(subj, school) else None
                            else:
                                link = None

                            subject_cards.append({
                                'name': subj.name,
                                'description': matching_app.description if matching_app else '',
                                'icon_name': matching_app.icon_name if matching_app else '',
                                'color': matching_app.color if matching_app else '#16a34a',
                                'link': link,
                                'is_enrolled': True,
                            })

                    if subject_cards:
                        school_sections.append({
                            'school': school,
                            'subjects': subject_cards,
                        })

                # Global SubjectApps not already represented by a school subject card
                uncovered_apps = [
                    app for app in all_subject_apps
                    if app.id not in covered_app_ids and not app.is_coming_soon
                ]
                global_subjects = _annotate_apps_with_questions(uncovered_apps)

                return render(request, 'hub/home.html', {
                    'greeting_tod': greeting_tod,
                    'time_daily': time_daily,
                    'time_weekly': time_weekly,
                    'school_sections': school_sections,
                    'global_subjects': global_subjects,
                    'is_school_student': True,
                    'hide_sidebar': True,
                    **hub_extra,
                })

        # ── INDIVIDUAL STUDENT path (or school student with no schools) ──
        # Only show apps that have global questions — hide the card entirely
        # if no global questions exist for that subject.
        global_subjects = [
            app for app in _annotate_apps_with_questions(
                SubjectApp.objects.filter(
                    is_active=True, is_coming_soon=False,
                ).order_by('order')
            )
            if app.has_questions
        ]
        subjects = global_subjects

        return render(request, 'hub/home.html', {
            'hide_sidebar': True,
            'greeting_tod': greeting_tod,
            'time_daily': time_daily,
            'time_weekly': time_weekly,
            'subjects': subjects,
            'schools': schools,
            'is_school_student': is_school_student,
            'active_source': active_source,
            'active_school': active_school,
            'subject_classes': subject_classes,
            'department_classes': department_classes,
            'enrolled_class_ids': enrolled_class_ids,
            'pending_class_ids': pending_class_ids,
            'school_sections': [],
            'global_subjects': global_subjects,
            **hub_extra,
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
        log_event(
            user=request.user if request.user.is_authenticated else None,
            school=None, category='data_change',
            action='contact_message_submitted',
            detail={'name': name, 'email': email, 'subject': subject},
            request=request,
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


class PrivacyPolicyView(View):
    """Public Privacy Policy page."""

    def get(self, request):
        return render(request, 'public/privacy.html')


class TermsConditionsView(View):
    """Public Terms and Conditions page."""

    def get(self, request):
        return render(request, 'public/terms.html')


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


# ── API: Department Levels ────────────────────────────────────────────────────

class DepartmentLevelsAPIView(LoginRequiredMixin, View):
    """Return levels mapped to a department, grouped by subject."""

    def get(self, request, dept_id):
        from django.http import JsonResponse
        from .models import DepartmentLevel, DepartmentSubject

        dept = Department.objects.filter(id=dept_id, is_active=True).first()
        if not dept:
            return JsonResponse({'error': 'Department not found'}, status=404)

        dept_subjects = (
            DepartmentSubject.objects.filter(department=dept)
            .select_related('subject')
            .order_by('order', 'subject__name')
        )
        dept_levels = (
            DepartmentLevel.objects.filter(department=dept)
            .select_related('level', 'level__subject')
            .exclude(level__level_number__gte=100, level__level_number__lt=200)
            .order_by('order', 'level__level_number')
        )

        subjects_data = []
        for ds in dept_subjects:
            year_levels = []
            custom_levels = []
            for dl in dept_levels:
                if dl.level.subject_id == ds.subject_id:
                    entry = {
                        'id': dl.level.id,
                        'level_number': dl.level.level_number,
                        'display_name': dl.effective_display_name,
                        'description': dl.level.description,
                    }
                    if dl.level.level_number <= 9:
                        year_levels.append(entry)
                    else:
                        custom_levels.append(entry)
            subjects_data.append({
                'id': ds.subject.id,
                'name': ds.subject.name,
                'levels': year_levels,
                'custom_levels': custom_levels,
            })

        # Backwards compatible: also include flat lists for legacy consumers
        all_year = []
        all_custom = []
        for sd in subjects_data:
            all_year.extend(sd['levels'])
            all_custom.extend(sd['custom_levels'])

        return JsonResponse({
            'subjects': subjects_data,
            # Legacy flat lists (backwards compatible)
            'levels': all_year,
            'custom_levels': all_custom,
        })
