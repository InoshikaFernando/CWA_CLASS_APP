"""
Tests for Stripe webhook handlers and the full webhook flow.

Covers:
- StripeWebhookView (signature validation, idempotency, dispatch)
- handle_checkout_completed (institute + individual)
- handle_subscription_updated / created (institute + individual + fallback)
- handle_subscription_deleted
- handle_payment_succeeded
- handle_payment_failed
"""
import json
import hmac
import hashlib
import time

from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser
from billing.models import (
    InstitutePlan, Package, SchoolSubscription, Subscription,
    ModuleSubscription, StripeEvent,
)
from billing.webhook_handlers import (
    handle_checkout_completed,
    handle_subscription_updated,
    handle_subscription_deleted,
    handle_payment_succeeded,
    handle_payment_failed,
)
from classroom.models import School
from accounts.models import Role, UserRole


class WebhookHandlerTestBase(TestCase):
    """Base class with common fixtures for webhook tests."""

    def setUp(self):
        # Create user
        self.user = CustomUser.objects.create_user(
            username='testowner', email='owner@test.com', password='testpass123',
        )
        # Create HoI role
        self.hoi_role, _ = Role.objects.get_or_create(
            name='head_of_institute',
            defaults={'display_name': 'Head of Institute'},
        )
        UserRole.objects.get_or_create(user=self.user, role=self.hoi_role)

        # Create school
        self.school = School.objects.create(
            name='Test School', slug='test-school', admin=self.user,
        )

        # Create plan
        self.plan = InstitutePlan.objects.create(
            name='Test Silver', slug='test-silver-wh', price=129.00,
            class_limit=10, student_limit=200,
            invoice_limit_yearly=750, extra_invoice_rate=0.25,
            stripe_price_id='price_test_silver',
        )

        # Create school subscription (trialing - as created during registration)
        self.school_sub = SchoolSubscription.objects.create(
            school=self.school,
            plan=self.plan,
            status=SchoolSubscription.STATUS_TRIALING,
            stripe_customer_id='cus_test_123',
        )


# ---------------------------------------------------------------------------
# checkout.session.completed
# ---------------------------------------------------------------------------

class HandleCheckoutCompletedInstituteTest(WebhookHandlerTestBase):
    """Tests for handle_checkout_completed with institute type."""

    def test_activates_institute_subscription(self):
        """checkout.session.completed should activate a trialing school subscription."""
        event_data = {
            'object': {
                'metadata': {
                    'type': 'institute',
                    'school_id': str(self.school.id),
                    'plan_id': str(self.plan.id),
                },
                'subscription': 'sub_test_abc123',
            }
        }

        handle_checkout_completed(event_data)

        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_ACTIVE)
        self.assertEqual(self.school_sub.stripe_subscription_id, 'sub_test_abc123')
        self.assertIsNone(self.school_sub.trial_end)

    def test_updates_plan_if_provided(self):
        """Should update the plan if plan_id is in metadata."""
        gold_plan = InstitutePlan.objects.create(
            name='Test Gold', slug='test-gold-wh', price=159.00,
            class_limit=15, student_limit=300,
            invoice_limit_yearly=1000, extra_invoice_rate=0.20,
            stripe_price_id='price_test_gold',
        )
        event_data = {
            'object': {
                'metadata': {
                    'type': 'institute',
                    'school_id': str(self.school.id),
                    'plan_id': str(gold_plan.id),
                },
                'subscription': 'sub_test_xyz',
            }
        }

        handle_checkout_completed(event_data)

        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.plan, gold_plan)

    def test_missing_school_id_does_nothing(self):
        """Should silently return if school_id is missing."""
        event_data = {
            'object': {
                'metadata': {'type': 'institute'},
                'subscription': 'sub_test_noid',
            }
        }
        handle_checkout_completed(event_data)
        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_TRIALING)

    def test_nonexistent_school_does_nothing(self):
        """Should log error if school doesn't exist."""
        event_data = {
            'object': {
                'metadata': {
                    'type': 'institute',
                    'school_id': '99999',
                    'plan_id': str(self.plan.id),
                },
                'subscription': 'sub_test_noschool',
            }
        }
        handle_checkout_completed(event_data)
        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_TRIALING)

    def test_unknown_type_logs_warning(self):
        """Unknown sub_type should log warning."""
        event_data = {
            'object': {
                'metadata': {'type': 'unknown_type'},
                'subscription': 'sub_test_unknown',
            }
        }
        # Should not raise
        handle_checkout_completed(event_data)


