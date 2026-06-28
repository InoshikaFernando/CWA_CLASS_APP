import uuid
from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings


class Subject(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    school = models.ForeignKey(
        'School', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='school_subjects',
        help_text='Null = global subject with question banks. Set = school-created custom subject.',
    )
    global_subject = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='school_variants',
        help_text='Future: link to global subject when it becomes available for level mapping.',
    )

    class Meta:
        ordering = ['order', 'name']
        unique_together = ('school', 'slug')

    def __str__(self):
        return self.name


class Level(models.Model):
    """
    level_number 1-8  → Year 1-8 curriculum levels
    level_number >= 100 → Basic Facts levels (always accessible)
    level_number >= 200 → School-specific custom levels
    """
    level_number = models.PositiveIntegerField(unique=True)
    display_name = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    subject = models.ForeignKey(
        'Subject', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='levels',
        help_text='Which subject this level belongs to. Used to filter levels when mapping to departments.',
    )
    school = models.ForeignKey(
        'School', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='custom_levels',
    )
    # DEPRECATED: replaced by DepartmentLevel M2M through table. Will be removed after data migration.
    department = models.ForeignKey(
        'Department', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='levels',
        help_text='DEPRECATED — use DepartmentLevel instead.',
    )

    class Meta:
        ordering = ['level_number']

    def __str__(self):
        return self.display_name

    @property
    def is_basic_facts_level(self):
        return self.level_number >= 100

    @property
    def year_number(self):
        if self.level_number <= 8:
            return self.level_number
        return None


class Topic(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='topics')
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='subtopics',
        help_text='Leave blank for top-level topics; set for subtopics.',
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    levels = models.ManyToManyField(Level, related_name='topics', blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']
        unique_together = ('subject', 'slug')

    def __str__(self):
        if self.parent_id:
            return f'{self.subject.name} — {self.parent.name} › {self.name}'
        return f'{self.subject.name} — {self.name}'


# ---------------------------------------------------------------------------
# Currency (reference / lookup table)
# ---------------------------------------------------------------------------

class Currency(models.Model):
    """ISO 4217 currency reference table. Active currencies appear in dropdowns."""

    SYMBOL_BEFORE = 'before'
    SYMBOL_AFTER = 'after'
    SYMBOL_POSITION_CHOICES = [
        (SYMBOL_BEFORE, 'Before amount'),
        (SYMBOL_AFTER, 'After amount'),
    ]

    code = models.CharField(
        max_length=3,
        primary_key=True,
        help_text='ISO 4217 three-letter currency code (e.g. NZD, USD).',
    )
    name = models.CharField(max_length=100, help_text='e.g. "New Zealand Dollar"')
    symbol = models.CharField(max_length=5, help_text='e.g. "$", "£", "€"')
    symbol_position = models.CharField(
        max_length=6,
        choices=SYMBOL_POSITION_CHOICES,
        default=SYMBOL_BEFORE,
    )
    decimal_places = models.PositiveSmallIntegerField(
        default=2,
        help_text='Number of decimal places (typically 2; 0 for JPY, KRW).',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Only active currencies are shown in dropdowns.',
    )

    class Meta:
        ordering = ['code']
        verbose_name = 'Currency'
        verbose_name_plural = 'Currencies'

    def __str__(self):
        return f'{self.code} - {self.name}'

    def get_references(self):
        """Return lists of schools/departments/classes that reference this currency.

        Used by guard-rail logic to prevent deactivating an in-use currency.
        Returns a dict with keys 'schools', 'departments', 'classes'.
        """
        # Import here to avoid circular import at module load
        schools = list(School.objects.filter(default_currency=self).values_list('name', flat=True))
        departments = list(Department.objects.filter(currency_override=self).values_list('name', flat=True))
        classes = list(ClassRoom.objects.filter(currency_override=self).values_list('name', flat=True))
        return {'schools': schools, 'departments': departments, 'classes': classes}

    def clean(self):
        """Block deactivation if any school/department/class still references this currency."""
        from django.core.exceptions import ValidationError
        if not self.is_active:
            # Check if this record already exists and was previously active
            if self.pk:
                try:
                    original = Currency.objects.get(pk=self.pk)
                except Currency.DoesNotExist:
                    return
                if original.is_active:
                    # Being set to inactive — check references
                    refs = self.get_references()
                    messages_parts = []
                    if refs['schools']:
                        messages_parts.append(f"Schools: {', '.join(refs['schools'])}")
                    if refs['departments']:
                        messages_parts.append(f"Departments: {', '.join(refs['departments'])}")
                    if refs['classes']:
                        messages_parts.append(f"Classes: {', '.join(refs['classes'])}")
                    if messages_parts:
                        raise ValidationError(
                            f"Cannot deactivate {self.code}: it is still in use. "
                            + " | ".join(messages_parts)
                        )

    def format_amount(self, value) -> str:
        """Return *value* formatted as a currency string using this currency's rules.

        Examples::

            nzd.format_amount(Decimal("99.50"))  → "$99.50"
            jpy.format_amount(Decimal("1500"))   → "¥1500"
            sek.format_amount(Decimal("250.00")) → "250.00\xa0kr"
        """
        from decimal import Decimal as _Decimal, ROUND_HALF_UP

        quantize_str = '1' if self.decimal_places == 0 else '0.' + '0' * self.decimal_places
        amount = _Decimal(str(value)).quantize(_Decimal(quantize_str), rounding=ROUND_HALF_UP)
        formatted = f'{amount:,f}'
        # Strip trailing zeros beyond desired decimal places then re-pad
        if self.decimal_places == 0:
            formatted = str(int(amount))
        else:
            formatted = f'{amount:.{self.decimal_places}f}'

        if self.symbol_position == self.SYMBOL_BEFORE:
            return f'{self.symbol}{formatted}'
        return f'{formatted}\u00a0{self.symbol}'


# ---------------------------------------------------------------------------
# School & Multi-tenancy
# ---------------------------------------------------------------------------

class School(models.Model):
    """A school managed by an admin. All operational data is scoped to a school."""
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='administered_schools',
        help_text='The admin user who owns this school.',
    )
    is_active = models.BooleanField(default=True)
    # Bank details for invoices
    bank_name = models.CharField(max_length=100, blank=True)
    bank_bsb = models.CharField('BSB', max_length=20, blank=True)
    bank_account_number = models.CharField(max_length=30, blank=True)
    bank_account_name = models.CharField(max_length=200, blank=True)
    invoice_terms = models.TextField(
        blank=True,
        help_text='Terms & conditions shown on invoices.',
    )
    invoice_due_days = models.PositiveIntegerField(
        default=30,
        help_text='Number of days after issue date before payment is due.',
    )
    # Company / structured address
    abn = models.CharField('Business Registration Number', max_length=50, blank=True)
    gst_number = models.CharField('GST / VAT Number', max_length=50, blank=True)
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state_region = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True)
    timezone = models.CharField(
        max_length=63, blank=True, default='',
        help_text='IANA timezone (e.g. America/New_York, Pacific/Auckland). '
                  'Used for scheduling and "today" calculations. '
                  'Falls back to server TIME_ZONE if blank.',
    )
    # Default fee – school-wide fallback when no class/level/subject/dept fee is set
    default_fee = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='School-wide default fee per session. Used when no class, level, subject, or department fee is configured.',
    )

    # Invoice email recipient policy
    INVOICE_RECIPIENT_POLICY_CHOICES = [
        ('parents_fallback_student', 'Parents (student if no parents)'),
        ('parents_only',             'Parents only (no email if no parents)'),
        ('parents_and_student',      'Parents and student always'),
        ('student_only',             'Student only'),
    ]
    invoice_recipient_policy = models.CharField(
        max_length=30,
        choices=INVOICE_RECIPIENT_POLICY_CHOICES,
        default='parents_fallback_student',
        help_text='Controls who receives invoice and cancellation emails.',
    )

    # Stripe payment
    stripe_payment_link = models.URLField(
        blank=True,
        help_text='Default Stripe Payment Link for this institute. Parents see a Pay Now button linking here.',
    )
    # Branding & email
    logo = models.ImageField(upload_to='school_logos/', blank=True)
    outgoing_email = models.EmailField(
        blank=True,
        help_text='Outgoing email address used for invoices and communications.',
    )
    subscription_discount_code = models.CharField(
        max_length=50, blank=True,
        help_text=(
            'Subscription discount code (a billing.DiscountCode) families can use '
            'at checkout. When set, it can be included in welcome/resend emails.'
        ),
    )

    # Currency
    default_currency = models.ForeignKey(
        'Currency',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='schools',
        help_text='Default currency for invoices. Null = USD system default.',
    )

    # Suspension
    is_suspended = models.BooleanField(default=False)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_reason = models.TextField(blank=True)
    suspended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    # Publish workflow
    is_published = models.BooleanField(
        default=False,
        help_text='Whether the school has been published. Unpublished schools are in setup mode.',
    )
    published_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.name) or 'school'
            slug = base
            n = 1
            while type(self).objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)
        # Auto-create SchoolTeacher + UserRole for the admin user
        if self.admin_id:
            self._ensure_admin_is_hoi()

    def _ensure_admin_is_hoi(self):
        """Ensure the admin user has SchoolTeacher(head_of_institute) and UserRole.

        Only promotes the new admin — demotion of the old HoI is handled
        explicitly by the view (SchoolEditView) so the user can choose
        what role the old HoI should get.
        """
        from accounts.models import Role, UserRole

        # Promote new admin
        SchoolTeacher.objects.update_or_create(
            school=self,
            teacher_id=self.admin_id,
            defaults={'role': 'head_of_institute', 'is_active': True},
        )
        hoi_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        UserRole.objects.get_or_create(user_id=self.admin_id, role=hoi_role)

    # Settings fields that can be overridden at department level
    SETTINGS_FIELDS = [
        'bank_name', 'bank_bsb', 'bank_account_number', 'bank_account_name',
        'invoice_terms', 'invoice_due_days',
        'invoice_recipient_policy',
        'outgoing_email', 'subscription_discount_code',
        'abn', 'gst_number',
        'street_address', 'city', 'state_region', 'postal_code', 'country',
        'logo', 'timezone',
    ]

    def get_effective_settings(self, department=None, classroom=None):
        """Return settings dict, applying department then classroom overrides where non-null/non-blank."""
        result = {}
        for field in self.SETTINGS_FIELDS:
            result[field] = getattr(self, field)
        if department:
            for field in self.SETTINGS_FIELDS:
                dept_val = getattr(department, field, None)
                if dept_val is None:
                    continue
                # For FileField/ImageField, check truthiness (empty FieldFile is falsy)
                if hasattr(dept_val, 'name'):
                    if dept_val:
                        result[field] = dept_val
                elif dept_val != '':
                    result[field] = dept_val
        if classroom:
            # Apply classroom-level overrides (subset of settings fields)
            for field in classroom.CLASS_OVERRIDE_FIELDS:
                cls_val = getattr(classroom, field, None)
                if cls_val is None:
                    continue
                if cls_val != '':
                    result[field] = cls_val
        return result

    def get_local_now(self):
        """Return the current datetime in the school's timezone."""
        import zoneinfo
        from django.utils import timezone as dj_tz
        tz_name = self.timezone or settings.TIME_ZONE
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except (KeyError, Exception):
            tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
        return dj_tz.now().astimezone(tz)

    def get_local_date(self):
        """Return today's date in the school's timezone."""
        return self.get_local_now().date()

    def get_effective_currency(self):
        """Return the effective Currency for this school.

        Returns ``default_currency`` if set, otherwise falls back to USD.
        If USD is not seeded, returns ``None``.
        """
        if self.default_currency_id:
            return self.default_currency
        try:
            return Currency.objects.get(code='USD')
        except Currency.DoesNotExist:
            return None

    def get_resolved_account_number(self):
        """Return this school's bank_account_number, or None if not configured.

        School is the top of the resolution chain — there is no parent to
        fall back to.
        """
        return self.bank_account_number or None

    def get_resolved_gst(self):
        """Return this school's gst_number, or None if not configured.

        GST is an institute-level concept; departments and classes delegate
        upward to this method.
        """
        return self.gst_number or None


