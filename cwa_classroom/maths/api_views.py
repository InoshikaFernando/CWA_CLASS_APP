"""Maths practice API.

The maths question bank is NOT exposed. ``maths.Question`` joins to
``maths.Answer``, which carries the correct answer and the explanation, and a
list endpoint over it would hand the answer key to any signed-in student. The
existing quiz views serve one question at a time and grade server-side; that
stays the only way to practise.

What is exposed is a student's own history — results and time spent — which is
what a progress screen needs and what a parent asks about.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from api.filters import int_param
from api.scoping import scope_by_student
from maths.models import BasicFactsResult, TimeLog


class BasicFactsResultSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='level.display_name',
                                       read_only=True, default=None)

    class Meta:
        model = BasicFactsResult
        fields = (
            'id', 'student_id', 'level_id', 'level_name', 'subtopic',
            'level_number', 'score', 'total_points', 'points',
            'time_taken_seconds', 'completed_at',
        )


class TimeLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimeLog
        fields = ('daily_total_seconds', 'weekly_total_seconds', 'last_activity')


class BasicFactsResultViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Basic-facts attempts for students the caller may read."""

    serializer_class = BasicFactsResultSerializer
    ordering_fields = ('completed_at', 'score')
    queryset = BasicFactsResult.objects.none()  # schema generation only

    @extend_schema(parameters=[
        OpenApiParameter('student', int, description='Filter to one student id.'),
        OpenApiParameter('subtopic', str, description='e.g. Addition.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = scope_by_student(
            BasicFactsResult.objects.select_related('level'), self.request.user)
        params = self.request.query_params
        student_id = int_param(params, 'student')
        if student_id is not None:
            queryset = queryset.filter(student_id=student_id)
        if params.get('subtopic'):
            queryset = queryset.filter(subtopic=params['subtopic'])
        return queryset.order_by('-completed_at', 'id')


class TimeSpentView(APIView):
    """Practice time for the caller today and this week.

    Reads through the model's own reset helpers so a stale daily total is
    rolled over rather than reported as today's — the same thing the web view
    does.
    """

    serializer_class = TimeLogSerializer

    @extend_schema(responses=TimeLogSerializer)
    def get(self, request):
        log = TimeLog.objects.filter(student=request.user).first()
        if log is None:
            return Response({'daily_total_seconds': 0,
                             'weekly_total_seconds': 0,
                             'last_activity': None})
        log.reset_daily_if_needed()
        log.reset_weekly_if_needed()
        return Response(TimeLogSerializer(log).data)
