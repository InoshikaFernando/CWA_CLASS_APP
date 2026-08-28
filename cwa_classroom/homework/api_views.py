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

from api.permissions import IsStudent
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
        if params.get('classroom'):
            queryset = queryset.filter(classroom_id=params['classroom'])
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
        """Hand in one complete attempt."""
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
        answers = serializer.validated_data['answers']

        assigned = {
            question.id: question
            for question in HomeworkQuestion.objects.filter(homework=homework)
        }
        unknown = [row['question_id'] for row in answers
                   if row['question_id'] not in assigned]
        if unknown:
            # Refusing the whole attempt beats recording a partial one: a
            # partial attempt still burns one of a limited number of tries.
            raise ValidationError({
                'answers': [f'Not part of this homework: {unknown}']})

        with transaction.atomic():
            submission = HomeworkSubmission.objects.create(
                homework=homework,
                student=student,
                attempt_number=used + 1,
                score=sum(1 for row in answers if row['is_correct']),
                total_questions=len(assigned) or len(answers),
                time_taken_seconds=serializer.validated_data.get('time_taken_seconds', 0),
            )
            HomeworkStudentAnswer.objects.bulk_create([
                HomeworkStudentAnswer(
                    submission=submission,
                    question=assigned[row['question_id']].question,
                    subject_slug=assigned[row['question_id']].subject_slug,
                    content_id=assigned[row['question_id']].content_id,
                    text_answer=row['answer'],
                    is_correct=row['is_correct'],
                    points_earned=1.0 if row['is_correct'] else 0.0,
                )
                for row in answers
            ])

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
        if params.get('homework'):
            queryset = queryset.filter(homework_id=params['homework'])
        if params.get('student'):
            queryset = queryset.filter(student_id=params['student'])
        return queryset.order_by('-submitted_at', 'id')

    @extend_schema(responses=HomeworkStudentAnswerSerializer(many=True))
    @action(detail=True, methods=['get'])
    def answers(self, request, pk=None):
        """The per-question breakdown, with whatever feedback exists."""
        submission = self.get_object()
        answers = HomeworkStudentAnswer.objects.filter(submission=submission).order_by('id')
        return Response(HomeworkStudentAnswerSerializer(answers, many=True).data)
