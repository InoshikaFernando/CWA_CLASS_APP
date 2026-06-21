"""WhatsApp parent-notification models (CPP-XXX).

Ships inert: ``WhatsAppConfig`` resolves *disabled* by default, so nothing can
be sent until a school is explicitly enabled and a Meta-approved template is
marked active. See docs/specs/CPP-XXX_whatsapp_parent_notifications.md.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class WhatsAppConfig(models.Model):
    """Per-school enablement with null-inheritance to a global default.

    A row with ``school=NULL`` is the global default. On a school row, a NULL
    boolean means "inherit the global value"; the global default itself is
    created disabled, so the feature is inert until someone opts a school in.
    Tri-state booleans (True / False / NULL) drive the inheritance — see
    ``whatsapp.services.config_for``.
    """
    school = models.OneToOneField(
        'classroom.School', on_delete=models.CASCADE,
        null=True, blank=True, related_name='whatsapp_config',
    )
    is_enabled = models.BooleanField(null=True, blank=True)
    notify_on_publish = models.BooleanField(null=True, blank=True)
    notify_on_submission = models.BooleanField(null=True, blank=True)
    # Optional Meta phone-number-id override (else falls back to the env value).
    sender_phone_id = models.CharField(max_length=64, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'WhatsApp config'
        verbose_name_plural = 'WhatsApp configs'

    def __str__(self):
        scope = self.school.name if self.school_id else 'GLOBAL DEFAULT'
        return f'WhatsAppConfig({scope}, enabled={self.is_enabled})'


class WhatsAppPreference(models.Model):
    """Per-parent opt-in. WhatsApp requires explicit consent before a business
    can message a user, so ``opted_in`` must be True for any send to proceed."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='whatsapp_preference',
    )
    # Confirmed E.164 number; if blank, recipient resolution falls back to
    # CustomUser.phone then Guardian.phone (Sprint 2).
    phone = models.CharField(max_length=30, blank=True)
    opted_in = models.BooleanField(default=False)
    opted_in_at = models.DateTimeField(null=True, blank=True)
    opted_out_at = models.DateTimeField(null=True, blank=True)
    receive_publish = models.BooleanField(default=True)
    receive_results = models.BooleanField(default=True)
    unsubscribe_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'WhatsAppPreference({self.user}, opted_in={self.opted_in})'

    def opt_in(self, phone='', when=None):
        when = when or timezone.now()
        self.opted_in = True
        self.opted_in_at = when
        self.opted_out_at = None
        if phone:
            self.phone = phone
        self.save()

    def opt_out(self, when=None):
        when = when or timezone.now()
        self.opted_in = False
        self.opted_out_at = when
        self.save()


class WhatsAppTemplate(models.Model):
    """Registry of Meta-approved message templates. A send is blocked unless the
    template for its event exists and ``is_active`` (i.e. approved by Meta)."""
    CATEGORY_UTILITY = 'utility'

    KEY_HOMEWORK_PUBLISHED = 'homework_published'
    KEY_HOMEWORK_RESULT = 'homework_result'

    key = models.CharField(max_length=50, unique=True)
    meta_template_name = models.CharField(max_length=100)
    language_code = models.CharField(max_length=10, default='en')
    category = models.CharField(max_length=20, default=CATEGORY_UTILITY)
    # Defaults False: a template only goes live once approved in Meta.
    is_active = models.BooleanField(default=False)
    # Documents the positional {{1}}, {{2}}… → field mapping for maintainers.
    body_param_order = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'WhatsAppTemplate({self.key}, active={self.is_active})'