class HandleCheckoutCompletedIndividualTest(TestCase):
    """Tests for handle_checkout_completed with individual type."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='student1', email='student@test.com', password='testpass123',
        )
        self.package = Package.objects.create(
            name='Premium', price=19.00, billing_type='recurring',
            stripe_price_id='price_test_premium',
        )
        self.sub = Subscription.objects.create(
            user=self.user,
            package=self.package,
            status=Subscription.STATUS_TRIALING,
        )

    def test_activates_individual_subscription(self):
        event_data = {
            'object': {
                'metadata': {
                    'type': 'individual',
                    'user_id': str(self.user.id),
                    'package_id': str(self.package.id),
                },
                'subscription': 'sub_ind_test',
            }
        }

        handle_checkout_completed(event_data)

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(self.sub.stripe_subscription_id, 'sub_ind_test')

    def test_school_student_type_works(self):
        """school_student type should also activate individual subscription."""
        event_data = {
            'object': {
                'metadata': {
                    'type': 'school_student',
                    'user_id': str(self.user.id),
                    'package_id': str(self.package.id),
                },
                'subscription': 'sub_school_student_test',
            }
        }

        handle_checkout_completed(event_data)

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_ACTIVE)

    def test_updates_user_package(self):
        """Should update user.package field."""
        new_pkg = Package.objects.create(
            name='Ultra', price=49.00, billing_type='recurring',
        )
        event_data = {
            'object': {
                'metadata': {
                    'type': 'individual',
                    'user_id': str(self.user.id),
                    'package_id': str(new_pkg.id),
                },
                'subscription': 'sub_pkg_test',
            }
        }

        handle_checkout_completed(event_data)

        self.user.refresh_from_db()
        self.assertEqual(self.user.package, new_pkg)

    def test_missing_user_id_does_nothing(self):
        event_data = {
            'object': {
                'metadata': {'type': 'individual'},
                'subscription': 'sub_nouser',
            }
        }
        handle_checkout_completed(event_data)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_TRIALING)


# ---------------------------------------------------------------------------
# customer.subscription.updated / created
# ---------------------------------------------------------------------------

class HandleSubscriptionUpdatedInstituteTest(WebhookHandlerTestBase):
    """Tests for handle_subscription_updated with institute type."""

    def test_syncs_active_status(self):
        """Should update status to active and set period dates."""
        now = int(time.time())
        event_data = {
            'object': {
                'id': 'sub_updated_inst',
                'status': 'active',
                'metadata': {
                    'type': 'institute',
                    'school_id': str(self.school.id),
                },
                'cancel_at_period_end': False,
                'current_period_start': now,
                'current_period_end': now + 2592000,  # +30 days
            }
        }

        handle_subscription_updated(event_data)

        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_ACTIVE)
        self.assertEqual(self.school_sub.stripe_subscription_id, 'sub_updated_inst')
        self.assertFalse(self.school_sub.cancel_at_period_end)

    def test_syncs_cancelled_status(self):
        """Should mark as cancelled."""
        self.school_sub.status = SchoolSubscription.STATUS_ACTIVE
        self.school_sub.stripe_subscription_id = 'sub_cancel_test'
        self.school_sub.save()

        event_data = {
            'object': {
                'id': 'sub_cancel_test',
                'status': 'canceled',
                'metadata': {
                    'type': 'institute',
                    'school_id': str(self.school.id),
                },
                'cancel_at_period_end': False,
                'current_period_start': None,
                'current_period_end': None,
            }
        }

        handle_subscription_updated(event_data)

        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_CANCELLED)

    def test_syncs_past_due_status(self):
        event_data = {
            'object': {
                'id': 'sub_past_due',
                'status': 'past_due',
                'metadata': {
                    'type': 'institute',
                    'school_id': str(self.school.id),
                },
                'cancel_at_period_end': False,
                'current_period_start': None,
                'current_period_end': None,
            }
        }

        handle_subscription_updated(event_data)

        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_PAST_DUE)

    def test_fallback_finds_by_stripe_id(self):
        """When metadata has no type, should fall back to finding by stripe_subscription_id."""
        self.school_sub.stripe_subscription_id = 'sub_fallback_test'
        self.school_sub.save()

        now = int(time.time())
        event_data = {
            'object': {
                'id': 'sub_fallback_test',
                'status': 'active',
                'metadata': {},  # No type!
                'cancel_at_period_end': False,
                'current_period_start': now,
                'current_period_end': now + 2592000,
            }
        }

        handle_subscription_updated(event_data)

        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_ACTIVE)

    def test_nonexistent_subscription_does_nothing(self):
        """Should log warning if no subscription found."""
        event_data = {
            'object': {
                'id': 'sub_nonexistent',
                'status': 'active',
                'metadata': {
                    'type': 'institute',
                    'school_id': '99999',
                },
                'cancel_at_period_end': False,
                'current_period_start': None,
                'current_period_end': None,
            }
        }
        # Should not raise
        handle_subscription_updated(event_data)

    def test_cancel_at_period_end(self):
        """Should set cancel_at_period_end flag."""
        event_data = {
            'object': {
                'id': 'sub_cancel_end',
                'status': 'active',
                'metadata': {
                    'type': 'institute',
                    'school_id': str(self.school.id),
                },
                'cancel_at_period_end': True,
                'current_period_start': None,
                'current_period_end': None,
            }
        }

        handle_subscription_updated(event_data)

        self.school_sub.refresh_from_db()
        self.assertTrue(self.school_sub.cancel_at_period_end)


class HandleSubscriptionUpdatedIndividualTest(TestCase):
    """Tests for handle_subscription_updated with individual type."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='student2', email='student2@test.com', password='testpass123',
        )
        self.sub = Subscription.objects.create(
            user=self.user,
            status=Subscription.STATUS_TRIALING,
        )

    def test_syncs_active_status(self):
        now = int(time.time())
        event_data = {
            'object': {
                'id': 'sub_ind_updated',
                'status': 'active',
                'metadata': {
                    'type': 'individual',
                    'user_id': str(self.user.id),
                },
                'cancel_at_period_end': False,
                'current_period_start': now,
                'current_period_end': now + 2592000,
            }
        }

        handle_subscription_updated(event_data)

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(self.sub.stripe_subscription_id, 'sub_ind_updated')

    def test_fallback_by_stripe_id(self):
        """Individual sub found by stripe_subscription_id when no metadata type."""
        self.sub.stripe_subscription_id = 'sub_ind_fallback'
        self.sub.save()

        event_data = {
            'object': {
                'id': 'sub_ind_fallback',
                'status': 'active',
                'metadata': {},
                'cancel_at_period_end': False,
                'current_period_start': None,
                'current_period_end': None,
            }
        }

        handle_subscription_updated(event_data)

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_ACTIVE)


