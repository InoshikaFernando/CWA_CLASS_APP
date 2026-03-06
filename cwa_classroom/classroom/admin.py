from django.contrib import admin
from .models import (
    Subject, Level, Topic, ClassRoom, ClassTeacher, ClassStudent,
    StudentLevelEnrollment, SubjectApp, ContactMessage,
)


class ClassTeacherInline(admin.TabularInline):
    model = ClassTeacher
    extra = 1


class ClassStudentInline(admin.TabularInline):
    model = ClassStudent
    extra = 1


@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'subject', 'created_by', 'is_active', 'student_count', 'created_at')
    list_filter = ('is_active', 'subject', 'levels')
    search_fields = ('name', 'code')
    inlines = [ClassTeacherInline, ClassStudentInline]
    filter_horizontal = ('levels',)
    readonly_fields = ('code',)
    autocomplete_fields = ('subject',)

    def student_count(self, obj):
        return obj.students.count()
    student_count.short_description = 'Students'


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


@admin.register(StudentLevelEnrollment)
class StudentLevelEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'level', 'enrolled_at')
    list_filter = ('subject', 'level')


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
