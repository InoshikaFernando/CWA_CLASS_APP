"""
Worksheets views: PDF upload → AI extraction → preview → confirm → assign → student session.
"""
import json
import os
import logging

logger = logging.getLogger(__name__)

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from accounts.models import Role
from billing.entitlements import get_school_for_user
from classroom.views import RoleRequiredMixin

from .grading_service import grade_extended_answer
from .models import (
    Worksheet,
    WorksheetAssignment,
    WorksheetQuestion,
    WorksheetStudentAnswer,
    WorksheetSubmission,
    WorksheetUploadSession,
)

# ---------------------------------------------------------------------------
# CPP-280: Answer partial dispatch map — question_type → template path
# ---------------------------------------------------------------------------
_PARTIAL = 'worksheets/partials/'
ANSWER_PARTIAL_MAP = {
    'multiple_choice':    _PARTIAL + '_answer_mcq.html',
    'true_false':         _PARTIAL + '_answer_mcq.html',
    'short_answer':       _PARTIAL + '_answer_short.html',
    'fill_blank':         _PARTIAL + '_answer_text.html',
    'calculation':        _PARTIAL + '_answer_text.html',
    'extended_answer':    _PARTIAL + '_answer_extended.html',
    'long_division':      _PARTIAL + '_answer_long_division.html',
    'prime_factorization': _PARTIAL + '_answer_prime_factorization.html',
}
_ANSWER_PARTIAL_DEFAULT = _PARTIAL + '_answer_text.html'


TEACHER_ROLES = [
    Role.INSTITUTE_OWNER,
    Role.HEAD_OF_INSTITUTE,
    Role.HEAD_OF_DEPARTMENT,
    Role.SENIOR_TEACHER,
    Role.TEACHER,
    Role.JUNIOR_TEACHER,
]


# ---------------------------------------------------------------------------
# Teacher: Worksheet Library
# ---------------------------------------------------------------------------

class WorksheetListView(RoleRequiredMixin, View):
    """List all worksheets for the teacher's school."""
    required_roles = TEACHER_ROLES

    def get(self, request):
        school = get_school_for_user(request.user)
        worksheets = Worksheet.objects.filter(school=school).select_related('created_by', 'level')
        return render(request, 'worksheets/list.html', {
            'worksheets': worksheets,
            'school': school,
        })


# ---------------------------------------------------------------------------
# Teacher: Upload Flow (3 steps)
# ---------------------------------------------------------------------------

class WorksheetUploadView(RoleRequiredMixin, View):
    """Step 1: Upload a PDF worksheet for AI extraction."""
    required_roles = TEACHER_ROLES

    def get(self, request):
        return render(request, 'worksheets/upload.html', {})

    def post(self, request):
        school = get_school_for_user(request.user)
        pdf_file = request.FILES.get('pdf_file')

        if not pdf_file:
            messages.error(request, 'Please select a PDF file.')
            return redirect('worksheets:upload')

        if not pdf_file.name.lower().endswith('.pdf'):
            messages.error(request, 'Only PDF files are supported.')
            return redirect('worksheets:upload')

        # Default worksheet name from filename (strip .pdf)
        worksheet_name = pdf_file.name
        if worksheet_name.lower().endswith('.pdf'):
            worksheet_name = worksheet_name[:-4]

        # Persist the upload + create a PROCESSING session, then classify in the
        # background (CPP-327) so the request returns immediately.
        session = WorksheetUploadSession.objects.create(
            user=request.user,
            school=school,
            pdf_filename=pdf_file.name,
            pdf_file=pdf_file,
            worksheet_name=worksheet_name,
            status=WorksheetUploadSession.STATUS_PROCESSING,
        )

        from taskqueue.services import enqueue_task
        from .tasks import process_worksheet_pdf
        try:
            enqueue_task(
                school=school,
                user=request.user,
                task_type='worksheet_pdf',
                func=process_worksheet_pdf,
                args=[session.pk],
                queue='default',
            )
        except Exception:
            logger.exception('Failed to enqueue worksheet PDF for session %s', session.pk)
            session.delete()
            messages.error(
                request,
                'The background processing service is temporarily unavailable. '
                'Please try again in a few minutes.',
            )
            return redirect('worksheets:upload')

        return redirect('worksheets:processing', session_id=session.pk)


