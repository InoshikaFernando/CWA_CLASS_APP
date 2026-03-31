from django.urls import path
from . import views
from . import views_admin

urlpatterns = [
    # Individual student billing
    path('billing/checkout/<int:package_id>/', views.CheckoutView.as_view(), name='billing_checkout'),
    path('billing/create-payment-intent/<int:package_id>/', views.CreatePaymentIntentView.as_view(), name='create_payment_intent'),
    path('billing/confirm-payment/', views.ConfirmPaymentView.as_view(), name='confirm_payment'),
    path('billing/apply-promo/<int:package_id>/', views.ApplyPromoCodeView.as_view(), name='apply_promo_code'),
    path('billing/success/', views.CheckoutSuccessView.as_view(), name='billing_success'),
    path('billing/cancel/', views.CheckoutCancelView.as_view(), name='billing_cancel'),
    path('stripe/webhook/', views.StripeWebhookView.as_view(), name='stripe_webhook'),

    # Institute subscription
    path('billing/institute/plans/', views.InstitutePlanSelectView.as_view(), name='institute_plan_select'),
    path('billing/institute/trial-expired/', views.InstituteTrialExpiredView.as_view(), name='institute_trial_expired'),
    path('billing/institute/upgrade/', views.InstitutePlanUpgradeView.as_view(), name='institute_plan_upgrade'),
    path('billing/institute/dashboard/', views.InstituteSubscriptionDashboardView.as_view(), name='institute_subscription_dashboard'),
    path('billing/module-required/', views.ModuleRequiredView.as_view(), name='module_required'),

    # Institute Stripe checkout & management
    path('billing/institute/checkout/', views.InstituteCheckoutView.as_view(), name='institute_checkout'),
    path('billing/institute/checkout/success/', views.InstituteCheckoutSuccessView.as_view(), name='institute_checkout_success'),
    path('billing/institute/change-plan/', views.InstituteChangePlanView.as_view(), name='institute_change_plan'),
    path('billing/institute/cancel/', views.InstituteCancelSubscriptionView.as_view(), name='institute_cancel_subscription'),
    path('billing/portal/', views.StripeBillingPortalView.as_view(), name='stripe_billing_portal'),
    path('billing/institute/module/toggle/', views.ModuleToggleView.as_view(), name='module_toggle'),
    path('billing/history/', views.BillingHistoryView.as_view(), name='billing_history'),

    # Super Admin Billing Management
    path('admin-dashboard/billing/', views_admin.BillingAdminDashboardView.as_view(), name='billing_admin_dashboard'),

    # Plans
    path('admin-dashboard/billing/plans/', views_admin.PlanListView.as_view(), name='billing_admin_plan_list'),
    path('admin-dashboard/billing/plans/create/', views_admin.PlanCreateView.as_view(), name='billing_admin_plan_create'),
    path('admin-dashboard/billing/plans/<int:pk>/edit/', views_admin.PlanEditView.as_view(), name='billing_admin_plan_edit'),
    path('admin-dashboard/billing/plans/<int:pk>/toggle/', views_admin.PlanToggleActiveView.as_view(), name='billing_admin_plan_toggle'),
    path('admin-dashboard/billing/plans/<int:pk>/sync-stripe/', views_admin.PlanSyncStripeView.as_view(), name='billing_admin_plan_sync'),

    # Unified Coupon Codes
    path('admin-dashboard/billing/coupon-codes/', views_admin.CouponCodeListView.as_view(), name='billing_admin_coupon_list'),
    path('admin-dashboard/billing/coupon-codes/create/', views_admin.CouponCodeCreateView.as_view(), name='billing_admin_coupon_create'),

    # Discount Codes (legacy routes, still used for edit/toggle)
    path('admin-dashboard/billing/discount-codes/', views_admin.DiscountCodeListView.as_view(), name='billing_admin_discount_list'),
    path('admin-dashboard/billing/discount-codes/create/', views_admin.DiscountCodeCreateView.as_view(), name='billing_admin_discount_create'),
    path('admin-dashboard/billing/discount-codes/<int:pk>/edit/', views_admin.DiscountCodeEditView.as_view(), name='billing_admin_discount_edit'),
    path('admin-dashboard/billing/discount-codes/<int:pk>/toggle/', views_admin.DiscountCodeToggleActiveView.as_view(), name='billing_admin_discount_toggle'),

    # Module Products
    path('admin-dashboard/billing/modules/', views_admin.ModuleProductListView.as_view(), name='billing_admin_module_list'),
    path('admin-dashboard/billing/modules/<int:pk>/edit/', views_admin.ModuleProductEditView.as_view(), name='billing_admin_module_edit'),
    path('admin-dashboard/billing/modules/<int:pk>/toggle/', views_admin.ModuleProductToggleActiveView.as_view(), name='billing_admin_module_toggle'),
    path('admin-dashboard/billing/modules/<int:pk>/sync-stripe/', views_admin.ModuleProductSyncStripeView.as_view(), name='billing_admin_module_sync'),

    # Subscriptions
    path('admin-dashboard/billing/subscriptions/', views_admin.SubscriptionListView.as_view(), name='billing_admin_subscription_list'),
    path('admin-dashboard/billing/subscriptions/<int:pk>/', views_admin.SubscriptionDetailView.as_view(), name='billing_admin_subscription_detail'),
    path('admin-dashboard/billing/subscriptions/<int:pk>/override/', views_admin.SubscriptionOverrideView.as_view(), name='billing_admin_subscription_override'),

    # Promo Codes
    path('admin-dashboard/billing/promo-codes/', views_admin.PromoCodeListView.as_view(), name='billing_admin_promo_list'),
    path('admin-dashboard/billing/promo-codes/create/', views_admin.PromoCodeCreateView.as_view(), name='billing_admin_promo_create'),
    path('admin-dashboard/billing/promo-codes/<int:pk>/edit/', views_admin.PromoCodeEditView.as_view(), name='billing_admin_promo_edit'),
    path('admin-dashboard/billing/promo-codes/<int:pk>/toggle/', views_admin.PromoCodeToggleActiveView.as_view(), name='billing_admin_promo_toggle'),
]
