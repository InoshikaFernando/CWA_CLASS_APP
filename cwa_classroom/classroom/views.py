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
    basic_facts_levels = Level.objects.filter(level_number__gte=100)
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
                Level.objects.filter(level_number__gte=100).values_list('id', flat=True)
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

        # ── Topic quiz progress grid ──────────────────────────────────────────
        from maths.models import TopicLevelStatistics
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
                        question_text=question_text, topic=maths_topic, level=maths_level
                    ).first()
                    fields = {'question_type': question_type, 'difficulty': q_data.get('difficulty', 1),
                              'points': q_data.get('points', 1), 'explanation': q_data.get('explanation', '')}
                    if existing:
                        for k, v in fields.items(): setattr(existing, k, v)
                        existing.save(); existing.answers.all().delete(); question = existing; updated += 1
                    else:
                        question = MathsQuestion.objects.create(
                            question_text=question_text, topic=maths_topic, level=maths_level, **fields
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
        from maths.models import Question as MathsQuestion, Level as MathsLevel
        level = get_object_or_404(Level, level_number=level_number)  # classroom.Level for display context
        maths_level = MathsLevel.objects.filter(level_number=level_number).first()
        questions = (
            MathsQuestion.objects.filter(level=maths_level).select_related('topic').prefetch_related('answers')
            if maths_level else MathsQuestion.objects.none()
        )
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
        level = get_object_or_404(Level, level_number=level_number)  # classroom.Level for display
        classroom_topic = get_object_or_404(Topic, id=request.POST.get('topic'))
        maths_level = get_object_or_404(MathsLevel, level_number=level_number)
        maths_topic = MathsTopic.objects.filter(name=classroom_topic.name).first()
        with transaction.atomic():
            question = MathsQuestion.objects.create(
                topic=maths_topic, level=maths_level,
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
        # Pass classroom.Topic objects for the dropdown; active topics for any level
        return render(request, 'teacher/question_form.html', {
            'question': question, 'level': question.level,
            'topics': Topic.objects.filter(is_active=True).order_by('name'),
            'question_types': MathsQuestion.QUESTION_TYPES,
            'difficulty_choices': MathsQuestion.DIFFICULTY_CHOICES,
        })

    def post(self, request, question_id):
        from maths.models import (Question as MathsQuestion, Answer as MathsAnswer,
                                  Topic as MathsTopic)
        question = get_object_or_404(MathsQuestion, id=question_id)
        # topic from POST is classroom.Topic.id — bridge to maths.Topic by name
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
        level_number = question.level.level_number
        question.delete()
        messages.success(request, 'Question deleted.')
        return redirect('question_list', level_number=level_number)


class HoDOverviewView(RoleRequiredMixin, View):
    required_role = Role.HEAD_OF_DEPARTMENT

    def get(self, request):
        school_id = request.session.get('current_school_id')
        school = None
        if school_id:
            school = School.objects.filter(id=school_id, is_active=True).first()

        if school:
            classes = ClassRoom.objects.filter(school=school, is_active=True).prefetch_related('teachers', 'students')
            teachers = CustomUser.objects.filter(
                school_memberships__school=school,
                school_memberships__is_active=True,
            )
            teacher_attendance_qs = TeacherAttendance.objects.filter(
                session__classroom__school=school,
            )
        else:
            classes = ClassRoom.objects.filter(is_active=True).prefetch_related('teachers', 'students')
            teachers = CustomUser.objects.filter(
                roles__name__in=[Role.TEACHER, Role.SENIOR_TEACHER, Role.JUNIOR_TEACHER],
            )
            teacher_attendance_qs = TeacherAttendance.objects.all()

        total_sessions = teacher_attendance_qs.count()
        present_count = teacher_attendance_qs.filter(status='present').count()
        total_students = sum(c.students.count() for c in classes)

        return render(request, 'hod/overview.html', {
            'school': school,
            'classes': classes,
            'teachers': teachers,
            'total_students': total_students,
            'total_sessions': total_sessions,
            'present_count': present_count,
        })


class HoDManageClassesView(RoleRequiredMixin, View):
    required_role = Role.HEAD_OF_DEPARTMENT

    def get(self, request):
        school_id = request.session.get('current_school_id')
        school = None
        if school_id:
            school = School.objects.filter(id=school_id, is_active=True).first()

        if school:
            classes = ClassRoom.objects.filter(school=school, is_active=True).prefetch_related('teachers')
            teachers = CustomUser.objects.filter(
                school_memberships__school=school,
                school_memberships__is_active=True,
            )
        else:
            classes = ClassRoom.objects.filter(is_active=True).prefetch_related('teachers')
            teachers = CustomUser.objects.filter(
                roles__name__in=[Role.TEACHER, Role.SENIOR_TEACHER, Role.JUNIOR_TEACHER],
            )

        return render(request, 'hod/manage_classes.html', {
            'school': school,
            'classes': classes,
            'teachers': teachers,
        })


class HoDWorkloadView(RoleRequiredMixin, View):
    required_role = Role.HEAD_OF_DEPARTMENT

    def get(self, request):
        school_id = request.session.get('current_school_id')
        school = None
        if school_id:
            school = School.objects.filter(id=school_id, is_active=True).first()

        if school:
            memberships = SchoolTeacher.objects.filter(
                school=school, is_active=True,
            ).select_related('teacher')
            teachers = CustomUser.objects.filter(
                school_memberships__school=school,
                school_memberships__is_active=True,
            )
            senior_teachers = memberships.filter(role='senior_teacher')
            junior_teachers = memberships.filter(role='junior_teacher')
        else:
            teachers = CustomUser.objects.filter(
                roles__name__in=[Role.TEACHER, Role.SENIOR_TEACHER, Role.JUNIOR_TEACHER],
            )
            senior_teachers = SchoolTeacher.objects.filter(role='senior_teacher', is_active=True)
            junior_teachers = SchoolTeacher.objects.filter(role='junior_teacher', is_active=True)

        return render(request, 'hod/workload.html', {
            'school': school,
            'teachers': teachers,
            'senior_teachers': senior_teachers,
            'junior_teachers': junior_teachers,
        })


class HoDReportsView(RoleRequiredMixin, View):
    required_role = Role.HEAD_OF_DEPARTMENT

    def get(self, request):
        school_id = request.session.get('current_school_id')
        school = None
        if school_id:
            school = School.objects.filter(id=school_id, is_active=True).first()

        return render(request, 'hod/reports.html', {
            'school': school,
            'levels': Level.objects.filter(level_number__lte=8),
            'topics': Topic.objects.filter(is_active=True),
            'attendance_report_url': 'hod_attendance_report',
        })


class HoDAttendanceReportView(RoleRequiredMixin, View):
    required_role = Role.HEAD_OF_DEPARTMENT

    def get(self, request):
        from django.db.models import Count, Q

        school_id = request.session.get('current_school_id')
        school = None
        if school_id:
            school = School.objects.filter(id=school_id, is_active=True).first()

        # --- Teacher attendance summary ---
        if school:
            teacher_att_qs = TeacherAttendance.objects.filter(
                session__classroom__school=school,
            )
            student_att_qs = StudentAttendance.objects.filter(
                session__classroom__school=school,
            )
        else:
            teacher_att_qs = TeacherAttendance.objects.all()
            student_att_qs = StudentAttendance.objects.all()

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
            'school': school,
            'teacher_summary': teacher_summary,
            'student_summary': student_summary,
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
    Redirects non-student roles to their role-specific dashboards.
    Students and Individual Students stay on the subjects hub.
    """

    def get(self, request):
        user = request.user
        role = user.primary_role

        # Redirect non-student roles to their dashboards
        if role == Role.ADMIN:
            return redirect('admin_dashboard')
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