# ---------------------------------------------------------------------------
# customer.subscription.deleted
# ---------------------------------------------------------------------------

class HandleSubscriptionDeletedTest(WebhookHandlerTestBase):

    def test_marks_as_cancelled(self):
        self.school_sub.status = SchoolSubscription.STATUS_ACTIVE
        self.school_sub.stripe_subscription_id = 'sub_to_delete'
        self.school_sub.save()

        event_data = {
            'object': {
                'id': 'sub_to_delete',
                'status': 'active',  # Will be overridden to 'canceled'
                'metadata': {
                    'type': 'institute',
                    'school_id': str(self.school.id),
                },
                'cancel_at_period_end': False,
                'current_period_start': None,
                'current_period_end': None,
            }
        }

        handle_subscription_deleted(event_data)

        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_CANCELLED)


# ---------------------------------------------------------------------------
# invoice.payment_succeeded / failed
# ---------------------------------------------------------------------------

class HandlePaymentSucceededTest(TestCase):

    def test_logs_event(self):
        """Should create audit log entry."""
        event_data = {
            'object': {
                'subscription': 'sub_paid',
                'amount_paid': 12900,
                'currency': 'nzd',
            }
        }
        # Should not raise
        handle_payment_succeeded(event_data)


class HandlePaymentFailedTest(WebhookHandlerTestBase):

    def test_logs_failure(self):
        event_data = {
            'object': {
                'subscription': 'sub_failed',
                'customer': 'cus_failed',
                'amount_due': 12900,
                'currency': 'nzd',
            }
        }
        # Should not raise
        handle_payment_failed(event_data)


