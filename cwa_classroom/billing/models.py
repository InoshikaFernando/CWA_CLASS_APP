import math

from django.db import models
from django.conf import settings
from django.utils import timezone


class Package(models.Model):
    """Individual student subscription package. billing_type is reserved for future one-time purchases."""
    BILLING_RECURRING = 'recurring'
    BILLING_ONE_TIME = 'one_time'

    BILLING_TYPES = [
        (BILLING_RECURRING, 'Recurring'),
        (BILLING_ONE_TIME, 'One-time'),
    ]

    name = models.CharField(max_length=100)
    class_limit = models.PositiveIntegerField(
        default=1,
        help_text='Number of classes allowed. 0 = unlimited.',
    )
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    stripe_price_id = models.CharField(max_length=200, blank=True)
    billing_type = models.CharField(max_length=20, choices=BILLING_TYPES, default=BILLING_RECURRING)
    trial_days = models.PositiveSmallIntegerField(default=14)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'price']

    def __str__(self):
        return self.name

    @property
    def is_free(self):
        return self.price == 0

    @property
    def is_unlimited(self):
        return self.class_limit == 0


class DiscountCode(models.Model):
    code = models.CharField(max_length=50, unique=True)
    discount_percent = models.PositiveSmallIntegerField(
        default=100,
        help_text='100 = fully free, skips Stripe entirely.',
    )
    max_uses = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Leave blank for unlimited uses.',
    )
    uses = models.PositiveIntegerField(default=0)
    stripe_coupon_id = models.CharField(
        max_length=100, blank=True,
        help_text='Stripe Coupon ID. Applied to checkout when discount is not 100%.',
    )
    grant_days = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Days of access granted when code is redeemed. For 100% codes this sets the subscription period.',
    )
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} ({self.discount_percent}% off)'

    def is_valid(self):
        if not self.is_active:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        if self.max_uses is not None and self.uses >= self.max_uses:
            return False
        return True

    @property
    def is_fully_free(self):
        return self.discount_percent == 100


class Payment(models.Model):
    """LEGACY: Used by the deprecated PaymentIntent checkout flow. Retained for historical records."""
    STATUS_PENDING = 'pending'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_FAILED = 'failed'
    STATUS_REFUNDED = 'refunded'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUCCEEDED, 'Succeeded'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_REFUNDED, 'Refunded'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payments',
    )
    package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, related_name='payments')
    stripe_payment_intent_id = models.CharField(max_length=200, blank=True)
    stripe_checkout_session_id = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=10, default='nzd')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.package} — {self.status}'


class PromoCode(models.Model):
    code = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=200, blank=True)
    discount_percent = models.PositiveSmallIntegerField(
        default=100,
        help_text='100 = fully free (no payment). Less than 100 = partial discount.',
    )
    class_limit = models.PositiveIntegerField(
        default=0,
        help_text='Class access granted. 0 = unlimited.',
    )
    grant_days = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Days of access granted. Leave blank to use package default.',
    )
    max_uses = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Leave blank for unlimited uses.',
    )
    uses = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='redeemed_promos',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        limit = 'unlimited' if self.class_limit == 0 else str(self.class_limit)
        return f'{self.code} ({limit} classes)'

    def is_valid(self):
        if not self.is_active:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        if self.max_uses is not None and self.uses >= self.max_uses:
            return False
        return True

    @property
    def is_fully_free(self):
        return self.discount_percent == 100


class InstituteDiscountCode(models.Model):
    """Discount codes for institutes — created by superusers via Django admin."""
    code = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=200, blank=True)
    discount_percent = models.PositiveSmallIntegerField(
        default=100,
        help_text='100 = fully free (unlimited access), otherwise % off monthly price.',
    )
    # Override plan limits when code grants unlimited access
    override_class_limit = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Override class limit. Leave blank to use plan default. 0 = unlimited.',
    )
    override_student_limit = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Override student limit. Leave blank to use plan default. 0 = unlimited.',
    )
    max_uses = models.PositiveIntegerField(
        default=1,
        help_text='Number of times this code can be used. Default 1 (single-use).',
    )
    uses = models.PositiveIntegerField(default=0)
    stripe_coupon_id = models.CharField(
        max_length=100, blank=True,
        help_text='Stripe Coupon ID. When set, this coupon is applied to the Stripe subscription.',
    )
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} ({self.discount_percent}% off)'

    def is_valid(self):
        if not self.is_active:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        if self.max_uses is not None and self.uses >= self.max_uses:
            return False
        return True

    @property
    def is_fully_free(self):
        return self.discount_percent == 100


class InstitutePlan(models.Model):
    """Subscription plan tiers for institutes/schools."""
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=50, unique=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    stripe_price_id = models.CharField(max_length=200, blank=True)
    class_limit = models.PositiveIntegerField(
        help_text='Maximum active classes allowed.',
    )
    student_limit = models.PositiveIntegerField(
        help_text='Maximum active students allowed.',
    )
    invoice_limit_yearly = models.PositiveIntegerField(
        help_text='Invoices included per year before overage billing.',
    )
    extra_invoice_rate = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Cost per invoice beyond the yearly limit.',
    )
    stripe_overage_price_id = models.CharField(
        max_length=200, blank=True,
        help_text='Stripe metered price ID for invoice overages.',
    )
    trial_days = models.PositiveSmallIntegerField(default=14)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'price']

    def __str__(self):
        return f'{self.name} (${self.price}/mo)'


