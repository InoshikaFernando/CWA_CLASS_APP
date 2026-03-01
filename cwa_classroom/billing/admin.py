from django.contrib import admin
from .models import Package, DiscountCode, Payment, Subscription


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'class_limit', 'price', 'trial_days', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    ordering = ('order',)


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'discount_percent', 'uses', 'max_uses', 'is_active', 'expires_at')
    list_filter = ('is_active',)
    search_fields = ('code',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('user', 'package', 'amount', 'currency', 'status', 'created_at')
    list_filter = ('status', 'currency')
    search_fields = ('user__username', 'stripe_payment_intent_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'package', 'status', 'trial_end', 'current_period_end')
    list_filter = ('status',)
    search_fields = ('user__username', 'stripe_subscription_id')
    readonly_fields = ('created_at', 'updated_at')
