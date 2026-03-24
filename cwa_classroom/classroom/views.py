import logging

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import transaction

from accounts.models import CustomUser, Role, UserRole
from billing.mixins import ModuleRequiredMixin
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

            # Bridge classroom.Topic → maths.Topic by name for quiz links
            from maths.models import Topic as MathsTopic, Level as MathsLevel, Question
            maths_topic_map = {t.name: t for t in MathsTopic.objects.all()}

            # Pre-fetch which maths topics have questions, keyed by (maths_topic_id, maths_level_id)
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
                # Resolve maths-side level for question lookup
                maths_level = MathsLevel.objects.filter(level_number=year).first()

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
                    # Bridge to maths Topic
                    mt = maths_topic_map.get(subtopic.name)
                    has_questions = (
                        mt is not None
                        and maths_level is not None
                        and (mt.id, maths_level.id) in questions_exist
                    )
                    strand_dict[sid]['subtopics'].append({
                        'topic': subtopic,
                        'maths_topic_id': mt.id if mt else None,
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
        from maths.models import Topic as MathsTopic

        # ── Topic quiz progress grid ──────────────────────────────────────────
        from maths.models import TopicLevelStatistics
        maths_topic_map = {t.name: t for t in MathsTopic.objects.all()}
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
                    'maths_topic': maths_topic_map.get(topic.name),
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
            classroom = ClassRoom.objects.filter(
                Q(id=class_id, department__head=user) |
                Q(id=class_id, teachers=user)
            ).first()
            if not classroom:
                raise Http404("No ClassRoom matches the given query.")
        else:
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)

        # Sessions for this class (last 10, with attendance counts)
        sessions = (
            ClassSession.objects.filter(classroom=classroom)
            .annotate(
                present_count=Count('student_attendance', filter=Q(student_attendance__status='present')),
                late_count=Count('student_attendance', filter=Q(student_attendance__status='late')),
                absent_count=Count('student_attendance', filter=Q(student_attendance__status='absent')),
            )
            .order_by('-date', '-start_time')[:10]
        )

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
        user = request.user
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            return get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            from django.db.models import Q
            classroom = ClassRoom.objects.filter(
                Q(id=class_id, department__head=user) |
                Q(id=class_id, teachers=user)
            ).first()
            if not classroom:
                raise Http404("No ClassRoom matches the given query.")
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
        user = request.user
        if user.has_role(Role.ADMIN) or user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            return get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            from django.db.models import Q
            classroom = ClassRoom.objects.filter(
                Q(id=class_id, department__head=user) |
                Q(id=class_id, teachers=user)
            ).first()
            if not classroom:
                raise Http404("No ClassRoom matches the given query.")
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
            all_students = CustomUser.objects.filter(id__in=school_student_ids)
        else:
            all_students = CustomUser.objects.filter(roles__name=Role.STUDENT)
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
        messages.success(request, f'{added} teacher(s) added, {removed} removed.')
        return redirect('class_detail', class_id=class_id)


class ClassAttendanceView(RoleRequiredMixin, ModuleRequiredMixin, View):
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [
        Role.TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def get(self, request, class_id):
        user = request.user
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            from django.db.models import Q
            classroom = ClassRoom.objects.filter(
                Q(id=class_id, department__head=user) |
                Q(id=class_id, teachers=user)
            ).first()
            if not classroom:
                raise Http404("No ClassRoom matches the given query.")
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
        from maths.models import (Question as MathsQuestion, Answer as MathsAnswer,
                                  Topic as MathsTopic, Level as MathsLevel)
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
            maths_topic = MathsTopic.objects.get(name__iexact=topic_name)
            maths_level = MathsLevel.objects.get(level_number=year_level)
        except (MathsTopic.DoesNotExist, MathsLevel.DoesNotExist) as e:
            messages.error(request, str(e))
            return redirect('upload_questions')
        # Tag uploaded questions with teacher's school
        user_school_id = SchoolTeacher.objects.filter(
            teacher=request.user, is_active=True
        ).values_list('school_id', flat=True).first()
        inserted = updated = failed = 0
        errors = []
        for i, q_data in enumerate(data.get('questions', []), 1):
            question_text = q_data.get('question_text', '').strip()
            question_type = q_data.get('question_type', '').strip()
            answers_data = q_data.get('answers', [])
            if not question_text: errors.append(f'Q{i}: missing question_text'); failed += 1; continue
            if question_type not in dict(MathsQuestion.QUESTION_TYPES): errors.append(f'Q{i}: bad type'); failed += 1; continue
            if not answers_data: errors.append(f'Q{i}: no answers'); failed += 1; continue
            try:
                with transaction.atomic():
                    existing = MathsQuestion.objects.filter(
                        question_text=question_text, topic=maths_topic, level=maths_level,
                        school_id=user_school_id,
                    ).first()
                    fields = {'question_type': question_type, 'difficulty': q_data.get('difficulty', 1),
                              'points': q_data.get('points', 1), 'explanation': q_data.get('explanation', '')}
                    if existing:
                        for k, v in fields.items(): setattr(existing, k, v)
                        existing.save(); existing.answers.all().delete(); question = existing; updated += 1
                    else:
                        question = MathsQuestion.objects.create(
                            question_text=question_text, topic=maths_topic, level=maths_level,
                            school_id=user_school_id, **fields
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
        return render(request, 'teacher/upload_questions.html', {
            'upload_results': {'inserted': inserted, 'updated': updated, 'failed': failed, 'errors': errors},
            'topics': Topic.objects.filter(is_active=True).select_related('subject'),
            'levels': Level.objects.filter(level_number__lte=8),
        })


class QuestionListView(LoginRequiredMixin, View):
    def get(self, request, level_number):
        from django.db.models import Q
        from maths.models import Question as MathsQuestion, Level as MathsLevel
        level = get_object_or_404(Level, level_number=level_number)
        maths_level = MathsLevel.objects.filter(level_number=level_number).first()
        if maths_level:
            # Show global questions + current school's private questions
            user_school = SchoolTeacher.objects.filter(
                teacher=request.user, is_active=True
            ).values_list('school', flat=True).first()
            q_filter = Q(level=maths_level) & (Q(school__isnull=True) | Q(school_id=user_school))
            questions = MathsQuestion.objects.filter(q_filter).select_related('topic', 'school').prefetch_related('answers')
        else:
            questions = MathsQuestion.objects.none()
        return render(request, 'teacher/question_list.html', {'level': level, 'questions': questions})


class AddQuestionView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request, level_number):
        from maths.models import Question as MathsQuestion
        level = get_object_or_404(Level, level_number=level_number)
        return render(request, 'teacher/question_form.html', {
            'level': level, 'topics': Topic.objects.filter(levels=level, is_active=True),
            'question_types': MathsQuestion.QUESTION_TYPES,
            'difficulty_choices': MathsQuestion.DIFFICULTY_CHOICES,
        })

    def post(self, request, level_number):
        from maths.models import (Question as MathsQuestion, Answer as MathsAnswer,
                                  Topic as MathsTopic, Level as MathsLevel)
        level = get_object_or_404(Level, level_number=level_number)
        classroom_topic = get_object_or_404(Topic, id=request.POST.get('topic'))
        maths_level = get_object_or_404(MathsLevel, level_number=level_number)
        maths_topic = MathsTopic.objects.filter(name=classroom_topic.name).first()
        # Tag question with teacher's school
        user_school_id = SchoolTeacher.objects.filter(
            teacher=request.user, is_active=True
        ).values_list('school_id', flat=True).first()
        with transaction.atomic():
            question = MathsQuestion.objects.create(
                topic=maths_topic, level=maths_level,
                school_id=user_school_id,
                question_text=request.POST.get('question_text', '').strip(),
                question_type=request.POST.get('question_type', MathsQuestion.MULTIPLE_CHOICE),
                difficulty=int(request.POST.get('difficulty', 1)),
                points=int(request.POST.get('points', 1)),
                explanation=request.POST.get('explanation', ''),
                image=request.FILES.get('image'),
            )
            for i in range(1, 5):
                text = request.POST.get(f'answer_text_{i}', '').strip()
                if text:
                    MathsAnswer.objects.create(
                        question=question, answer_text=text,
                        is_correct=request.POST.get(f'answer_correct_{i}') == 'true',
                        order=int(request.POST.get(f'answer_order_{i}', i)),
                    )
        messages.success(request, 'Question added.')
        return redirect('question_list', level_number=level_number)


class EditQuestionView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def get(self, request, question_id):
        from maths.models import Question as MathsQuestion
        question = get_object_or_404(MathsQuestion, id=question_id)
        return render(request, 'teacher/question_form.html', {
            'question': question, 'level': question.level,
            'topics': Topic.objects.filter(is_active=True).order_by('name'),
            'question_types': MathsQuestion.QUESTION_TYPES,
            'difficulty_choices': MathsQuestion.DIFFICULTY_CHOICES,
            'is_global': question.school is None,
        })

    def post(self, request, question_id):
        from maths.models import (Question as MathsQuestion, Answer as MathsAnswer,
                                  Topic as MathsTopic)
        question = get_object_or_404(MathsQuestion, id=question_id)
        # Only allow editing school-owned questions, not global ones
        if question.school is None:
            messages.error(request, 'Global questions cannot be edited.')
            return redirect('question_list', level_number=question.level.level_number)
        classroom_topic = get_object_or_404(Topic, id=request.POST.get('topic'))
        question.topic = MathsTopic.objects.filter(name=classroom_topic.name).first()
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
        messages.success(request, 'Question updated.')
        return redirect('question_list', level_number=question.level.level_number)


class DeleteQuestionView(RoleRequiredMixin, View):
    required_role = Role.TEACHER

    def post(self, request, question_id):
        from maths.models import Question as MathsQuestion
        question = get_object_or_404(MathsQuestion, id=question_id)
        # Only allow deleting school-owned questions, not global ones
        if question.school is None:
            messages.error(request, 'Global questions cannot be deleted.')
            return redirect('question_list', level_number=question.level.level_number)
        level_number = question.level.level_number
        question.delete()
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

        from django.db.models import Count
        from django.utils import timezone
        from datetime import timedelta
        from collections import defaultdict

        # ── Next classes: check if user also teaches ──
        today = timezone.localdate()
        week_ahead = today + timedelta(days=7)

        my_teaching_classes = ClassRoom.objects.filter(
            class_teachers__teacher=request.user,
            is_active=True,
        ).select_related('department', 'subject').prefetch_related('students', 'teachers').annotate(
            student_count=Count('students', distinct=True),
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
            # HoD: scope to their departments + classes they teach in other depts
            from django.db.models import Q
            departments = Department.objects.filter(head=request.user, is_active=True)
            dept_ids = list(departments.values_list('id', flat=True))
            classes = ClassRoom.objects.filter(
                Q(department_id__in=dept_ids, is_active=True) |
                Q(teachers=request.user, is_active=True)
            ).distinct().select_related('department', 'subject').prefetch_related('teachers', 'students').annotate(
                student_count=Count('students', distinct=True),
                teacher_count=Count('teachers', distinct=True),
            )
            my_school_ids = list(departments.values_list('school_id', flat=True).distinct())
            teachers = CustomUser.objects.filter(
                department_memberships__department_id__in=dept_ids,
            ).distinct()
            teacher_attendance_qs = TeacherAttendance.objects.filter(
                session__classroom__department_id__in=dept_ids,
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
            my_schools = School.objects.filter(admin=request.user)
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
                student_count=Count('students', distinct=True),
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
        total_students = classes.values_list('students', flat=True).distinct().count()

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

        # ── Next classes: upcoming sessions or schedule fallback ──
        if next_classes_scope is None:
            next_classes_scope = classes

        upcoming_sessions = list(ClassSession.objects.filter(
            classroom__in=next_classes_scope,
            date__gte=today,
            date__lte=week_ahead,
            status='scheduled',
        ).select_related(
            'classroom', 'classroom__department', 'classroom__subject',
        ).prefetch_related(
            'classroom__teachers', 'classroom__students',
        ).order_by('date', 'start_time')[:4])

        # Fallback: derive from ClassRoom.day if no sessions exist
        next_classes_from_schedule = []
        if not upcoming_sessions:
            DAY_MAP = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                'friday': 4, 'saturday': 5, 'sunday': 6,
            }
            today_idx = today.weekday()
            now_time = timezone.localtime().time()

            def _days_until(day_str, start_time=None):
                target = DAY_MAP.get(day_str, 7)
                diff = (target - today_idx) % 7
                if diff == 0:
                    if start_time and start_time > now_time:
                        return 0
                    return 7
                return diff

            scheduled = sorted(
                [c for c in (next_classes_scope if is_teacher_too else classes_list) if c.day],
                key=lambda c: (_days_until(c.day, c.start_time), c.start_time or timezone.datetime.min.time()),
            )
            # Attach computed next_date for template display
            for c in scheduled[:4]:
                du = _days_until(c.day, c.start_time)
                c.next_date = today + timedelta(days=du)
            next_classes_from_schedule = scheduled[:4]

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

        return render(request, 'hod/overview.html', {
            'school_data': school_data,
            'classes': classes_list,
            'teachers': teachers,
            'total_students': total_students,
            'total_sessions': total_sessions,
            'present_count': present_count,
            'is_hod_only': is_hod_only,
            'departments': departments,
            'pending_enrollment_count': pending_enrollment_count,
            'classes_no_students': classes_no_students,
            'classes_no_teachers': classes_no_teachers,
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
            from django.db.models import Q
            departments = Department.objects.filter(head=request.user, is_active=True)
            dept_ids = list(departments.values_list('id', flat=True))
            school_ids = list(departments.values_list('school_id', flat=True).distinct())
            classes = ClassRoom.objects.filter(
                Q(department_id__in=dept_ids, is_active=True) |
                Q(teachers=request.user, is_active=True)
            ).distinct().select_related('department').prefetch_related('teachers')
            teachers = CustomUser.objects.filter(
                department_memberships__department_id__in=dept_ids,
            ).distinct()
        else:
            school_ids = list(School.objects.filter(admin=request.user).values_list('id', flat=True))
            departments = Department.objects.filter(school_id__in=school_ids, is_active=True)
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

        return render(request, 'hod/manage_classes.html', {
            'classes': classes,
            'teachers': teachers,
            'is_hod_only': is_hod_only,
            'departments': departments,
            'unassigned_classes': unassigned_classes,
            'specialty_map': specialty_map,
        })


class HoDWorkloadView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        is_hod_only = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not request.user.has_role(Role.HEAD_OF_INSTITUTE)
            and not request.user.has_role(Role.INSTITUTE_OWNER)
        )

        if is_hod_only:
            dept_ids = list(
                Department.objects.filter(head=request.user, is_active=True).values_list('id', flat=True)
            )
            teacher_ids = list(
                CustomUser.objects.filter(
                    department_memberships__department_id__in=dept_ids,
                ).values_list('id', flat=True).distinct()
            )
            memberships = SchoolTeacher.objects.filter(
                teacher_id__in=teacher_ids, is_active=True,
            ).select_related('teacher')
            teachers = CustomUser.objects.filter(id__in=teacher_ids)
        else:
            my_school_ids = list(School.objects.filter(admin=request.user).values_list('id', flat=True))
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
            departments = Department.objects.filter(head=request.user, is_active=True)

        return render(request, 'hod/reports.html', {
            'levels': Level.objects.filter(level_number__lte=8),
            'topics': Topic.objects.filter(is_active=True),
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
            dept_ids = list(
                Department.objects.filter(head=request.user, is_active=True).values_list('id', flat=True)
            )
            teacher_att_qs = TeacherAttendance.objects.filter(
                session__classroom__department_id__in=dept_ids,
            )
            student_att_qs = StudentAttendance.objects.filter(
                session__classroom__department_id__in=dept_ids,
            )
        else:
            my_school_ids = list(School.objects.filter(admin=request.user).values_list('id', flat=True))
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

        if user_type == 'teacher':
            qs = TeacherAttendance.objects.filter(teacher_id=user_id)
            if is_hod_only:
                dept_ids = list(
                    Department.objects.filter(head=request.user, is_active=True)
                    .values_list('id', flat=True)
                )
                qs = qs.filter(session__classroom__department_id__in=dept_ids)
            else:
                school_ids = list(
                    School.objects.filter(admin=request.user).values_list('id', flat=True)
                )
                qs = qs.filter(session__classroom__school_id__in=school_ids)

            if status_filter and status_filter != 'all':
                qs = qs.filter(status=status_filter)

            records = qs.select_related('session', 'session__classroom').order_by('-session__date', '-session__start_time')
        else:
            qs = StudentAttendance.objects.filter(student_id=user_id)
            if is_hod_only:
                dept_ids = list(
                    Department.objects.filter(head=request.user, is_active=True)
                    .values_list('id', flat=True)
                )
                qs = qs.filter(session__classroom__department_id__in=dept_ids)
            else:
                school_ids = list(
                    School.objects.filter(admin=request.user).values_list('id', flat=True)
                )
                qs = qs.filter(session__classroom__school_id__in=school_ids)

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
            school_ids = School.objects.filter(admin=user).values_list('id', flat=True)
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

                        messages.success(request, f'Subject "{subject.name}" moved to {new_dept.name}.')
                        return self._redirect_to_dept(department)
                else:
                    messages.error(request, 'Target department not found.')
                    return self._redirect_to_dept(department)

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
            school_ids = School.objects.filter(admin=request.user).values_list('id', flat=True)
            department = Department.objects.filter(school_id__in=school_ids, id=dept_id, is_active=True).first()

        if department:
            DepartmentLevel.objects.filter(department=department, level_id=level_id).delete()
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
        if user.has_role(Role.ADMIN) or user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, is_active=True)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            from django.db.models import Q
            classroom = ClassRoom.objects.filter(
                Q(id=class_id, department__head=user, is_active=True) |
                Q(id=class_id, teachers=user, is_active=True)
            ).first()
            if not classroom:
                raise Http404("No ClassRoom matches the given query.")
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
        user = request.user
        if user.has_role(Role.ADMIN) or user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            from django.db.models import Q
            classroom = ClassRoom.objects.filter(
                Q(id=class_id, department__head=user) |
                Q(id=class_id, teachers=user)
            ).first()
            if not classroom:
                raise Http404("No ClassRoom matches the given query.")
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
            school_ids = School.objects.filter(admin=user).values_list('id', flat=True)
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
            school_ids = School.objects.filter(admin=request.user).values_list('id', flat=True)
            department = get_object_or_404(
                Department, id=dept_id, school_id__in=school_ids, is_active=True
            )

        classroom = get_object_or_404(
            ClassRoom, id=class_id, school=department.school,
            department__isnull=True, is_active=True,
        )

        classroom.department = department
        classroom.save(update_fields=['department'])

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


class SubjectsHubView(LoginRequiredMixin, View):
    """
    Authenticated home -- shows greeting + subject cards.
    Redirects non-student roles to their role-specific dashboards.
    Students and Individual Students stay on the subjects hub with
    optional school/open-practice toggle.
    """

    def get(self, request):
        user = request.user
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

        # SubjectApp cards (always shown)
        subjects = SubjectApp.objects.exclude(
            is_active=False, is_coming_soon=False,
        ).order_by('order')

        # Determine if user is a school student
        is_school_student = user.has_role(Role.STUDENT)
        schools = []
        if is_school_student:
            schools = list(
                School.objects.filter(
                    school_students__student=user,
                    school_students__is_active=True,
                    is_active=True,
                ).distinct()
            )

        # Source toggle: "school" or "open"
        active_source = request.GET.get(
            'source', 'school' if schools else 'open',
        )
        active_school = schools[0] if (active_source == 'school' and schools) else None

        # Global classes grouped by subject (for "Open Practice" or individual students)
        subject_classes = []
        if active_source == 'open' or not schools:
            subjects_with_classes = Subject.objects.filter(
                classrooms__school__isnull=True,
                classrooms__is_active=True,
            ).distinct().order_by('order', 'name')
            for subj in subjects_with_classes:
                classes = list(
                    ClassRoom.objects.filter(
                        subject=subj, school__isnull=True, is_active=True,
                    ).select_related('subject').order_by('name')
                )
                if classes:
                    subject_classes.append({
                        'subject': subj,
                        'classes': classes,
                    })

        # School departments with classes (for school mode)
        department_classes = []
        if active_school:
            departments = Department.objects.filter(
                school=active_school, is_active=True,
            ).order_by('name')
            for dept in departments:
                classes = list(
                    ClassRoom.objects.filter(
                        department=dept, is_active=True,
                    ).select_related('subject').order_by('name')
                )
                if classes:
                    department_classes.append({
                        'department': dept,
                        'classes': classes,
                    })

        # Enrollment status sets for the class cards
        enrolled_class_ids = set(
            ClassStudent.objects.filter(
                student=user, is_active=True,
            ).values_list('classroom_id', flat=True)
        )
        pending_class_ids = set(
            Enrollment.objects.filter(
                student=user, status='pending',
            ).values_list('classroom_id', flat=True)
        )

        return render(request, 'hub/home.html', {
            'subjects': subjects,
            'schools': schools,
            'is_school_student': is_school_student,
            'active_source': active_source,
            'active_school': active_school,
            'subject_classes': subject_classes,
            'department_classes': department_classes,
            'enrolled_class_ids': enrolled_class_ids,
            'pending_class_ids': pending_class_ids,
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
