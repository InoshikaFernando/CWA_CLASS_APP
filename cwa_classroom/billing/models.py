import math

from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from django.utils import timezone


DURATION_CHOICES = [
    ('forever', 'Forever'),
    ('once', 'Once'),
    ('repeating', 'Multiple Months'),
]


class StudentBasicGrantMixin:
    """The rules for ``grants_student_basic``, shared by both code models.

    Two rules, and both exist because breaking them is silent.

    **A code that still charges may not carry the tier.** Nothing in account
    creation mentions tiers: the student picks a plan at step 3 of the sign-up
    form, where they read the full price, and types the code at step 5, which
    gives no feedback — it is validated on submit. There is no screen in
    between. A paying student would get fewer questions than the plan they had
    just read described, with no disclosure anywhere.

    **The flag cannot be changed on a code students already hold.** A code is
    recorded on the subscriptions that redeemed it, and the tier is resolved
    from it every time one of those subscriptions is activated. So flipping the
    flag on a code already in circulation reaches BACKWARDS: the next time one
    of those students re-checks-out — or the success page runs — they are put on
    Student Basic, having been promised nothing of the sort. CWA's own free
    students are exactly the population this would hit.

    A new promotion therefore needs a NEW code. The error says so.
    """

    def clean(self):
        super().clean()
        if self.grants_student_basic and self.discount_percent != 100:
            raise ValidationError({
                'grants_student_basic': (
                    'Student Basic can only be granted by a code that is 100% '
                    'off. This code charges the student '
                    f'{100 - self.discount_percent}% of the price, and nothing '
                    'in the sign-up flow tells them the tier leaves out the '
                    'AI-graded questions.'
                ),
            })
        if self.pk:
            stored = type(self).objects.filter(pk=self.pk).values(
                'grants_student_basic', 'uses').first()
            if (stored and stored['grants_student_basic']
                    != self.grants_student_basic and stored['uses'] > 0):
                raise ValidationError({
                    'grants_student_basic': (
                        f'{self.code} has already been redeemed '
                        f'{stored["uses"]} time(s). Changing this now would '
                        'change what those students get the next time their '
                        'subscription is activated. Issue a new code for the '
                        'new promotion instead.'
                    ),
                })


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
    is_default = models.BooleanField(
        default=False,
        help_text='Mark as the default student subscription package. Only one should be default.',
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'price']

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.price > 0 and not self.stripe_price_id:
            raise ValidationError(
                {'stripe_price_id': 'Paid packages (price > $0) must have a Stripe Price ID.'},
            )

    @property
    def is_free(self):
        return self.price == 0

    @property
    def is_unlimited(self):
        return self.class_limit == 0


class DiscountCode(StudentBasicGrantMixin, models.Model):
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
    duration = models.CharField(
        max_length=20, choices=DURATION_CHOICES, default='forever',
        help_text='Stripe coupon duration: forever, once, or repeating (multiple months).',
    )
    duration_in_months = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Number of months for repeating duration. Required when duration is "repeating".',
    )
    applicable_packages = models.ManyToManyField(
        'Package', blank=True, related_name='discount_codes',
        help_text='Packages this code applies to. Leave empty for all packages.',
    )
    grants_student_basic = models.BooleanField(
        default=False,
        help_text=(
            'Put students who redeem this code on the Student Basic module — '
            'the free promotional edition, without the AI-graded questions. '
            'Off by default: an ordinary code grants the app in full.'
        ),
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
    currency = models.CharField(max_length=10, default='usd')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.package} — {self.status}'