class WhatsAppMessageLog(models.Model):
    """Append-only delivery log, mirroring classroom.EmailLog.

    ``status`` starts at ``queued``, advances to ``sent`` once the provider
    accepts it, then ``delivered``/``read`` as webhooks report progress.
    ``apply_delivery_event`` enforces precedence so a late lower-ranked event
    can't clobber a terminal one (same pattern as EmailLog).
    """
    STATUS_QUEUED = 'queued'
    STATUS_SENT = 'sent'
    STATUS_DELIVERED = 'delivered'
    STATUS_READ = 'read'
    STATUS_FAILED = 'failed'
    STATUS_UNDELIVERABLE = 'undeliverable'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_SENT, 'Sent'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_READ, 'Read'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_UNDELIVERABLE, 'Undeliverable'),
    ]
    STATUS_RANK = {
        STATUS_QUEUED: 0,
        STATUS_SENT: 1,
        STATUS_DELIVERED: 2,
        STATUS_READ: 3,
        STATUS_FAILED: 4,
        STATUS_UNDELIVERABLE: 4,
    }

    EVENT_HOMEWORK_PUBLISHED = 'homework_published'
    EVENT_HOMEWORK_RESULT = 'homework_result'
    EVENT_CHOICES = [
        (EVENT_HOMEWORK_PUBLISHED, 'Homework published'),
        (EVENT_HOMEWORK_RESULT, 'Homework result'),
    ]

    school = models.ForeignKey(
        'classroom.School', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='whatsapp_logs', db_index=True,
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='whatsapp_logs',
    )
    recipient_phone = models.CharField(max_length=30, blank=True)
    template = models.ForeignKey(
        WhatsAppTemplate, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='logs',
    )
    # Params already rendered for the template body, in positional order — kept
    # on the log so the async deliver task has everything it needs.
    template_params = models.JSONField(default=list, blank=True)
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES, blank=True)
    related_homework = models.ForeignKey(
        'homework.Homework', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='whatsapp_logs',
    )
    related_submission = models.ForeignKey(
        'homework.HomeworkSubmission', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='whatsapp_logs',
    )
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    provider_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    error_code = models.CharField(max_length=50, blank=True)
    error_detail = models.TextField(blank=True)
    # Non-null, unique: blocks RQ-retry / webhook double-sends. The service
    # computes a deterministic key per (event, related object, phone); callers
    # without an idempotency need get a unique uuid so the constraint is inert.
    idempotency_key = models.CharField(max_length=120, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    status_updated_at = models.DateTimeField(null=True, blank=True)

    _STATUS_TIMESTAMP_FIELD = {
        STATUS_SENT: 'sent_at',
        STATUS_DELIVERED: 'delivered_at',
        STATUS_READ: 'read_at',
        STATUS_FAILED: 'failed_at',
        STATUS_UNDELIVERABLE: 'failed_at',
    }

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', 'status']),
        ]

    def __str__(self):
        return f'{self.recipient_phone} — {self.event_type} ({self.status})'

    def apply_delivery_event(self, new_status, when, code='', detail=''):
        """Apply a status event respecting precedence. Returns True if changed.

        Always stamps the event's own timestamp (so every event is recorded),
        but only advances ``status`` when the new event ranks at least as high
        as the current one. The caller saves.
        """
        changed = False
        ts_field = self._STATUS_TIMESTAMP_FIELD.get(new_status)
        if ts_field and getattr(self, ts_field) is None:
            setattr(self, ts_field, when)
            changed = True

        if code and not self.error_code:
            self.error_code = code
            changed = True
        if detail and not self.error_detail:
            self.error_detail = detail
            changed = True

        current_rank = self.STATUS_RANK.get(self.status, 0)
        new_rank = self.STATUS_RANK.get(new_status, 0)
        if new_rank >= current_rank and new_status != self.status:
            self.status = new_status
            changed = True

        if changed:
            self.status_updated_at = when
        return changed

    def mark_sent(self, provider_message_id='', when=None):
        when = when or timezone.now()
        if provider_message_id:
            self.provider_message_id = provider_message_id
        self.apply_delivery_event(self.STATUS_SENT, when)
        self.save()

    def mark_failed(self, code='', detail='', when=None):
        when = when or timezone.now()
        self.apply_delivery_event(self.STATUS_FAILED, when, code=code, detail=detail)
        self.save()
