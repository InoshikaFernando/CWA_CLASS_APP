import json
import stripe

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from .models import Package, Subscription, Payment, InstitutePlan, SchoolSubscription, ModuleSubscription
from .entitlements import get_school_for_user, get_school_subscription, check_class_limit, check_student_limit, check_invoice_limit
from audit.services import log_event

stripe.api_key = settings.STRIPE_SECRET_KEY


class CheckoutView(LoginRequiredMixin, View):
    """DEPRECATED: Legacy PaymentIntent checkout. Use Stripe Checkout Sessions instead."""

    def get(self, request, package_id):
        package = get_object_or_404(Package, id=package_id, is_active=True)
        return render(request, 'billing/checkout.html', {
            'package': package,
            'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
        })


class CreatePaymentIntentView(LoginRequiredMixin, View):
    """DEPRECATED: Create a Stripe PaymentIntent. Use Stripe Checkout Sessions instead."""

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

            log_event(
                user=request.user, school=None, category='billing',
                action='payment_intent_created',
                detail={'package_id': package.id, 'package_name': package.name, 'amount': amount},
                request=request,
            )

            return JsonResponse({'client_secret': intent.client_secret})

        except stripe.error.StripeError as e:
            return JsonResponse({'error': str(e)}, status=400)


class ConfirmPaymentView(LoginRequiredMixin, View):
    """DEPRECATED: Confirm a PaymentIntent. Use Stripe Checkout Sessions + webhooks instead."""

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

        log_event(
            user=request.user, school=None, category='billing',
            action='payment_confirmed',
            detail={'package_id': package.id, 'package_name': package.name, 'amount': str(package.price), 'stripe_payment_intent_id': payment_intent_id},
            request=request,
        )

        return JsonResponse({'success': True, 'redirect_url': '/billing/success/'})


class CheckoutSuccessView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'billing/success.html')


class CheckoutCancelView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect('select_classes')


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(View):
    """
    Handle Stripe webhook events for subscription lifecycle.
    Supports both legacy payment_intent events and new subscription events.
    """

    EVENT_HANDLERS = {
        'checkout.session.completed': 'billing.webhook_handlers.handle_checkout_completed',
        'customer.subscription.created': 'billing.webhook_handlers.handle_subscription_updated',
        'customer.subscription.updated': 'billing.webhook_handlers.handle_subscription_updated',
        'customer.subscription.deleted': 'billing.webhook_handlers.handle_subscription_deleted',
        'invoice.payment_succeeded': 'billing.webhook_handlers.handle_payment_succeeded',
        'invoice.payment_failed': 'billing.webhook_handlers.handle_payment_failed',
    }

    def post(self, request):
        import logging
        logger = logging.getLogger(__name__)

        # Rate limit webhook requests
        from billing.rate_limiting import check_rate_limit
        from audit.services import get_client_ip
        ip = get_client_ip(request) or 'unknown'
        if not check_rate_limit(f'webhook:{ip}', max_attempts=100, window_seconds=60):
            return HttpResponse(status=429)

        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            return HttpResponse(status=400)

        event_id = event.get('id', '')
        event_type = event.get('type', '')

        # Idempotency check
        from billing.models import StripeEvent
        if StripeEvent.objects.filter(event_id=event_id).exists():
            return HttpResponse(status=200)

        # Legacy: handle payment_intent.succeeded for backward compatibility
        if event_type == 'payment_intent.succeeded':
            self._handle_legacy_payment_intent(event)

        # New: dispatch to dedicated handlers
        handler_path = self.EVENT_HANDLERS.get(event_type)
        handler_succeeded = True
        if handler_path:
            try:
                module_path, func_name = handler_path.rsplit('.', 1)
                import importlib
                module = importlib.import_module(module_path)
                handler = getattr(module, func_name)
                handler(event['data'])
            except Exception:
                logger.exception('Error handling webhook event %s', event_type)
                handler_succeeded = False

        # Only record event if handler succeeded — allows retry on failure
        if handler_succeeded:
            StripeEvent.objects.create(
                event_id=event_id,
                event_type=event_type,
                payload=event.get('data', {}),
            )
            log_event(
                user=None, school=None, category='billing',
                action='stripe_webhook_processed',
                detail={'event_id': event_id, 'event_type': event_type},
                request=request,
            )
        else:
            # Return 500 so Stripe retries the event
            return HttpResponse(status=500)

        return HttpResponse(status=200)

    @staticmethod
    def _handle_legacy_payment_intent(event):
        """Backward-compatible handler for payment_intent.succeeded events."""
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