class PromoCode(StudentBasicGrantMixin, models.Model):
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
    duration = models.CharField(
        max_length=20, choices=DURATION_CHOICES, default='forever',
        help_text='Stripe coupon duration: forever, once, or repeating (multiple months).',
    )
    duration_in_months = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Number of months for repeating duration.',
    )
    applicable_packages = models.ManyToManyField(
        'Package', blank=True, related_name='promo_codes',
        help_text='Packages this code applies to. Leave empty for all packages.',
    )
    max_uses = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Leave blank for unlimited uses.',
    )
    uses = models.PositiveIntegerField(default=0)
    grants_student_basic = models.BooleanField(
        default=False,
        help_text=(
            'Put students who redeem this code on the Student Basic module — '
            'the free promotional edition, without the AI-graded questions. '
            'Off by default: an ordinary code grants the app in full.'
        ),
    )
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
    duration = models.CharField(
        max_length=20, choices=DURATION_CHOICES, default='forever',
        help_text='Stripe coupon duration: forever, once, or repeating (multiple months).',
    )
    duration_in_months = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Number of months for repeating duration. Required when duration is "repeating".',
    )
    applicable_plans = models.ManyToManyField(
        'InstitutePlan', blank=True, related_name='discount_codes',
        help_text='Plans this code applies to. Leave empty for all plans.',
    )
    applicable_modules = models.ManyToManyField(
        'ModuleProduct', blank=True, related_name='discount_codes',
        help_text='Modules this code applies to. Leave empty for all modules.',
    )
    max_uses = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Leave blank for unlimited uses.',
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

    def clean(self):
        super().clean()
        if self.price > 0 and not self.stripe_price_id:
            raise ValidationError(
                {'stripe_price_id': 'Paid plans (price > $0) must have a Stripe Price ID.'},
            )

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
        indexes = [
            models.Index(fields=['status']),
        ]

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
    pages_per_month = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Monthly page quota for AI import modules. NULL = not applicable, 0 = unlimited.',
    )
    is_active = models.BooleanField(default=True)
    # Quota for AI grading modules — null = unlimited (Enterprise)
    questions_per_month = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Monthly AI-graded answer quota. Null = unlimited. Only relevant for ai_grading_* modules.',
    )

    class Meta:
        ordering = ['module']

    def __str__(self):
        return f'{self.name} (${self.price}/mo)'