class SchoolSubscription(models.Model):
    """Links a School to an InstitutePlan with Stripe billing."""
    STATUS_TRIALING = 'trialing'
    STATUS_ACTIVE = 'active'
    STATUS_PAST_DUE = 'past_due'
    STATUS_CANCELLED = 'cancelled'
    STATUS_EXPIRED = 'expired'
    STATUS_SUSPENDED = 'suspended'

    STATUS_CHOICES = [
        (STATUS_TRIALING, 'Trialing'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_PAST_DUE, 'Past Due'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_SUSPENDED, 'Suspended'),
    ]

    school = models.OneToOneField(
        'classroom.School',
        on_delete=models.CASCADE,
        related_name='subscription',
    )
    plan = models.ForeignKey(
        InstitutePlan,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='school_subscriptions',
    )
    discount_code = models.ForeignKey(
        InstituteDiscountCode,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='subscriptions',
        help_text='Discount code applied at registration.',
    )
    stripe_subscription_id = models.CharField(max_length=200, blank=True)
    stripe_customer_id = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_TRIALING,
    )
    trial_end = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    has_used_trial = models.BooleanField(
        default=False,
        help_text='Set to True after the first trial. Prevents repeat trials on upgrade/downgrade.',
    )
    cancel_at_period_end = models.BooleanField(default=False)
    invoices_used_this_year = models.PositiveIntegerField(default=0)
    invoice_year_start = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        plan_name = self.plan.name if self.plan else 'No plan'
        return f'{self.school.name} — {plan_name} — {self.status}'

    @property
    def is_active_or_trialing(self):
        return self.status in (self.STATUS_ACTIVE, self.STATUS_TRIALING)

    @property
    def trial_days_remaining(self):
        if self.status != self.STATUS_TRIALING or not self.trial_end:
            return 0
        delta = self.trial_end - timezone.now()
        total_seconds = delta.total_seconds()
        if total_seconds <= 0:
            return 0
        return math.ceil(total_seconds / 86400)


class ModuleProduct(models.Model):
    """Stores Stripe pricing for each module add-on (in database, not .env)."""
    module = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    stripe_price_id = models.CharField(max_length=200, blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=10.00)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['module']

    def __str__(self):
        return f'{self.name} (${self.price}/mo)'


class ModuleSubscription(models.Model):
    """Per-school module add-on subscriptions ($10/mo each)."""
    MODULE_TEACHERS_ATTENDANCE = 'teachers_attendance'
    MODULE_STUDENTS_ATTENDANCE = 'students_attendance'
    MODULE_PROGRESS_REPORTS = 'student_progress_reports'

    MODULE_CHOICES = [
        (MODULE_TEACHERS_ATTENDANCE, 'Teachers Attendance'),
        (MODULE_STUDENTS_ATTENDANCE, 'Students Attendance'),
        (MODULE_PROGRESS_REPORTS, 'Student Progress Reports'),
    ]

    school_subscription = models.ForeignKey(
        SchoolSubscription,
        on_delete=models.CASCADE,
        related_name='modules',
    )
    module = models.CharField(max_length=50, choices=MODULE_CHOICES)
    stripe_subscription_item_id = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    activated_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('school_subscription', 'module')
        ordering = ['module']

    def __str__(self):
        return f'{self.school_subscription.school.name} — {self.get_module_display()}'


class Subscription(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_TRIALING = 'trialing'
    STATUS_PAST_DUE = 'past_due'
    STATUS_CANCELLED = 'cancelled'
    STATUS_EXPIRED = 'expired'

    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_TRIALING, 'Trialing'),
        (STATUS_PAST_DUE, 'Past Due'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscription',
    )
    package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, related_name='subscriptions')
    stripe_subscription_id = models.CharField(max_length=200, blank=True)
    stripe_customer_id = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TRIALING)
    trial_end = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.package} — {self.status}'

    @property
    def is_active_or_trialing(self):
        return self.status in (self.STATUS_ACTIVE, self.STATUS_TRIALING)

    @property
    def trial_days_remaining(self):
        if self.status != self.STATUS_TRIALING or not self.trial_end:
            return 0
        delta = self.trial_end - timezone.now()
        total_seconds = delta.total_seconds()
        if total_seconds <= 0:
            return 0
        return math.ceil(total_seconds / 86400)


class StripeEvent(models.Model):
    """Idempotency table to track processed Stripe webhook events."""
    event_id = models.CharField(max_length=200, unique=True, db_index=True)
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField(default=dict)

    class Meta:
        ordering = ['-processed_at']

    def __str__(self):
        return f'{self.event_type} — {self.event_id}'
