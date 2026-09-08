"""Homework API — what a student is set, and what they hand in.

The student-visibility rule here is not obvious and is copied from the web
view deliberately (``homework.views.StudentHomeworkListView``): a student who
has LEFT a class but is still in the school keeps that class's homework, which
is what ``moved_at`` records. Only a whole-school removal — inactive with
``moved_at`` unset — takes it away. Filtering on ``is_active=True`` alone would
quietly delete a moved student's history from their own app.
"""

from django.db.models import Count, Q
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from api.filters import int_param
from api.permissions import IsStudent
from audit.services import log_event
from api.scoping import classrooms_for, scope_by_student
from classroom.models import ClassStudent
from homework.api_serializers import (
    HomeworkQuestionSerializer, HomeworkSerializer,
    HomeworkStudentAnswerSerializer, HomeworkSubmissionSerializer,
    HomeworkSubmitSerializer,
)
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudentAnswer, HomeworkSubmission,
)


def student_class_ids(user):
    """Classes whose homework *user* may still open. See the module docstring."""
    return list(
        ClassStudent.objects
        .filter(Q(is_active=True) | Q(moved_at__isnull=False), student=user)
        .values_list('classroom_id', flat=True)
    )


class HomeworkViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      viewsets.GenericViewSet):
    """Homework the caller can see.

    A student sees published homework for their classes. Staff see everything
    in the classes they teach or administer, including drafts and scheduled
    items that have not gone live.
    """

    serializer_class = HomeworkSerializer
    ordering_fields = ('due_date', 'created_at')
    search_fields = ('title',)
    # Declared for schema generation only — get_queryset() is what runs, and it
    # is always narrowed to the caller.
    queryset = Homework.objects.none()

    @extend_schema(parameters=[
        OpenApiParameter('classroom', int, description='Filter to one class id.'),
        OpenApiParameter('status', str,
                         description='created | published | expired'),
        OpenApiParameter('due', str,
                         description='upcoming | overdue'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        # Homework.objects hides soft-deleted rows via HomeworkManager, so a
        # homework a teacher removed disappears here too without this view
        # needing to know about deleted_at.
        queryset = Homework.objects.select_related('classroom').prefetch_related('topics')

        if user.is_student or user.is_individual_student:
            queryset = queryset.filter(
                classroom_id__in=student_class_ids(user),
                published_at__isnull=False,
            ).annotate(student_attempts=Count(
                'submissions',
                filter=Q(submissions__student=user),
                distinct=True,
            ))
        else:
            # Teachers, institute staff and parents see through their classes.
            queryset = queryset.filter(classroom__in=classrooms_for(user))

        params = self.request.query_params
        classroom_id = int_param(params, 'classroom')
        if classroom_id is not None:
            queryset = queryset.filter(classroom_id=classroom_id)
        if params.get('due') == 'upcoming':
            queryset = queryset.filter(due_date__gte=timezone.now())
        elif params.get('due') == 'overdue':
            queryset = queryset.filter(due_date__lt=timezone.now())

        requested_status = params.get('status')
        if requested_status == Homework.STATUS_PUBLISHED:
            queryset = queryset.filter(published_at__isnull=False,
                                       due_date__gte=timezone.now())
        elif requested_status == Homework.STATUS_CREATED:
            queryset = queryset.filter(published_at__isnull=True)
        elif requested_status == Homework.STATUS_EXPIRED:
            queryset = queryset.filter(due_date__lt=timezone.now())

        return queryset.order_by('due_date', 'id')

    @extend_schema(responses=HomeworkQuestionSerializer(many=True))
    @action(detail=True, methods=['get'])
    def questions(self, request, pk=None):
        """The items assigned, in order.

        Only identifiers are returned — the app fetches each item's body from
        the subject that owns it. Sending the maths answer key alongside the
        question would put the correct answers on the device before the
        student has answered.
        """
        homework = self.get_object()
        questions = HomeworkQuestion.objects.filter(homework=homework).order_by('order', 'id')
        return Response(HomeworkQuestionSerializer(questions, many=True).data)

    @extend_schema(
        request=HomeworkSubmitSerializer,
        responses={201: HomeworkSubmissionSerializer},
    )
    @action(detail=True, methods=['post'], permission_classes=[IsStudent])
    def submit(self, request, pk=None):
        """Hand in one complete attempt.

        Marking happens HERE, through the same subject plugins the web view
        uses (``classroom.subject_registry``). The client sends only what the
        student answered — an endpoint that accepted the client's own verdict
        on correctness would let anyone POST a perfect score, and the score
        would look exactly like an honest one in every report afterwards.

        The rest of the submission pipeline is the web view's, not a
        re-implementation: the attempt number comes from
        ``get_next_attempt_number`` (``count() + 1`` collides with the
        unique constraint once ``prune_old_attempts`` has deleted a row),
        points from ``calculate_points``, and the leaderboard award, pruning
        and audit entry from the helpers that already exist. Anything less
        and an attempt made in the app is worth nothing on the leaderboard
        while an identical one made in the browser counts.
        """
        homework = self.get_object()
        student = request.user

        if not homework.is_published:
            raise ValidationError({'detail': 'This homework is not published yet.'})

        membership = ClassStudent.objects.filter(
            Q(is_active=True) | Q(moved_at__isnull=False),
            student=student, classroom=homework.classroom,
        ).first()
        if membership is None:
            raise ValidationError({'detail': 'You are not enrolled in this class.'})

        used = HomeworkSubmission.objects.filter(homework=homework, student=student).count()
        if not homework.attempts_unlimited and used >= homework.max_attempts:
            raise ValidationError({
                'detail': f'You have used all {homework.max_attempts} attempts.'})

        serializer = HomeworkSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answers_by_question = {
            row['question_id']: row['answer']
            for row in serializer.validated_data['answers']
        }
        time_taken = serializer.validated_data.get('time_taken_seconds', 0)

        assigned = list(homework.homework_questions.order_by('order'))
        assigned_ids = {question.id for question in assigned}
        unknown = sorted(set(answers_by_question) - assigned_ids)
        if unknown:
            # Refusing the whole attempt beats recording a partial one: a
            # partial attempt still burns one of a limited number of tries.
            raise ValidationError({
                'answers': [f'Not part of this homework: {unknown}']})

        return _record_attempt(request, homework, student, assigned,
                               answers_by_question, time_taken)


def _record_attempt(request, homework, student, assigned, answers_by_question,
                    time_taken):
    """Grade and persist one attempt, mirroring StudentHomeworkTakeView.post."""
    from classroom.subject_registry import get as get_plugin
    from homework.views import _award_homework_points, calculate_points
    from maths.models import Question

    # Grade OUTSIDE the transaction: a coding item calls Piston over HTTP and
    # would otherwise hold a DB transaction open for seconds at a time.
    plugin_lookup = {}
    for question in assigned:
        if question.subject_slug not in plugin_lookup:
            plugin_lookup[question.subject_slug] = get_plugin(question.subject_slug)

    graded_rows = []
    for question in assigned:
        if question.id not in answers_by_question:
            # Unanswered. Recorded as wrong rather than skipped so
            # total_questions and the per-question review both stay honest.
            graded_rows.append((question, None))
            continue
        plugin = plugin_lookup.get(question.subject_slug)
        if plugin is None:
            graded_rows.append((question, None))
            continue
        # Plugins read the answer under `answer_<content_id>`, the same key the
        # web form posts.
        payload = {f'answer_{question.content_id}': answers_by_question[question.id]}
        try:
            graded_rows.append((question, plugin.grade_answer(question.content_id, payload)))
        except Exception:
            # A per-item grading failure must not lose the whole submission —
            # the web path takes the same view. The row is marked wrong and
            # says why, rather than vanishing.
            graded_rows.append((question, {
                'is_correct': False, 'points_earned': 0, 'text_answer': '',
                'selected_answer_id': None, 'question_id': None,
                'answer_data': {'error': 'grading failed'},
            }))

    score = 0
    credit = 0.0
    total = len(assigned)
    answer_records = []
    for question, graded in graded_rows:
        graded = graded or {
            'is_correct': False, 'points_earned': 0, 'text_answer': '',
            'selected_answer_id': None, 'question_id': None, 'answer_data': {},
        }
        if graded.get('is_correct'):
            score += 1
        credit += float(graded.get('points_earned') or 0)
        answer_records.append(HomeworkStudentAnswer(
            question_id=graded.get('question_id') or question.question_id,
            selected_answer_id=graded.get('selected_answer_id'),
            text_answer=graded.get('text_answer', ''),
            subject_slug=question.subject_slug,
            content_id=question.content_id,
            answer_data=graded.get('answer_data', {}),
            is_correct=graded.get('is_correct', False),
            points_earned=graded.get('points_earned', 0),
        ))

    with transaction.atomic():
        submission = HomeworkSubmission.objects.create(
            homework=homework,
            student=student,
            attempt_number=HomeworkSubmission.get_next_attempt_number(homework, student),
            total_questions=total,
            time_taken_seconds=time_taken,
        )
        for row in answer_records:
            row.submission = submission

        # Maths questions marked for AI or human review are queued rather than
        # reported as finally graded.
        question_ids = [row.question_id for row in answer_records if row.question_id]
        if question_ids:
            validation = dict(
                Question.objects.filter(id__in=question_ids)
                .values_list('id', 'validation_type')
            )
            for row in answer_records:
                if not row.question_id:
                    continue
                kind = validation.get(row.question_id, 'auto')
                if kind == Question.VALIDATION_AI:
                    row.review_status = HomeworkStudentAnswer.REVIEW_PENDING_AI
                elif kind == Question.VALIDATION_HUMAN:
                    row.review_status = HomeworkStudentAnswer.REVIEW_PENDING_TEACHER

        HomeworkStudentAnswer.objects.bulk_create(answer_records)

        submission.score = score
        submission.points = calculate_points(credit, total, time_taken)
        submission.save(update_fields=['score', 'points'])

        HomeworkSubmission.prune_old_attempts(homework, student)

    _award_homework_points(submission)

    log_event(
        user=student,
        school=homework.classroom.school,
        category='data_change',
        action='homework_submitted',
        request=request,
    )

    return Response(
        HomeworkSubmissionSerializer(submission).data,
        status=status.HTTP_201_CREATED,
    )


class HomeworkSubmissionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                                viewsets.GenericViewSet):
    """Submissions for students the caller may read."""

    serializer_class = HomeworkSubmissionSerializer
    ordering_fields = ('submitted_at', 'score')

    @extend_schema(parameters=[
        OpenApiParameter('homework', int, description='Filter to one homework id.'),
        OpenApiParameter('student', int, description='Filter to one student id.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = scope_by_student(
            HomeworkSubmission.objects.select_related('homework', 'student'),
            self.request.user,
        )
        params = self.request.query_params
        homework_id = int_param(params, 'homework')
        if homework_id is not None:
            queryset = queryset.filter(homework_id=homework_id)
        student_id = int_param(params, 'student')
        if student_id is not None:
            queryset = queryset.filter(student_id=student_id)
        return queryset.order_by('-submitted_at', 'id')

    @extend_schema(responses=HomeworkStudentAnswerSerializer(many=True))
    @action(detail=True, methods=['get'])
    def answers(self, request, pk=None):
        """The per-question breakdown, with whatever feedback exists."""
        submission = self.get_object()
        answers = HomeworkStudentAnswer.objects.filter(submission=submission).order_by('id')
        return Response(HomeworkStudentAnswerSerializer(answers, many=True).data)
