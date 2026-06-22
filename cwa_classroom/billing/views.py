import json
import logging
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

from datetime import timedelta
from .models import Package, Subscription, Payment, DiscountCode, PromoCode, InstitutePlan, SchoolSubscription, ModuleSubscription
from .entitlements import get_school_for_user, get_school_subscription, check_class_limit, check_student_limit, check_invoice_limit
from audit.services import log_event

stripe.api_key = settings.STRIPE_SECRET_KEY

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_account_from_pending(pending, stripe_subscription_id=''):
    """
    Atomically convert a PendingRegistration into a real CustomUser + Subscription.
    Returns the new user, or None if already completed or package missing.
    Idempotent: re-entrant calls (webhook + browser) are both safe.
    """
    from django.db import transaction
    from accounts.models import CustomUser, Role, UserRole, PendingRegistration
    from audit.services import log_event

    with transaction.atomic():
        try:
            pending = PendingRegistration.objects.select_for_update().get(
                id=pending.id, completed=False
            )
        except PendingRegistration.DoesNotExist:
            # Already completed by another process (webhook vs. browser race)
            return CustomUser.objects.filter(email=pending.email).first()

        package = Package.objects.filter(id=pending.package_id, is_active=True).first()
        if not package:
            return None

        data = pending.data
        user = CustomUser(
            username=pending.username,
            email=pending.email,
            password=pending.password_hash,  # already hashed by make_password()
            package=package,
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            phone=data.get('phone', ''),
            street_address=data.get('street_address', ''),
            city=data.get('city', ''),
            postal_code=data.get('postal_code', ''),
            country=data.get('country', ''),
            terms_accepted_at=timezone.now(),
        )
        if data.get('date_of_birth'):
            user.date_of_birth = data['date_of_birth']
        user.save()

        role, _ = Role.objects.get_or_create(
            name=Role.INDIVIDUAL_STUDENT,
            defaults={'display_name': 'Individual Student'},
        )
        UserRole.objects.create(user=user, role=role)

        Subscription.objects.create(
            user=user,
            package=package,
            status=Subscription.STATUS_ACTIVE,
            stripe_subscription_id=stripe_subscription_id or '',
        )

        pending.completed = True
        pending.save(update_fields=['completed'])

    log_event(
        user=user, school=None, category='auth',
        action='individual_student_registered',
        detail={
            'username': user.username, 'email': user.email,
            'package': package.name,
            'via': 'stripe_payment',
            'discount_code': data.get('discount_code'),
        },
    )
    return user


class CheckoutView(LoginRequiredMixin, View):
    """Start a Stripe Checkout (subscription mode) for a package.

    This used to render a legacy one-time PaymentIntent page that charged the
    card WITHOUT creating a recurring subscription and without saving a card —
    leaving the customer paid-but-unsubscribed (active ``Subscription`` with an
    empty ``stripe_subscription_id``, a Stripe customer with a charge but no
    subscription). It now always routes through Stripe Checkout in subscription
    mode, so any successful payment creates a real subscription that the webhook
    links back to the user. School students use the school-student checkout;
    everyone else the individual checkout.
    """

    def get(self, request, package_id):
        package = get_object_or_404(Package, id=package_id, is_active=True)
        if package.is_free:
            messages.info(request, 'This package is free — no payment is required.')
            return redirect('subjects_hub')

        from .stripe_service import (
            create_individual_checkout_session,
            create_student_checkout_session,
        )
        try:
            if request.user.is_student:
                session = create_student_checkout_session(request.user, package, request)
            else:
                session = create_individual_checkout_session(request.user, package, request)
        except Exception as e:  # noqa: BLE001 — surface any Stripe/config error to the user
            logger.error(
                'Checkout session creation failed for user %s, package %s: %s',
                request.user.id, package.id, e,
            )
            messages.error(
                request,
                'Could not start checkout. Please try again, or contact support if it persists.',
            )
            return redirect('trial_expired')
        return redirect(session.url)


class CreatePaymentIntentView(LoginRequiredMixin, View):
    """REMOVED: legacy one-time PaymentIntent checkout.

    Kept as a hard-disabled stub so any stale client/bookmark can never create a
    one-off charge that doesn't set up a subscription. All payments now go
    through Stripe Checkout (subscription mode) via :class:`CheckoutView`.
    """

    def post(self, request, package_id):
        return JsonResponse(
            {'error': 'This checkout method is no longer available. Please reload the page and try again.'},
            status=410,
        )


