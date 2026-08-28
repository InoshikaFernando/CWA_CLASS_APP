"""Points and leaderboard endpoints.

Ranking is not recomputed here. ``rewards.services`` already defines what a
board is (who is ranked, how ties break, how far the next rank is) and the web
hub renders from it; a second definition in the API would eventually disagree
with the website about a child's rank, which is the kind of bug a parent
reports and nobody can reproduce.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from api.filters import int_param
from api.permissions import CanViewStudentData
from api.scoping import scope_by_student
from rewards import services
from rewards.api_serializers import (
    PointsAwardSerializer, StandingSerializer, StudentPointsTotalSerializer,
)
from rewards.models import PointsAward, StudentPointsTotal


class PointsAwardViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Individual point awards for students the caller may read."""

    serializer_class = PointsAwardSerializer
    ordering_fields = ('points', 'first_earned_at')

    @extend_schema(parameters=[
        OpenApiParameter('student', int, description='Filter to one student id.'),
        OpenApiParameter('source', str, description='Filter to one points source.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = scope_by_student(
            PointsAward.objects.select_related('student'), self.request.user)
        params = self.request.query_params
        student_id = int_param(params, 'student')
        if student_id is not None:
            queryset = queryset.filter(student_id=student_id)
        if params.get('source'):
            queryset = queryset.filter(source=params['source'])
        return queryset.order_by('-points', 'source', 'id')


class PointsTotalView(APIView):
    """A student's running total.

    Defaults to the caller; a parent or teacher may ask for a student they are
    allowed to see by passing ``?student=``.
    """

    serializer_class = StudentPointsTotalSerializer

    @extend_schema(
        parameters=[OpenApiParameter(
            'student', int, description='Defaults to the caller.')],
        responses=StudentPointsTotalSerializer,
    )
    def get(self, request):
        student = _resolve_student(request)
        total = StudentPointsTotal.objects.filter(student=student).first()
        if total is None:
            # A student who has not scored yet is a real, expected state — it
            # is a zero, not a 404.
            return Response({
                'total_points': 0.0, 'units_completed': 0, 'is_ranked': True,
                'display_name': student.get_full_name() or student.username,
                'last_earned_at': None,
            })
        return Response(StudentPointsTotalSerializer(total).data)


class LeaderboardView(APIView):
    """The board a student sits on, global or school-scoped."""

    serializer_class = StandingSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter('student', int, description='Defaults to the caller.'),
            OpenApiParameter('scope', str, description="'global' (default) or 'school'."),
        ],
        responses=StandingSerializer,
    )
    def get(self, request):
        student = _resolve_student(request)
        scope = request.query_params.get('scope', services.SCOPE_GLOBAL)

        if scope == 'school':
            school = services.get_school_for(student)
            if school is None:
                # An individual student has no school board. Saying so beats
                # silently handing back the global one under a school label.
                return Response(
                    {'error': {'code': 'no_school_board',
                               'detail': 'This student is not a member of a school.'}},
                    status=404,
                )
            standing = services.get_student_standing(
                student, school=school, scope='school', scope_label=school.name)
        else:
            standing = services.get_student_standing(student)

        return Response(StandingSerializer(standing).data)


def _resolve_student(request):
    """The student a points request is about, checked against the caller.

    Falls back to the caller themselves. When ``?student=`` names someone
    else, ``CanViewStudentData`` decides — via the same helper the web views
    use — whether this caller may read them.
    """
    from django.shortcuts import get_object_or_404

    from accounts.models import CustomUser

    student_id = request.query_params.get('student')
    if not student_id:
        return request.user

    student = get_object_or_404(CustomUser, pk=student_id)
    from progress.access import can_view_student
    if not can_view_student(request.user, student):
        # 404 rather than 403: a 403 would confirm this student exists, which
        # is itself a leak about another family's child.
        from django.http import Http404
        raise Http404
    return student
