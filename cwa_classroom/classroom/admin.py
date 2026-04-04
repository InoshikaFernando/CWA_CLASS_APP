from django.contrib import admin
from .models import (
    Currency,
    Subject, Level, Topic, ClassRoom, ClassTeacher, ClassStudent,
    StudentLevelEnrollment, SubjectApp, ContactMessage,
    School, SchoolStudent, SchoolTeacher, AcademicYear, TopicLevel, SubTopic,
    ClassSession, Enrollment, StudentAttendance, TeacherAttendance,
    ProgressCriteria, ProgressRecord, Notification, DepartmentLevel,
    EmailCampaign, EmailLog, EmailPreference,
    DepartmentFee, StudentFeeOverride, InvoiceNumberSequence,
    Invoice, InvoiceLineItem, CSVColumnTemplate, CSVImport,
    PaymentReferenceMapping, InvoicePayment, CreditTransaction,
    TeacherHourlyRate, TeacherRateOverride, SalaryNumberSequence,
    SalarySlip, SalarySlipLineItem, SalaryPayment,
    ParentStudent, ParentInvite, Term,
)


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'symbol', 'symbol_position', 'decimal_places', 'is_active')
    list_filter = ('is_active', 'symbol_position')
    list_editable = ('is_active',)
    search_fields = ('code', 'name')
    ordering = ('code',)


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


@admin.register(SchoolStudent)
class SchoolStudentAdmin(admin.ModelAdmin):
    list_display = ('student', 'school', 'opening_balance', 'is_active', 'joined_at')
    list_filter = ('school', 'is_active')
    list_editable = ('opening_balance',)
    search_fields = ('student__username', 'student__first_name', 'student__last_name', 'school__name')


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('school', 'year', 'start_date', 'end_date', 'is_current')
    list_filter = ('school', 'is_current')


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ('name', 'school', 'academic_year', 'start_date', 'end_date', 'order')
    list_filter = ('school', 'academic_year')
    ordering = ('school', 'order', 'start_date')


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


@admin.register(DepartmentLevel)
class DepartmentLevelAdmin(admin.ModelAdmin):
    list_display = ('department', 'level', 'local_display_name', 'order')
    list_filter = ('department',)
    ordering = ('department', 'order', 'level__level_number')


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
    list_display = ('name', 'slug', 'subject', 'is_active', 'is_coming_soon', 'order', 'external_url')
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


# ---------------------------------------------------------------------------
# Email Service
# ---------------------------------------------------------------------------

@admin.register(EmailCampaign)
class EmailCampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'school', 'status', 'total_recipients', 'sent_count', 'sent_at')
    list_filter = ('status', 'school')
    readonly_fields = ('sent_count', 'failed_count', 'total_recipients')


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ('recipient_email', 'subject', 'status', 'notification_type', 'sent_at')
    list_filter = ('status', 'notification_type')
    search_fields = ('recipient_email', 'subject')
    date_hierarchy = 'sent_at'


@admin.register(EmailPreference)
class EmailPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'receive_transactional', 'receive_campaigns', 'updated_at')
    list_filter = ('receive_transactional', 'receive_campaigns')
    search_fields = ('user__username', 'user__email')


# ---------------------------------------------------------------------------
# Invoicing
# ---------------------------------------------------------------------------

class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0
    readonly_fields = ('classroom', 'department', 'daily_rate', 'rate_source',
                        'sessions_held', 'sessions_attended', 'sessions_charged', 'line_amount')


class InvoicePaymentInline(admin.TabularInline):
    model = InvoicePayment
    extra = 0
    readonly_fields = ('amount', 'payment_date', 'payment_method', 'reference_name', 'status')


@admin.register(DepartmentFee)
class DepartmentFeeAdmin(admin.ModelAdmin):
    list_display = ('department', 'daily_rate', 'effective_from', 'created_by', 'created_at')
    list_filter = ('department__school',)
    search_fields = ('department__name',)


@admin.register(StudentFeeOverride)
class StudentFeeOverrideAdmin(admin.ModelAdmin):
    list_display = ('student', 'school', 'daily_rate', 'reason', 'effective_from', 'created_at')
    list_filter = ('school',)
    search_fields = ('student__username', 'student__first_name', 'student__last_name')


@admin.register(InvoiceNumberSequence)
class InvoiceNumberSequenceAdmin(admin.ModelAdmin):
    list_display = ('school', 'year', 'last_number')
    list_filter = ('school', 'year')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'student', 'school', 'amount', 'status',
                     'billing_period_start', 'billing_period_end', 'created_at')
    list_filter = ('status', 'school', 'attendance_mode')
    search_fields = ('invoice_number', 'student__username', 'student__first_name', 'student__last_name')
    date_hierarchy = 'created_at'
    readonly_fields = ('invoice_number', 'created_at', 'updated_at')
    inlines = [InvoiceLineItemInline, InvoicePaymentInline]