class SchoolTeacher(models.Model):
    """Through table: links a teacher to a school with a seniority role."""
    ROLE_CHOICES = [
        ('head_of_institute', 'Head of Institute'),
        ('head_of_department', 'Head of Department'),
        ('senior_teacher', 'Senior Teacher'),
        ('teacher', 'Teacher'),
        ('junior_teacher', 'Junior Teacher'),
        ('accountant', 'Accountant'),
    ]
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='school_teachers')
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='school_memberships',
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='teacher')
    specialty = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the teacher was notified about being added to this school.',
    )
    pending_password = models.CharField(
        max_length=50, blank=True,
        help_text='Temporary plain-text password stored until publish email is sent, then cleared.',
    )

    class Meta:
        unique_together = ('school', 'teacher')
        ordering = ['school', 'role', 'teacher']
        indexes = [
            models.Index(fields=['school', 'is_active']),
        ]

    def __str__(self):
        return f'{self.teacher.username} @ {self.school.name} ({self.get_role_display()})'


class Department(models.Model):
    """A department within a school (e.g. Mathematics, English, Science)."""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='departments')
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True)
    subjects = models.ManyToManyField(
        'Subject', through='DepartmentSubject',
        related_name='departments_m2m', blank=True,
    )
    mapped_levels = models.ManyToManyField(
        'Level', through='DepartmentLevel',
        related_name='mapped_departments', blank=True,
    )
    head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='headed_departments',
        help_text='The HoD (Head of Department) user assigned to this department.',
    )
    is_active = models.BooleanField(default=True)
    default_fee = models.DecimalField(
        max_digits=8, decimal_places=2,
        null=True, blank=True,
        help_text='Default fee (USD) for all subjects/levels/classes in this department.',
    )
    # ── Settings overrides (blank = use school default) ──
    bank_name = models.CharField(max_length=100, blank=True)
    bank_bsb = models.CharField('BSB', max_length=20, blank=True)
    bank_account_number = models.CharField(
        max_length=30,
        null=True, blank=True,
        help_text='Account number override for invoices. Null = inherit from school.',
    )
    bank_account_name = models.CharField(max_length=200, blank=True)
    invoice_terms = models.TextField(blank=True)
    invoice_due_days = models.PositiveIntegerField(null=True, blank=True)
    invoice_recipient_policy = models.CharField(max_length=30, blank=True)
    outgoing_email = models.EmailField(blank=True)
    abn = models.CharField('Business Registration Number', max_length=50, blank=True)
    gst_number = models.CharField(
        'GST / VAT Number', max_length=50,
        null=True, blank=True,
        help_text='GST/VAT number override. Null = inherit from school.',
    )
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state_region = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True)
    logo = models.ImageField(upload_to='department_logos/', blank=True)
    stripe_payment_link = models.URLField(
        blank=True,
        help_text='Stripe Payment Link override for this department. Overrides the institute default.',
    )
    currency_override = models.ForeignKey(
        'Currency',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='departments',
        help_text='Currency override for this department. Null = inherit from school.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('school', 'slug')
        ordering = ['school', 'name']
        indexes = [
            models.Index(fields=['school', 'is_active']),
        ]

    def __str__(self):
        return f'{self.name} — {self.school.name}'

    def get_effective_currency(self):
        """Return the effective Currency for this department.

        Resolution: ``currency_override`` → ``school.get_effective_currency()``.
        """
        if self.currency_override_id:
            return self.currency_override
        return self.school.get_effective_currency()

    def get_resolved_account_number(self):
        """Return the effective bank account number for this department.

        Resolution chain::

            Department.bank_account_number  (local override)
            → School.bank_account_number    (institute default)

        Returns ``None`` if neither level has a value configured.
        """
        if self.bank_account_number:
            return self.bank_account_number
        return self.school.get_resolved_account_number()

    def get_resolved_gst(self):
        """Return the effective GST number for this department.

        GST is configured only at the institute level — always delegates upward.
        """
        return self.school.get_resolved_gst()

    @property
    def primary_subject(self):
        """First subject — backwards compatibility."""
        ds = self.department_subjects.select_related('subject').first()
        return ds.subject if ds else None


class DepartmentTeacher(models.Model):
    """Links a teacher to a department. Teachers can belong to multiple departments."""
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='department_teachers')
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='department_memberships',
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('department', 'teacher')
        ordering = ['department', 'teacher']

    def __str__(self):
        return f'{self.teacher.username} @ {self.department.name}'


