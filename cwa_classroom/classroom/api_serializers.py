"""Serializers for the classroom domain — the shape the mobile app reads."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.serializers import UserSummarySerializer
from classroom.models import (
    ClassRoom, ClassSession, ClassStudent, Level, Notification,
    ParentStudent, StudentAttendance, Subject, Topic,
)


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ('id', 'name', 'slug', 'description', 'order', 'is_active')


class LevelSerializer(serializers.ModelSerializer):
    subject_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Level
        fields = ('id', 'level_number', 'display_name', 'description', 'subject_id')


class TopicSerializer(serializers.ModelSerializer):
    subject_id = serializers.IntegerField(read_only=True)
    parent_id = serializers.IntegerField(read_only=True)
    level_ids = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = (
            'id', 'name', 'slug', 'description', 'order', 'is_active',
            'subject_id', 'parent_id', 'level_ids',
        )

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField()))
    def get_level_ids(self, obj):
        return [level.id for level in obj.levels.all()]


class ClassRoomSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    teachers = serializers.SerializerMethodField()
    student_count = serializers.SerializerMethodField()
    school_name = serializers.CharField(source='school.name', read_only=True, default=None)
    location_name = serializers.CharField(source='location.name', read_only=True, default=None)

    class Meta:
        model = ClassRoom
        fields = (
            'id', 'name', 'code', 'description',
            'day', 'start_time', 'end_time',
            'is_online', 'location_name', 'school_name',
            'subject', 'teachers', 'student_count', 'is_active',
        )

    @extend_schema_field(UserSummarySerializer(many=True))
    def get_teachers(self, obj):
        # `class_teachers` is prefetched by the viewset; going through it
        # rather than `obj.teachers.all()` keeps this to zero extra queries.
        return UserSummarySerializer(
            [link.teacher for link in obj.class_teachers.all()], many=True,
        ).data

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_student_count(self, obj):
        # Annotated by the viewset. Falling back to a count() here would turn
        # a class list into one query per row.
        return getattr(obj, 'active_student_count', None)


class ClassStudentSerializer(serializers.ModelSerializer):
    student = UserSummarySerializer(read_only=True)
    classroom_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ClassStudent
        fields = ('id', 'classroom_id', 'student', 'joined_at', 'is_active')


class ClassSessionSerializer(serializers.ModelSerializer):
    classroom_id = serializers.IntegerField(read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)

    class Meta:
        model = ClassSession
        fields = (
            'id', 'classroom_id', 'classroom_name', 'date',
            'start_time', 'end_time', 'status', 'cancellation_reason',
        )


class StudentAttendanceSerializer(serializers.ModelSerializer):
    student = UserSummarySerializer(read_only=True)
    session = ClassSessionSerializer(read_only=True)

    class Meta:
        model = StudentAttendance
        fields = (
            'id', 'session', 'student', 'status',
            'marked_at', 'self_reported', 'approved_at',
        )


class AttendanceMarkSerializer(serializers.Serializer):
    """Payload for a teacher marking one student present/absent/late."""

    student_id = serializers.IntegerField()
    status = serializers.ChoiceField(
        choices=[choice[0] for choice in StudentAttendance.STATUS_CHOICES])


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = (
            'id', 'message', 'notification_type', 'is_read', 'link', 'created_at',
        )
        read_only_fields = ('id', 'message', 'notification_type', 'link', 'created_at')


class ChildSerializer(serializers.ModelSerializer):
    """A parent's linked child, as the parent's app lists them."""

    student = UserSummarySerializer(read_only=True)

    class Meta:
        model = ParentStudent
        fields = ('id', 'student', 'relationship', 'is_primary_contact')