# ---------------------------------------------------------------------------
# Institute Plan Views
# ---------------------------------------------------------------------------

class InstitutePlanSelectView(LoginRequiredMixin, View):
    """Show available institute plans for comparison and selection."""

    def get(self, request):
        school = get_school_for_user(request.user)
        if not school:
            messages.error(request, 'No school found for your account.')
            return redirect('subjects_hub')

        plans = InstitutePlan.objects.filter(is_active=True)
        sub = get_school_subscription(school)

        # Get current usage for comparison
        from classroom.models import ClassRoom, SchoolStudent
        current_classes = ClassRoom.objects.filter(school=school, is_active=True).count()
        current_students = SchoolStudent.objects.filter(school=school, is_active=True).count()

        return render(request, 'billing/institute_plans.html', {
            'plans': plans,
            'school': school,
            'subscription': sub,
            'current_plan': sub.plan if sub else None,
            'current_classes': current_classes,
            'current_students': current_students,
        })


class InstituteTrialExpiredView(LoginRequiredMixin, View):
    """Landing page when an institute's trial has expired."""

    def get(self, request):
        school = get_school_for_user(request.user)
        sub = get_school_subscription(school) if school else None
        plans = InstitutePlan.objects.filter(is_active=True)

        return render(request, 'billing/institute_trial_expired.html', {
            'school': school,
            'subscription': sub,
            'plans': plans,
        })


class InstitutePlanUpgradeView(LoginRequiredMixin, View):
    """Show upgrade options for institute plan and modules."""

    def get(self, request):
        school = get_school_for_user(request.user)
        if not school:
            messages.error(request, 'No school found for your account.')
            return redirect('subjects_hub')

        plans = InstitutePlan.objects.filter(is_active=True)
        sub = get_school_subscription(school)

        # Get current usage
        from classroom.models import ClassRoom, SchoolStudent
        current_classes = ClassRoom.objects.filter(school=school, is_active=True).count()
        current_students = SchoolStudent.objects.filter(school=school, is_active=True).count()

        # Get usage info
        _, invoices_used, invoice_limit, overage_rate = check_invoice_limit(school)

        return render(request, 'billing/institute_upgrade.html', {
            'plans': plans,
            'school': school,
            'subscription': sub,
            'current_plan': sub.plan if sub else None,
            'current_classes': current_classes,
            'current_students': current_students,
            'invoices_used': invoices_used,
            'invoice_limit': invoice_limit,
            'overage_rate': overage_rate,
        })


class InstituteSubscriptionDashboardView(LoginRequiredMixin, View):
    """Dashboard showing current subscription status, usage, and limits."""

    def get(self, request):
        school = get_school_for_user(request.user)
        if not school:
            messages.error(request, 'No school found for your account.')
            return redirect('subjects_hub')

        sub = get_school_subscription(school)
        if not sub:
            return redirect('institute_plan_select')

        from classroom.models import ClassRoom, SchoolStudent

        class_allowed, current_classes, class_limit = check_class_limit(school)
        student_allowed, current_students, student_limit = check_student_limit(school)
        _, invoices_used, invoice_limit, overage_rate = check_invoice_limit(school)

        # Module status
        from .models import ModuleSubscription
        active_modules = sub.modules.filter(is_active=True).values_list('module', flat=True)

        return render(request, 'billing/institute_dashboard.html', {
            'school': school,
            'subscription': sub,
            'plan': sub.plan,
            'current_classes': current_classes,
            'class_limit': class_limit,
            'current_students': current_students,
            'student_limit': student_limit,
            'invoices_used': invoices_used,
            'invoice_limit': invoice_limit,
            'overage_rate': overage_rate,
            'active_modules': list(active_modules),
            'all_modules': ModuleSubscription.MODULE_CHOICES,
        })


class ModuleRequiredView(LoginRequiredMixin, View):
    """Landing page shown when a user tries to access a gated module feature."""

    def get(self, request):
        module_slug = request.GET.get('module', '')
        module_name = dict(ModuleSubscription.MODULE_CHOICES).get(
            module_slug, module_slug.replace('_', ' ').title(),
        )
        return render(request, 'billing/module_required.html', {
            'module_slug': module_slug,
            'module_name': module_name,
        })