class DepartmentLevel(models.Model):
    """
    Maps a Level to a Department (M2M through table).
    Allows multiple departments to share the same global Year levels,
    and supports local display-name overrides (e.g. "Year 1 (AU)").
    """
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name='department_levels',
    )
    level = models.ForeignKey(
        Level, on_delete=models.CASCADE, related_name='department_levels',
    )
    local_display_name = models.CharField(
        max_length=100, blank=True,
        help_text='Optional override, e.g. "Year 1 (AU)" to relabel a level for this department.',
    )
    order = models.PositiveIntegerField(default=0)
    fee_override = models.DecimalField(
        max_digits=8, decimal_places=2,
        null=True, blank=True,
        help_text='Fee override for this level. NULL = inherit from subject or department.',
    )

    class Meta:
        unique_together = ('department', 'level')
        ordering = ['order', 'level__level_number']

    def __str__(self):
        name = self.local_display_name or self.level.display_name
        return f'{self.department.name} — {name}'

    @property
    def effective_display_name(self):
        return self.local_display_name or self.level.display_name


class DepartmentSubject(models.Model):
    """
    Links a Subject to a Department.
    Within a school, each subject is assigned to at most one department.
    """
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name='department_subjects',
    )
    subject = models.ForeignKey(
        'Subject', on_delete=models.CASCADE, related_name='department_subjects',
    )
    order = models.PositiveIntegerField(default=0)
    fee_override = models.DecimalField(
        max_digits=8, decimal_places=2,
        null=True, blank=True,
        help_text='Fee override for this subject. NULL = inherit from department.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('department', 'subject')
        ordering = ['order', 'subject__name']

    def __str__(self):
        return f'{self.department.name} — {self.subject.name}'

    def clean(self):
        from django.core.exceptions import ValidationError
        existing = DepartmentSubject.objects.filter(
            subject=self.subject,
            department__school=self.department.school,
        ).exclude(department=self.department)
        if existing.exists():
            raise ValidationError(
                f'Subject "{self.subject.name}" is already assigned to '
                f'"{existing.first().department.name}" in this school.'
            )


class AcademicYear(models.Model):
    """Represents an academic year for a school. Sessions are generated from this."""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='academic_years')
    year = models.PositiveIntegerField(help_text='e.g. 2026')
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    number_of_terms = models.PositiveIntegerField(null=True, blank=True, help_text='Number of terms in this academic year (1–6)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('school', 'year')
        ordering = ['-year']

    def __str__(self):
        return f'{self.school.name} — {self.year}'

    def save(self, *args, **kwargs):
        # Ensure only one academic year per school is current
        if self.is_current:
            AcademicYear.objects.filter(
                school=self.school, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)


class Term(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='terms')
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name='terms',
        null=True, blank=True,
    )
    name = models.CharField(max_length=50)  # "Term 1", "Term 2", etc.
    start_date = models.DateField()
    end_date = models.DateField()
    order = models.PositiveIntegerField(default=0)
    is_confirmed = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['order', 'start_date']
        unique_together = ('school', 'name', 'academic_year')

    def __str__(self):
        yr = f' ({self.academic_year.year})' if self.academic_year else ''
        return f'{self.name}{yr} — {self.school.name}'


class SchoolHoliday(models.Model):
    """A holiday period specific to a school (e.g. half-term, inset days)."""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='school_holidays')
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, null=True, blank=True, related_name='school_holidays'
    )
    term = models.ForeignKey(
        Term, on_delete=models.SET_NULL, null=True, blank=True, related_name='school_holidays'
    )
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ['start_date']

    def __str__(self):
        return f'{self.name} ({self.start_date} – {self.end_date}) — {self.school.name}'


class PublicHoliday(models.Model):
    """A public/national holiday on which the school does not hold classes."""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='public_holidays')
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, null=True, blank=True, related_name='public_holidays'
    )
    name = models.CharField(max_length=100)
    date = models.DateField()

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f'{self.name} ({self.date}) — {self.school.name}'


# ---------------------------------------------------------------------------
# Curriculum extensions: TopicLevel & SubTopic
# ---------------------------------------------------------------------------

class TopicLevel(models.Model):
    """Explicit through table for Topic ↔ Level M2M (allows SubTopic scoping)."""
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='topic_levels')
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='topic_levels')

    class Meta:
        unique_together = ('topic', 'level')
        ordering = ['level', 'topic']

    def __str__(self):
        return f'{self.topic.name} — {self.level.display_name}'


class SubTopic(models.Model):
    """A subtopic scoped to a specific Topic + Level combination."""
    topic_level = models.ForeignKey(TopicLevel, on_delete=models.CASCADE, related_name='subtopics')
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('topic_level', 'slug')
        ordering = ['order', 'name']

    def __str__(self):
        return f'{self.topic_level} — {self.name}'


# ---------------------------------------------------------------------------
# ClassRoom (updated with school FK)
# ---------------------------------------------------------------------------