class ConfirmPaymentView(LoginRequiredMixin, View):
    """REMOVED: legacy PaymentIntent confirmation.

    Subscriptions are now created and activated by Stripe Checkout + the
    webhook handler, never by a one-off confirm call. Hard-disabled so it can no
    longer create a ``Payment`` + ``active`` subscription with no
    ``stripe_subscription_id``.
    """

    def post(self, request):
        return JsonResponse(
            {'error': 'This checkout method is no longer available. Please reload the page and try again.'},
            status=410,
        )


class ApplyPromoCodeView(LoginRequiredMixin, View):
    """Validate and apply a promotion code at checkout."""

    def post(self, request, package_id):
        package = get_object_or_404(Package, id=package_id, is_active=True)
        data = json.loads(request.body)
        code_str = (data.get('code') or '').strip().upper()

        if not code_str:
            return JsonResponse({'error': 'Please enter a promotion code.'}, status=400)

        # Check DiscountCode first (billing discounts), then PromoCode (class access)
        discount = None
        promo = None
        try:
            discount = DiscountCode.objects.get(code=code_str)
        except DiscountCode.DoesNotExist:
            try:
                promo = PromoCode.objects.get(code=code_str)
            except PromoCode.DoesNotExist:
                return JsonResponse({'error': 'Invalid promotion code.'}, status=400)

        # Handle PromoCode
        if promo:
            if not promo.is_valid():
                return JsonResponse({'error': 'This promotion code has expired or reached its usage limit.'}, status=400)

            if promo.redeemed_by.filter(id=request.user.id).exists():
                return JsonResponse({'error': 'You have already used this promotion code.'}, status=400)

            if promo.is_fully_free:
                # 100% off — activate subscription immediately
                grant_days = promo.grant_days or package.trial_days or 30

                promo.uses += 1
                promo.save(update_fields=['uses'])
                promo.redeemed_by.add(request.user)

                sub, _ = Subscription.objects.get_or_create(
                    user=request.user,
                    defaults={'package': package},
                )
                sub.package = package
                sub.status = Subscription.STATUS_ACTIVE
                sub.trial_end = timezone.now() + timedelta(days=grant_days)
                sub.promo_code_used = promo.code
                sub.save(update_fields=['package', 'status', 'trial_end', 'promo_code_used', 'updated_at'])

                request.user.package = package
                request.user.save(update_fields=['package'])

                log_event(
                    user=request.user, school=None, category='billing',
                    action='promo_code_redeemed',
                    detail={
                        'code': promo.code, 'type': 'promo', 'discount_percent': 100,
                        'grant_days': grant_days, 'package': package.name,
                    },
                    request=request,
                )

                return JsonResponse({
                    'fully_free': True,
                    'redirect_url': '/hub/',
                    'grant_days': grant_days,
                })

            # Partial discount from PromoCode
            promo.uses += 1
            promo.save(update_fields=['uses'])
            promo.redeemed_by.add(request.user)

            discounted_price = round(float(package.price) * (1 - promo.discount_percent / 100), 2)

            log_event(
                user=request.user, school=None, category='billing',
                action='promo_code_applied',
                detail={
                    'code': promo.code, 'type': 'promo',
                    'discount_percent': promo.discount_percent,
                    'original_price': str(package.price), 'discounted_price': str(discounted_price),
                },
                request=request,
            )

            return JsonResponse({
                'fully_free': False,
                'discount_percent': promo.discount_percent,
                'discounted_price': discounted_price,
                'stripe_coupon_id': '',
            })

        # Handle DiscountCode
        if not discount.is_valid():
            return JsonResponse({'error': 'This promotion code has expired or reached its usage limit.'}, status=400)

        if discount.is_fully_free:
            # 100% off — activate subscription immediately, no Stripe needed
            grant_days = discount.grant_days or package.trial_days or 30

            discount.uses += 1
            discount.save(update_fields=['uses'])

            sub, _ = Subscription.objects.get_or_create(
                user=request.user,
                defaults={'package': package},
            )
            sub.package = package
            sub.status = Subscription.STATUS_TRIALING
            sub.trial_end = timezone.now() + timedelta(days=grant_days)
            sub.save(update_fields=['package', 'status', 'trial_end', 'updated_at'])

            request.user.package = package
            request.user.save(update_fields=['package'])

            log_event(
                user=request.user, school=None, category='billing',
                action='promo_code_redeemed',
                detail={
                    'code': discount.code, 'type': 'discount', 'discount_percent': 100,
                    'grant_days': grant_days, 'package': package.name,
                },
                request=request,
            )

            return JsonResponse({
                'fully_free': True,
                'redirect_url': '/hub/',
                'grant_days': grant_days,
            })

        # Partial discount — return info for Stripe checkout
        discount.uses += 1
        discount.save(update_fields=['uses'])

        discounted_price = round(float(package.price) * (1 - discount.discount_percent / 100), 2)

        log_event(
            user=request.user, school=None, category='billing',
            action='promo_code_applied',
            detail={
                'code': discount.code, 'discount_percent': discount.discount_percent,
                'original_price': str(package.price), 'discounted_price': str(discounted_price),
            },
            request=request,
        )

        return JsonResponse({
            'fully_free': False,
            'discount_percent': discount.discount_percent,
            'discounted_price': discounted_price,
            'stripe_coupon_id': discount.stripe_coupon_id,
        })