# ---------------------------------------------------------------------------
# Stripe Checkout & Subscription Management Views
# ---------------------------------------------------------------------------

class InstituteCheckoutView(LoginRequiredMixin, View):
    """Create a Stripe Checkout Session for institute plan subscription."""

    def post(self, request):
        plan_slug = request.POST.get('plan', '')
        plan = InstitutePlan.objects.filter(slug=plan_slug, is_active=True).first()
        if not plan:
            messages.error(request, 'Invalid plan selected.')
            return redirect('institute_plan_select')

        if not plan.stripe_price_id:
            messages.error(request, 'This plan is not yet available for online checkout.')
            return redirect('institute_plan_select')

        school = get_school_for_user(request.user)
        if not school:
            messages.error(request, 'No school found for your account.')
            return redirect('subjects_hub')

        try:
            from billing.stripe_service import create_institute_checkout_session
            sub = get_school_subscription(school)
            # Only offer trial if the school hasn't used one before
            trial_days = plan.trial_days if (not sub or not sub.has_used_trial) else None
            session = create_institute_checkout_session(
                school, plan, request, trial_period_days=trial_days,
            )
            log_event(
                user=request.user, school=school, category='billing',
                action='checkout_session_created',
                detail={'plan_id': plan.id, 'plan_name': plan.name, 'plan_slug': plan_slug, 'trial_days': trial_days},
                request=request,
            )
            return redirect(session.url)
        except stripe.error.StripeError as e:
            messages.error(request, f'Payment error: {e.user_message or str(e)}')
            return redirect('institute_plan_select')


class InstituteCheckoutSuccessView(LoginRequiredMixin, View):
    """Success page after Stripe Checkout for institute subscription."""

    def get(self, request):
        school = get_school_for_user(request.user)
        sub = get_school_subscription(school) if school else None
        return render(request, 'billing/institute_checkout_success.html', {
            'school': school,
            'subscription': sub,
        })


