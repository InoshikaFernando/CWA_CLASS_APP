from django.db import models
from django.conf import settings
from django.utils import timezone


class Package(models.Model):
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
    class_limit = models.PositiveIntegerField(
        default=0,
        help_text='Class access granted. 0 = unlimited.',
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
        return max(0, delta.days)