class ClassRoom(models.Model):
    DAY_CHOICES = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ]

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=8, unique=True, editable=False)
    day = models.CharField(max_length=10, choices=DAY_CHOICES, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    # Stored for a future "post to the class WhatsApp group" backend. The
    # official WhatsApp Business API cannot post to groups, so this is unused by
    # the current per-parent notification path (CPP-XXX).
    whatsapp_group_id = models.CharField(max_length=64, blank=True)
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='classrooms',
        help_text='The school this class belongs to.',
    )
    department = models.ForeignKey(
        'Department',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='classrooms',
        help_text='The department this class belongs to.',
    )
    subject = models.ForeignKey(
        'Subject',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='classrooms',
    )
    levels = models.ManyToManyField(Level, related_name='classrooms', blank=True)
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='classrooms',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_classes',
    )
    teachers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='ClassTeacher',
        related_name='teaching_classes',
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='ClassStudent',
        related_name='enrolled_classes',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    fee_override = models.DecimalField(
        max_digits=8, decimal_places=2,
        null=True, blank=True,
        help_text='Fee override for this class. NULL = inherit from level/subject/department.',
    )
    currency_override = models.ForeignKey(
        'Currency',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='classes',
        help_text='Currency override for this class. Null = inherit from department.',
    )
    # ── Settings overrides (blank = use department/school default) ──
    bank_name = models.CharField(max_length=100, blank=True)
    bank_bsb = models.CharField('BSB', max_length=20, blank=True)
    bank_account_number = models.CharField(
        max_length=30,
        null=True, blank=True,
        help_text='Account number override for invoices. Null = inherit from department.',
    )
    bank_account_name = models.CharField(max_length=200, blank=True)
    gst_number = models.CharField(
        'GST / VAT Number', max_length=50,
        null=True, blank=True,
        help_text='GST/VAT number override. Null = inherit from department.',
    )

    # Fields that can be overridden at class level
    CLASS_OVERRIDE_FIELDS = [
        'bank_name', 'bank_bsb', 'bank_account_number', 'bank_account_name',
        'gst_number',
    ]

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.code})'

    def get_effective_currency(self):
        """Return the effective Currency for this class.

        Resolution chain::

            ClassRoom.currency_override
            → Department.currency_override
            → School.default_currency
            → USD (system default)

        Returns ``None`` only if USD is not seeded.
        """
        if self.currency_override_id:
            return self.currency_override
        if self.department_id:
            return self.department.get_effective_currency()
        if self.school_id:
            return self.school.get_effective_currency()
        try:
            return Currency.objects.get(code='USD')
        except Currency.DoesNotExist:
            return None

    def get_resolved_account_number(self):
        """Return the effective bank account number for this class.

        Resolution chain::

            ClassRoom.bank_account_number  (class override)
            → Department.bank_account_number  (department override)
            → School.bank_account_number      (institute default)

        Returns ``None`` if no level in the chain has a value configured.
        When ``None`` is returned, no payment details section appears on invoices.
        """
        if self.bank_account_number:
            return self.bank_account_number
        if self.department_id:
            return self.department.get_resolved_account_number()
        if self.school_id:
            return self.school.get_resolved_account_number()
        return None

    def get_resolved_gst(self):
        """Return the effective GST number for this class.

        GST is configured only at the institute level.
        Resolution chain: class → department → school (all delegate upward).
        """
        if self.department_id:
            return self.department.get_resolved_gst()
        if self.school_id:
            return self.school.get_resolved_gst()
        return None

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)

    def get_accessible_levels(self):
        return self.levels.all()


class ClassTeacher(models.Model):
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name='class_teachers')
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='class_teacher_entries',
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('classroom', 'teacher')

    def __str__(self):
        return f'{self.teacher.username} → {self.classroom.name}'


class ClassStudent(models.Model):
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name='class_students')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='class_student_entries',
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    fee_override = models.DecimalField(
        max_digits=8, decimal_places=2,
        null=True, blank=True,
        help_text='Individual fee override for this student. NULL = inherit from class cascade.',
    )
    billing_start_date = models.DateField(
        null=True, blank=True,
        help_text=(
            'First date this student is billable for this class. '
            'NULL = bill the full requested period (e.g. backdated data entry '
            "for a student who was already attending). Set to a date when the "
            'student genuinely starts mid-period — sessions before this date '
            'will not be billed.'
        ),
    )

    class Meta:
        unique_together = ('classroom', 'student')
        indexes = [
            models.Index(fields=['classroom', 'is_active']),
        ]

    def __str__(self):
        return f'{self.student.username} → {self.classroom.name}'


class SchoolStudent(models.Model):
    """Through table: links a student to a school."""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='school_students')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='school_student_entries',
    )
    student_id_code = models.CharField(
        max_length=20, blank=True, db_index=True,
        help_text='Auto-generated student ID (e.g. STU-001-0042). Used for parent linking.',
    )
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    opening_balance = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Outstanding amount from before the system. Consumed on first invoice.',
    )
    notified_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the student was notified about being added to this school.',
    )
    pending_password = models.CharField(
        max_length=50, blank=True,
        help_text='Temporary plain-text password stored until publish email is sent, then cleared.',
    )

    class Meta:
        unique_together = ('school', 'student')
        ordering = ['student__first_name', 'student__last_name']
        indexes = [
            models.Index(fields=['school', 'is_active']),
        ]

    def save(self, *args, **kwargs):
        if not self.student_id_code:
            self.student_id_code = self._generate_student_id()
        super().save(*args, **kwargs)

    def _generate_student_id(self):
        """Generate a unique student ID like STU-001-0042."""
        school_part = f'{self.school_id:03d}'
        last = SchoolStudent.objects.filter(
            school=self.school,
            student_id_code__startswith=f'STU-{school_part}-',
        ).order_by('-student_id_code').values_list('student_id_code', flat=True).first()
        if last:
            try:
                seq = int(last.split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1
        return f'STU-{school_part}-{seq:04d}'

    def __str__(self):
        return f'{self.student.username} @ {self.school.name}'


# ---------------------------------------------------------------------------
# Guardian / StudentGuardian
# ---------------------------------------------------------------------------

class Guardian(models.Model):
    """A parent or guardian linked to one or more students within a school."""
    RELATIONSHIP_CHOICES = [
        ('mother', 'Mother'),
        ('father', 'Father'),
        ('guardian', 'Guardian'),
        ('other', 'Other'),
    ]
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='guardians')
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    relationship = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES, default='guardian')
    address = models.CharField(max_length=300, blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('school', 'email')
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.email})'


class StudentGuardian(models.Model):
    """Links students to their guardians (M2M through table)."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='student_guardians',
    )
    guardian = models.ForeignKey(
        Guardian, on_delete=models.CASCADE, related_name='guardian_students',
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        unique_together = ('student', 'guardian')

    def __str__(self):
        return f'{self.student.username} ← {self.guardian}'


class StudentLevelEnrollment(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='level_enrollments',
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    level = models.ForeignKey(Level, on_delete=models.CASCADE)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'subject', 'level')

    def __str__(self):
        return f'{self.student.username} → {self.subject.name} {self.level.display_name}'


# ---------------------------------------------------------------------------
# Class Sessions & Scheduling
# ---------------------------------------------------------------------------

class ClassSession(models.Model):
    """A single scheduled session (lesson) for a class."""
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name='sessions')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    cancellation_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_sessions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'start_time']
        indexes = [
            models.Index(fields=['classroom', 'status']),
        ]

    def __str__(self):
        return f'{self.classroom.name} — {self.date} {self.start_time}'


# ---------------------------------------------------------------------------
# Enrollment (student join requests)
# ---------------------------------------------------------------------------

class Enrollment(models.Model):
    """Student enrollment request for a class (via class code)."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('removed', 'Removed'),
    ]
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name='enrollments')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='enrollment_requests',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='enrollment_approvals',
    )
    rejection_reason = models.TextField(blank=True)

    class Meta:
        unique_together = ('classroom', 'student')
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['classroom', 'status']),
        ]

    def __str__(self):
        return f'{self.student.username} → {self.classroom.name} ({self.status})'


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

