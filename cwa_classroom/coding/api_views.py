"""Coding practice API.

``CodingExercise.solution_code`` is the reference solution and its own
help_text says it is shown to teachers and never to students. The serializer
therefore drops it per-request rather than relying on every view remembering
to defer it — a field excluded in one place cannot be forgotten in the next.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, viewsets

from api.filters import int_param
from api.pagination import LargePagination
from api.scoping import scope_by_student
from coding.models import (
    CodingExercise, CodingLanguage, CodingTopic, StudentExerciseSubmission,
)


class CodingLanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodingLanguage
        fields = '__all__'


class CodingTopicSerializer(serializers.ModelSerializer):
    language_name = serializers.CharField(source='language.name', read_only=True)

    class Meta:
        model = CodingTopic
        fields = ('id', 'name', 'slug', 'description', 'order',
                  'language_id', 'language_name')


class CodingExerciseSerializer(serializers.ModelSerializer):
    """An exercise as the student opens it.

    ``solution_code`` is present in ``Meta.fields`` only so staff can read it;
    ``to_representation`` removes it for everyone else. Putting the reference
    solution on a student's device would end the exercise.
    """

    class Meta:
        model = CodingExercise
        fields = (
            'id', 'title', 'description', 'starter_code', 'expected_output',
            'hints', 'order', 'question_type', 'uses_browser_sandbox',
            'topic_level_id', 'solution_code',
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        is_staff = bool(user and (user.is_superuser or user.is_any_teacher
                                  or user.is_head_of_department
                                  or user.is_head_of_institute
                                  or user.is_institute_owner))
        if not is_staff:
            data.pop('solution_code', None)
        return data


class StudentExerciseSubmissionSerializer(serializers.ModelSerializer):
    """A student's attempt at an exercise.

    ``exercise`` is a real relation field, not a bare ``exercise_id``: DRF does
    not treat ``<fk>_id`` as writable, so naming it that way meant the value
    was dropped on create and the write failed with a 500 instead of a
    validation error.
    """

    exercise = serializers.PrimaryKeyRelatedField(
        queryset=CodingExercise.objects.filter(is_active=True))

    class Meta:
        model = StudentExerciseSubmission
        fields = (
            'id', 'exercise', 'code_submitted', 'output_received',
            'stderr_received', 'is_completed', 'time_taken_seconds',
            'submitted_at',
        )
        read_only_fields = ('id', 'submitted_at')


class CodingLanguageViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = CodingLanguageSerializer
    pagination_class = LargePagination
    queryset = CodingLanguage.objects.all()


class CodingTopicViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         viewsets.GenericViewSet):
    serializer_class = CodingTopicSerializer
    pagination_class = LargePagination
    queryset = (CodingTopic.objects.filter(is_active=True)
                .select_related('language').order_by('order', 'name', 'id'))

    @extend_schema(parameters=[
        OpenApiParameter('language', int, description='Filter to one language id.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        language = int_param(self.request.query_params, 'language')
        return queryset.filter(language_id=language) if language is not None else queryset


class CodingExerciseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                            viewsets.GenericViewSet):
    serializer_class = CodingExerciseSerializer
    pagination_class = LargePagination
    queryset = (CodingExercise.objects.filter(is_active=True)
                .order_by('order', 'id'))

    @extend_schema(parameters=[
        OpenApiParameter('topic_level', int, description='Filter to one topic level.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        topic_level = int_param(self.request.query_params, 'topic_level')
        return queryset.filter(topic_level_id=topic_level) if topic_level is not None else queryset


class CodingSubmissionViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                              mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """A student's coding attempts.

    Creating one records what the student ran; grading and points stay with
    the existing coding views, which own that logic.
    """

    serializer_class = StudentExerciseSubmissionSerializer
    ordering_fields = ('submitted_at',)
    queryset = StudentExerciseSubmission.objects.none()  # schema generation only

    def get_queryset(self):
        queryset = scope_by_student(
            StudentExerciseSubmission.objects.select_related('exercise'),
            self.request.user,
        )
        exercise = int_param(self.request.query_params, 'exercise')
        if exercise is not None:
            queryset = queryset.filter(exercise_id=exercise)
        return queryset.order_by('-submitted_at', 'id')

    def perform_create(self, serializer):
        # The student is the caller, never the payload.
        serializer.save(student=self.request.user)