class CheckoutSuccessView(View):
    """
    Handles Stripe's redirect after a successful checkout session.
    For pending registrations (no account yet), creates the account here.
    For existing users, verifies the session with Stripe and activates
    the subscription immediately (safety net if webhook is delayed).
    """
    def get(self, request):
        session_id = request.GET.get('session_id', '')
        if session_id and not request.user.is_authenticated:
            self._complete_pending_registration(request, session_id)
        elif session_id and request.user.is_authenticated:
            self._activate_from_session(request.user, session_id)
        return render(request, 'billing/success.html')

    @staticmethod
    def _activate_from_session(user, session_id):
        """Verify checkout session with Stripe and activate if paid."""
        try:
            sub = user.subscription
        except Subscription.DoesNotExist:
            return
        if sub.status == Subscription.STATUS_ACTIVE:
            return
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status in ('paid', 'no_payment_required'):
                sub.status = Subscription.STATUS_ACTIVE
                sub.stripe_subscription_id = session.subscription or sub.stripe_subscription_id
                sub.trial_end = None
                sub.current_period_start = timezone.now()
                if session.metadata.get('package_id'):
                    pkg = Package.objects.filter(id=session.metadata['package_id']).first()
                    if pkg:
                        sub.package = pkg
                        user.package = pkg
                        user.save(update_fields=['package'])
                sub.save()
                log_event(
                    user=user, category='billing',
                    action='subscription_activated_from_success_page',
                    detail={'session_id': session_id},
                )
        except stripe.error.StripeError:
            pass

    @staticmethod
    def _complete_pending_registration(request, stripe_session_id):
        from accounts.models import PendingRegistration
        from django.contrib.auth import login as auth_login
        try:
            pending = PendingRegistration.objects.get(
                stripe_session_id=stripe_session_id, completed=False
            )
        except PendingRegistration.DoesNotExist:
            return

        user = _create_account_from_pending(pending, stripe_subscription_id='')
        if user:
            auth_login(request, user, backend='accounts.backends.EmailOrUsernameBackend')


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

        active_sub = sub if sub and sub.is_active_or_trialing else None
        return render(request, 'billing/institute_plans.html', {
            'plans': plans,
            'school': school,
            'subscription': active_sub,
            'current_plan': active_sub.plan if active_sub else None,
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
        active_modules = list(sub.modules.filter(is_active=True).values_list('module', flat=True))

        # Split standard modules from AI import tiers
        AI_IMPORT_SLUGS = {'ai_import_starter', 'ai_import_professional', 'ai_import_enterprise'}
        standard_modules = [
            (k, v) for k, v in ModuleSubscription.MODULE_CHOICES
            if k not in AI_IMPORT_SLUGS
        ]
        ai_import_tiers = [
            {'slug': 'ai_import_starter', 'name': 'Starter', 'pages': 300, 'price': 15, 'full_price': 30, 'discount_months': 6},
            {'slug': 'ai_import_professional', 'name': 'Professional', 'pages': 600, 'price': 30, 'full_price': 60, 'discount_months': 6},
            {'slug': 'ai_import_enterprise', 'name': 'Enterprise', 'pages': 1000, 'price': 50, 'full_price': 99, 'discount_months': 6},
        ]
        active_ai_import_tier = next(
            (s for s in AI_IMPORT_SLUGS if s in active_modules), None
        )

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
            'active_modules': active_modules,
            'standard_modules': standard_modules,
            'ai_import_tiers': ai_import_tiers,
            'active_ai_import_tier': active_ai_import_tier,
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
            # Update plan on existing subscription so we don't create duplicates
            if sub and sub.plan_id != plan.id:
                sub.plan = plan
                sub.save(update_fields=['plan'])
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
    """Success page after Stripe Checkout for institute subscription.

    Stripe redirects here with ?session_id=... after payment. We verify
    the session with Stripe and activate the subscription immediately,
    so the user doesn't depend on the webhook arriving first.
    """

    def get(self, request):
        school = get_school_for_user(request.user)
        sub = get_school_subscription(school) if school else None

        session_id = request.GET.get('session_id', '')
        if session_id and sub and sub.status != SchoolSubscription.STATUS_ACTIVE:
            self._activate_from_session(session_id, sub)
            sub.refresh_from_db()

        return render(request, 'billing/institute_checkout_success.html', {
            'school': school,
            'subscription': sub,
        })

    @staticmethod
    def _activate_from_session(session_id, sub):
        """Verify checkout session with Stripe and activate if paid."""
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status in ('paid', 'no_payment_required'):
                sub.status = SchoolSubscription.STATUS_ACTIVE
                sub.stripe_subscription_id = session.subscription or sub.stripe_subscription_id
                sub.trial_end = None
                sub.current_period_start = timezone.now()
                if session.metadata.get('plan_id'):
                    from billing.models import InstitutePlan
                    plan = InstitutePlan.objects.filter(
                        id=session.metadata['plan_id'],
                    ).first()
                    if plan:
                        sub.plan = plan
                sub.save()
                log_event(
                    user=None, school=sub.school, category='billing',
                    action='subscription_activated_from_success_page',
                    detail={'session_id': session_id, 'plan_id': sub.plan_id},
                )
        except stripe.error.StripeError:
            pass


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


class IndividualCancelSubscriptionView(LoginRequiredMixin, View):
    """Cancel an individual/student subscription at end of current period.

    Mirrors InstituteCancelSubscriptionView but operates on the requesting
    user's own one-to-one Subscription, so there is no cross-account vector.
    Used from the individual student billing page (billing_history) and the
    parent billing page.
    """

    def _billing_page(self, request):
        from accounts.models import Role
        if request.user.has_role(Role.PARENT):
            return 'parent_billing'
        return 'billing_history'

    def post(self, request):
        try:
            sub = request.user.subscription
        except Subscription.DoesNotExist:
            sub = None

        if not sub or not sub.stripe_subscription_id:
            messages.error(request, 'No active subscription to cancel.')
            return redirect(self._billing_page(request))

        if sub.cancel_at_period_end:
            messages.info(
                request,
                'Your subscription is already set to cancel at the end of the billing period.',
            )
            return redirect(self._billing_page(request))

        try:
            from billing.stripe_service import cancel_subscription
            cancel_subscription(sub.stripe_subscription_id, at_period_end=True)
            # Safety net: reflect the change locally in case the
            # customer.subscription.updated webhook is delayed.
            sub.cancel_at_period_end = True
            sub.cancelled_at = timezone.now()
            sub.save(update_fields=['cancel_at_period_end', 'cancelled_at', 'updated_at'])
            log_event(
                user=request.user, school=None, category='billing',
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

        return redirect(self._billing_page(request))


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

        # AI import tiers are mutually exclusive — deactivate others when adding one
        AI_IMPORT_SLUGS = {'ai_import_starter', 'ai_import_professional', 'ai_import_enterprise'}
        is_ai_import = module_slug in AI_IMPORT_SLUGS

        try:
            if action == 'add':
                # Deactivate other AI tiers first (mutual exclusivity)
                if is_ai_import:
                    other_ai_slugs = AI_IMPORT_SLUGS - {module_slug}
                    for other_slug in other_ai_slugs:
                        existing = ModuleSubscription.objects.filter(
                            school_subscription=sub, module=other_slug, is_active=True,
                        ).first()
                        if existing:
                            if sub.stripe_subscription_id:
                                from billing.stripe_service import remove_module_from_subscription
                                remove_module_from_subscription(sub, other_slug)
                            else:
                                from django.utils import timezone as tz
                                ModuleSubscription.objects.filter(
                                    school_subscription=sub, module=other_slug, is_active=True,
                                ).update(is_active=False, deactivated_at=tz.now())

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