class AbsenceToken(models.Model):
    """Token issued when a student marks themselves absent, redeemable at another
    class covering the same level as a makeup session."""

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='absence_tokens',
    )
    original_session = models.ForeignKey(
        ClassSession,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='absence_tokens',
    )
    original_classroom = models.ForeignKey(
        ClassRoom,
        on_delete=models.CASCADE,
        related_name='absence_tokens',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='absence_tokens_created',
    )
    note = models.TextField(blank=True)

    # Approval workflow
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    expires_at = models.DateTimeField(null=True, blank=True)  # None = unlimited
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='absence_tokens_reviewed',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # Redemption fields
    redeemed = models.BooleanField(default=False)
    redeemed_session = models.ForeignKey(
        ClassSession,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='redeemed_tokens',
    )
    redeemed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        label = 'Used' if self.redeemed else self.get_status_display()
        return f'AbsenceToken({self.student.username}, {self.original_classroom.name}, {label})'

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        from django.utils import timezone
        return timezone.now() > self.expires_at


class StudentAttendance(models.Model):
    """Tracks student attendance for a specific class session."""
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
    ]
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name='student_attendance')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attendance_records',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='present')
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='attendance_marks_given',
    )
    marked_at = models.DateTimeField(auto_now_add=True)
    self_reported = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='student_attendance_approvals',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    makeup_token = models.ForeignKey(
        AbsenceToken,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='makeup_attendance',
    )

    class Meta:
        unique_together = ('session', 'student')
        ordering = ['session', 'student']

    def __str__(self):
        return f'{self.student.username} — {self.session} ({self.status})'