class ModuleSubscription(models.Model):
    """Per-school module add-on subscriptions ($10/mo each)."""
    MODULE_TEACHERS_ATTENDANCE = 'teachers_attendance'
    MODULE_STUDENTS_ATTENDANCE = 'students_attendance'
    MODULE_PROGRESS_REPORTS = 'student_progress_reports'
    MODULE_AI_IMPORT_STARTER = 'ai_import_starter'
    MODULE_AI_IMPORT_PROFESSIONAL = 'ai_import_professional'
    MODULE_AI_IMPORT_ENTERPRISE = 'ai_import_enterprise'
    MODULE_AI_GRADING_STARTER = 'ai_grading_starter'
    MODULE_AI_GRADING_PROFESSIONAL = 'ai_grading_professional'
    MODULE_AI_GRADING_ENTERPRISE = 'ai_grading_enterprise'

    MODULE_CHOICES = [
        (MODULE_TEACHERS_ATTENDANCE, 'Teachers Attendance'),
        (MODULE_STUDENTS_ATTENDANCE, 'Students Attendance'),
        (MODULE_PROGRESS_REPORTS, 'Student Progress Reports'),
        (MODULE_AI_IMPORT_STARTER, 'AI Question Import - Starter'),
        (MODULE_AI_IMPORT_PROFESSIONAL, 'AI Question Import - Professional'),
        (MODULE_AI_IMPORT_ENTERPRISE, 'AI Question Import - Enterprise'),
        (MODULE_AI_GRADING_STARTER, 'AI Grading - Starter (1,000 answers/mo)'),
        (MODULE_AI_GRADING_PROFESSIONAL, 'AI Grading - Professional (5,000 answers/mo)'),
        (MODULE_AI_GRADING_ENTERPRISE, 'AI Grading - Enterprise (unlimited)'),
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
    promo_code_used = models.CharField(
        max_length=50, blank=True,
        help_text='Promo code used to activate this subscription.',
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    # Discount snapshot — set when a code is redeemed at the CompleteProfileView
    # gate (school students). NULL = no discount recorded. The percent is
    # snapshotted so history survives later edits/deletion of the DiscountCode.
    discount_code = models.ForeignKey(
        'billing.DiscountCode', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='redeemed_subscriptions',
        help_text='Discount code redeemed for this subscription, if any.',
    )
    discount_percent_snapshot = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Percent off at redemption (100 = fully free). Snapshot, not live.',
    )
    discount_cleared_at = models.DateTimeField(null=True, blank=True)
    discount_cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # discount_state values
    DISCOUNT_NONE = 'none'
    DISCOUNT_FREE_100 = 'free_100'
    DISCOUNT_PARTIAL = 'partial'
    DISCOUNT_FULL = 'full'

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.package} — {self.status}'

    @staticmethod
    def classify_discount(status, stripe_subscription_id, discount_percent_snapshot, has_paid):
        """Pure discount classifier — single source of truth for the property,
        the HoI list view, and the backfill command (CPP-XXX).

        ``has_paid`` is "the user has a succeeded billing.Payment", supplied by
        the caller so a list view can batch it (avoid an N+1). Rules:
          * non-active/trialing                          -> none
          * snapshot >= 100                              -> free_100
          * 0 < snapshot < 100 AND a Stripe sub exists   -> partial
            (a partial snapshot with no Stripe sub is an abandoned checkout)
          * snapshot == 0                                -> full
          * no snapshot, ACTIVE, no Stripe sub, not paid -> free_100 (legacy)
            (TRIALING is excluded so a paid-plan trial isn't read as free; the
            has_paid guard excludes legacy one-time-PaymentIntent payers)
          * otherwise                                    -> full
        """
        if status not in (Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING):
            return Subscription.DISCOUNT_NONE
        pct = discount_percent_snapshot
        if pct is not None:
            if pct >= 100:
                return Subscription.DISCOUNT_FREE_100
            if pct > 0:
                return (Subscription.DISCOUNT_PARTIAL if stripe_subscription_id
                        else Subscription.DISCOUNT_NONE)
            return Subscription.DISCOUNT_FULL
        if (status == Subscription.STATUS_ACTIVE
                and not stripe_subscription_id and not has_paid):
            return Subscription.DISCOUNT_FREE_100
        return Subscription.DISCOUNT_FULL

    @property
    def discount_state(self):
        # Only the legacy-inference branch needs the Payment lookup.
        has_paid = False
        if (self.discount_percent_snapshot is None
                and self.status == self.STATUS_ACTIVE
                and not self.stripe_subscription_id):
            has_paid = Payment.objects.filter(
                user_id=self.user_id, status=Payment.STATUS_SUCCEEDED,
            ).exists()
        return self.classify_discount(
            self.status, self.stripe_subscription_id,
            self.discount_percent_snapshot, has_paid,
        )

    @property
    def has_discount(self):
        return self.discount_state in (self.DISCOUNT_FREE_100, self.DISCOUNT_PARTIAL)

    def clear_discount(self, by_user=None):
        """Remove the discount and cancel the discounted access (CPP-XXX).

        Cancels this subscription and clears the discount snapshot so the
        student must re-pay full at the CompleteProfileView gate. Does NOT touch
        Stripe (the caller cancels the Stripe subscription, if any) and does NOT
        re-gate the user (the caller sets profile_completed=False) — kept here as
        the pure DB state change so it's easy to test.
        """
        self.status = self.STATUS_CANCELLED
        self.discount_code = None
        self.discount_percent_snapshot = None
        self.discount_cleared_at = timezone.now()
        self.discount_cleared_by = by_user
        self.cancelled_at = timezone.now()
        self.save(update_fields=[
            'status', 'discount_code', 'discount_percent_snapshot',
            'discount_cleared_at', 'discount_cleared_by', 'cancelled_at', 'updated_at',
        ])

    @property
    def is_promo_activated(self):
        """True if this subscription was activated via a promo code."""
        return bool(self.promo_code_used)

    @property
    def is_active_or_trialing(self):
        return self.status in (self.STATUS_ACTIVE, self.STATUS_TRIALING)

    @property
    def access_days_remaining(self):
        """Days remaining for promo-activated subscriptions."""
        if not self.trial_end:
            return 0
        delta = self.trial_end - timezone.now()
        total_seconds = delta.total_seconds()
        if total_seconds <= 0:
            return 0
        return max(1, int(total_seconds / 86400) + (1 if total_seconds % 86400 > 0 else 0))

    @property
    def trial_days_remaining(self):
        if self.status != self.STATUS_TRIALING or not self.trial_end:
            return 0
        delta = self.trial_end - timezone.now()
        total_seconds = delta.total_seconds()
        if total_seconds <= 0:
            return 0
        return math.ceil(total_seconds / 86400)