class InstituteChangePlanView(LoginRequiredMixin, View):
    """Change institute plan (upgrade/downgrade)."""

    def post(self, request):
        plan_slug = request.POST.get('plan', '')
        plan = InstitutePlan.objects.filter(slug=plan_slug, is_active=True).first()
        if not plan:
            messages.error(request, 'Invalid plan selected.')
            return redirect('institute_plan_select')

        school = get_school_for_user(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        sub = get_school_subscription(school)
        if not sub or not sub.stripe_subscription_id:
            messages.info(request, 'Please subscribe first.')
            return redirect('institute_plan_select')

        try:
            from billing.stripe_service import change_institute_plan
            change_institute_plan(sub, plan)
            log_event(
                user=request.user, school=school, category='billing',
                action='subscription_plan_changed',
                detail={'plan_id': plan.id, 'plan_name': plan.name, 'plan_slug': plan_slug, 'subscription_id': sub.id},
                request=request,
            )
            messages.success(request, f'Plan changed to {plan.name}.')
        except (stripe.error.StripeError, ValueError) as e:
            messages.error(request, f'Could not change plan: {e}')

        return redirect('institute_subscription_dashboard')


class InstituteCancelSubscriptionView(LoginRequiredMixin, View):
    """Cancel institute subscription at end of current period."""

    def post(self, request):
        school = get_school_for_user(request.user)
        if not school:
            return redirect('subjects_hub')

        sub = get_school_subscription(school)
        if not sub or not sub.stripe_subscription_id:
            messages.error(request, 'No active subscription to cancel.')
            return redirect('institute_subscription_dashboard')

        try:
            from billing.stripe_service import cancel_subscription
            cancel_subscription(sub.stripe_subscription_id, at_period_end=True)
            log_event(
                user=request.user, school=school, category='billing',
                action='subscription_cancelled',
                detail={'subscription_id': sub.id, 'stripe_subscription_id': sub.stripe_subscription_id},
                request=request,
            )
            messages.success(
                request,
                'Your subscription will be cancelled at the end of the current billing period.',
            )
        except stripe.error.StripeError as e:
            messages.error(request, f'Could not cancel: {e}')

        return redirect('institute_subscription_dashboard')


class StripeBillingPortalView(LoginRequiredMixin, View):
    """Redirect to Stripe Customer Portal for payment method management."""

    def get(self, request):
        school = get_school_for_user(request.user)
        customer_id = None

        if school:
            sub = get_school_subscription(school)
            if sub:
                customer_id = sub.stripe_customer_id

        if not customer_id and hasattr(request.user, 'subscription'):
            try:
                customer_id = request.user.subscription.stripe_customer_id
            except Exception:
                pass

        if not customer_id:
            messages.error(request, 'No billing account found.')
            return redirect('subjects_hub')

        try:
            from billing.stripe_service import create_billing_portal_session
            return_url = request.build_absolute_uri(
                request.META.get('HTTP_REFERER', '/billing/institute/dashboard/')
            )
            session = create_billing_portal_session(customer_id, return_url)
            return redirect(session.url)
        except stripe.error.StripeError as e:
            messages.error(request, f'Could not open billing portal: {e}')
            return redirect('institute_subscription_dashboard')


class ModuleToggleView(LoginRequiredMixin, View):
    """Toggle a module add-on for an institute subscription."""

    def post(self, request):
        module_slug = request.POST.get('module_slug', '') or request.POST.get('module', '')
        action = request.POST.get('action', '')  # 'add' or 'remove'

        if module_slug not in dict(ModuleSubscription.MODULE_CHOICES):
            messages.error(request, 'Invalid module.')
            return redirect('institute_subscription_dashboard')

        school = get_school_for_user(request.user)
        if not school:
            messages.error(request, 'No school found for your account.')
            return redirect('subjects_hub')

        sub = get_school_subscription(school)
        if not sub:
            messages.error(request, 'Please subscribe to a plan first.')
            return redirect('institute_plan_select')

        from billing.models import ModuleProduct
        module_product = ModuleProduct.objects.filter(module=module_slug, is_active=True).first()
        stripe_price_id = module_product.stripe_price_id if module_product else ''
        module_name = dict(ModuleSubscription.MODULE_CHOICES).get(module_slug, module_slug)

        try:
            if action == 'add':
                if sub.stripe_subscription_id and stripe_price_id:
                    # Production: add via Stripe
                    from billing.stripe_service import add_module_to_subscription
                    add_module_to_subscription(sub, module_slug, stripe_price_id)
                else:
                    # No Stripe subscription — activate locally (trial/test)
                    ModuleSubscription.objects.update_or_create(
                        school_subscription=sub,
                        module=module_slug,
                        defaults={'is_active': True, 'deactivated_at': None},
                    )
                log_event(
                    user=request.user, school=school, category='billing',
                    action='module_activated',
                    detail={'module_slug': module_slug, 'module_name': module_name, 'subscription_id': sub.id},
                    request=request,
                )
                messages.success(request, f'{module_name} module activated.')
            elif action == 'remove':
                if sub.stripe_subscription_id:
                    from billing.stripe_service import remove_module_from_subscription
                    removed = remove_module_from_subscription(sub, module_slug)
                else:
                    # Local deactivation
                    from django.utils import timezone as tz
                    updated = ModuleSubscription.objects.filter(
                        school_subscription=sub, module=module_slug, is_active=True,
                    ).update(is_active=False, deactivated_at=tz.now())
                    removed = updated > 0
                if removed:
                    log_event(
                        user=request.user, school=school, category='billing',
                        action='module_deactivated',
                        detail={'module_slug': module_slug, 'module_name': module_name, 'subscription_id': sub.id},
                        request=request,
                    )
                    messages.success(request, f'{module_name} module deactivated.')
                else:
                    messages.info(request, 'Module was not active.')
            else:
                messages.error(request, 'Invalid action.')
        except (stripe.error.StripeError, ValueError) as e:
            messages.error(request, f'Could not update module: {e}')

        return redirect('institute_subscription_dashboard')


class BillingHistoryView(LoginRequiredMixin, View):
    """Show billing history — links to Stripe Billing Portal for full invoice details."""

    def get(self, request):
        school = get_school_for_user(request.user)
        sub = get_school_subscription(school) if school else None

        # Also check individual subscription
        individual_sub = None
        if not sub and hasattr(request.user, 'subscription'):
            try:
                individual_sub = request.user.subscription
            except Exception:
                pass

        return render(request, 'billing/billing_history.html', {
            'school': school,
            'subscription': sub,
            'individual_sub': individual_sub,
        })