class TeacherAttendance(models.Model):
    """Tracks teacher attendance (self-reported, admin-approved)."""
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
    ]
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name='teacher_attendance')
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='teacher_attendance_records',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='present')
    self_reported = models.BooleanField(default=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='teacher_attendance_approvals',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('session', 'teacher')
        ordering = ['session', 'teacher']

    def __str__(self):
        return f'{self.teacher.username} — {self.session} ({self.status})'


# ---------------------------------------------------------------------------
# Progress Criteria & Tracking
# ---------------------------------------------------------------------------

class ProgressCriteria(models.Model):
    """Progress criteria per School + Subject + Level. Teacher creates, Senior Teacher approves."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='progress_criteria')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, null=True, blank=True, related_name='progress_criteria',
                                help_text='Null = applies to all subjects.')
    level = models.ForeignKey(Level, on_delete=models.CASCADE, null=True, blank=True, related_name='progress_criteria',
                              help_text='Null = applies to all levels for the chosen subject.')
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='children',
        help_text='Leave blank for top-level criteria; set for sub-criteria.',
    )
    name = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_criteria',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_criteria',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['subject', 'level', 'order']
        verbose_name = 'Progress Criteria'
        verbose_name_plural = 'Progress Criteria'

    def __str__(self):
        level_name = self.level.display_name if self.level else 'All Levels'
        subject_name = self.subject.name if self.subject else 'All Subjects'
        return f'{self.name} ({subject_name} — {level_name})'


class ProgressRecord(models.Model):
    """Records a student's progress against a specific criteria."""
    # Four-level developmental rubric (Beginning → Advanced) plus an unrated
    # baseline. See SPEC_TEACHER_CLASS_STUDENT_PROGRESS §12.7.
    STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('beginning', 'Beginning'),
        ('developing', 'Developing'),
        ('confident', 'Confident'),
        ('advanced', 'Advanced'),
    ]
    # Buckets used by the dashboards/summaries (progress bars count "proficient").
    PROFICIENT_STATUSES = ('confident', 'advanced')
    DEVELOPING_STATUSES = ('beginning', 'developing')

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='progress_records',
    )
    criteria = models.ForeignKey(ProgressCriteria, on_delete=models.CASCADE, related_name='records')
    session = models.ForeignKey(
        ClassSession,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='progress_records',
        help_text='Optional: the session during which this progress was recorded.',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started')
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='progress_records_given',
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-recorded_at']
        unique_together = ('student', 'criteria', 'session')

    def __str__(self):
        return f'{self.student.username} — {self.criteria.name} ({self.status})'

    @property
    def is_proficient(self):
        """True when this rating counts as proficient (Confident or Advanced)."""
        return self.status in self.PROFICIENT_STATUSES


class ProgressReportComment(models.Model):
    """A teacher's narrative comment on a student's progress for a term.

    Multiple comments may exist per student / term (e.g. from different
    teachers or subjects); each one is editable so teachers can update old
    comments at any time.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='progress_report_comments',
    )
    school = models.ForeignKey(
        School, on_delete=models.CASCADE,
        related_name='progress_report_comments',
    )
    term = models.ForeignKey(
        Term, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='progress_report_comments',
        help_text='Term this comment applies to. Null = general / all terms.',
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='progress_report_comments',
        help_text='Optional: a subject-specific comment. Null = overall comment.',
    )
    body = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='authored_progress_comments',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Comment on {self.student.username} by {self.created_by.username if self.created_by else "?"}'

    @property
    def was_edited(self):
        # auto_now / auto_now_add can differ by microseconds on creation.
        if not self.created_at or not self.updated_at:
            return False
        return (self.updated_at - self.created_at).total_seconds() > 1


class ProgressReport(models.Model):
    """A generated end-of-term progress report for a student.

    Teachers generate the report (a draft) and then send it to the student's
    linked parents/guardians. The progress data and comments are rendered live
    at view / send time; this model tracks the generate → send lifecycle.
    """
    STATUS_DRAFT = 'draft'
    STATUS_SENT = 'sent'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SENT, 'Sent'),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='progress_reports',
    )
    school = models.ForeignKey(
        School, on_delete=models.CASCADE,
        related_name='progress_reports',
    )
    term = models.ForeignKey(
        Term, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='progress_reports',
    )
    # The class the report was generated from — scopes the homework summary and
    # records which class a batch (per-class) generation belonged to.
    classroom = models.ForeignKey(
        'ClassRoom', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='progress_reports',
    )
    # Staff "include this section" selections (see §12.8). The rubric is on by
    # default; the cross-app summaries are opt-in.
    include_rubric = models.BooleanField(default=True)
    include_homework = models.BooleanField(default=False)
    include_maths = models.BooleanField(default=False)
    include_coding = models.BooleanField(default=False)
    # Point-in-time snapshot of the Homework/Maths/Coding summary computed at
    # generation, so the report and the dashboard card show consistent numbers.
    summary_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='generated_progress_reports',
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sent_progress_reports',
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    recipient_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        term_name = self.term.name if self.term else 'All terms'
        return f'Report: {self.student.username} — {term_name} ({self.status})'

    @property
    def is_sent(self):
        return self.status == self.STATUS_SENT


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class Notification(models.Model):
    """In-app notification for approval workflows, enrollment, etc."""
    TYPE_CHOICES = [
        ('criteria_approval', 'Criteria Approval Request'),
        ('criteria_approved', 'Criteria Approved'),
        ('criteria_rejected', 'Criteria Rejected'),
        ('enrollment_request', 'Enrollment Request'),
        ('enrollment_approved', 'Enrollment Approved'),
        ('enrollment_rejected', 'Enrollment Rejected'),
        ('attendance', 'Attendance'),
        ('parent_link_request', 'Parent Link Request'),
        ('parent_link_approved', 'Parent Link Approved'),
        ('parent_link_rejected', 'Parent Link Rejected'),
        ('homework_assigned', 'Homework Assigned'),
        ('progress_report', 'Progress Report'),
        ('general', 'General'),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    message = models.TextField()
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='general')
    is_read = models.BooleanField(default=False)
    link = models.CharField(max_length=500, blank=True, help_text='URL to navigate to when clicked.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
        ]

    def __str__(self):
        return f'{self.user.username} — {self.notification_type} ({self.created_at:%Y-%m-%d})'


# ---------------------------------------------------------------------------
# Parent / Family Account models
# ---------------------------------------------------------------------------

class ParentStudent(models.Model):
    """Links a parent user to a student user within a school context."""
    RELATIONSHIP_CHOICES = [
        ('mother', 'Mother'),
        ('father', 'Father'),
        ('guardian', 'Guardian'),
        ('other', 'Other'),
    ]

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='parent_student_links',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='student_parent_links',
    )
    school = models.ForeignKey(
        'School', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='parent_student_links',
    )
    relationship = models.CharField(
        max_length=30, choices=RELATIONSHIP_CHOICES, blank=True,
    )
    is_primary_contact = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='+',
    )

    class Meta:
        ordering = ['student__first_name', 'student__last_name']
        constraints = [
            models.UniqueConstraint(
                condition=models.Q(school__isnull=False),
                fields=['parent', 'student', 'school'],
                name='unique_parent_student_school',
            ),
            models.UniqueConstraint(
                condition=models.Q(school__isnull=True),
                fields=['parent', 'student'],
                name='unique_parent_student_no_school',
            ),
        ]

    def __str__(self):
        school_part = self.school.name if self.school else 'Individual'
        return f'{self.parent.username} → {self.student.username} @ {school_part}'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.school is not None:
            existing = ParentStudent.objects.filter(
                student=self.student, school=self.school, is_active=True,
            ).exclude(pk=self.pk).count()
            if existing >= 2:
                raise ValidationError(
                    f'{self.student.username} already has 2 active parent links '
                    f'in {self.school.name}.'
                )


class ParentInvite(models.Model):
    """Invite token for a parent to register or link to a student."""
    import uuid

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('expired', 'Expired'),
        ('revoked', 'Revoked'),
    ]

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    school = models.ForeignKey(
        'School', on_delete=models.CASCADE,
        related_name='parent_invites',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='parent_invites',
    )
    parent_email = models.EmailField()
    relationship = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Invite {self.parent_email} → {self.student.username} ({self.status})'

    @property
    def is_valid(self):
        from django.utils import timezone
        return self.status == 'pending' and self.expires_at > timezone.now()


# ---------------------------------------------------------------------------
# Parent Link Request — approval workflow for self-join parents
# ---------------------------------------------------------------------------

class ParentLinkRequest(models.Model):
    """
    Pending request from a self-registered parent to be linked to a student.
    Created when a parent registers via /register/parent-join/.
    A teacher/HoI must approve before ParentStudent is created.
    """
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    RELATIONSHIP_CHOICES = ParentStudent.RELATIONSHIP_CHOICES

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='parent_link_requests',
    )
    school_student = models.ForeignKey(
        'SchoolStudent', on_delete=models.CASCADE,
        related_name='parent_link_requests',
    )
    relationship = models.CharField(
        max_length=30, choices=RELATIONSHIP_CHOICES, blank=True,
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-requested_at']
        unique_together = ('parent', 'school_student')

    def __str__(self):
        return (
            f'{self.parent.username} → {self.school_student.student.username} '
            f'@ {self.school_student.school.name} ({self.status})'
        )


# ---------------------------------------------------------------------------
# Subject Hub models (public landing page & subject hub feature)
# ---------------------------------------------------------------------------

class SubjectApp(models.Model):
    """
    Represents a top-level subject application shown on the Subjects Hub.
    Separate from the existing classroom.Subject model, which represents
    internal curriculum subjects. SubjectApp represents external (or future
    internal) subject applications that users can launch from the hub.
    """
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    icon_name = models.CharField(
        max_length=50, blank=True,
        help_text='Heroicon name (e.g. "calculator") or emoji',
    )
    external_url = models.URLField(
        blank=True, null=True,
        help_text='Full URL to the external subject app. null = not yet available.',
    )
    is_active = models.BooleanField(default=False)
    is_coming_soon = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=7, default='#16a34a')
    subject = models.ForeignKey(
        'Subject', null=True, blank=True, on_delete=models.SET_NULL,
        help_text='Optional link to internal classroom.Subject for future use.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Subject App'
        verbose_name_plural = 'Subject Apps'

    def __str__(self):
        return self.name

    def clean(self):
        if self.is_active and self.is_coming_soon:
            raise ValidationError(
                'A subject cannot be both active and coming soon.'
            )
        if self.is_active and not self.external_url:
            raise ValidationError(
                'Active subjects must have an external_url.'
            )


CONTACT_SUBJECT_CHOICES = [
    ('general', 'General Inquiry'),
    ('support', 'Technical Support'),
    ('billing', 'Billing'),
    ('partnership', 'Partnership'),
    ('other', 'Other'),
]


class ContactMessage(models.Model):
    """Stores contact form submissions from the public Contact Us page."""
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=50, choices=CONTACT_SUBJECT_CHOICES)
    message = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Contact Message'
        verbose_name_plural = 'Contact Messages'

    def __str__(self):
        return f'{self.name} — {self.get_subject_display()} ({self.created_at:%Y-%m-%d})'


# ---------------------------------------------------------------------------
# Email Service
# ---------------------------------------------------------------------------

class EmailCampaign(models.Model):
    """Tracks bulk/marketing email sends by admin."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]
    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=300)
    html_body = models.TextField()
    school = models.ForeignKey(
        'School', on_delete=models.CASCADE, related_name='email_campaigns',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    recipient_filter = models.JSONField(
        default=dict, blank=True,
        help_text='{"roles": [...], "class_ids": [...], "individual_ids": [...]}',
    )
    total_recipients = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='created_campaigns',
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.status})'