class WorksheetProcessingView(RoleRequiredMixin, View):
    """Interstitial page shown while the worksheet PDF is classified in the background."""
    required_roles = TEACHER_ROLES

    def get(self, request, session_id):
        session = get_object_or_404(
            WorksheetUploadSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        if session.status == WorksheetUploadSession.STATUS_READY:
            return redirect('worksheets:preview', session_id=session.pk)
        return render(request, 'worksheets/processing.html', {'session': session})


class WorksheetStatusView(RoleRequiredMixin, View):
    """HTMX poll endpoint: returns the status partial for a processing session.

    On READY the partial sends an HX-Redirect to the preview page; on FAILED it
    shows the error with a retry link.
    """
    required_roles = TEACHER_ROLES

    def get(self, request, session_id):
        session = get_object_or_404(
            WorksheetUploadSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        response = render(request, 'worksheets/_partials/status.html', {'session': session})
        if session.status == WorksheetUploadSession.STATUS_READY:
            response['HX-Redirect'] = reverse('worksheets:preview', args=[session.pk])
        return response


class WorksheetPreviewView(RoleRequiredMixin, View):
    """Step 2: Preview AI-extracted questions. Teacher can edit, include/exclude, rename worksheet."""
    required_roles = TEACHER_ROLES

    def get(self, request, session_id):
        session = get_object_or_404(
            WorksheetUploadSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        # Not finished yet — bounce back to the processing page.
        if session.status == WorksheetUploadSession.STATUS_PROCESSING:
            return redirect('worksheets:processing', session_id=session.pk)
        if session.status == WorksheetUploadSession.STATUS_FAILED:
            messages.error(request, f'PDF processing failed: {session.error_message}')
            return redirect('worksheets:upload')
        data = session.extracted_data
        questions = data.get('questions', [])

        from classroom.models import Topic, Level
        levels = Level.objects.filter(level_number__lte=12).order_by('level_number')

        # Parent topics (no parent FK) for the topic picker dropdown
        parent_topics = list(Topic.objects.filter(
            subject__slug='mathematics', parent__isnull=True, is_active=True,
        ).order_by('name').values_list('name', flat=True))

        # Subtopics grouped by parent name for the subtopic picker
        subtopics_map = {}
        for st in Topic.objects.filter(
            subject__slug='mathematics', parent__isnull=False, is_active=True,
        ).select_related('parent').order_by('name'):
            subtopics_map.setdefault(st.parent.name, []).append(st.name)

        image_list = [
            {'ref': ref, 'name': ref, 'base64': b64}
            for ref, b64 in session.extracted_images.items()
        ]

        for q in questions:
            q.setdefault('year_level', data.get('year_level'))
            q.setdefault('subject', data.get('subject', 'Mathematics'))
            q.setdefault('strand', data.get('strand', ''))
            q.setdefault('topic', data.get('topic', ''))
            q.setdefault('subtopic', '')
            q.setdefault('include', True)
            # Attach base64 image data directly to question dict so templates
            # don't need a custom filter for dict lookups.
            ref = q.get('image_ref')
            q['image_b64'] = session.extracted_images.get(ref) if ref else None

        # Recovery: if every question ended up with include=False (stuck state
        # from a previous all-uncheck submission), reset them all to True so
        # the teacher doesn't have to manually re-tick every question.
        if questions and not any(q.get('include') for q in questions):
            for q in questions:
                q['include'] = True
            # Save only the include reset — strip image_b64 first since that
            # is added in-memory for template rendering only and must not be
            # persisted (it bloats the JSONField with base64 image data).
            clean_questions = [{k: v for k, v in q.items() if k != 'image_b64'} for q in questions]
            data['questions'] = clean_questions
            session.extracted_data = data
            session.save(update_fields=['extracted_data'])
            # Restore the in-memory list reference so the template still gets image_b64.
            data['questions'] = questions

        return render(request, 'worksheets/preview.html', {
            'session': session,
            'data': data,
            'questions': questions,
            'levels': levels,
            'parent_topics_json': json.dumps(parent_topics),
            'subtopics_json': json.dumps(subtopics_map),
            'image_list': image_list,
            'image_refs_json': json.dumps([img['ref'] for img in image_list]),
            'question_types': [
                ('multiple_choice', 'Multiple Choice'),
                ('true_false', 'True / False'),
                ('short_answer', 'Short Answer'),
                ('fill_blank', 'Fill in the Blank'),
                ('calculation', 'Calculation'),
            ],
        })

    def post(self, request, session_id):
        """Save preview edits and redirect to confirm step."""
        session = get_object_or_404(
            WorksheetUploadSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        data = session.extracted_data

        # Worksheet name (editable)
        worksheet_name = request.POST.get('worksheet_name', '').strip()
        if worksheet_name:
            session.worksheet_name = worksheet_name

        # Global defaults
        data['year_level'] = int(request.POST.get('year_level', data.get('year_level', 1)))
        data['topic'] = request.POST.get('topic', data.get('topic', ''))
        data['strand'] = request.POST.get('strand', data.get('strand', ''))
        data['subject'] = request.POST.get('subject', data.get('subject', 'Mathematics'))

        questions = data.get('questions', [])
        for idx, q in enumerate(questions):
            prefix = f'q_{idx}_'
            q['include'] = request.POST.get(f'{prefix}include') == 'on'
            q['question_text'] = request.POST.get(f'{prefix}text', q.get('question_text', ''))
            q['question_type'] = request.POST.get(f'{prefix}type', q.get('question_type', 'short_answer'))
            q['difficulty'] = int(request.POST.get(f'{prefix}difficulty', q.get('difficulty', 1)))
            q['points'] = int(request.POST.get(f'{prefix}points', q.get('points', 1)))
            q['explanation'] = request.POST.get(f'{prefix}explanation', q.get('explanation', ''))
            q['year_level'] = int(request.POST.get(f'{prefix}year_level', q.get('year_level', data['year_level'])))
            q['subject'] = request.POST.get(f'{prefix}subject', q.get('subject', data['subject']))
            q['strand'] = request.POST.get(f'{prefix}strand', q.get('strand', data['strand']))
            q['topic'] = request.POST.get(f'{prefix}topic', q.get('topic', data['topic']))
            q['subtopic'] = request.POST.get(f'{prefix}subtopic', q.get('subtopic', ''))

            img_ref = request.POST.get(f'{prefix}image_ref', '')
            q['image_ref'] = img_ref if img_ref and img_ref != 'none' else None

            answers = []
            for a_idx in range(20):
                a_text = request.POST.get(f'{prefix}answer_{a_idx}_text', '')
                if a_text.strip():
                    answers.append({
                        'text': a_text,
                        'is_correct': request.POST.get(f'{prefix}answer_{a_idx}_correct') == 'on',
                    })
            if answers:
                q['answers'] = answers

        data['questions'] = questions
        session.extracted_data = data
        session.save(update_fields=['extracted_data', 'worksheet_name'])

        return redirect('worksheets:confirm', session_id=session.pk)


class WorksheetConfirmView(RoleRequiredMixin, View):
    """Step 3: Save questions to DB and create Worksheet record."""
    required_roles = TEACHER_ROLES

    def get(self, request, session_id):
        session = get_object_or_404(
            WorksheetUploadSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        data = session.extracted_data
        included = [q for q in data.get('questions', []) if q.get('include', True)]
        excluded_count = len(data.get('questions', [])) - len(included)

        return render(request, 'worksheets/confirm.html', {
            'session': session,
            'included_count': len(included),
            'excluded_count': excluded_count,
            'total_count': len(data.get('questions', [])),
            'images_count': sum(1 for q in included if q.get('image_ref')),
        })

    def post(self, request, session_id):
        session = get_object_or_404(
            WorksheetUploadSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        school = get_school_for_user(request.user)

        # Allow final name override from confirm form
        worksheet_name = request.POST.get('worksheet_name', '').strip() or session.worksheet_name or session.pdf_filename

        data = session.extracted_data
        questions_data = [q for q in data.get('questions', []) if q.get('include', True)]

        if not questions_data:
            messages.error(request, 'No questions to save. Please include at least one question.')
            return redirect('worksheets:preview', session_id=session.pk)

        from ai_import.services import save_questions_from_session
        from ai_import.models import AIImportSession
        from django.db import transaction

        # We reuse save_questions_from_session by creating a lightweight adapter
        # Build a temporary AIImportSession-like object
        class _TempSession:
            extracted_data = data
            extracted_images = session.extracted_images
            pk = session.pk
            is_confirmed = False

            def save(self, update_fields=None):
                pass  # Real confirmation handled below after worksheet creation

        temp_session = _TempSession()
        result = save_questions_from_session(temp_session, request.user, data)

        if result['failed'] == len(questions_data):
            messages.error(request, 'All questions failed to save. Check error details.')
            return redirect('worksheets:preview', session_id=session.pk)

        # Create the Worksheet
        with transaction.atomic():
            from classroom.models import Level
            year_level = data.get('year_level')
            level = None
            if year_level:
                level = Level.objects.filter(level_number=int(year_level)).first()

            worksheet = Worksheet.objects.create(
                school=school,
                name=worksheet_name,
                original_filename=session.pdf_filename,
                level=level,
                created_by=request.user,
                question_count=0,
            )

            # Re-query the questions we just saved, in order
            from maths.models import Question as MathsQuestion
            from ai_import.services import _resolve_topic_for_question

            order = 1
            for q in questions_data:
                if not q.get('include', True):
                    continue
                q_text = q.get('question_text', '').strip()
                if not q_text:
                    continue

                # Resolve the topic/level to find the saved question
                subject, topic, level_obj, topic_slug, yl = _resolve_topic_for_question(q, data)
                if not level_obj:
                    continue

                from classroom.views import _get_question_scope
                school_id, dept_id, classroom_ids = _get_question_scope(request.user)

                maths_q = MathsQuestion.objects.filter(
                    question_text=q_text,
                    topic=topic,
                    level=level_obj,
                    school_id=school_id,
                ).first()

                if maths_q:
                    WorksheetQuestion.objects.create(
                        worksheet=worksheet,
                        question=maths_q,
                        order=order,
                        subject_slug='mathematics',
                        content_id=maths_q.id,
                    )
                    order += 1

            worksheet.refresh_question_count()

        # Mark session as confirmed
        session.is_confirmed = True
        session.worksheet = worksheet
        session.save(update_fields=['is_confirmed', 'worksheet'])

        messages.success(
            request,
            f'Worksheet "{worksheet.name}" created with {worksheet.question_count} questions.',
        )
        return redirect('worksheets:detail', pk=worksheet.pk)


# ---------------------------------------------------------------------------
# Teacher: Worksheet Management
# ---------------------------------------------------------------------------

class WorksheetDetailView(RoleRequiredMixin, View):
    """View a worksheet's questions and manage assignments."""
    required_roles = TEACHER_ROLES

    def get(self, request, pk):
        school = get_school_for_user(request.user)
        worksheet = get_object_or_404(Worksheet, pk=pk, school=school)
        wqs = worksheet.worksheet_questions.select_related(
            'question', 'question__topic', 'question__topic__parent',
            'coding_exercise', 'coding_exercise__topic_level',
            'coding_exercise__topic_level__topic',
            'coding_exercise__topic_level__topic__language',
        ).prefetch_related('question__answers', 'coding_exercise__answers')
        assignments = worksheet.assignments.select_related('classroom').order_by('-assigned_at')

        from classroom.models import ClassRoom
        classrooms = ClassRoom.objects.filter(
            school=school, is_active=True,
        ).order_by('name')

        return render(request, 'worksheets/detail.html', {
            'worksheet': worksheet,
            'worksheet_questions': wqs,
            'assignments': assignments,
            'classrooms': classrooms,
        })


class WorksheetDeleteView(RoleRequiredMixin, View):
    """Delete a worksheet. Blocked if it has any assignment."""
    required_roles = TEACHER_ROLES

    def post(self, request, pk):
        school = get_school_for_user(request.user)
        worksheet = get_object_or_404(Worksheet, pk=pk, school=school)

        if worksheet.assignments.exists():
            messages.error(request, 'Cannot delete a worksheet that has been assigned to a class. Deactivate assignments first.')
            return redirect('worksheets:detail', pk=pk)

        name = worksheet.name
        worksheet.delete()
        messages.success(request, f'Worksheet "{name}" deleted.')
        return redirect('worksheets:list')


# ---------------------------------------------------------------------------
# Teacher: Assignment
# ---------------------------------------------------------------------------

class WorksheetAssignView(RoleRequiredMixin, View):
    """Assign a worksheet to a class with a question range."""
    required_roles = TEACHER_ROLES

    def post(self, request, pk):
        school = get_school_for_user(request.user)
        worksheet = get_object_or_404(Worksheet, pk=pk, school=school)

        from classroom.models import ClassRoom
        classroom_id = request.POST.get('classroom_id')
        classroom = get_object_or_404(ClassRoom, pk=classroom_id, school=school)

        range_type = request.POST.get('range_type', 'all')
        total = worksheet.question_count

        if range_type == 'first_n':
            n = int(request.POST.get('first_n', total))
            question_start = 1
            question_end = min(n, total)
        elif range_type == 'range':
            question_start = max(1, int(request.POST.get('range_from', 1)))
            question_end = min(int(request.POST.get('range_to', total)), total)
            if question_start > question_end:
                messages.error(request, 'Range start must be less than or equal to range end.')
                return redirect('worksheets:detail', pk=pk)
        else:
            question_start = 1
            question_end = None

        assignment = WorksheetAssignment.objects.create(
            worksheet=worksheet,
            classroom=classroom,
            question_start=question_start,
            question_end=question_end,
            assigned_by=request.user,
            is_active=True,
        )
        messages.success(
            request,
            f'Worksheet assigned to {classroom.name}. {assignment.assigned_question_count} questions.',
        )
        return redirect('worksheets:assignment_detail', pk=assignment.pk)


class AssignmentDetailView(RoleRequiredMixin, View):
    """Teacher view: assignment progress across the class."""
    required_roles = TEACHER_ROLES

    def get(self, request, pk):
        school = get_school_for_user(request.user)
        assignment = get_object_or_404(
            WorksheetAssignment, pk=pk, worksheet__school=school,
        )
        submissions = assignment.submissions.select_related('student').prefetch_related('answers')
        assigned_questions = list(assignment.assigned_questions)

        # Build student progress list
        from classroom.models import ClassStudent
        enrolled_students = ClassStudent.objects.filter(
            classroom=assignment.classroom, is_active=True,
        ).select_related('student')

        student_progress = []
        for cs in enrolled_students:
            sub = next((s for s in submissions if s.student_id == cs.student_id), None)
            student_progress.append({
                'student': cs.student,
                'submission': sub,
                'answered': sub.answered_count if sub else 0,
                'total': assignment.assigned_question_count,
                'score': sub.score if sub else 0,
                'is_complete': sub.is_complete if sub else False,
            })

        return render(request, 'worksheets/assignment_detail.html', {
            'assignment': assignment,
            'assigned_questions': assigned_questions,
            'student_progress': student_progress,
            'submissions': submissions,
        })


class AssignmentToggleView(RoleRequiredMixin, View):
    """Toggle assignment active/inactive (HTMX-friendly)."""
    required_roles = TEACHER_ROLES

    def post(self, request, pk):
        school = get_school_for_user(request.user)
        assignment = get_object_or_404(
            WorksheetAssignment, pk=pk, worksheet__school=school,
        )
        assignment.is_active = not assignment.is_active
        assignment.save(update_fields=['is_active'])

        if request.headers.get('HX-Request'):
            status = 'Active' if assignment.is_active else 'Inactive'
            btn_class = 'bg-emerald-100 text-emerald-700' if assignment.is_active else 'bg-gray-100 text-gray-500'
            return JsonResponse({'is_active': assignment.is_active, 'label': status})

        return redirect('worksheets:assignment_detail', pk=pk)


# ---------------------------------------------------------------------------
# Student: Worksheet Session
# ---------------------------------------------------------------------------

def _get_student_assignment(request, pk):
    """Get a WorksheetAssignment visible to the current student."""
    from classroom.models import ClassStudent
    assignment = get_object_or_404(WorksheetAssignment, pk=pk, is_active=True)
    # Ensure the student is enrolled in the assignment's class
    if not request.user.is_superuser:
        enrolled = ClassStudent.objects.filter(
            classroom=assignment.classroom,
            student=request.user,
            is_active=True,
        ).exists()
        if not enrolled:
            from django.http import Http404
            raise Http404
    return assignment


class WorksheetSessionView(LoginRequiredMixin, View):
    """Student: start or resume a worksheet session."""

    def get(self, request, pk):
        from classroom.subject_registry import get as get_plugin

        assignment = _get_student_assignment(request, pk)
        assigned_qs = list(assignment.assigned_questions)

        # Get or create submission
        submission, created = WorksheetSubmission.objects.get_or_create(
            assignment=assignment,
            student=request.user,
            defaults={'total_questions': len(assigned_qs)},
        )

        if submission.is_complete:
            return redirect('worksheets:results', pk=pk)

        # Track answered by (subject_slug, content_id) pairs — works for any plugin
        answered_pairs = set(
            submission.answers.values_list('subject_slug', 'content_id')
        )
        current_wq = None
        for wq in assigned_qs:
            if (wq.subject_slug, wq.content_id) not in answered_pairs:
                current_wq = wq
                break

        if current_wq is None:
            submission.completed_at = timezone.now()
            submission.save(update_fields=['completed_at'])
            return redirect('worksheets:results', pk=pk)

        question_number = assigned_qs.index(current_wq) + 1
        answered_count = len(answered_pairs)

        # Dispatch rendering by subject plugin
        if current_wq.subject_slug == 'coding':
            plugin = get_plugin('coding')
            ctx = plugin.take_item_context(current_wq.content_id)
            return render(request, 'worksheets/session.html', {
                'assignment': assignment,
                'submission': submission,
                'current_wq': current_wq,
                'question_number': question_number,
                'total_questions': len(assigned_qs),
                'answered_count': answered_count,
                'is_coding': True,
                'coding_ctx': ctx,
            })

        # Maths question
        question = current_wq.question
        answers = list(question.answers.order_by('order'))
        answer_partial = ANSWER_PARTIAL_MAP.get(question.question_type, _ANSWER_PARTIAL_DEFAULT)

        return render(request, 'worksheets/session.html', {
            'assignment': assignment,
            'submission': submission,
            'current_wq': current_wq,
            'question': question,
            'answers': answers,
            'answer_partial': answer_partial,
            'question_number': question_number,
            'total_questions': len(assigned_qs),
            'answered_count': answered_count,
        })


# ---------------------------------------------------------------------------
# CPP-281: Grading helpers
# ---------------------------------------------------------------------------

def _grade_long_division(question, text_answer: str) -> bool:
    """
    Grade a long-division answer submitted as "quotient r remainder" or just "quotient".
    Accepts "6 r 0" and "6" as equivalent when expected remainder is 0.
    """
    if not (question.dividend and question.divisor):
        return False
    try:
        expected_quotient = question.dividend // question.divisor
        expected_remainder = question.dividend % question.divisor

        text = text_answer.strip().lower().replace(' r ', ' r')
        if ' r' in text:
            parts = text.split(' r', 1)
            submitted_quotient = int(parts[0].strip())
            submitted_remainder = int(parts[1].strip()) if parts[1].strip() else 0
        else:
            submitted_quotient = int(text.strip())
            submitted_remainder = 0

        return submitted_quotient == expected_quotient and submitted_remainder == expected_remainder
    except (ValueError, TypeError, IndexError):
        return False


def _prime_factors(n: int):
    """Return sorted list of prime factors of n (with repetition), e.g. 12 → [2, 2, 3]."""
    factors = []
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors.append(d)
            n //= d
        d += 1
    if n > 1:
        factors.append(n)
    return sorted(factors)


def _grade_prime_factorization(question, text_answer: str) -> bool:
    """
    Grade a prime-factorisation answer submitted as "2x3x5" (factors joined by 'x').
    Order-insensitive — compares sorted factor lists.
    """
    if not question.target_number:
        return False
    try:
        raw = text_answer.strip().lower().replace('×', 'x')
        if not raw:
            return False
        submitted_factors = sorted(int(f.strip()) for f in raw.split('x') if f.strip())
        expected_factors = _prime_factors(question.target_number)
        return submitted_factors == expected_factors
    except (ValueError, TypeError):
        return False


class WorksheetAnswerView(LoginRequiredMixin, View):
    """HTMX: student submits an answer; returns feedback partial."""

    def post(self, request, pk):
        from classroom.subject_registry import get as get_plugin

        assignment = _get_student_assignment(request, pk)
        assigned_qs = list(assignment.assigned_questions.select_related(
            'question', 'coding_exercise',
        ).prefetch_related('question__answers'))

        submission = get_object_or_404(
            WorksheetSubmission, assignment=assignment, student=request.user,
        )

        subject_slug = request.POST.get('subject_slug', 'mathematics')
        content_id = int(request.POST.get('content_id', 0))

        # --- Coding exercise grading ---
        if subject_slug == 'coding':
            from coding.models import CodingExercise as CodingExModel
            plugin = get_plugin('coding')
            result = plugin.grade_answer(content_id, request.POST)
            coding_ex = get_object_or_404(CodingExModel, pk=content_id)
            student_answer, _ = WorksheetStudentAnswer.objects.update_or_create(
                submission=submission,
                subject_slug='coding',
                content_id=content_id,
                defaults={
                    'coding_exercise': coding_ex,
                    'question': None,
                    'text_answer': result.get('text_answer', ''),
                    'is_correct': result.get('is_correct', False),
                    'points_earned': float(result.get('points_earned', 0)),
                    'answer_data': result.get('answer_data', {}),
                },
            )
        else:
            # --- Maths question grading ---
            from maths.models import Question as MathsQuestion, Answer as MathsAnswer
            question = get_object_or_404(MathsQuestion, pk=content_id)

            selected_answer = None
            text_answer = ''
            is_correct = False
            points_earned = 0.0
            answer_data = {}

            if question.question_type in ('multiple_choice', 'true_false'):
                answer_id = request.POST.get('answer_id')
                if answer_id:
                    selected_answer = get_object_or_404(MathsAnswer, pk=answer_id, question=question)
                    is_correct = selected_answer.is_correct
                    if is_correct:
                        points_earned = float(question.points)

            elif question.question_type == 'long_division':
                text_answer = request.POST.get('text_answer', '').strip()
                is_correct = _grade_long_division(question, text_answer)
                if is_correct:
                    points_earned = float(question.points)

            elif question.question_type == 'prime_factorization':
                text_answer = request.POST.get('text_answer', '').strip()
                is_correct = _grade_prime_factorization(question, text_answer)
                if is_correct:
                    points_earned = float(question.points)

            elif question.question_type == 'extended_answer':
                text_answer = request.POST.get('text_answer', '').strip()
                school = get_school_for_user(request.user)
                try:
                    result = grade_extended_answer(question, text_answer, school=school)
                    is_correct = result.get('is_correct', False)
                    score_frac = result.get('score_fraction', 0.0)
                    answer_data = {
                        'feedback': result.get('feedback', ''),
                        'score_fraction': score_frac,
                        'cache_hit': result.get('cache_hit', False),
                        'is_partial': result.get('is_partial', 0.1 <= score_frac < 0.6),
                        'what_was_correct': result.get('what_was_correct', ''),
                        'what_to_add': result.get('what_to_add', ''),
                    }
                    if result.get('quota_exceeded'):
                        answer_data['review_status'] = 'pending_ai'
                    if is_correct:
                        points_earned = float(question.points)
                    elif answer_data['is_partial']:
                        points_earned = round(float(question.points) * score_frac, 2)
                except Exception as exc:
                    logger.exception(f'Extended answer grading failed for Q{question.pk}: {exc}')
                    answer_data = {'review_status': 'pending_ai'}

            else:
                text_answer = request.POST.get('text_answer', '').strip()
                correct_answers = [
                    a.answer_text.strip().lower()
                    for a in question.answers.filter(is_correct=True)
                ]
                if text_answer.lower() in correct_answers:
                    is_correct = True
                    points_earned = float(question.points)

            student_answer, _ = WorksheetStudentAnswer.objects.update_or_create(
                submission=submission,
                subject_slug='mathematics',
                content_id=content_id,
                defaults={
                    'question': question,
                    'selected_answer': selected_answer,
                    'text_answer': text_answer,
                    'is_correct': is_correct,
                    'points_earned': points_earned,
                    'answer_data': answer_data,
                },
            )

        # Update submission score
        submission.score = submission.answers.filter(is_correct=True).count()
        submission.save(update_fields=['score'])

        # Determine next question
        answered_pairs = set(submission.answers.values_list('subject_slug', 'content_id'))
        next_wq = None
        for wq in assigned_qs:
            if (wq.subject_slug, wq.content_id) not in answered_pairs:
                next_wq = wq
                break

        is_last = next_wq is None
        if is_last and not submission.is_complete:
            submission.completed_at = timezone.now()
            submission.save(update_fields=['completed_at'])

        # Render feedback partial
        if subject_slug == 'coding':
            return render(request, 'worksheets/answer_feedback.html', {
                'student_answer': student_answer,
                'is_correct': student_answer.is_correct,
                'is_last': is_last,
                'assignment_pk': pk,
                'next_wq': next_wq,
                'is_coding': True,
            })

        return render(request, 'worksheets/answer_feedback.html', {
            'question': question,
            'student_answer': student_answer,
            'is_correct': is_correct,
            'correct_answers': list(question.answers.filter(is_correct=True).values('answer_text')),
            'is_last': is_last,
            'assignment_pk': pk,
            'next_wq': next_wq,
        })


class WorksheetResultsView(LoginRequiredMixin, View):
    """Student: show completion screen with score and wrong-answer review."""

    def get(self, request, pk):
        from classroom.subject_registry import get as get_plugin

        assignment = _get_student_assignment(request, pk)
        submission = get_object_or_404(
            WorksheetSubmission, assignment=assignment, student=request.user,
        )

        answers = list(submission.answers.select_related(
            'question', 'selected_answer', 'coding_exercise',
        ).prefetch_related('question__answers').order_by('answered_at'))

        # Build plugin-dispatched review items (same pattern as homework result view)
        review_items = []
        for ans in answers:
            plugin = get_plugin(ans.subject_slug)
            if plugin is None:
                continue
            review_items.append({
                'ans': ans,
                'template': plugin.result_item_template(),
                'ctx': plugin.result_item_context(ans),
            })

        return render(request, 'worksheets/results.html', {
            'assignment': assignment,
            'submission': submission,
            'answers': answers,
            'review_items': review_items,
        })


# ---------------------------------------------------------------------------
# Student: Worksheet Assignment List
# ---------------------------------------------------------------------------

class StudentWorksheetListView(LoginRequiredMixin, View):
    """Student: list active worksheet assignments for their classes.

    Accepts an optional ``?subject=<slug>`` query param to filter to worksheets
    that contain questions from a specific subject plugin (e.g. ``mathematics``
    or ``coding``).  Omitting the param returns all subjects.
    """

    def get(self, request):
        from classroom.models import ClassStudent
        # Optional subject filter from sidebar links (e.g. ?subject=mathematics)
        subject_filter = request.GET.get('subject', '').strip().lower() or None

        # Get all active class enrolments for this student
        class_ids = ClassStudent.objects.filter(
            student=request.user, is_active=True,
        ).values_list('classroom_id', flat=True)

        # Active assignments across those classes
        assignments = WorksheetAssignment.objects.filter(
            classroom_id__in=class_ids,
            is_active=True,
        ).select_related('worksheet', 'classroom').order_by('-assigned_at')

        # Filter to a specific subject if requested
        if subject_filter:
            assignments = assignments.filter(
                worksheet__worksheet_questions__subject_slug=subject_filter,
            ).distinct()

        # Attach submission info to each assignment
        submissions = WorksheetSubmission.objects.filter(
            assignment__in=assignments,
            student=request.user,
        ).select_related('assignment')
        submissions_by_assignment = {s.assignment_id: s for s in submissions}

        assignment_rows = []
        for a in assignments:
            sub = submissions_by_assignment.get(a.pk)
            assignment_rows.append({
                'assignment': a,
                'submission': sub,
                'answered': sub.answered_count if sub else 0,
                'total': a.assigned_question_count,
                'is_complete': sub.is_complete if sub else False,
                'percentage': sub.percentage if sub else 0,
            })

        # Human-readable subject label for the page heading
        subject_labels = {
            'mathematics': 'Maths',
            'coding': 'Coding',
        }
        subject_label = subject_labels.get(subject_filter, subject_filter.title() if subject_filter else None)

        return render(request, 'worksheets/student_list.html', {
            'assignment_rows': assignment_rows,
            'subject_filter': subject_filter,
            'subject_label': subject_label,
        })
