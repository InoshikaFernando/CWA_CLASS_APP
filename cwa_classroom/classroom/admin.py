from django.contrib import admin
from .models import Subject, Level, Topic, ClassRoom, ClassTeacher, ClassStudent, StudentLevelEnrollment


class ClassTeacherInline(admin.TabularInline):
    model = ClassTeacher
    extra = 1


class ClassStudentInline(admin.TabularInline):
    model = ClassStudent
    extra = 1


@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'created_by', 'is_active', 'student_count', 'created_at')
    list_filter = ('is_active', 'levels')
    search_fields = ('name', 'code')
    inlines = [ClassTeacherInline, ClassStudentInline]
    filter_horizontal = ('levels',)
    readonly_fields = ('code',)

    def student_count(self, obj):
        return obj.students.count()
    student_count.short_description = 'Students'


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'order')
    prepopulated_fields = {'slug': ('name',)}


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


@admin.register(StudentLevelEnrollment)
class StudentLevelEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'level', 'enrolled_at')
    list_filter = ('subject', 'level')
