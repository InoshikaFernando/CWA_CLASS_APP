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
    StudentLevelEnrollment, SubjectApp, ContactMessage, CONTACT_SUBJECT_CHOICES,
    School, SchoolTeacher, ClassSession, StudentAttendance, TeacherAttendance,
    Department,
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
                return redirect('subjects_hub')

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
                    strand_dict[sid]['subtopics'].append(subtopic)
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

        # Determine which year levels this student has access to via their classrooms
        classrooms = ClassRoom.objects.filter(students=request.user, is_active=True)
        enrolled_level_ids = set(
            Level.objects.filter(classrooms__in=classrooms, level_number__lte=8).values_list('id', flat=True)
        )
        # Fall back to all Year 1-8 levels if not in any classroom yet
        if not enrolled_level_ids:
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

        # ── Times Tables results ──────────────────────────────────────────────
        tt_results = []
        for table in range(1, 13):
            best_mul = StudentFinalAnswer.objects.filter(
                student=request.user,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                operation='multiplication',
                level__level_number=table,
            ).order_by('-points').first()
            best_div = StudentFinalAnswer.objects.filter(
                student=request.user,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                operation='division',
                level__level_number=table,
            ).order_by('-points').first()
            # Legacy: attempts without operation saved (old records)
            if not best_mul and not best_div:
                best_legacy = StudentFinalAnswer.objects.filter(
                    student=request.user,
                    quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                    operation='',
                    level__level_number=table,
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

        from maths.views import update_time_log_from_activities
        time_log = update_time_log_from_activities(request.user)

        return render(request, 'student/dashboard.html', {
            'progress_grid': progress_grid,
            'bf_grid': bf_grid,
            'tt_results': tt_results,
            'recent_topic': recent_topic,
            'recent_bf': recent_bf,
            'recent_tt': recent_tt,
            'time_log': time_log,
            'time_daily': _format_seconds(time_log.daily_total_seconds if time_log else 0),
            'time_weekly': _format_seconds(time_log.weekly_total_seconds if time_log else 0),
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
    required_role = Role.TEACHER

    def get(self, request):
        levels = Level.objects.filter(level_number__lte=8, school__isnull=True).order_by('level_number')
        # Get custom levels from teacher's school
        custom_levels = Level.objects.none()
        school_membership = SchoolTeacher.objects.filter(teacher=request.user).select_related('school').first()
        if school_membership:
            custom_levels = Level.objects.filter(school=school_membership.school).order_by('level_number')
        return render(request, 'teacher/create_class.html', {
            'levels': levels,
            'custom_levels': custom_levels,
        })

    def post(self, request):
        name = request.POST.get('name', '').strip()
        level_ids = request.POST.getlist('levels')
        day = request.POST.get('day', '').strip()
        start_time = request.POST.get('start_time', '').strip() or None
        end_time = request.POST.get('end_time', '').strip() or None
        description = request.POST.get('description', '').strip()
        if not name:
            messages.error(request, 'Class name is required.')
            return redirect('create_class')
        with transaction.atomic():
            classroom = ClassRoom.objects.create(
                name=name,
                day=day,
                start_time=start_time,
                end_time=end_time,
                description=description,
                created_by=request.user,
            )
            if level_ids:
                classroom.levels.set(Level.objects.filter(id__in=level_ids))
            ClassTeacher.objects.create(classroom=classroom, teacher=request.user)
        messages.success(request, f'Class "{name}" created. Code: {classroom.code}')
        return redirect('subjects_hub')


class ClassDetailView(RoleRequiredMixin, View):
    required_roles = [
        Role.TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def get(self, request, class_id):
        user = request.user
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            classroom = get_object_or_404(
                ClassRoom, id=class_id,
                department__head=user,
            )
        else:
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
        return render(request, 'teacher/class_detail.html', {
            'classroom': classroom,
            'students': classroom.students.all(),
            'teachers': classroom.teachers.all(),
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
            return get_object_or_404(ClassRoom, id=class_id, department__head=user)
        else:
            return get_object_or_404(ClassRoom, id=class_id, teachers=request.user)

    def get(self, request, class_id):
        classroom = self._get_classroom(request, class_id)
        levels = Level.objects.filter(level_number__lte=8, school__isnull=True).order_by('level_number')
        custom_levels = Level.objects.none()
        if classroom.school:
            custom_levels = Level.objects.filter(school=classroom.school).order_by('level_number')
        back_url = request.GET.get('next', '')
        return render(request, 'teacher/edit_class.html', {
            'classroom': classroom,
            'levels': levels,
            'custom_levels': custom_levels,
            'selected_levels': list(classroom.levels.values_list('id', flat=True)),
            'back_url': back_url,
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
        classroom.save()
        classroom.levels.set(Level.objects.filter(id__in=level_ids))

        messages.success(request, f'Class "{name}" updated.')
        if next_url:
            return redirect(next_url)
        return redirect('class_detail', class_id=class_id)


class AssignStudentsView(RoleRequiredMixin, View):
    required_roles = [
        Role.TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def _get_classroom(self, request, class_id):
        user = request.user
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            return get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            return get_object_or_404(ClassRoom, id=class_id, department__head=user)
        else:
            return get_object_or_404(ClassRoom, id=class_id, teachers=request.user)

    def get(self, request, class_id):
        classroom = self._get_classroom(request, class_id)
        # Show school-scoped students if classroom belongs to a school
        if classroom.school:
            from .models import SchoolStudent
            school_student_ids = SchoolStudent.objects.filter(
                school=classroom.school
            ).values_list('student_id', flat=True)
            all_students = CustomUser.objects.filter(id__in=school_student_ids)
        else:
            all_students = CustomUser.objects.filter(roles__name=Role.STUDENT)
        return render(request, 'teacher/assign_students.html', {
            'classroom': classroom,
            'all_students': all_students,
            'enrolled': classroom.students.all(),
        })

    def post(self, request, class_id):
        classroom = self._get_classroom(request, class_id)
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


class ClassProgressView(RoleRequiredMixin, View):
    required_roles = [
        Role.TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def get(self, request, class_id):
        user = request.user
        # Teachers must be assigned to the class
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            classroom = get_object_or_404(
                ClassRoom, id=class_id,
                department__head=user,
            )
        else:
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=user)
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
        classes = ClassRoom.objects.filter(
            teachers=request.user, is_active=True
        ).prefetch_related('teachers')
        # Build specialty map from SchoolTeacher for all teachers across classes
        teacher_ids = set()
        for c in classes:
            teacher_ids.update(c.teachers.values_list('id', flat=True))
        specialty_map = {}
        if teacher_ids:
            for st in SchoolTeacher.objects.filter(teacher_id__in=teacher_ids):
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

        if is_hod_only:
            # HoD: scope to their departments
            departments = Department.objects.filter(head=request.user, is_active=True)
            dept_ids = list(departments.values_list('id', flat=True))
            classes = ClassRoom.objects.filter(
                department_id__in=dept_ids, is_active=True
            ).prefetch_related('teachers', 'students')
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
                    'student_count': sum(c.students.count() for c in dept_classes),
                    'class_count': len(dept_classes),
                })
        else:
            # HoI/Owner: scope to their schools (existing logic)
            departments = None
            my_schools = School.objects.filter(admin=request.user)
            my_school_ids = list(my_schools.values_list('id', flat=True))
            school_data = []
            for s in my_schools:
                teacher_count = SchoolTeacher.objects.filter(school=s, is_active=True).count()
                student_count = ClassRoom.objects.filter(
                    school=s, is_active=True
                ).values_list('students', flat=True).distinct().count()
                school_data.append({
                    'school': s,
                    'teacher_count': teacher_count,
                    'student_count': student_count,
                })
            classes = ClassRoom.objects.filter(
                school_id__in=my_school_ids, is_active=True
            ).prefetch_related('teachers', 'students')
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

        return render(request, 'hod/overview.html', {
            'school_data': school_data,
            'classes': classes,
            'teachers': teachers,
            'total_students': total_students,
            'total_sessions': total_sessions,
            'present_count': present_count,
            'is_hod_only': is_hod_only,
            'departments': departments,
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
            departments = Department.objects.filter(head=request.user, is_active=True)
            dept_ids = list(departments.values_list('id', flat=True))
            school_ids = list(departments.values_list('school_id', flat=True).distinct())
            classes = ClassRoom.objects.filter(
                department_id__in=dept_ids, is_active=True
            ).select_related('department').prefetch_related('teachers')
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
        for st in SchoolTeacher.objects.filter(school_id__in=school_ids):
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


class HoDAttendanceReportView(RoleRequiredMixin, View):
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
        levels = Level.objects.filter(level_number__lte=8, school__isnull=True).order_by('level_number')
        selected_dept = request.GET.get('department', '')
        # Custom levels from user's schools
        school_ids = departments.values_list('school_id', flat=True).distinct()
        custom_levels = Level.objects.filter(school_id__in=school_ids).order_by('level_number')
        return render(request, 'hod/create_class.html', {
            'departments': departments,
            'levels': levels,
            'custom_levels': custom_levels,
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

        with transaction.atomic():
            classroom = ClassRoom.objects.create(
                name=name,
                school=department.school,
                department=department,
                day=day,
                start_time=start_time,
                end_time=end_time,
                description=description,
                created_by=request.user,
            )
            if level_ids:
                classroom.levels.set(Level.objects.filter(id__in=level_ids))

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
    Redirects non-student roles to their role-specific dashboards.
    Students and Individual Students stay on the subjects hub.
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
        if role in (Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER):
            return redirect('teacher_dashboard')

        # Students and Individual Students stay on the subjects hub
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
