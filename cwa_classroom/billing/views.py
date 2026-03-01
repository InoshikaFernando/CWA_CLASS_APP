from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.conf import settings
from .models import Package


class CheckoutView(LoginRequiredMixin, View):
    def get(self, request, package_id):
        package = get_object_or_404(Package, id=package_id, is_active=True)
        # Stripe integration to be implemented
        # For now, skip to success
        return render(request, 'billing/checkout.html', {
            'package': package,
            'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
        })


class CheckoutSuccessView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'billing/success.html')


class CheckoutCancelView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect('select_classes')


class StripeWebhookView(View):
    def post(self, request):
        # Stripe webhook handler — to be implemented
        return HttpResponse(status=200)
