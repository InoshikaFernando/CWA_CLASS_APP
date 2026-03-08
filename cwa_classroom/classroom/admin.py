from django.contrib import admin
from .models import (
    Subject, Level, Topic, ClassRoom, ClassTeacher, ClassStudent,
    StudentLevelEnrollment, SubjectApp, ContactMessage,
    School, SchoolTeacher, AcademicYear, TopicLevel, SubTopic,
    ClassSession, Enrollment, StudentAttendance, TeacherAttendance,
    ProgressCriteria, ProgressRecord, Notification,
)


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class ClassTeacherInline(admin.TabularInline):
    model = ClassTeacher
    extra = 1


class ClassStudentInline(admin.TabularInline):
    model = ClassStudent
    extra = 1


class SchoolTeacherInline(admin.TabularInline):
    model = SchoolTeacher
    extra = 1


class TopicLevelInline(admin.TabularInline):
    model = TopicLevel
    extra = 1


class SubTopicInline(admin.TabularInline):
    model = SubTopic
    extra = 1


class ClassSessionInline(admin.TabularInline):
    model = ClassSession
    extra = 0
    fields = ('date', 'start_time', 'end_time', 'status')


# ---------------------------------------------------------------------------
# School & Multi-tenancy
# ---------------------------------------------------------------------------

@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'admin', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [SchoolTeacherInline]


@admin.register(SchoolTeacher)
class SchoolTeacherAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'school', 'role', 'is_active', 'joined_at')
    list_filter = ('role', 'is_active', 'school')
    search_fields = ('teacher__username', 'school__name')


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('school', 'year', 'start_date', 'end_date', 'is_current')
    list_filter = ('school', 'is_current')


# ---------------------------------------------------------------------------
# Curriculum
# ---------------------------------------------------------------------------

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'order')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ('level_number', 'display_name')
    ordering = ('level_number',)


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('name', 'subject', 'is_active', 'order')
    list_filter = ('subject', 'is_active', 'levels')
    filter_horizontal = ('levels',)
    prepopulated_fields = {'slug': ('name',)}
    inlines = [TopicLevelInline]


@admin.register(TopicLevel)
class TopicLevelAdmin(admin.ModelAdmin):
    list_display = ('topic', 'level')
    list_filter = ('level',)
    inlines = [SubTopicInline]


@admin.register(SubTopic)
class SubTopicAdmin(admin.ModelAdmin):
    list_display = ('name', 'topic_level', 'order', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)


# ---------------------------------------------------------------------------
# ClassRoom
# ---------------------------------------------------------------------------

@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'school', 'subject', 'created_by', 'is_active', 'student_count', 'created_at')
    list_filter = ('is_active', 'school', 'subject', 'levels')
    search_fields = ('name', 'code')
    inlines = [ClassTeacherInline, ClassStudentInline, ClassSessionInline]
    filter_horizontal = ('levels',)
    readonly_fields = ('code',)
    autocomplete_fields = ('subject',)

    def student_count(self, obj):
        return obj.students.count()
    student_count.short_description = 'Students'


@admin.register(StudentLevelEnrollment)
class StudentLevelEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'level', 'enrolled_at')
    list_filter = ('subject', 'level')


# ---------------------------------------------------------------------------
# Sessions, Enrollment, Attendance
# ---------------------------------------------------------------------------

@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    list_display = ('classroom', 'date', 'start_time', 'end_time', 'status')
    list_filter = ('status', 'classroom__school')
    date_hierarchy = 'date'


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'classroom', 'status', 'requested_at', 'approved_at')
    list_filter = ('status', 'classroom__school')
    search_fields = ('student__username', 'classroom__name')


@admin.register(StudentAttendance)
class StudentAttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'session', 'status', 'marked_by', 'marked_at')
    list_filter = ('status',)


@admin.register(TeacherAttendance)
class TeacherAttendanceAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'session', 'status', 'self_reported', 'approved_by')
    list_filter = ('status', 'self_reported')


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

@admin.register(ProgressCriteria)
class ProgressCriteriaAdmin(admin.ModelAdmin):
    list_display = ('name', 'school', 'subject', 'level', 'status', 'created_by', 'created_at')
    list_filter = ('status', 'school', 'subject', 'level')
    search_fields = ('name',)


@admin.register(ProgressRecord)
class ProgressRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'criteria', 'status', 'recorded_by', 'recorded_at')
    list_filter = ('status',)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('user__username', 'message')


# ---------------------------------------------------------------------------
# Subject Hub & Contact
# ---------------------------------------------------------------------------

@admin.register(SubjectApp)
class SubjectAppAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'is_coming_soon', 'order', 'external_url')
    list_filter = ('is_active', 'is_coming_soon')
    list_editable = ('order', 'is_active', 'is_coming_soon')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'is_read', 'created_at')
    list_filter = ('is_read', 'subject', 'created_at')
    list_editable = ('is_read',)
    search_fields = ('name', 'email', 'message')
    readonly_fields = ('name', 'email', 'subject', 'message', 'ip_address', 'created_at')
    date_hierarchy = 'created_at'
