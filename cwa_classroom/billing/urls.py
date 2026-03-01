from django.urls import path
from . import views

urlpatterns = [
    path('billing/checkout/<int:package_id>/', views.CheckoutView.as_view(), name='billing_checkout'),
    path('billing/success/', views.CheckoutSuccessView.as_view(), name='billing_success'),
    path('billing/cancel/', views.CheckoutCancelView.as_view(), name='billing_cancel'),
    path('stripe/webhook/', views.StripeWebhookView.as_view(), name='stripe_webhook'),
]