# ---------------------------------------------------------------------------
# Full Webhook View Integration Tests
# ---------------------------------------------------------------------------

@override_settings(
    STRIPE_WEBHOOK_SECRET='whsec_test_secret',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class StripeWebhookViewTest(WebhookHandlerTestBase):
    """Integration tests for the full webhook view."""

    def _build_signed_payload(self, event_dict):
        """Build a Stripe-signed webhook payload."""
        payload = json.dumps(event_dict)
        timestamp = str(int(time.time()))
        signed_payload = f'{timestamp}.{payload}'
        signature = hmac.new(
            b'whsec_test_secret',
            signed_payload.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        sig_header = f't={timestamp},v1={signature}'
        return payload, sig_header

    def test_invalid_signature_returns_400(self):
        response = self.client.post(
            reverse('stripe_webhook'),
            data='{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=123,v1=badsig',
        )
        self.assertEqual(response.status_code, 400)

    def test_valid_checkout_completed_activates_subscription(self):
        """Full end-to-end: webhook receives checkout.session.completed and activates subscription."""
        event = {
            'id': 'evt_checkout_test_001',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'metadata': {
                        'type': 'institute',
                        'school_id': str(self.school.id),
                        'plan_id': str(self.plan.id),
                    },
                    'subscription': 'sub_checkout_live',
                }
            }
        }
        payload, sig = self._build_signed_payload(event)

        response = self.client.post(
            reverse('stripe_webhook'),
            data=payload,
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE=sig,
        )

        self.assertEqual(response.status_code, 200)
        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_ACTIVE)
        self.assertEqual(self.school_sub.stripe_subscription_id, 'sub_checkout_live')

        # Verify event recorded
        self.assertTrue(StripeEvent.objects.filter(event_id='evt_checkout_test_001').exists())

    def test_valid_subscription_created_activates_subscription(self):
        """customer.subscription.created should also activate via handle_subscription_updated."""
        now = int(time.time())
        event = {
            'id': 'evt_sub_created_001',
            'type': 'customer.subscription.created',
            'data': {
                'object': {
                    'id': 'sub_created_live',
                    'status': 'active',
                    'metadata': {
                        'type': 'institute',
                        'school_id': str(self.school.id),
                    },
                    'cancel_at_period_end': False,
                    'current_period_start': now,
                    'current_period_end': now + 2592000,
                }
            }
        }
        payload, sig = self._build_signed_payload(event)

        response = self.client.post(
            reverse('stripe_webhook'),
            data=payload,
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE=sig,
        )

        self.assertEqual(response.status_code, 200)
        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_ACTIVE)
        self.assertEqual(self.school_sub.stripe_subscription_id, 'sub_created_live')

    def test_idempotency_skips_duplicate_event(self):
        """Same event_id should be processed only once."""
        StripeEvent.objects.create(
            event_id='evt_duplicate',
            event_type='checkout.session.completed',
        )

        event = {
            'id': 'evt_duplicate',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'metadata': {
                        'type': 'institute',
                        'school_id': str(self.school.id),
                    },
                    'subscription': 'sub_dupe',
                }
            }
        }
        payload, sig = self._build_signed_payload(event)

        response = self.client.post(
            reverse('stripe_webhook'),
            data=payload,
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE=sig,
        )

        self.assertEqual(response.status_code, 200)
        # Subscription should NOT have been updated (still trialing)
        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_TRIALING)

    def test_unhandled_event_returns_200(self):
        """Unhandled event types should still return 200."""
        event = {
            'id': 'evt_unhandled_001',
            'type': 'charge.refunded',
            'data': {
                'object': {'id': 'ch_test'}
            }
        }
        payload, sig = self._build_signed_payload(event)

        response = self.client.post(
            reverse('stripe_webhook'),
            data=payload,
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE=sig,
        )

        self.assertEqual(response.status_code, 200)

    def test_subscription_updated_via_webhook(self):
        """customer.subscription.updated should sync status."""
        self.school_sub.stripe_subscription_id = 'sub_to_update'
        self.school_sub.status = SchoolSubscription.STATUS_ACTIVE
        self.school_sub.save()

        now = int(time.time())
        event = {
            'id': 'evt_sub_updated_001',
            'type': 'customer.subscription.updated',
            'data': {
                'object': {
                    'id': 'sub_to_update',
                    'status': 'past_due',
                    'metadata': {
                        'type': 'institute',
                        'school_id': str(self.school.id),
                    },
                    'cancel_at_period_end': False,
                    'current_period_start': now,
                    'current_period_end': now + 2592000,
                }
            }
        }
        payload, sig = self._build_signed_payload(event)

        response = self.client.post(
            reverse('stripe_webhook'),
            data=payload,
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE=sig,
        )

        self.assertEqual(response.status_code, 200)
        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_PAST_DUE)

    def test_subscription_deleted_via_webhook(self):
        """customer.subscription.deleted should cancel subscription."""
        self.school_sub.stripe_subscription_id = 'sub_to_delete_wh'
        self.school_sub.status = SchoolSubscription.STATUS_ACTIVE
        self.school_sub.save()

        event = {
            'id': 'evt_sub_deleted_001',
            'type': 'customer.subscription.deleted',
            'data': {
                'object': {
                    'id': 'sub_to_delete_wh',
                    'status': 'canceled',
                    'metadata': {
                        'type': 'institute',
                        'school_id': str(self.school.id),
                    },
                    'cancel_at_period_end': False,
                    'current_period_start': None,
                    'current_period_end': None,
                }
            }
        }
        payload, sig = self._build_signed_payload(event)

        response = self.client.post(
            reverse('stripe_webhook'),
            data=payload,
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE=sig,
        )

        self.assertEqual(response.status_code, 200)
        self.school_sub.refresh_from_db()
        self.assertEqual(self.school_sub.status, SchoolSubscription.STATUS_CANCELLED)


