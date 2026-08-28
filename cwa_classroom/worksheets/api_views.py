"""Worksheets API — what has been assigned, and how a student did on it."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, viewsets

from api.scoping import classrooms_for, scope_by_student
from worksheets.models import (
    Worksheet, WorksheetAssignment, WorksheetSubmission,
)


class WorksheetSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='level.display_name',
                                       read_only=True, default=None)

    class Meta:
        model = Worksheet
        fields = ('id', 'name', 'question_count', 'level_id', 'level_name',
                  'created_at')


class WorksheetAssignmentSerializer(serializers.ModelSerializer):
    worksheet = WorksheetSerializer(read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)

    class Meta:
        model = WorksheetAssignment
        fields = ('id', 'worksheet', 'classroom_id', 'classroom_name',
                  'question_start', 'question_end', 'assigned_at', 'is_active')


class WorksheetSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorksheetSubmission
        fields = ('id', 'assignment_id', 'student_id', 'score',
                  'total_questions', 'started_at', 'completed_at')


class WorksheetAssignmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                                 viewsets.GenericViewSet):
    """Assignments in classes the caller can see.

    The worksheet PDF itself is not linked here: it lives in private storage
    behind the existing worksheet views, and handing out a URL to it would
    bypass whatever those views check.
    """

    serializer_class = WorksheetAssignmentSerializer
    ordering_fields = ('assigned_at',)
    queryset = WorksheetAssignment.objects.none()  # schema generation only

    @extend_schema(parameters=[
        OpenApiParameter('classroom', int, description='Filter to one class id.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = (WorksheetAssignment.objects
                    .filter(classroom__in=classrooms_for(self.request.user),
                            is_active=True)
                    .select_related('worksheet__level', 'classroom'))
        classroom = self.request.query_params.get('classroom')
        if classroom:
            queryset = queryset.filter(classroom_id=classroom)
        return queryset.order_by('-assigned_at', 'id')


class WorksheetSubmissionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Worksheet results for students the caller may read."""

    serializer_class = WorksheetSubmissionSerializer
    ordering_fields = ('started_at', 'score')
    queryset = WorksheetSubmission.objects.none()  # schema generation only

    def get_queryset(self):
        return scope_by_student(
            WorksheetSubmission.objects.select_related('assignment'),
            self.request.user,
        ).order_by('-started_at', 'id')