class StudentModule(models.Model):
    """A module switched on (or deliberately off) for ONE individual student.

    The individual-student mirror of :class:`ModuleSubscription`, which does the
    same job for a school: a school buys modules against its
    ``SchoolSubscription``, a student carries them on their own
    ``billing.Subscription``.

    **Nothing here is a default.** A student with no rows in this table behaves
    exactly as they did before the table existed — the app in full, AI-graded
    questions included. That is deliberate and load-bearing: every student on
    the site today has no rows, so the migration that creates this table changes
    nobody's access, and a student who subscribes tomorrow gets no rows either.
    Modules are attached one student at a time, by hand or by a promotion code
    that says to.

    Two modules, reading in opposite directions:

    ``student_basic``
        The free promotional edition: the questions the app can mark for
        itself, and none of the ones a model has to mark. It is a *withhold*,
        so it applies only to the student it is attached to.

    ``student_ai_grading``
        The paid add-on that puts the AI-graded questions back. A student
        holding it is AI-graded whatever else they hold — it is the thing a
        Student Basic student upgrades to, so it has to win.
    """

    MODULE_BASIC = 'student_basic'
    MODULE_AI_GRADING = 'student_ai_grading'

    MODULE_CHOICES = [
        (MODULE_BASIC, 'Student Basic — self-marked questions only'),
        (MODULE_AI_GRADING, 'AI Graded Questions'),
    ]

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name='student_modules',
    )
    module = models.CharField(max_length=50, choices=MODULE_CHOICES)
    is_active = models.BooleanField(
        default=True,
        help_text='Untick to switch the module off without losing the record of it.',
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
        help_text='Who attached this module. Blank when a promotion code did.',
    )
    source_code = models.CharField(
        max_length=50, blank=True,
        help_text='The promotion/discount code that granted it, if any.',
    )
    note = models.CharField(
        max_length=200, blank=True,
        help_text='Why this student has it — shown on the admin list.',
    )
    activated_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('subscription', 'module')
        ordering = ['module']

    def __str__(self):
        state = '' if self.is_active else ' (off)'
        return f'{self.subscription.user.username} — {self.get_module_display()}{state}'


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


class InvoiceStripePayment(models.Model):
    """
    Tracks a Stripe Checkout Session initiated by a parent to pay
    outstanding invoice balances. A single session may cover multiple invoices.
    Allocation (oldest-first) is recorded in invoice_allocations JSON field.
    """
    STATUS_PENDING = 'pending'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_FAILED = 'failed'
    STATUS_EXPIRED = 'expired'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUCCEEDED, 'Succeeded'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='invoice_stripe_payments',
    )
    # Total charged to card (includes Stripe fee)
    total_charged = models.DecimalField(max_digits=10, decimal_places=2)
    # Amount that will be allocated to invoices (excl. fee)
    amount_applied = models.DecimalField(max_digits=10, decimal_places=2)
    stripe_fee = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=10, default='nzd')
    stripe_checkout_session_id = models.CharField(max_length=200, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # JSON list: [{"invoice_id": 1, "amount": "120.00"}, ...]  oldest-first allocation
    invoice_allocations = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'InvoiceStripePayment #{self.pk} — {self.parent} — {self.status}'


class AIGradingUsage(models.Model):
    """Tracks per-school AI grading usage per billing period (monthly).

    Each row = one school's usage for one calendar month.
    `answers_graded` counts actual Claude API calls made (cache hits are free and not counted).
    """
    school = models.ForeignKey(
        'classroom.School',
        on_delete=models.CASCADE,
        related_name='ai_grading_usage',
    )
    period_start = models.DateField(help_text='First day of the billing month.')
    answers_graded = models.PositiveIntegerField(
        default=0,
        help_text='Number of answers graded by Claude this period (cache hits excluded).',
    )
    tokens_used = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, default=0,
        help_text='Estimated Anthropic API cost in USD for this period.',
    )
    highest_alert_sent = models.PositiveIntegerField(
        default=0,
        help_text=(
            'Highest usage-percentage warning already emailed for this period '
            '(0 = none sent). The 75/80/85/90/95/100% alerts fire once each: '
            'without this they would re-send on every answer graded past the '
            'threshold. Resets naturally, since each month gets its own row.'
        ),
    )

    class Meta:
        unique_together = ('school', 'period_start')
        ordering = ['-period_start']

    def __str__(self):
        return f'{self.school.name} — {self.period_start} — {self.answers_graded} answers'


