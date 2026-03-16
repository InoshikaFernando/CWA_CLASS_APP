import json
import stripe

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from .models import Package, Subscription, Payment

stripe.api_key = settings.STRIPE_SECRET_KEY


class CheckoutView(LoginRequiredMixin, View):
    def get(self, request, package_id):
        package = get_object_or_404(Package, id=package_id, is_active=True)
        return render(request, 'billing/checkout.html', {
            'package': package,
            'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
        })


class CreatePaymentIntentView(LoginRequiredMixin, View):
    """Create a Stripe PaymentIntent and return the client_secret."""

    def post(self, request, package_id):
        package = get_object_or_404(Package, id=package_id, is_active=True)
        if package.is_free:
            return JsonResponse({'error': 'Cannot checkout a free package.'}, status=400)

        amount = int(package.price * 100)  # Stripe uses cents

        try:
            # Get or create Stripe customer
            sub = getattr(request.user, 'subscription', None)
            customer_id = sub.stripe_customer_id if sub and sub.stripe_customer_id else None

            if not customer_id:
                customer = stripe.Customer.create(
                    email=request.user.email,
                    metadata={'user_id': request.user.id},
                )
                customer_id = customer.id
                if sub:
                    sub.stripe_customer_id = customer_id
                    sub.save(update_fields=['stripe_customer_id'])

            intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=settings.STRIPE_CURRENCY,
                customer=customer_id,
                metadata={
                    'user_id': request.user.id,
                    'package_id': package.id,
                },
            )

            return JsonResponse({'client_secret': intent.client_secret})

        except stripe.error.StripeError as e:
            return JsonResponse({'error': str(e)}, status=400)


class ConfirmPaymentView(LoginRequiredMixin, View):
    """Called after successful Stripe payment to activate the subscription."""

    def post(self, request):
        data = json.loads(request.body)
        payment_intent_id = data.get('payment_intent_id')
        package_id = data.get('package_id')

        if not payment_intent_id or not package_id:
            return JsonResponse({'error': 'Missing parameters.'}, status=400)

        package = get_object_or_404(Package, id=package_id)

        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        except stripe.error.StripeError:
            return JsonResponse({'error': 'Invalid payment.'}, status=400)

        if intent.status != 'succeeded':
            return JsonResponse({'error': 'Payment not completed.'}, status=400)

        # Record payment
        Payment.objects.create(
            user=request.user,
            package=package,
            amount=package.price,
            stripe_payment_intent_id=payment_intent_id,
            status=Payment.STATUS_SUCCEEDED,
        )

        # Activate subscription
        sub, _ = Subscription.objects.get_or_create(
            user=request.user,
            defaults={'package': package},
        )
        sub.package = package
        sub.status = Subscription.STATUS_ACTIVE
        sub.trial_end = None
        sub.current_period_start = timezone.now()
        sub.save()

        # Update user package
        request.user.package = package
        request.user.save(update_fields=['package'])

        return JsonResponse({'success': True, 'redirect_url': '/billing/success/'})


class CheckoutSuccessView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'billing/success.html')


class CheckoutCancelView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect('select_classes')


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(View):
    """Handle Stripe webhook events for async payment confirmation."""

    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            return HttpResponse(status=400)

        if event['type'] == 'payment_intent.succeeded':
            intent = event['data']['object']
            user_id = intent['metadata'].get('user_id')
            package_id = intent['metadata'].get('package_id')

            if user_id and package_id:
                from accounts.models import CustomUser
                try:
                    user = CustomUser.objects.get(id=user_id)
                    package = Package.objects.get(id=package_id)

                    sub, _ = Subscription.objects.get_or_create(
                        user=user, defaults={'package': package},
                    )
                    sub.package = package
                    sub.status = Subscription.STATUS_ACTIVE
                    sub.trial_end = None
                    sub.current_period_start = timezone.now()
                    sub.save()

                    user.package = package
                    user.save(update_fields=['package'])
                except (CustomUser.DoesNotExist, Package.DoesNotExist):
                    pass

        return HttpResponse(status=200)