@admin.register(InvoiceLineItem)
class InvoiceLineItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'classroom', 'daily_rate', 'sessions_charged', 'line_amount')
    list_filter = ('rate_source',)


@admin.register(CSVColumnTemplate)
class CSVColumnTemplateAdmin(admin.ModelAdmin):
    list_display = ('school', 'name', 'created_by', 'created_at')
    list_filter = ('school',)


@admin.register(CSVImport)
class CSVImportAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'school', 'status', 'total_rows', 'matched_count',
                     'unmatched_count', 'confirmed_count', 'uploaded_at')
    list_filter = ('status', 'school')
    readonly_fields = ('uploaded_at',)


@admin.register(PaymentReferenceMapping)
class PaymentReferenceMappingAdmin(admin.ModelAdmin):
    list_display = ('reference_name', 'student', 'school', 'is_ignored', 'created_at')
    list_filter = ('school', 'is_ignored')
    search_fields = ('reference_name', 'student__username', 'student__first_name')


@admin.register(InvoicePayment)
class InvoicePaymentAdmin(admin.ModelAdmin):
    list_display = ('student', 'amount', 'payment_date', 'payment_method', 'status',
                     'invoice', 'created_at')
    list_filter = ('status', 'payment_method', 'school')
    search_fields = ('student__username', 'reference_name')
    readonly_fields = ('created_at',)


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = ('student', 'school', 'amount', 'reason', 'created_at')
    list_filter = ('reason', 'school')
    search_fields = ('student__username',)
    readonly_fields = ('created_at',)


# ---------------------------------------------------------------------------
# Salary Admin
# ---------------------------------------------------------------------------

class SalarySlipLineItemInline(admin.TabularInline):
    model = SalarySlipLineItem
    extra = 0
    readonly_fields = ('classroom', 'department', 'hourly_rate', 'rate_source',
                        'sessions_taught', 'hours_per_session', 'total_hours', 'line_amount')


class SalaryPaymentInline(admin.TabularInline):
    model = SalaryPayment
    extra = 0
    readonly_fields = ('amount', 'payment_date', 'payment_method', 'reference_name', 'status')


@admin.register(TeacherHourlyRate)
class TeacherHourlyRateAdmin(admin.ModelAdmin):
    list_display = ('school', 'hourly_rate', 'effective_from', 'created_by', 'created_at')
    list_filter = ('school',)


@admin.register(TeacherRateOverride)
class TeacherRateOverrideAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'school', 'hourly_rate', 'reason', 'effective_from', 'created_at')
    list_filter = ('school',)
    search_fields = ('teacher__username', 'teacher__first_name', 'teacher__last_name')


@admin.register(SalaryNumberSequence)
class SalaryNumberSequenceAdmin(admin.ModelAdmin):
    list_display = ('school', 'year', 'last_number')
    list_filter = ('school', 'year')


@admin.register(SalarySlip)
class SalarySlipAdmin(admin.ModelAdmin):
    list_display = ('slip_number', 'teacher', 'school', 'amount', 'status',
                     'billing_period_start', 'billing_period_end', 'created_at')
    list_filter = ('status', 'school')
    search_fields = ('slip_number', 'teacher__username', 'teacher__first_name', 'teacher__last_name')
    date_hierarchy = 'created_at'
    readonly_fields = ('slip_number', 'created_at', 'updated_at')
    inlines = [SalarySlipLineItemInline, SalaryPaymentInline]


@admin.register(SalarySlipLineItem)
class SalarySlipLineItemAdmin(admin.ModelAdmin):
    list_display = ('salary_slip', 'classroom', 'hourly_rate', 'sessions_taught', 'total_hours', 'line_amount')
    list_filter = ('rate_source',)


@admin.register(SalaryPayment)
class SalaryPaymentAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'amount', 'payment_date', 'payment_method', 'status',
                     'salary_slip', 'created_at')
    list_filter = ('status', 'payment_method', 'school')
    search_fields = ('teacher__username', 'reference_name')
    readonly_fields = ('created_at',)


# ---------------------------------------------------------------------------
# Parent / Family Account
# ---------------------------------------------------------------------------

@admin.register(ParentStudent)
class ParentStudentAdmin(admin.ModelAdmin):
    list_display = ('parent', 'student', 'school', 'relationship', 'is_active', 'created_at')
    list_filter = ('is_active', 'relationship', 'school')
    search_fields = ('parent__username', 'parent__email', 'student__username', 'student__email')
    readonly_fields = ('created_at',)


@admin.register(ParentInvite)
class ParentInviteAdmin(admin.ModelAdmin):
    list_display = ('parent_email', 'student', 'school', 'status', 'created_at', 'expires_at')
    list_filter = ('status', 'school')
    search_fields = ('parent_email', 'student__username')
    readonly_fields = ('token', 'created_at', 'accepted_at')