# ---------------------------------------------------------------------------
# Operating expenses (income-vs-expense dashboard)
# ---------------------------------------------------------------------------

class ExpenseCategory(models.TextChoices):
    """Vendor buckets for operating costs. Stripe income is the counterpart."""
    CLAUDE_API = 'claude_api', 'Claude API (Anthropic)'
    CLAUDE_CODE = 'claude_code', 'Claude Code'
    OPENAI_API = 'openai_api', 'OpenAI API (GPT)'
    DIGITALOCEAN = 'digitalocean', 'DigitalOcean'
    RESEND = 'resend', 'Resend (email)'
    GODADDY = 'godaddy', 'GoDaddy (domain)'
    GITHUB = 'github', 'GitHub'
    STRIPE_FEES = 'stripe_fees', 'Stripe fees'
    OTHER = 'other', 'Other'


# How an Expense row got created. Manual rows are user-owned; recurring and
# ai_grading rows are machine-owned and re-synced idempotently by the
# materialize_recurring_expenses command — so they must never be hand-edited.
EXPENSE_SOURCE_MANUAL = 'manual'
EXPENSE_SOURCE_RECURRING = 'recurring'
EXPENSE_SOURCE_AI_GRADING = 'ai_grading'
EXPENSE_SOURCE_DIGITALOCEAN = 'digitalocean_api'
# What GitHub billed, from its enhanced billing usage report (CPP-384).
EXPENSE_SOURCE_GITHUB = 'github_api'
# Billed AI spend fetched from the vendor's own API (CPP-383). Kept distinct
# from EXPENSE_SOURCE_AI_GRADING (the token estimate) so the two can coexist
# during the switchover and the authoritative one is identifiable.
EXPENSE_SOURCE_AI_VENDOR = 'ai_vendor_api'
EXPENSE_SOURCE_CHOICES = [
    (EXPENSE_SOURCE_MANUAL, 'Manual entry'),
    (EXPENSE_SOURCE_RECURRING, 'Recurring template'),
    (EXPENSE_SOURCE_AI_GRADING, 'AI usage (auto)'),
    (EXPENSE_SOURCE_DIGITALOCEAN, 'DigitalOcean API (auto)'),
    (EXPENSE_SOURCE_GITHUB, 'GitHub billing API (auto)'),
    (EXPENSE_SOURCE_AI_VENDOR, 'AI vendor billed (auto)'),
]

# Sources a human owns and may edit/delete in the UI. Everything else is
# machine-synced (re-derived each run) and therefore read-only.
EXPENSE_EDITABLE_SOURCES = {EXPENSE_SOURCE_MANUAL, EXPENSE_SOURCE_RECURRING}

# Sources carrying a vendor's OWN billed figure for a month, as opposed to the
# flat estimate a RecurringExpense template books ahead of the invoice. Once
# one of these exists for a (category, month) the estimate for that month is
# superseded and must not be re-booked — otherwise the month is counted twice.
AUTHORITATIVE_AUTO_SOURCES = (
    EXPENSE_SOURCE_DIGITALOCEAN,
    EXPENSE_SOURCE_GITHUB,
    EXPENSE_SOURCE_AI_VENDOR,
)


