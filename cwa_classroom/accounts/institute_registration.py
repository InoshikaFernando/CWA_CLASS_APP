"""Building an institute account — once, from one place.

The signup used to create the user, the school and a trialing subscription and
*then* redirect to Stripe. Abandoning that redirect left a working school with
no card on file, which nothing noticed until the trial expired a fortnight
later. Account creation now waits for Stripe to confirm the card.

That means the same account has to be built from three places — the fully-free
path (no card needed), the ``checkout.session.completed`` webhook, and the
success redirect that covers a late webhook — so it is built here, once.
``activate_pending_institute`` is idempotent because the webhook and the
browser routinely arrive together and must converge on one school, not two.
"""
import logging

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

logger = logging.getLogger(__name__)


def unique_school_slug(center_name):
    """A slug no existing school holds."""
    from classroom.models import School

    base = slugify(center_name) or 'school'
    slug = base
    counter = 1
    while School.objects.filter(slug=slug).exists():
        slug = f'{base}-{counter}'
        counter += 1
    return slug


def create_institute_account(*, username, email, center_name, plan,
                             password=None, password_hash=None,
                             discount_obj=None, address=None,
                             status=None, trial_end=None,
                             stripe_subscription_id='', stripe_customer_id='',
                             count_discount_use=True):
    """Create the HoI user, their school and its subscription, atomically.

    Exactly one of ``password`` (raw) or ``password_hash`` (already hashed by
    ``make_password``) must be given — the pending row stores a hash, the
    free-signup path has the raw value.

    Returns ``(user, school, subscription)``.
    """
    from billing.models import SchoolSubscription
    from classroom.models import School

    from .models import CustomUser, Role, UserRole

    if (password is None) == (password_hash is None):
        raise ValueError('Pass exactly one of password or password_hash')

    address = address or {}
    status = status or SchoolSubscription.STATUS_TRIALING

    with transaction.atomic():
        if password_hash is not None:
            user = CustomUser(username=username, email=email,
                              password=password_hash)
            user.terms_accepted_at = timezone.now()
            user.save()
        else:
            user = CustomUser.objects.create_user(
                username=username, email=email, password=password,
            )
            user.terms_accepted_at = timezone.now()
            user.save(update_fields=['terms_accepted_at'])

        role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        UserRole.objects.create(user=user, role=role)

        school = School.objects.create(
            name=center_name,
            slug=unique_school_slug(center_name),
            admin=user,
            abn=address.get('abn', ''),
            phone=address.get('phone', ''),
            street_address=address.get('street_address', ''),
            city=address.get('city', ''),
            state_region=address.get('state_region', ''),
            postal_code=address.get('postal_code', ''),
            country=address.get('country', ''),
        )

        sub = SchoolSubscription.objects.create(
            school=school,
            plan=plan,
            discount_code=discount_obj,
            status=status,
            trial_end=trial_end,
            # A trial that has been started is spent, whatever happens next —
            # otherwise cancelling and re-registering renews it forever.
            has_used_trial=trial_end is not None,
            stripe_subscription_id=stripe_subscription_id or '',
            stripe_customer_id=stripe_customer_id or '',
            invoice_year_start=timezone.now().date(),
        )

        if discount_obj and count_discount_use:
            discount_obj.uses += 1
            discount_obj.save(update_fields=['uses'])

    return user, school, sub


def activate_pending_institute(pending, *, stripe_subscription_id='',
                               stripe_customer_id='', trial_end=None):
    """Turn a ``PendingInstituteRegistration`` into a real institute.

    Idempotent by construction: the webhook and the browser redirect both call
    this, often within the same second. The row is locked and re-read with
    ``completed=False``, so the loser of that race returns the account the
    winner made rather than building a second school.

    Returns ``(user, school, subscription)``, or ``(None, None, None)`` when the
    plan has since been deactivated — the caller decides how loudly to fail.
    """
    from billing.models import InstitutePlan, InstituteDiscountCode, SchoolSubscription
    from classroom.models import School

    from .models import CustomUser, PendingInstituteRegistration

    with transaction.atomic():
        try:
            pending = (PendingInstituteRegistration.objects
                       .select_for_update()
                       .get(id=pending.id, completed=False))
        except PendingInstituteRegistration.DoesNotExist:
            # Someone else already built it. Hand back what they made.
            user = CustomUser.objects.filter(email__iexact=pending.email).first()
            school = School.objects.filter(admin=user).first() if user else None
            sub = None
            if school:
                sub = SchoolSubscription.objects.filter(school=school).first()
            return user, school, sub

        plan = InstitutePlan.objects.filter(id=pending.plan_id).first()
        if not plan:
            logger.error(
                'Plan %s missing while activating institute registration %s',
                pending.plan_id, pending.id,
            )
            return None, None, None

        data = pending.data or {}
        code = data.get('discount_code')
        discount_obj = (
            InstituteDiscountCode.objects.filter(code__iexact=code).first()
            if code else None
        )

        user, school, sub = create_institute_account(
            username=pending.username,
            email=pending.email,
            password_hash=pending.password_hash,
            center_name=pending.center_name,
            plan=plan,
            discount_obj=discount_obj,
            address=data,
            status=SchoolSubscription.STATUS_TRIALING,
            trial_end=trial_end,
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
        )

        pending.completed = True
        pending.save(update_fields=['completed'])

    # Stripe now knows which school this subscription belongs to, so later
    # status changes (trial ending, a failed card) route by metadata instead of
    # falling back to a lookup by subscription id.
    if stripe_subscription_id:
        _tag_stripe_subscription(stripe_subscription_id, school.id, plan.id)

    return user, school, sub


def _tag_stripe_subscription(stripe_subscription_id, school_id, plan_id):
    """Best-effort: write school_id onto the Stripe subscription's metadata.

    Never raises. The account already exists and the webhook handler can find
    the subscription by its Stripe id regardless, so a failure here costs
    routing convenience, not correctness.
    """
    try:
        import stripe

        from billing.stripe_service import _ensure_stripe_key
        _ensure_stripe_key()
        stripe.Subscription.modify(
            stripe_subscription_id,
            metadata={
                'type': 'institute',
                'school_id': school_id,
                'plan_id': plan_id,
            },
        )
    except Exception:  # noqa: BLE001 — cosmetic, never block activation
        logger.warning(
            'Could not tag Stripe subscription %s with school %s',
            stripe_subscription_id, school_id, exc_info=True,
        )
