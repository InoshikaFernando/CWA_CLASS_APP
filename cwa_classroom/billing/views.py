import json
import logging
import stripe

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from datetime import timedelta
from .models import (
    Package, Subscription, Payment, DiscountCode, PromoCode, InstitutePlan,
    SchoolSubscription, ModuleSubscription, StudentModule,
)
from .entitlements import (
    get_school_for_user, get_school_subscription,
    check_class_limit, check_student_limit, check_invoice_limit,
    student_has_module, sync_student_modules,
)
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

        # The discount code the student typed at sign-up rode along in the
        # pending row (they had no account to record it against yet). Record it
        # on the subscription now: it is what the tier is read from, here and at
        # every later activation.
        code = None
        if data.get('discount_code'):
            code = DiscountCode.objects.filter(
                code__iexact=data['discount_code']).first()
        sub = Subscription.objects.create(
            user=user,
            package=package,
            status=Subscription.STATUS_ACTIVE,
            stripe_subscription_id=stripe_subscription_id or '',
            discount_code=code,
        )
        sync_student_modules(sub)

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
            from .stripe_health import record_checkout_failure
            record_checkout_failure(
                e, user=request.user, package=package, request=request,
                flow='checkout_view',
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
            discount = DiscountCode.objects.get(code__iexact=code_str)
        except DiscountCode.DoesNotExist:
            try:
                promo = PromoCode.objects.get(code__iexact=code_str)
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

                # Attach whatever tier the OWNER flagged on this code, read
                # off the subscription rather than the form. Nothing here is
                # student-chosen: a code with no flag (every code that exists
                # today) leaves the student on the app in full.
                sync_student_modules(sub)

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

            # Partial discount from PromoCode — the student pays the rest by
            # card. Same reasoning as the DiscountCode branch below: record the
            # code before they leave for Stripe, because the tier is read back
            # off the subscription when the webhook activates them.
            promo.uses += 1
            promo.save(update_fields=['uses'])
            promo.redeemed_by.add(request.user)

            sub, _ = Subscription.objects.get_or_create(
                user=request.user, defaults={'package': package},
            )
            sub.package = package
            sub.promo_code_used = promo.code
            sub.save(update_fields=['package', 'promo_code_used', 'updated_at'])

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
            # Record WHICH code activated this subscription. It was not stored
            # anywhere before, so there was nothing to read afterwards — not for
            # the tier below, and not for anyone asking later why this student
            # pays nothing.
            sub.discount_code = discount
            sub.save(update_fields=['package', 'status', 'trial_end',
                                    'discount_code', 'updated_at'])

            sync_student_modules(sub)

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

        # Partial discount — the student pays the remainder by card, so they
        # leave for Stripe here and come back activated by the webhook. Record
        # the code on their subscription BEFORE they go: it is the only thing
        # that survives the round trip, and the tier is read off it on the way
        # back in (``sync_student_modules``). Without this a half-price
        # promotion would grant the app in full while a free one did not.
        discount.uses += 1
        discount.save(update_fields=['uses'])

        sub, _ = Subscription.objects.get_or_create(
            user=request.user, defaults={'package': package},
        )
        sub.package = package
        sub.discount_code = discount
        sub.save(update_fields=['package', 'discount_code', 'updated_at'])

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
        """Verify checkout session with Stripe and activate if paid.

        Safety net for a delayed/lost webhook. Handles users who have no
        pre-created ``Subscription`` row yet (e.g. school students, whose sub is
        created on activation) by creating one from the session metadata —
        rather than silently doing nothing.
        """
        try:
            sub = user.subscription
        except Subscription.DoesNotExist:
            sub = None
        if sub and sub.status == Subscription.STATUS_ACTIVE:
            return
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status in ('paid', 'no_payment_required'):
                pkg = None
                if session.metadata.get('package_id'):
                    pkg = Package.objects.filter(id=session.metadata['package_id']).first()
                if sub is None:
                    # No local row yet — create it so the payment isn't lost.
                    if not pkg:
                        logger.warning(
                            'Success-page activation for user %s has no local sub '
                            'and no package in session %s; cannot create.',
                            user.id, session_id,
                        )
                        return
                    sub = Subscription(user=user, package=pkg)
                sub.status = Subscription.STATUS_ACTIVE
                sub.stripe_subscription_id = session.subscription or sub.stripe_subscription_id
                if getattr(session, 'customer', None):
                    sub.stripe_customer_id = session.customer
                sub.trial_end = None
                sub.current_period_start = timezone.now()
                if pkg:
                    sub.package = pkg
                    user.package = pkg
                    user.save(update_fields=['package'])
                sub.save()
                # The webhook normally does this; it is repeated here for the
                # same reason the activation is — a lost or late webhook must
                # not leave the student on a different tier from the one their
                # promotion code bought. Idempotent, so doing both is free.
                sync_student_modules(sub)
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

        # The add-on list on this page was three module names typed by hand
        # under a heading that read "($10/mo each)". Both had gone stale: there
        # are twelve sellable modules now, they range from $10 to $149, and the
        # three that were listed are billed at $9 in Stripe. A hand-kept list
        # on the page a prospect reads before paying is the last place to let
        # drift happen, so it comes from the catalogue.
        #
        # One row per tier family rather than three, since a family is a
        # pick-one ladder and listing every rung reads as nine products.
        from billing import registry
        from billing.models import ModuleProduct as _MP

        addons, seen_families = [], set()
        for product in _MP.objects.filter(is_active=True).order_by('price'):
            module = registry.REGISTRY.get(product.module)
            if module is None:
                continue
            if module.family:
                if module.family in seen_families:
                    continue
                seen_families.add(module.family)
                cheapest = registry.ordered_members_of(module.family)[0]
                addons.append({
                    'name': module.name.split('—')[0].strip(),
                    'price': _MP.objects.filter(module=cheapest.slug).values_list(
                        'price', flat=True).first(),
                    'from': True,
                })
            else:
                addons.append({'name': module.name, 'price': product.price,
                               'from': False})

        active_sub = sub if sub and sub.is_active_or_trialing else None
        return render(request, 'billing/institute_plans.html', {
            'plans': plans,
            'school': school,
            'subscription': active_sub,
            'current_plan': active_sub.plan if active_sub else None,
            'current_classes': current_classes,
            'current_students': current_students,
            'addons': addons,
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


#: Families with a hand-written section on the institute dashboard, because
#: each has copy the generic renderer has no business knowing about: the AI
#: import introductory discount, and the AI grading answers-used meter.
#:
#: Everything NOT listed here is rendered generically. Adding a family to this
#: set without also adding its template block would make it invisible — which
#: is the exact failure question_automation hit — so tests_tier_ui.py checks
#: that every name here really does have a block.
BESPOKE_TIER_FAMILIES = frozenset({'ai_import', 'ai_grading'})


def _allowance_label(product):
    """What one tier of a ladder includes, in words, or '' if it is not metered.

    Reads whichever allowance column the family actually uses. A tier whose
    column is NULL is the unlimited top of its ladder — said explicitly,
    because a blank there reads as "unknown" rather than "no limit".
    """
    if product.schedules_limit is not None:
        return f'{product.schedules_limit} schedules at once'
    if product.pages_per_month:
        return f'{product.pages_per_month} pages/mo'
    if product.questions_per_month:
        return f'{product.questions_per_month} answers/mo'
    return 'unlimited'


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

        # Split standard modules from the two tiered add-ons. Both AI families
        # are pick-one ladders, not independent $10 switches — listing them in
        # the flat module list let a school "Add" Starter and Professional at
        # once and be billed for both while only one took effect.
        from billing.page_quota import AI_IMPORT_MODULE_PREFIX
        from billing.quota_alerts import GRADING_TIER_ORDER
        from billing import registry
        AI_IMPORT_SLUGS = registry.members_of('ai_import')
        # Any module in a family is a ladder, so ask the registry instead of
        # naming the two we happened to know about. question_automation became
        # a third ladder, and a hard-coded list would have shown its tiers here
        # as three independent switches — precisely the bug above.
        #
        # GRADING_TIER_ORDER stays for the tier CARDS further down: those need
        # the ladder in weakest-to-strongest order, and a family is a set.
        # Price comes from the product row, never a literal. The heading here
        # read "Modules ($10/mo each)" and both confirm dialogs said "$10/mo",
        # which was true only while every standalone module happened to cost
        # the same — a claim that silently becomes a lie the first time one is
        # repriced, on the screen where somebody agrees to pay it.
        from billing.models import ModuleProduct as _MP
        _products = {p.module: p for p in _MP.objects.filter(is_active=True)}
        standard_modules = [
            {
                'key': k,
                'name': v,
                'price': _products[k].price if k in _products else None,
            }
            for k, v in ModuleSubscription.MODULE_CHOICES
            if not registry.siblings_of(k)
        ]
        # Shared with the public plans page — see billing/ai_tiers.py. This
        # list used to be a second copy whose 'price' key meant the discounted
        # price while the plans page's meant the full one.
        from billing.ai_tiers import (
            ai_import_tiers as _ai_import_tiers, discount_context,
        )
        ai_import_tiers = _ai_import_tiers()
        active_ai_import_tier = next(
            (s for s in AI_IMPORT_SLUGS if s in active_modules), None
        )

        # Grading tiers come from the catalogue rather than a literal list, so
        # a price or allowance change in ModuleProduct shows here without a
        # code edit. Order is the ladder in GRADING_TIER_ORDER, not the DB's.
        from billing.models import ModuleProduct
        products = {
            p.module: p for p in ModuleProduct.objects.filter(
                module__in=GRADING_TIER_ORDER, is_active=True,
            )
        }
        ai_grading_tiers = []
        for slug in GRADING_TIER_ORDER:
            product = products.get(slug)
            if not product:
                continue
            ai_grading_tiers.append({
                'slug': slug,
                # 'AI Grading - Professional' → 'Professional'
                'name': product.name.split('-')[-1].strip(),
                'answers': product.questions_per_month,
                'price': product.price,
            })
        active_ai_grading_tier = next(
            (s for s in GRADING_TIER_ORDER if s in active_modules), None
        )

        # Every OTHER ladder, rendered generically.
        #
        # ai_import and ai_grading have hand-written blocks above because each
        # carries family-specific copy — the introductory discount, and the
        # answers-used meter. Nothing else does, and question_automation proved
        # what happens when a new family has neither a block of its own nor a
        # generic path: `standard_modules` drops it for having siblings, the two
        # hand-written sections do not know about it, and the module becomes
        # gated and unbuyable. A school hit the schedule pages, got the upsell
        # page, and found nothing on it to buy.
        #
        # tests_tier_ui.py fails the build if a family reaches neither path, so
        # a fourth ladder cannot go missing the same way.
        tier_families = []
        for family, modules in registry.families():
            if family in BESPOKE_TIER_FAMILIES:
                continue
            tiers = []
            for module in modules:
                product = _products.get(module.slug)
                if not product:
                    # No product row means no price and no Stripe id — showing
                    # it would offer something checkout cannot complete.
                    continue
                tiers.append({
                    'slug': module.slug,
                    # 'Question Automation — Starter' → 'Starter'
                    'name': module.name.split('—')[-1].strip(),
                    'price': product.price,
                    'allowance': _allowance_label(product),
                })
            if not tiers:
                continue
            tier_families.append({
                'family': family,
                'label': modules[0].name.split('—')[0].strip(),
                'tiers': tiers,
                'active_slug': next(
                    (m.slug for m in modules if m.slug in active_modules), None
                ),
            })

        # Live meters so the institute sees what it is actually consuming next
        # to the plan it is choosing between.
        from billing.page_quota import quota_status
        from worksheets.grading_service import check_ai_grading_quota
        _grading_allowed, grading_used, grading_limit = check_ai_grading_quota(school)

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
            'ai_grading_tiers': ai_grading_tiers,
            'active_ai_grading_tier': active_ai_grading_tier,
            'tier_families': tier_families,
            'grading_used': grading_used,
            'grading_limit': grading_limit,
            'grading_percent': (
                min(100, round(grading_used / grading_limit * 100))
                if grading_limit else 0
            ),
            'page_quota': quota_status(school),
            # The introductory offer's wording, from the same place the plans
            # page takes it.
            **discount_context(),
        })


class AIPagesRequiredView(LoginRequiredMixin, View):
    """"Reading a PDF with AI needs an AI module" — what happened, and what next.

    The PDF control on all three upload screens points here when the school has
    no AI page allowance, as does the link in the refusal message when an upload
    is turned away.

    It exists because the pricing page is the wrong destination on its own.
    Sending a teacher straight there answered "how do I buy one?" without ever
    answering "what just happened?" — the explanation lived on the screen they
    had just left, and arriving at a price list with no context is exactly the
    confusion this page removes.

    Not ModuleRequiredView either: that one is generic, names one module's price
    with no allowance to go with it, and says nothing about what still works.

    ``from`` is a label for the screen they came from, not a URL. It is echoed
    into the page, so it is looked up in a known map rather than trusted.
    """

    SCREEN_LABELS = {
        'homework': 'Upload PDF Homework',
        'worksheet': 'Upload Worksheet',
        'ai_import': 'AI Question Import',
    }
    BACK_URLS = {
        'homework': '/homework/pdf/upload/',
        'worksheet': '/worksheets/upload/',
        'ai_import': '/ai-import/upload/',
    }

    def get(self, request):
        from billing.entitlements import get_school_for_user
        from billing.page_quota import quota_status

        school = get_school_for_user(request.user)
        status = quota_status(school)
        screen = request.GET.get('from', '')

        return render(request, 'billing/ai_pages_required.html', {
            # A school that CAN spend pages should never be told it cannot, so
            # the page reads its own answer from quota_status rather than
            # assuming the link that brought it here was still true.
            'has_allowance': not status.get('no_allowance'),
            'no_school': status.get('reason') == 'no_school',
            'school_name': getattr(school, 'name', ''),
            'from_label': self.SCREEN_LABELS.get(screen, ''),
            'back_url': self.BACK_URLS.get(screen, ''),
        })


class ModuleRequiredView(LoginRequiredMixin, View):
    """Landing page shown when a user tries to access a gated module feature."""

    def get(self, request):
        module_slug = request.GET.get('module', '')
        module_name = dict(ModuleSubscription.MODULE_CHOICES).get(
            module_slug, module_slug.replace('_', ' ').title(),
        )
        # The real price, not a literal. This page said "$10/month" for every
        # module, on the screen a blocked school reads — while the modules it
        # gates run from $10 to $149.
        from billing.models import ModuleProduct as _MP
        product = _MP.objects.filter(module=module_slug, is_active=True).first()
        return render(request, 'billing/module_required.html', {
            'module_slug': module_slug,
            'module_name': module_name,
            'module_price': product.price if product else None,
        })


# ---------------------------------------------------------------------------
# Stripe Checkout & Subscription Management Views
# ---------------------------------------------------------------------------

class InstituteCheckoutView(LoginRequiredMixin, View):
    """Create a Stripe Checkout Session for institute plan subscription.

    The school may already carry a discount code — typed at registration, or
    attached later by a super-admin — and it has to reach Stripe HERE. It did
    not: this view never passed a coupon, so a school whose subscription
    records "50% off" was sent to checkout at the full list price. Stripe
    charges what the session says; the discount existed only in our database.

    A 100% code is the other half of the same hole. Those deliberately have no
    Stripe coupon (``is_fully_free`` short-circuits every sync), so there was
    nothing to pass and the school was billed in full for a plan it had been
    granted for free. Nothing to charge means Stripe is not involved at all —
    the plan is activated directly, the way registration already does it.
    """

    def post(self, request):
        plan_slug = request.POST.get('plan', '')
        plan = InstitutePlan.objects.filter(slug=plan_slug, is_active=True).first()
        if not plan:
            messages.error(request, 'Invalid plan selected.')
            return redirect('institute_plan_select')

        school = get_school_for_user(request.user)
        if not school:
            messages.error(request, 'No school found for your account.')
            return redirect('subjects_hub')

        sub = get_school_subscription(school)
        discount = sub.discount_code if sub else None

        # ── Nothing to charge: activate the plan, never visit Stripe ─────────
        if sub and discount and discount.is_fully_free:
            sub.plan = plan
            sub.status = SchoolSubscription.STATUS_ACTIVE
            sub.trial_end = None
            sub.save(update_fields=['plan', 'status', 'trial_end', 'updated_at'])
            log_event(
                user=request.user, school=school, category='billing',
                action='institute_plan_activated_free',
                detail={'plan_id': plan.id, 'plan_name': plan.name,
                        'plan_slug': plan_slug, 'discount_code': discount.code},
                request=request,
            )
            messages.success(
                request,
                f'{plan.name} is active — discount code {discount.code} covers '
                f'the full cost, so there is nothing to pay.',
            )
            # Said out loud because the code does NOT stop an existing Stripe
            # subscription; it only keeps us from starting a new one.
            if sub.stripe_subscription_id:
                messages.warning(
                    request,
                    'A Stripe subscription is still attached to this school and '
                    'will keep billing until it is cancelled.',
                )
            return redirect('institute_subscription_dashboard')

        if not plan.stripe_price_id:
            messages.error(request, 'This plan is not yet available for online checkout.')
            return redirect('institute_plan_select')

        # A partial code Stripe has never seen is ignored by Checkout without
        # complaint — the school pays list price against a subscription that
        # says they are discounted. Refuse the checkout instead of overcharging.
        stripe_coupon_id = None
        if discount:
            from billing.stripe_service import ensure_stripe_coupon
            synced, sync_error = ensure_stripe_coupon(discount)
            if not synced:
                logger.error(
                    'Institute checkout blocked: discount %s (%s%% off) for '
                    'school %s has no Stripe coupon — %s',
                    discount.code, discount.discount_percent, school.id, sync_error,
                )
                messages.error(
                    request,
                    f'Your discount code {discount.code} could not be applied, '
                    'so we have not charged you. Please contact support.',
                )
                return redirect('institute_plan_select')
            stripe_coupon_id = discount.stripe_coupon_id or None

        try:
            from billing.stripe_service import create_institute_checkout_session
            # Update plan on existing subscription so we don't create duplicates
            if sub and sub.plan_id != plan.id:
                sub.plan = plan
                sub.save(update_fields=['plan'])
            # Only offer trial if the school hasn't used one before
            trial_days = plan.trial_days if (not sub or not sub.has_used_trial) else None
            session = create_institute_checkout_session(
                school, plan, request, trial_period_days=trial_days,
                stripe_coupon_id=stripe_coupon_id,
            )
            log_event(
                user=request.user, school=school, category='billing',
                action='checkout_session_created',
                detail={'plan_id': plan.id, 'plan_name': plan.name, 'plan_slug': plan_slug,
                        'trial_days': trial_days,
                        'discount_code': discount.code if discount else None},
                request=request,
            )
            return redirect(session.url)
        except stripe.error.StripeError as e:
            messages.error(request, f'Payment error: {e.user_message or str(e)}')
            return redirect('institute_plan_select')


class InstituteCheckoutSuccessView(View):
    """Success page after Stripe Checkout for institute subscription.

    Stripe redirects here with ?session_id=... after payment. The session is
    verified with Stripe and the subscription activated straight away, so the
    outcome never depends on the webhook arriving first.

    Deliberately NOT login-required. A new institute has no account at this
    point — that is the whole change: nothing is created until Stripe confirms
    the card, so this page is where a brand-new signup lands, still anonymous,
    and it builds the account and signs them in. An existing school upgrading a
    plan arrives here logged in and takes the branch below.
    """

    def get(self, request):
        session_id = request.GET.get('session_id', '')

        # A signup that has not been built yet: no user, no school, nothing.
        if session_id:
            created = self._activate_pending_signup(request, session_id)
            if created:
                return created

        if not request.user.is_authenticated:
            return redirect('login')

        school = get_school_for_user(request.user)
        sub = get_school_subscription(school) if school else None

        if session_id and sub and sub.status != SchoolSubscription.STATUS_ACTIVE:
            self._activate_from_session(session_id, sub)
            sub.refresh_from_db()

        return render(request, 'billing/institute_checkout_success.html', {
            'school': school,
            'subscription': sub,
        })

    def _activate_pending_signup(self, request, session_id):
        """Build and sign in a brand-new institute, or return None.

        The webhook usually wins this race; when it does, ``completed`` is
        already True and this finds nothing to do — but the person still needs
        signing in, so the account is looked up and used either way. Running
        both paths must never produce two schools, which is why activation is
        idempotent rather than guarded by a flag checked here.
        """
        from django.contrib.auth import login as auth_login

        from accounts.institute_registration import activate_pending_institute
        from accounts.models import PendingInstituteRegistration

        pending = PendingInstituteRegistration.objects.filter(
            stripe_session_id=session_id).first()
        if not pending:
            return None

        trial_end, stripe_sub_id, stripe_customer_id = self._session_facts(session_id)
        user, school, sub = activate_pending_institute(
            pending,
            stripe_subscription_id=stripe_sub_id,
            stripe_customer_id=stripe_customer_id,
            trial_end=trial_end,
        )
        if not user:
            messages.error(
                request,
                'Your payment details were saved but we could not finish '
                'setting up your school. Please contact support — you have not '
                'been charged.',
            )
            return redirect('register_teacher_center')

        if not request.user.is_authenticated:
            auth_login(request, user,
                       backend='accounts.backends.EmailOrUsernameBackend')

        log_event(
            user=user, school=school, category='auth',
            action='hoi_registered',
            detail={'center_name': school.name if school else None,
                    'via': 'stripe_checkout', 'session_id': session_id},
            request=request,
        )
        try:
            from notifications.services import send_welcome_notification
            send_welcome_notification(user, school=school)
        except Exception:
            logger.exception('Failed to send welcome email for HoI user %s', user.pk)

        return render(request, 'billing/institute_checkout_success.html', {
            'school': school,
            'subscription': sub,
        })

    @staticmethod
    def _session_facts(session_id):
        """``(trial_end, subscription_id, customer_id)`` for a checkout session.

        Read from Stripe rather than assumed: Stripe owns the date it bills on,
        and a locally computed "now + 14 days" would drift from it.
        """
        from billing.webhook_handlers import _stripe_trial_end
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            session = stripe.checkout.Session.retrieve(session_id)
            sub_id = session.get('subscription') if isinstance(session, dict) \
                else getattr(session, 'subscription', '')
            cus_id = session.get('customer') if isinstance(session, dict) \
                else getattr(session, 'customer', '')
            return _stripe_trial_end(sub_id or ''), sub_id or '', cus_id or ''
        except Exception:  # noqa: BLE001 — never lose an account to a lookup
            logger.warning('Could not read checkout session %s', session_id,
                           exc_info=True)
            return None, '', ''

    @staticmethod
    def _activate_from_session(session_id, sub):
        """Verify checkout session with Stripe and activate if paid."""
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status in ('paid', 'no_payment_required'):
                sub.status = SchoolSubscription.STATUS_ACTIVE
                sub.stripe_subscription_id = session.subscription or sub.stripe_subscription_id
                if getattr(session, 'customer', None):
                    sub.stripe_customer_id = session.customer
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
        customer_id = None
        # Where Stripe sends them back to. Resolved from our own URLconf, never
        # from the request: this used to be built from HTTP_REFERER, so any
        # page that linked here chose where the school's billing admin landed
        # afterwards — an off-site redirect handed out by a header.
        return_to = 'billing_history'

        # Only the school's own admin (HoI / institute owner) may open the
        # SCHOOL's Stripe billing portal. Students, parents and other members
        # must NEVER resolve the school's Stripe customer — otherwise a gated
        # student sent here from the payment wall could view/change the school's
        # card or cancel the school subscription. Everyone else gets their OWN
        # subscription's customer only.
        school = get_school_for_user(request.user)
        if school and school.admin_id == request.user.id:
            sub = get_school_subscription(school)
            if sub:
                customer_id = sub.stripe_customer_id
                # Only when the school's customer is the one being opened — a
                # school with no Stripe customer falls through to the user's own
                # subscription below, and belongs back on its own page.
                if customer_id:
                    return_to = 'institute_subscription_dashboard'

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
            return_url = request.build_absolute_uri(reverse(return_to))
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

        # Both AI families are pick-one ladders: adding a tier must retire the
        # tier it replaces, or the school is billed for two and only one takes
        # effect. Grading was missing from this and was sold as three separate
        # $10 modules that could all be switched on at once.
        # Read the family from the registry rather than listing it here. This
        # was two hard-coded sets, and question_automation became a third
        # ladder without either of them knowing — a new family that nobody
        # remembered to add would silently sell two tiers at once.
        from billing import registry
        AI_IMPORT_SLUGS = registry.members_of('ai_import')

        try:
            if action == 'add':
                # Deactivate the other tiers in this family (mutual exclusivity)
                other_ai_slugs = registry.siblings_of(module_slug)
                if other_ai_slugs:
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
                    # No Stripe subscription — activate locally (trial/test).
                    #
                    # But separate the two reasons for landing here, because
                    # only one of them is legitimate. A school with no Stripe
                    # subscription is on trial or comped: nothing to bill, so a
                    # local row is right. A school that HAS a Stripe
                    # subscription and reaches this branch is here because the
                    # module has no stripe_price_id — and it silently receives
                    # a paid module for free, forever, with no line on any
                    # invoice and nothing anywhere reporting it.
                    #
                    # That is how AI Grading Professional was given away: the
                    # module was active on a paying school for months, at $49
                    # list, and simply never appeared on a Stripe invoice.
                    # Nobody found out until the invoice was read by hand.
                    if sub.stripe_subscription_id and not stripe_price_id:
                        logger.error(
                            'Module %s activated for school %s with no Stripe '
                            'price — it will NOT be billed. Run '
                            '"manage.py sync_stripe_prices --create-missing".',
                            module_slug, sub.school_id,
                        )
                        log_event(
                            user=request.user, school=sub.school,
                            category='entitlement',
                            action='module_activated_unbilled',
                            result='success',
                            detail={'module': module_slug,
                                    'reason': 'no stripe_price_id'},
                            request=request,
                        )
                        messages.warning(
                            request,
                            f'{module_name} was switched on, but it has no '
                            f'price set up in Stripe yet, so it will not be '
                            f'billed. Tell support before relying on it.',
                        )
                    ModuleSubscription.objects.update_or_create(
                        school_subscription=sub,
                        module=module_slug,
                        defaults={'is_active': True, 'deactivated_at': None},
                    )
                # The plans page quotes the first-year price, so the discount
                # is attached here — automatically, with no code for anyone to
                # type. Stripe drops it after twelve months on its own.
                #
                # A failure is SHOWN, never swallowed: the school was quoted
                # half price, so silently landing on the full price is an
                # overcharge nobody would notice until the invoice.
                from billing import ai_tiers
                if module_slug in AI_IMPORT_SLUGS and ai_tiers.INTRO_DISCOUNT_ENABLED:
                    from billing.stripe_service import apply_ai_intro_discount
                    applied, discount_error = apply_ai_intro_discount(sub)
                    if not applied and discount_error:
                        messages.warning(request, discount_error)

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


class StudentAIGradingView(LoginRequiredMixin, View):
    """What the AI Graded Questions add-on is, for a student on Student Basic.

    Deliberately NOT a checkout. Per-student modules have no Stripe flow yet, so
    offering a Buy button would be a lie; the POST records interest in the audit
    log and tells the student the truth — that somebody will set it up with them.
    Nothing on their account changes here.

    There is no route in the other direction: a student cannot put themselves on
    Student Basic from this page or anywhere else. That tier is granted.
    """

    INTEREST_ACTION = 'student_ai_grading_interest'

    def get(self, request):
        return render(request, 'billing/student_ai_grading.html',
                      self._context(request))

    def post(self, request):
        context = self._context(request)
        if not context['already_included']:
            log_event(
                user=request.user, school=None, category='billing',
                action=self.INTEREST_ACTION,
                detail={'module': StudentModule.MODULE_AI_GRADING},
                request=request,
            )
            context['registered'] = True
        return render(request, 'billing/student_ai_grading.html', context)

    @staticmethod
    def standard_plan():
        """The paid plan a Student Basic student would move onto.

        The upgrade out of Student Basic is not a cheap module bolted on the
        side — it is becoming an ordinary paying subscriber on the same plan
        everyone else sees at sign-up. So the price quoted here is read off
        that ``Package`` and can never drift from the one step 3 of the
        registration form shows.

        ``is_default`` wins if the owner has set it; otherwise the cheapest
        active paid package. The free packages (`grant_free_access` creates
        one) are excluded — quoting $0.00 as the upgrade price would be worse
        than quoting nothing.
        """
        paid = Package.objects.filter(is_active=True, price__gt=0)
        return paid.filter(is_default=True).first() or paid.order_by(
            'order', 'price').first()

    def _context(self, request):
        from worksheets.grading_service import student_can_be_ai_graded

        entitled = student_can_be_ai_graded(request.user)
        on_basic = student_has_module(request.user, StudentModule.MODULE_BASIC)
        plan = self.standard_plan()
        return {
            'already_included': entitled,
            'current_tier': 'Student Basic' if on_basic else 'Full access',
            'plan': plan,
            'price': plan.price if plan else None,
            'registered': False,
        }


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


class AIGradingAlertAckView(LoginRequiredMixin, View):
    """Remember that this head of institute has seen the AI grading warning.

    Written only once the modal has actually rendered in front of them, so a
    head who never clicks anything still sees it exactly once — and sees it
    again at the next rung, because the token carries the threshold.
    """

    def post(self, request):
        import json

        from billing.quota_alerts import SESSION_KEY

        try:
            token = json.loads(request.body or '{}').get('token', '')
        except (ValueError, TypeError):
            token = ''
        if token:
            request.session[SESSION_KEY] = str(token)[:32]
        return JsonResponse({'ok': True})