class EmailLog(models.Model):
    """Tracks every individual email sent through the system.

    ``status`` starts at ``sent`` (accepted by Resend) or ``failed`` (never
    accepted), then advances as Resend webhooks report what the recipient's
    mail server did with it (delivered/bounced/etc.) — see
    ``apply_delivery_event``.
    """
    STATUS_CHOICES = [
        ('sent', 'Sent'),            # accepted by Resend, awaiting delivery
        ('delivered', 'Delivered'),  # recipient server accepted it
        ('opened', 'Opened'),
        ('clicked', 'Clicked'),
        ('delayed', 'Delayed'),      # transient issue, Resend retrying
        ('bounced', 'Bounced'),
        ('complained', 'Complained'),  # recipient marked as spam
        ('failed', 'Failed'),        # never accepted by Resend
    ]

    # Status precedence for webhook updates. A later, lower-ranked event (e.g. a
    # delayed "opened") must not clobber a terminal outcome (e.g. "bounced").
    STATUS_RANK = {
        'sent': 0,
        'delayed': 1,
        'opened': 2,
        'clicked': 3,
        'delivered': 4,
        'complained': 5,
        'bounced': 5,
        'failed': 5,
    }

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='email_logs',
    )
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=300)
    notification_type = models.CharField(max_length=30, blank=True)
    campaign = models.ForeignKey(
        EmailCampaign, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='logs',
    )
    school = models.ForeignKey(
        'School', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='email_logs',
        db_index=True,
    )
    invoice = models.ForeignKey(
        'Invoice', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='email_logs',
        db_index=True,
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='sent')
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    # Delivery tracking (populated by the Resend webhook). provider_message_id
    # is the Resend email id and the correlation key for incoming events.
    provider_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    bounced_at = models.DateTimeField(null=True, blank=True)
    complained_at = models.DateTimeField(null=True, blank=True)
    bounce_reason = models.TextField(blank=True)
    status_updated_at = models.DateTimeField(null=True, blank=True)

    # Maps a webhook status to the timestamp field it stamps (None = no stamp).
    _STATUS_TIMESTAMP_FIELD = {
        'delivered': 'delivered_at',
        'opened': 'opened_at',
        'clicked': 'clicked_at',
        'bounced': 'bounced_at',
        'complained': 'complained_at',
        'delayed': None,
    }

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f'{self.recipient_email} — {self.subject} ({self.status})'

    def apply_delivery_event(self, new_status, when, reason=''):
        """Apply a webhook delivery event, respecting status precedence.

        Always stamps the event's own timestamp field (so we keep an accurate
        record of every event), but only advances ``status`` when the new
        event ranks at least as high as the current one — preventing a late
        "opened" from overwriting a terminal "bounced". Returns True if the row
        was changed. The caller is responsible for saving.
        """
        changed = False
        ts_field = self._STATUS_TIMESTAMP_FIELD.get(new_status)
        if ts_field and getattr(self, ts_field) is None:
            setattr(self, ts_field, when)
            changed = True

        if new_status == 'bounced' and reason and not self.bounce_reason:
            self.bounce_reason = reason
            changed = True

        current_rank = self.STATUS_RANK.get(self.status, 0)
        new_rank = self.STATUS_RANK.get(new_status, 0)
        if new_rank >= current_rank and new_status != self.status:
            self.status = new_status
            changed = True

        if changed:
            self.status_updated_at = when
        return changed


class EmailQueue(models.Model):
    """Stores emails that couldn't be sent due to daily sending limits.

    Processed by the process_email_queue management command, which runs
    daily via cron and drains this queue up to the remaining daily quota.
    """
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='queued_emails',
    )
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=300)
    from_email = models.EmailField()
    html_content = models.TextField()
    text_content = models.TextField(blank=True)
    cc = models.JSONField(default=list, blank=True)
    reply_to = models.JSONField(default=list, blank=True)
    notification_type = models.CharField(max_length=30, blank=True)
    campaign = models.ForeignKey(
        'EmailCampaign', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='queued_emails',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.recipient_email} — {self.subject} ({self.status})'


