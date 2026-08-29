"""Serializers for homework as the mobile app reads and submits it."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.serializers import UserSummarySerializer
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudentAnswer, HomeworkSubmission,
)


class HomeworkSerializer(serializers.ModelSerializer):
    classroom_id = serializers.IntegerField(read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)
    status = serializers.CharField(read_only=True)
    is_past_due = serializers.BooleanField(read_only=True)
    topics = serializers.SerializerMethodField()
    attempts_used = serializers.SerializerMethodField()
    best_score = serializers.SerializerMethodField()

    class Meta:
        model = Homework
        fields = (
            'id', 'title', 'description', 'homework_type', 'subject_slug',
            'classroom_id', 'classroom_name', 'num_questions', 'due_date',
            'max_attempts', 'published_at', 'status', 'is_past_due',
            'topics', 'attempts_used', 'best_score', 'created_at',
        )

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_topics(self, obj):
        return [topic.name for topic in obj.topics.all()]

    @extend_schema_field(serializers.IntegerField())
    def get_attempts_used(self, obj):
        """How many attempts the *requesting* student has already used.

        Annotated by the viewset for the list endpoint; falls back to a query
        for a single detail fetch. Returns 0 for a teacher, who has no
        attempts of their own on a homework they set.
        """
        annotated = getattr(obj, 'student_attempts', None)
        if annotated is not None:
            return annotated
        student = self._student()
        if student is None:
            return 0
        return HomeworkSubmission.objects.filter(homework=obj, student=student).count()

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_best_score(self, obj):
        student = self._student()
        if student is None:
            return None
        best = (HomeworkSubmission.objects
                .filter(homework=obj, student=student)
                .order_by('-score').first())
        return best.score if best else None

    def _student(self):
        request = self.context.get('request')
        if request is None:
            return None
        user = request.user
        return user if (user.is_student or user.is_individual_student) else None


class HomeworkQuestionSerializer(serializers.ModelSerializer):
    """One assigned item.

    ``content_id`` plus ``subject_slug`` is the real identity — a homework can
    hold maths questions, coding exercises or anything else the subject
    registry knows about, so the app resolves the body through the matching
    subject endpoint rather than expecting a maths question here.
    """

    class Meta:
        model = HomeworkQuestion
        fields = ('id', 'order', 'subject_slug', 'content_id')


class HomeworkStudentAnswerSerializer(serializers.ModelSerializer):
    """One graded answer, as the student sees it after submitting.

    Fields are listed explicitly rather than with ``__all__``: the model also
    carries the grading internals (which teacher graded it, the AI confidence
    fraction, the raw answer_data blob), and ``__all__`` would ship every one
    of those to the phone the moment someone adds a column.
    """

    feedback = serializers.CharField(source='feedback_for_student', read_only=True)
    is_pending_review = serializers.BooleanField(read_only=True)

    class Meta:
        model = HomeworkStudentAnswer
        fields = (
            'id', 'subject_slug', 'content_id', 'text_answer',
            'is_correct', 'points_earned', 'review_status',
            'is_pending_review', 'feedback',
        )
        read_only_fields = fields


class HomeworkSubmissionSerializer(serializers.ModelSerializer):
    student = UserSummarySerializer(read_only=True)
    homework_id = serializers.IntegerField(read_only=True)
    homework_title = serializers.CharField(source='homework.title', read_only=True)
    percentage = serializers.IntegerField(read_only=True)
    submission_status = serializers.CharField(read_only=True)

    class Meta:
        model = HomeworkSubmission
        fields = (
            'id', 'homework_id', 'homework_title', 'student', 'attempt_number',
            'score', 'total_questions', 'percentage', 'points',
            'time_taken_seconds', 'submission_status', 'submitted_at',
        )


class SubmittedAnswerSerializer(serializers.Serializer):
    """One answered item inside a submission payload.

    The client sends what the student ANSWERED and nothing about whether it
    was right. Marking is the server's job — see
    ``homework.api_views.HomeworkViewSet.submit``. An earlier version of this
    serializer accepted ``is_correct`` from the client, which let anyone with
    the endpoint POST themselves a perfect score.
    """

    question_id = serializers.IntegerField(
        help_text='HomeworkQuestion id this answer is for.')
    answer = serializers.CharField(
        allow_blank=True, trim_whitespace=False,
        help_text='The student\'s answer, as the subject plugin expects it: '
                  'the chosen Answer id for multiple choice / true-false, the '
                  'typed text for short answer, the source for a coding task.')


class HomeworkSubmitSerializer(serializers.Serializer):
    """A completed attempt, submitted in one request.

    Deliberately one call rather than an answer-at-a-time stream: a phone on a
    school's wifi drops connections mid-quiz, and a half-recorded attempt that
    still counts against ``max_attempts`` is worse than a failed one the
    student can retry.
    """

    answers = SubmittedAnswerSerializer(many=True, allow_empty=False)
    time_taken_seconds = serializers.IntegerField(required=False, min_value=0, default=0)

    def validate_answers(self, value):
        """One answer per question — a repeat would violate the answer table's
        (submission, subject_slug, content_id) unique constraint and surface as
        a 500 rather than a validation error."""
        seen = [row['question_id'] for row in value]
        duplicates = {qid for qid in seen if seen.count(qid) > 1}
        if duplicates:
            raise serializers.ValidationError(
                f'More than one answer given for question(s): {sorted(duplicates)}')
        return value
