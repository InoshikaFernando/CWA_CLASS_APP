from io import StringIO

from django.contrib import admin, messages
from django.core.management import call_command
from django.db import transaction

from audit.services import log_event
from .models import (
    Package, DiscountCode, Payment, Subscription, PromoCode,
    InstituteDiscountCode,
    InstitutePlan, SchoolSubscription, ModuleProduct, ModuleSubscription,
    StripeEvent, Expense, RecurringExpense,
)


@admin.action(
    description='Make this the only student package '
                '(sync USD price, set default, retire the rest)',
)
def make_sole_student_package(modeladmin, request, queryset):
    """Point every future student at one package, in one action.

    Done as separate clicks this leaves windows where the wrong thing is true —
    a default package still carrying a non-USD price, or every package inactive
    at once — and it was exactly such a gap that let a student check out on an
    NZD price. So the Stripe sync, the default flag and the retirement of the
    other packages land together or not at all: anything that fails rolls the
    whole action back, including the price IDs the sync wrote.
    """
    packages = list(queryset)
    if len(packages) != 1:
        modeladmin.message_user(
            request,
            'Select exactly one package — this action makes it the only one '
            'students can subscribe to.',
            level=messages.ERROR,
        )
        return

    package = packages[0]
    if package.is_free:
        modeladmin.message_user(
            request,
            f'"{package.name}" is free, so it has no Stripe price to sync. '
            f'Pick the paid package students should be put on.',
            level=messages.ERROR,
        )
        return

    sync_log = StringIO()
    try:
        with transaction.atomic():
            # Pulls the active USD price for every plan, package and module.
            # It refuses to guess between two USD prices at one amount, so a
            # package it cannot resolve keeps whatever it had — which the
            # currency check below then rejects.
            call_command('sync_stripe_prices', stdout=sync_log, stderr=sync_log)
            package.refresh_from_db()

            from .stripe_service import assert_subscription_price_currency
            assert_subscription_price_currency(
                package.stripe_price_id, f'Package "{package.name}"',
            )

            package.is_active = True
            package.is_default = True
            package.save()   # clears is_default on every other package

            retired = Package.objects.exclude(pk=package.pk).filter(is_active=True)
            retired_names = list(retired.values_list('name', flat=True))
            retired.update(is_active=False)
    except Exception as exc:   # noqa: BLE001 — every failure is the admin's to see
        modeladmin.message_user(
            request,
            f'Nothing was changed. {exc}',
            level=messages.ERROR,
        )
        modeladmin.message_user(request, sync_log.getvalue(), level=messages.INFO)
        return

    log_event(
        user=request.user, school=None, category='data_change',
        action='billing_sole_student_package_set',
        detail={
            'package_id': package.id,
            'package_name': package.name,
            'stripe_price_id': package.stripe_price_id,
            'retired_packages': retired_names,
        },
        request=request,
    )
    retired_note = (
        f'Retired: {", ".join(retired_names)}.' if retired_names
        else 'No other package was active.'
    )
    modeladmin.message_user(
        request,
        f'"{package.name}" is now the only student package — '
        f'USD price {package.stripe_price_id}. {retired_note} '
        f'Students already subscribed keep the package they are on.',
        level=messages.SUCCESS,
    )


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    # is_default and stripe_price_id decide which package a school student is
    # put on and what currency their card is charged, so both are visible here
    # rather than only on the change form. Ticking is_default on one row clears
    # it on the others (Package.save).
    list_display = (
        'name', 'class_limit', 'price', 'stripe_price_id', 'trial_days',
        'is_active', 'is_default', 'order',
    )
    list_editable = ('is_active', 'is_default', 'order')
    ordering = ('order',)
    actions = (make_sole_student_package,)


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


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('incurred_on', 'category', 'vendor', 'amount', 'source')
    list_filter = ('category', 'source')
    search_fields = ('vendor', 'description', 'note')
    date_hierarchy = 'incurred_on'
    ordering = ('-incurred_on',)


@admin.register(RecurringExpense)
class RecurringExpenseAdmin(admin.ModelAdmin):
    list_display = (
        'category', 'vendor', 'amount', 'frequency', 'start_date',
        'end_date', 'is_active',
    )
    list_filter = ('category', 'frequency', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('vendor', 'description', 'note')
