from django.contrib import admin
from .models import (
    Package, DiscountCode, Payment, Subscription, PromoCode,
    InstituteDiscountCode,
    InstitutePlan, SchoolSubscription, ModuleProduct, ModuleSubscription,
    StripeEvent,
)


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'class_limit', 'price', 'trial_days', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    ordering = ('order',)


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'discount_percent', 'grant_days', 'uses', 'max_uses', 'is_active', 'expires_at')
    list_filter = ('is_active', 'discount_percent')
    search_fields = ('code',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('user', 'package', 'amount', 'currency', 'status', 'created_at')
    list_filter = ('status', 'currency')
    search_fields = ('user__username', 'stripe_payment_intent_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'class_limit', 'uses', 'max_uses', 'is_active', 'expires_at')
    list_editable = ('is_active',)
    search_fields = ('code', 'description')
    filter_horizontal = ('redeemed_by',)
    readonly_fields = ('uses', 'created_at')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'package', 'status', 'trial_end', 'current_period_end')
    list_filter = ('status',)
    search_fields = ('user__username', 'stripe_subscription_id')
    readonly_fields = ('created_at', 'updated_at')


class ModuleSubscriptionInline(admin.TabularInline):
    model = ModuleSubscription
    extra = 0
    readonly_fields = ('activated_at',)


@admin.register(InstituteDiscountCode)
class InstituteDiscountCodeAdmin(admin.ModelAdmin):
    list_display = (
        'code', 'description', 'discount_percent',
        'override_class_limit', 'override_student_limit',
        'uses', 'max_uses', 'is_active', 'expires_at',
    )
    list_editable = ('is_active',)
    list_filter = ('is_active', 'discount_percent')
    search_fields = ('code', 'description')
    readonly_fields = ('uses', 'created_at')
    fieldsets = (
        (None, {
            'fields': ('code', 'description', 'discount_percent', 'is_active'),
        }),
        ('Limit Overrides', {
            'fields': ('override_class_limit', 'override_student_limit'),
            'description': 'Leave blank to use plan defaults. Set to 0 for unlimited.',
        }),
        ('Usage', {
            'fields': ('max_uses', 'uses', 'expires_at', 'created_at'),
        }),
    )


@admin.register(InstitutePlan)
class InstitutePlanAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'slug', 'price', 'class_limit', 'student_limit',
        'invoice_limit_yearly', 'extra_invoice_rate', 'trial_days',
        'is_active', 'order',
    )
    list_editable = ('is_active', 'order')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('order',)


@admin.register(SchoolSubscription)
class SchoolSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'school', 'plan', 'status', 'trial_end',
        'invoices_used_this_year', 'current_period_end',
    )
    list_filter = ('status', 'plan')
    search_fields = ('school__name', 'stripe_subscription_id')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ModuleSubscriptionInline]


@admin.register(ModuleProduct)
class ModuleProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'module', 'price', 'stripe_price_id', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('name', 'module')


@admin.register(ModuleSubscription)
class ModuleSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'school_subscription', 'module', 'is_active',
        'activated_at', 'deactivated_at',
    )
    list_filter = ('module', 'is_active')
    search_fields = ('school_subscription__school__name',)


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'event_type', 'processed_at')
    list_filter = ('event_type',)
    search_fields = ('event_id', 'event_type')
    readonly_fields = ('event_id', 'event_type', 'processed_at', 'payload')