# ---------------------------------------------------------------------------
# Billing Dashboard navigation after webhook
# ---------------------------------------------------------------------------

class BillingDashboardAfterWebhookTest(WebhookHandlerTestBase):
    """Regression: verify dashboard loads after subscription is activated."""

    def test_dashboard_loads_with_active_subscription(self):
        """Dashboard should show subscription details, not redirect to plan select."""
        self.school_sub.status = SchoolSubscription.STATUS_ACTIVE
        self.school_sub.stripe_subscription_id = 'sub_dashboard_test'
        self.school_sub.save()

        self.client.login(username='testowner', password='testpass123')
        response = self.client.get(reverse('institute_subscription_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Subscription')
        self.assertContains(response, 'Silver')

    def test_dashboard_redirects_without_subscription(self):
        """Dashboard should redirect to plan select when no subscription exists."""
        self.school_sub.delete()

        self.client.login(username='testowner', password='testpass123')
        response = self.client.get(reverse('institute_subscription_dashboard'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('institute/plans', response.url)

    def test_dashboard_shows_module_toggle_buttons(self):
        """Dashboard should show Add buttons for modules when subscription is active."""
        self.school_sub.status = SchoolSubscription.STATUS_ACTIVE
        self.school_sub.stripe_subscription_id = 'sub_module_test'
        self.school_sub.save()

        self.client.login(username='testowner', password='testpass123')
        response = self.client.get(reverse('institute_subscription_dashboard'))

        self.assertEqual(response.status_code, 200)
        # Should have Add buttons for modules
        self.assertContains(response, 'module/toggle')
        self.assertContains(response, 'Students Attendance')
        self.assertContains(response, 'Teachers Attendance')

    def test_trialing_subscription_shows_dashboard(self):
        """Trialing status should also show dashboard, not redirect."""
        self.school_sub.status = SchoolSubscription.STATUS_TRIALING
        self.school_sub.save()

        self.client.login(username='testowner', password='testpass123')
        response = self.client.get(reverse('institute_subscription_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Subscription')