class EmailPreference(models.Model):
    """Per-user email opt-in/opt-out preferences."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='email_preference',
    )
    receive_transactional = models.BooleanField(
        default=True, help_text='Enrollment, progress, attendance notifications.',
    )
    receive_campaigns = models.BooleanField(
        default=True, help_text='Newsletters and announcements.',
    )
    unsubscribe_token = models.UUIDField(default=uuid.uuid4, unique=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.username} email prefs'


# ---------------------------------------------------------------------------
# Invoicing Models
# ---------------------------------------------------------------------------

class DepartmentFee(models.Model):
    """Daily rate for a department, with effective date for audit trail."""
    department = models.ForeignKey('Department', on_delete=models.CASCADE,
                                   related_name='fees')
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2)
    effective_from = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self):
        return f'{self.department} — ${self.daily_rate} from {self.effective_from}'


class StudentFeeOverride(models.Model):
    """Per-student daily rate override, scoped to a school."""
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='fee_overrides')
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='student_fee_overrides')
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(blank=True)
    effective_from = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self):
        return f'{self.student} — ${self.daily_rate} from {self.effective_from}'


class InvoiceNumberSequence(models.Model):
    """Tracks the next invoice number per school per year.
    Uses select_for_update() for concurrency safety."""
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='invoice_sequences')
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('school', 'year')

    def __str__(self):
        return f'{self.school} {self.year} — #{self.last_number}'


class Invoice(models.Model):
    ATTENDANCE_MODE_CHOICES = [
        ('all_class_days', 'All Class Days'),
        ('attended_days_only', 'Attended Days Only'),
    ]
    BILLING_TYPE_CHOICES = [
        ('post_term', 'Post-Term'),
        ('upfront', 'Upfront'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ]
    PERIOD_TYPE_CHOICES = [
        ('custom', 'Custom'),
        ('month', 'Month'),
        ('term', 'Term'),
        ('year', 'Year'),
    ]

    invoice_number = models.CharField(max_length=50, unique=True)
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='invoices')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='invoices')
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    attendance_mode = models.CharField(max_length=20, choices=ATTENDANCE_MODE_CHOICES)
    billing_type = models.CharField(max_length=20, choices=BILLING_TYPE_CHOICES,
                                     default='post_term')
    period_type = models.CharField(max_length=10, choices=PERIOD_TYPE_CHOICES,
                                    default='custom')
    calculated_amount = models.DecimalField(max_digits=10, decimal_places=2,
                                             help_text='System-calculated sum of line items')
    amount = models.DecimalField(max_digits=10, decimal_places=2,
                                  help_text='Final amount (may be adjusted by HoI)')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    issued_at = models.DateTimeField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    stripe_payment_link = models.URLField(
        blank=True,
        help_text='Stripe Payment Link override for this invoice. Overrides department and institute defaults.',
    )
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['school', 'status']),
        ]

    def __str__(self):
        return f'{self.invoice_number} — {self.student} (${self.amount})'

    def get_stripe_payment_link(self):
        """Resolve Stripe Payment Link using fallback chain: invoice → department → institute."""
        if self.stripe_payment_link:
            return self.stripe_payment_link
        first_li = self.line_items.select_related('department').filter(
            department__stripe_payment_link__gt='',
        ).first()
        if first_li:
            return first_li.department.stripe_payment_link
        if self.school_id and self.school.stripe_payment_link:
            return self.school.stripe_payment_link
        return None

    @property
    def amount_paid(self):
        from django.db.models import Sum
        return self.payments.filter(status='confirmed').aggregate(
            total=Sum('amount'))['total'] or 0

    @property
    def amount_due(self):
        return self.amount - self.amount_paid


class InvoiceLineItem(models.Model):
    RATE_SOURCE_CHOICES = [
        ('student_override', 'Student Override'),
        ('department_default', 'Department Default'),
        ('opening_balance', 'Opening Balance'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE,
                                 related_name='line_items')
    classroom = models.ForeignKey('ClassRoom', on_delete=models.SET_NULL, null=True)
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True,
                                    help_text='Denormalized for reporting')
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2)
    rate_source = models.CharField(max_length=20, choices=RATE_SOURCE_CHOICES)
    sessions_held = models.PositiveIntegerField()
    sessions_attended = models.PositiveIntegerField()
    sessions_charged = models.PositiveIntegerField()
    line_amount = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f'{self.invoice.invoice_number} — {self.classroom} (${self.line_amount})'


class CSVColumnTemplate(models.Model):
    """Saved CSV column mapping templates per school."""
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='csv_column_templates')
    name = models.CharField(max_length=100)
    column_mapping = models.JSONField(
        help_text='{"date_col": 0, "amount_col": 2, "reference_col": 3, '
                  '"transaction_id_col": null, "amount_type": "credit"}')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('school', 'name')

    def __str__(self):
        return f'{self.school} — {self.name}'


class CSVImport(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
    ]

    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='csv_imports')
    file_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    column_mapping = models.JSONField(default=dict,
                                       help_text='The column mapping used for this import')
    total_rows = models.PositiveIntegerField(default=0)
    credit_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    unmatched_count = models.PositiveIntegerField(default=0)
    ignored_count = models.PositiveIntegerField(default=0)
    confirmed_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    def __str__(self):
        return f'{self.file_name} ({self.status})'


class PaymentReferenceMapping(models.Model):
    """Maps bank CSV reference names to students for auto-matching."""
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='payment_reference_mappings')
    reference_name = models.CharField(max_length=255,
                                       help_text='Normalized: lowercase, trimmed')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True,
                                 related_name='payment_reference_mappings')
    is_ignored = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('school', 'reference_name')
        indexes = [
            models.Index(fields=['school', 'reference_name']),
        ]

    def __str__(self):
        if self.is_ignored:
            return f'{self.reference_name} — IGNORED'
        return f'{self.reference_name} → {self.student}'


class InvoicePayment(models.Model):
    STATUS_CHOICES = [
        ('matched', 'Matched'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
        ('other', 'Other'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL,
                                 null=True, blank=True,
                                 related_name='payments')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='invoice_payments')
    school = models.ForeignKey('School', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES,
                                       default='bank_transfer')
    reference_name = models.CharField(max_length=255, blank=True)
    bank_transaction_id = models.CharField(max_length=255, blank=True)
    csv_import = models.ForeignKey('CSVImport', on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='payments')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='matched')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'${self.amount} — {self.student} ({self.status})'


class CreditTransaction(models.Model):
    """Tracks student credit balance changes (overpayments, cancellations, applications)."""
    REASON_CHOICES = [
        ('overpayment', 'Overpayment'),
        ('invoice_cancelled', 'Invoice Cancelled'),
        ('applied_to_invoice', 'Applied to Invoice'),
        ('opening_balance', 'Opening Balance Credit'),
    ]

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='credit_transactions')
    school = models.ForeignKey('School', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2,
                                  help_text='Positive = credit added, Negative = credit used')
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    related_payment = models.ForeignKey('InvoicePayment', on_delete=models.SET_NULL,
                                         null=True, blank=True)
    related_invoice = models.ForeignKey('Invoice', on_delete=models.SET_NULL,
                                         null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.student} — ${self.amount} ({self.reason})'


# ---------------------------------------------------------------------------
# Salary Models
# ---------------------------------------------------------------------------

class TeacherHourlyRate(models.Model):
    """Default hourly rate for teachers at a school, with effective date."""
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='teacher_hourly_rates')
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2)
    effective_from = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self):
        return f'{self.school} — ${self.hourly_rate}/hr from {self.effective_from}'


class TeacherRateOverride(models.Model):
    """Per-teacher hourly rate override, scoped to a school."""
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='salary_rate_overrides')
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='teacher_rate_overrides')
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(blank=True)
    effective_from = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self):
        return f'{self.teacher} — ${self.hourly_rate}/hr from {self.effective_from}'


class SalaryNumberSequence(models.Model):
    """Tracks the next salary slip number per school per year."""
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='salary_sequences')
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('school', 'year')

    def __str__(self):
        return f'{self.school} {self.year} — #{self.last_number}'


class SalarySlip(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ]

    slip_number = models.CharField(max_length=50, unique=True)
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='salary_slips')
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='salary_slips')
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    calculated_amount = models.DecimalField(max_digits=10, decimal_places=2,
                                             help_text='System-calculated sum of line items')
    amount = models.DecimalField(max_digits=10, decimal_places=2,
                                  help_text='Final amount (may be adjusted)')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    issued_at = models.DateTimeField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.slip_number} — {self.teacher} (${self.amount})'

    @property
    def amount_paid(self):
        from django.db.models import Sum
        return self.payments.filter(status='confirmed').aggregate(
            total=Sum('amount'))['total'] or 0

    @property
    def amount_due(self):
        return self.amount - self.amount_paid


class SalarySlipLineItem(models.Model):
    RATE_SOURCE_CHOICES = [
        ('teacher_override', 'Teacher Override'),
        ('school_default', 'School Default'),
    ]

    salary_slip = models.ForeignKey(SalarySlip, on_delete=models.CASCADE,
                                      related_name='line_items')
    classroom = models.ForeignKey('ClassRoom', on_delete=models.SET_NULL, null=True)
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True,
                                    help_text='Denormalized for reporting')
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2)
    rate_source = models.CharField(max_length=20, choices=RATE_SOURCE_CHOICES)
    sessions_taught = models.PositiveIntegerField()
    hours_per_session = models.DecimalField(max_digits=5, decimal_places=2,
                                              help_text='Average duration per session in hours')
    total_hours = models.DecimalField(max_digits=8, decimal_places=2)
    line_amount = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f'{self.salary_slip.slip_number} — {self.classroom} (${self.line_amount})'


class SalaryPayment(models.Model):
    STATUS_CHOICES = [
        ('matched', 'Matched'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
        ('other', 'Other'),
    ]

    salary_slip = models.ForeignKey(SalarySlip, on_delete=models.SET_NULL,
                                      null=True, blank=True,
                                      related_name='payments')
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='salary_payments')
    school = models.ForeignKey('School', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES,
                                       default='bank_transfer')
    reference_name = models.CharField(max_length=255, blank=True)
    bank_transaction_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'${self.amount} — {self.teacher} ({self.status})'


class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('rent', 'Rent'),
        ('utilities', 'Utilities'),
        ('salaries', 'Salaries'),
        ('supplies', 'Supplies'),
        ('transport', 'Transport'),
        ('maintenance', 'Maintenance'),
        ('marketing', 'Marketing'),
        ('other', 'Other'),
    ]

    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='expenses')
    department = models.ForeignKey('Department', on_delete=models.SET_NULL,
                                    null=True, blank=True,
                                    related_name='expenses')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['school', 'date']),
        ]

    def __str__(self):
        return f'{self.get_category_display()} — ${self.amount} ({self.date})'
