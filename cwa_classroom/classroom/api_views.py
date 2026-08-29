"""Classroom API — classes, rosters, sessions, attendance, notifications.

Every list here is narrowed through ``api.scoping``. The pattern is
deliberate and worth keeping: a viewset that builds its own filter is a
viewset that can forget one.
"""

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.filters import int_param
from api.pagination import LargePagination
from api.permissions import IsTeacher
from api.scoping import child_ids_of, classrooms_for, scope_by_student
from classroom.api_serializers import (
    AttendanceMarkSerializer, ChildSerializer, ClassRoomSerializer,
    ClassSessionSerializer, ClassStudentSerializer, LevelSerializer,
    NotificationSerializer, StudentAttendanceSerializer, SubjectSerializer,
    TopicSerializer,
)
from classroom.models import (
    ClassRoom, ClassSession, ClassStudent, Level, Notification,
    ParentStudent, StudentAttendance, Subject, Topic,
)


class SubjectViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                     viewsets.GenericViewSet):
    """Subjects the caller can see: the global ones plus their own school's."""

    serializer_class = SubjectSerializer
    pagination_class = LargePagination
    search_fields = ('name', 'slug')
    ordering_fields = ('order', 'name')

    def get_queryset(self):
        from api.scoping import schools_administered_by
        from billing.entitlements import get_school_for_user

        user = self.request.user
        # school=None marks a global subject with a question bank behind it;
        # every user gets those. A school's custom subjects are added on top.
        condition = Q(school__isnull=True)
        school = get_school_for_user(user)
        if school is not None:
            condition |= Q(school=school)
        administered = schools_administered_by(user)
        if administered.exists():
            condition |= Q(school__in=administered)
        return Subject.objects.filter(condition, is_active=True).distinct()


class LevelViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                   viewsets.GenericViewSet):
    """Curriculum levels, optionally filtered to one subject."""

    serializer_class = LevelSerializer
    pagination_class = LargePagination
    ordering_fields = ('level_number',)

    @extend_schema(parameters=[
        OpenApiParameter('subject', int, description='Filter to one subject id.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Level.objects.all()
        subject_id = int_param(self.request.query_params, 'subject')
        if subject_id is not None:
            queryset = queryset.filter(subject_id=subject_id)
        return queryset


class TopicViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                   viewsets.GenericViewSet):
    """Topics, filterable by subject and level — what the practice picker needs."""

    serializer_class = TopicSerializer
    pagination_class = LargePagination
    search_fields = ('name', 'slug')
    ordering_fields = ('order', 'name')

    @extend_schema(parameters=[
        OpenApiParameter('subject', int, description='Filter to one subject id.'),
        OpenApiParameter('level', int, description='Filter to one level id.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = (Topic.objects
                    .filter(is_active=True)
                    .select_related('subject')
                    .prefetch_related('levels'))
        subject_id = int_param(self.request.query_params, 'subject')
        if subject_id is not None:
            queryset = queryset.filter(subject_id=subject_id)
        level_id = int_param(self.request.query_params, 'level')
        if level_id is not None:
            queryset = queryset.filter(levels__id=level_id)
        return queryset.distinct()


class ClassRoomViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                       viewsets.GenericViewSet):
    """Classes the caller teaches, attends, administers, or has a child in."""

    serializer_class = ClassRoomSerializer
    search_fields = ('name', 'code')
    ordering_fields = ('name', 'day')

    def get_queryset(self):
        return (
            classrooms_for(self.request.user)
            .select_related('subject', 'school', 'location')
            .prefetch_related('class_teachers__teacher')
            # Subquery rather than annotate(): classrooms_for() already
            # filters on `class_students` for a student or parent, and Django
            # reuses that same join for a following annotate — so a member of
            # a class of thirty would be told it has one student. A subquery
            # counts the real roster whatever the outer filter did.
            .annotate(active_student_count=Subquery(
                ClassStudent.objects
                .filter(classroom=OuterRef('pk'), is_active=True)
                .values('classroom')
                .annotate(total=Count('id'))
                .values('total')[:1],
                output_field=IntegerField(),
            ))
            # ClassRoom has no Meta.ordering. Paginating an unordered queryset
            # lets the database return rows in a different order per page, so
            # a client scrolling a list sees duplicates and gaps.
            .order_by('name', 'id')
        )

    @extend_schema(responses=ClassStudentSerializer(many=True))
    @action(detail=True, methods=['get'])
    def students(self, request, pk=None):
        """The class roster.

        Staff-only: a parent can see that a class exists and who teaches it,
        but the list of the other children in it is not theirs to read.
        """
        classroom = self.get_object()
        user = request.user
        is_staff = (
            user.is_superuser
            or classroom.class_teachers.filter(teacher=user).exists()
            or user.is_head_of_institute or user.is_institute_owner
            or user.is_head_of_department
        )
        if not is_staff:
            return Response(
                {'error': {'code': 'permission_denied',
                           'detail': 'Only teaching staff can view a class roster.'}},
                status=status.HTTP_403_FORBIDDEN,
            )
        roster = (ClassStudent.objects
                  .filter(classroom=classroom, is_active=True)
                  .select_related('student')
                  .order_by('student__first_name', 'student__username', 'id'))
        page = self.paginate_queryset(roster)
        serializer = ClassStudentSerializer(page or roster, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(responses=ClassSessionSerializer(many=True))
    @action(detail=True, methods=['get'])
    def sessions(self, request, pk=None):
        """Scheduled sessions for this class, soonest first."""
        classroom = self.get_object()
        sessions = ClassSession.objects.filter(classroom=classroom)
        page = self.paginate_queryset(sessions)
        serializer = ClassSessionSerializer(page or sessions, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class ClassSessionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          viewsets.GenericViewSet):
    """Sessions across every class the caller can see — the app's timetable."""

    serializer_class = ClassSessionSerializer
    ordering_fields = ('date', 'start_time')

    @extend_schema(parameters=[
        OpenApiParameter('from', str, description='ISO date — sessions on or after.'),
        OpenApiParameter('to', str, description='ISO date — sessions on or before.'),
        OpenApiParameter('upcoming', bool, description='Only today and later.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = (ClassSession.objects
                    .filter(classroom__in=classrooms_for(self.request.user))
                    .select_related('classroom'))
        params = self.request.query_params
        if params.get('from'):
            queryset = queryset.filter(date__gte=params['from'])
        if params.get('to'):
            queryset = queryset.filter(date__lte=params['to'])
        if params.get('upcoming') in ('1', 'true', 'True'):
            queryset = queryset.filter(date__gte=timezone.localdate())
        return queryset

    @extend_schema(
        request=AttendanceMarkSerializer(many=True),
        responses=StudentAttendanceSerializer(many=True),
    )
    @action(detail=True, methods=['post'], permission_classes=[IsTeacher])
    def attendance(self, request, pk=None):
        """Mark attendance for a session. Teachers only.

        Accepts a list so a teacher can submit a whole roster in one request —
        marking thirty students one call at a time over a classroom's wifi is
        thirty chances to half-succeed.
        """
        session = self.get_object()
        if not (request.user.is_superuser
                or session.classroom.class_teachers.filter(teacher=request.user).exists()):
            return Response(
                {'error': {'code': 'permission_denied',
                           'detail': 'You do not teach this class.'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = AttendanceMarkSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        enrolled = set(
            ClassStudent.objects
            .filter(classroom=session.classroom, is_active=True)
            .values_list('student_id', flat=True)
        )
        unknown = [row['student_id'] for row in serializer.validated_data
                   if row['student_id'] not in enrolled]
        if unknown:
            # Reject the whole batch rather than silently marking the students
            # we recognise: a partly-applied roster looks identical to a
            # successful one from the app's side.
            return Response(
                {'error': {'code': 'validation_error',
                           'detail': 'Some students are not enrolled in this class.',
                           'fields': {'student_id': unknown}}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        records = []
        for row in serializer.validated_data:
            record, _ = StudentAttendance.objects.update_or_create(
                session=session, student_id=row['student_id'],
                defaults={
                    'status': row['status'],
                    'marked_by': request.user,
                    # A teacher's mark is authoritative, so the self-report
                    # state has to be cleared with it. Left set, the row still
                    # reads as an unapproved student claim — and
                    # classroom.views_student only lets a student overwrite a
                    # row while self_reported is True, so the teacher's mark
                    # would stay overwritable from the web.
                    'self_reported': False,
                    'approved_by': None,
                    'approved_at': None,
                },
            )
            records.append(record)
        return Response(StudentAttendanceSerializer(records, many=True).data,
                        status=status.HTTP_200_OK)


class AttendanceViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Attendance records for students the caller may read."""

    serializer_class = StudentAttendanceSerializer
    ordering_fields = ('marked_at',)

    @extend_schema(parameters=[
        OpenApiParameter('student', int, description='Filter to one student id.'),
        OpenApiParameter('classroom', int, description='Filter to one class id.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = scope_by_student(
            StudentAttendance.objects.select_related('session__classroom', 'student'),
            self.request.user,
        )
        params = self.request.query_params
        student_id = int_param(params, 'student')
        if student_id is not None:
            queryset = queryset.filter(student_id=student_id)
        classroom_id = int_param(params, 'classroom')
        if classroom_id is not None:
            queryset = queryset.filter(session__classroom_id=classroom_id)
        return queryset


class NotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          viewsets.GenericViewSet):
    """The caller's own in-app notifications. Never anyone else's."""

    serializer_class = NotificationSerializer
    ordering_fields = ('created_at',)
    # Declared for schema generation only — get_queryset() below is what
    # actually runs, and it is always narrowed to the caller.
    queryset = Notification.objects.none()

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @extend_schema(parameters=[
        OpenApiParameter('unread', bool, description='Only unread notifications.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.request.query_params.get('unread') in ('1', 'true', 'True'):
            queryset = queryset.filter(is_read=False)
        return queryset

    @extend_schema(responses=NotificationSerializer)
    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        return Response(NotificationSerializer(notification).data)

    @extend_schema(responses={200: None})
    @action(detail=False, methods=['post'], url_path='read-all')
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({'marked_read': updated})

    @extend_schema(responses={200: None})
    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        """Cheap poll for the app's badge — one indexed count, no serialising."""
        return Response({'unread': self.get_queryset().filter(is_read=False).count()})


class ChildrenViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """A parent's linked children — the app's child switcher."""

    serializer_class = ChildSerializer

    def get_queryset(self):
        return (ParentStudent.objects
                .filter(parent=self.request.user, is_active=True)
                .select_related('student')
                .order_by('student__first_name', 'student__username', 'id'))