class Expense(models.Model):
    """A single operating cost, recorded in NZD (the dashboard's base currency).

    Vendor bills in USD (Claude, DigitalOcean, Resend …) are converted to NZD
    when entered — `amount` is always NZD so the dashboard can sum across
    categories without FX handling. `original_amount` / `original_currency`
    keep the source figure for reference only; they are never summed.

    Rows are grouped by `source`:
      * manual     — typed in the admin UI by a superuser.
      * recurring  — generated from a RecurringExpense template by the
                     materialize_recurring_expenses command (idempotent).
      * ai_grading — one row per month synced from AIGradingUsage's estimated
                     Anthropic cost (USD→NZD). Covers grading API spend only;
                     other Anthropic usage is entered manually as claude_api.
    """
    category = models.CharField(
        max_length=32, choices=ExpenseCategory.choices,
        default=ExpenseCategory.OTHER,
    )
    vendor = models.CharField(max_length=120, blank=True)
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text='Cost in NZD (convert foreign bills before entering).',
    )
    incurred_on = models.DateField(
        help_text='Date the cost applies to. Use the 1st of the month for '
                  'monthly bills so it groups cleanly.',
    )
    original_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Optional: the bill amount in its native currency, for '
                  'reference only (not used in totals).',
    )
    original_currency = models.CharField(max_length=3, blank=True)
    source = models.CharField(
        max_length=20, choices=EXPENSE_SOURCE_CHOICES,
        default=EXPENSE_SOURCE_MANUAL,
    )
    recurring = models.ForeignKey(
        'RecurringExpense', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generated_expenses',
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-incurred_on', 'category']
        indexes = [models.Index(fields=['incurred_on'])]
        constraints = [
            # One auto row per template per month, and one ai_grading row per
            # vendor per month — makes re-running the sync command a no-op.
            models.UniqueConstraint(
                fields=['recurring', 'incurred_on'],
                condition=models.Q(recurring__isnull=False),
                name='uniq_recurring_expense_per_date',
            ),
            # Category is part of the key because AI spend is now expensed per
            # provider: one Anthropic row and one OpenAI row can share a month.
            # Without the category the schema silently enforced "exactly one AI
            # vendor", which is how OpenAI spend had nowhere to go (CPP-382).
            models.UniqueConstraint(
                fields=['source', 'incurred_on', 'category'],
                condition=models.Q(source='ai_grading'),
                name='uniq_ai_grading_expense_per_month_vendor',
            ),
        ]

    def __str__(self):
        return f'{self.get_category_display()} — {self.incurred_on} — ${self.amount}'

    @property
    def is_auto(self):
        return self.source != EXPENSE_SOURCE_MANUAL

    @property
    def is_editable(self):
        """Manual + recurring rows can be hand-edited; synced rows can't."""
        return self.source in EXPENSE_EDITABLE_SOURCES


class RecurringExpense(models.Model):
    """Template for a fixed, predictable cost (domain renewal, flat sub …).

    The materialize_recurring_expenses command walks active templates each run
    and creates any missing Expense rows up to the current period, so the
    operator records the amount once instead of re-typing it every month.
    """
    FREQUENCY_MONTHLY = 'monthly'
    FREQUENCY_YEARLY = 'yearly'
    FREQUENCY_CHOICES = [
        (FREQUENCY_MONTHLY, 'Monthly'),
        (FREQUENCY_YEARLY, 'Yearly'),
    ]

    category = models.CharField(
        max_length=32, choices=ExpenseCategory.choices,
        default=ExpenseCategory.OTHER,
    )
    vendor = models.CharField(max_length=120, blank=True)
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text='Cost in NZD per occurrence.',
    )
    frequency = models.CharField(
        max_length=10, choices=FREQUENCY_CHOICES, default=FREQUENCY_MONTHLY,
    )
    start_date = models.DateField(
        help_text='First period this cost applies. Day is ignored — costs are '
                  'booked to the 1st of the month.',
    )
    end_date = models.DateField(
        null=True, blank=True,
        help_text='Optional: stop generating after this date (e.g. cancelled).',
    )
    is_active = models.BooleanField(default=True)
    is_estimate = models.BooleanField(
        default=False,
        help_text='Placeholder for a cost nobody can fetch (Claude Code bills '
                  'per use with no API). A charge entered by hand for the same '
                  'month replaces the estimate instead of adding to it.',
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'vendor']

    def __str__(self):
        return f'{self.get_category_display()} — ${self.amount}/{self.frequency}'
