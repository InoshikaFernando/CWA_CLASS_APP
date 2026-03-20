from django.urls import path
from . import views

urlpatterns = [
    # Individual student billing
    path('billing/checkout/<int:package_id>/', views.CheckoutView.as_view(), name='billing_checkout'),
    path('billing/create-payment-intent/<int:package_id>/', views.CreatePaymentIntentView.as_view(), name='create_payment_intent'),
    path('billing/confirm-payment/', views.ConfirmPaymentView.as_view(), name='confirm_payment'),
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
]
