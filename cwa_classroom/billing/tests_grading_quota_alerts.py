"""AI grading allowance: the 75/80/85/90/95/100% warning emails, and the stop.

The behaviour under test is the one an institute actually experiences — warned
on the way up, told when it stops, and each warning arriving once rather than
on every answer graded past the line.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser
from billing.models import (
    AIGradingUsage, InstitutePlan, ModuleProduct, ModuleSubscription,
    SchoolSubscription,
)
from billing import quota_alerts
from classroom.models import School


def _seed_grading_products():
    for slug, name, answers, price in [
        ('ai_grading_starter', 'AI Grading - Starter', 1000, '15.00'),
        ('ai_grading_professional', 'AI Grading - Professional', 5000, '49.00'),
        ('ai_grading_enterprise', 'AI Grading - Enterprise', None, '149.00'),
    ]:
        ModuleProduct.objects.update_or_create(
            module=slug,
            defaults={'name': name, 'price': Decimal(price),
                      'questions_per_month': answers, 'is_active': True},
        )


def _school(slug='grading', module='ai_grading_starter', used=0, alert=0):
    admin = CustomUser.objects.create_user(
        f'{slug}-admin', f'{slug}@test.internal', 'pw1!')
    school = School.objects.create(
        name=f'{slug} School', slug=slug, admin=admin, is_active=True)
    plan = InstitutePlan.objects.create(
        name=f'{slug} Plan', slug=f'{slug}-plan', price=Decimal('89.00'),
        class_limit=5, student_limit=100, invoice_limit_yearly=500,
        extra_invoice_rate=Decimal('0.30'),
    )
    sub = SchoolSubscription.objects.create(
        school=school, plan=plan, status='active',
        current_period_start=timezone.now(),
        current_period_end=timezone.now() + timezone.timedelta(days=30),
    )
    if module:
        ModuleSubscription.objects.create(
            school_subscription=sub, module=module, is_active=True)
    AIGradingUsage.objects.create(
        school=school, period_start=timezone.localdate().replace(day=1),
        answers_graded=used, highest_alert_sent=alert,
    )
    return school


class ThresholdLadderTests(TestCase):
    def test_the_ladder_is_the_one_that_was_asked_for(self):
        self.assertEqual(quota_alerts.ALERT_THRESHOLDS, (75, 80, 85, 90, 95, 100))

    def test_below_the_first_rung_is_no_alert(self):
        self.assertEqual(quota_alerts.threshold_reached(74), 0)

    def test_each_rung_resolves_to_itself(self):
        for rung in (75, 80, 85, 90, 95, 100):
            self.assertEqual(quota_alerts.threshold_reached(rung), rung)

    def test_between_rungs_resolves_down(self):
        self.assertEqual(quota_alerts.threshold_reached(84), 80)
        self.assertEqual(quota_alerts.threshold_reached(99), 95)


class AlertSendingTests(TestCase):
    def setUp(self):
        _seed_grading_products()

    @patch('billing.quota_alerts.send_grading_quota_alert')
    def test_crossing_75_percent_sends_one_alert(self, mock_send):
        school = _school(used=750)
        sent = quota_alerts.check_grading_quota_alerts(school, 750, 1000)
        self.assertEqual(sent, 75)
        self.assertEqual(mock_send.call_count, 1)
        self.assertEqual(mock_send.call_args.kwargs['percent'], 75)
        self.assertFalse(mock_send.call_args.kwargs['stopped'])

    @patch('billing.quota_alerts.send_grading_quota_alert')
    def test_the_same_rung_does_not_send_twice(self, mock_send):
        school = _school(used=760)
        self.assertEqual(quota_alerts.check_grading_quota_alerts(school, 760, 1000), 75)
        # Two more answers graded, still inside the 75% band.
        self.assertIsNone(quota_alerts.check_grading_quota_alerts(school, 770, 1000))
        self.assertIsNone(quota_alerts.check_grading_quota_alerts(school, 780, 1000))
        self.assertEqual(mock_send.call_count, 1)

    @patch('billing.quota_alerts.send_grading_quota_alert')
    def test_each_higher_rung_sends_again(self, mock_send):
        school = _school(used=0)
        for used, expected in [(750, 75), (800, 80), (850, 85),
                               (900, 90), (950, 95), (1000, 100)]:
            AIGradingUsage.objects.filter(school=school).update(answers_graded=used)
            self.assertEqual(
                quota_alerts.check_grading_quota_alerts(school, used, 1000), expected)
        self.assertEqual(mock_send.call_count, 6)
        self.assertEqual(
            [c.kwargs['percent'] for c in mock_send.call_args_list],
            [75, 80, 85, 90, 95, 100],
        )

    @patch('billing.quota_alerts.send_grading_quota_alert')
    def test_jumping_several_rungs_sends_only_the_highest(self, mock_send):
        """A burst of grading shouldn't fire five emails at once."""
        school = _school(used=960)
        self.assertEqual(quota_alerts.check_grading_quota_alerts(school, 960, 1000), 95)
        self.assertEqual(mock_send.call_count, 1)
        self.assertEqual(mock_send.call_args.kwargs['percent'], 96)

    @patch('billing.quota_alerts.send_grading_quota_alert')
    def test_the_100_percent_alert_says_it_stopped(self, mock_send):
        school = _school(used=1000, alert=95)
        self.assertEqual(quota_alerts.check_grading_quota_alerts(school, 1000, 1000), 100)
        self.assertTrue(mock_send.call_args.kwargs['stopped'])

    @patch('billing.quota_alerts.send_grading_quota_alert')
    def test_an_already_alerted_rung_is_skipped_after_a_restart(self, mock_send):
        school = _school(used=800, alert=80)
        self.assertIsNone(quota_alerts.check_grading_quota_alerts(school, 800, 1000))
        mock_send.assert_not_called()

    @patch('billing.quota_alerts.send_grading_quota_alert')
    def test_no_limit_means_no_alerts(self, mock_send):
        school = _school(module='ai_grading_enterprise', used=99999)
        self.assertIsNone(quota_alerts.check_grading_quota_alerts(school, 99999, None))
        mock_send.assert_not_called()

    @patch('billing.quota_alerts.send_grading_quota_alert', side_effect=RuntimeError('smtp down'))
    def test_a_failing_send_never_raises_into_the_grader(self, _mock_send):
        school = _school(used=750)
        self.assertIsNone(quota_alerts.check_grading_quota_alerts(school, 750, 1000))


class AlertContentTests(TestCase):
    def setUp(self):
        _seed_grading_products()

    @patch('classroom.email_service.send_templated_email', return_value=True)
    def test_the_email_names_the_next_tier_up(self, mock_email):
        school = _school(used=750)
        quota_alerts.send_grading_quota_alert(
            school, percent=75, used=750, limit=1000,
            tier_slug='ai_grading_starter', stopped=False,
        )
        context = mock_email.call_args.kwargs['context']
        self.assertEqual(context['next_tier_name'], 'AI Grading - Professional')
        self.assertEqual(context['next_tier_answers'], 5000)
        self.assertEqual(context['remaining'], 250)
        self.assertIn('75%', mock_email.call_args.kwargs['subject'])

    @patch('classroom.email_service.send_templated_email', return_value=True)
    def test_the_stopped_email_says_so_in_the_subject(self, mock_email):
        school = _school(used=1000)
        quota_alerts.send_grading_quota_alert(
            school, percent=100, used=1000, limit=1000,
            tier_slug='ai_grading_starter', stopped=True,
        )
        self.assertIn('paused', mock_email.call_args.kwargs['subject'].lower())

    @patch('classroom.email_service.send_templated_email', return_value=True)
    def test_the_top_tier_offers_no_upgrade(self, mock_email):
        school = _school(slug='top', module='ai_grading_enterprise', used=10)
        quota_alerts.send_grading_quota_alert(
            school, percent=75, used=75, limit=100,
            tier_slug='ai_grading_enterprise', stopped=False,
        )
        self.assertEqual(mock_email.call_args.kwargs['context']['next_tier_name'], '')

    @patch('classroom.email_service.send_templated_email', return_value=True)
    def test_the_school_admin_is_emailed(self, mock_email):
        school = _school(slug='admin-target', used=750)
        quota_alerts.send_grading_quota_alert(
            school, percent=75, used=750, limit=1000,
            tier_slug='ai_grading_starter', stopped=False,
        )
        self.assertEqual(
            mock_email.call_args.kwargs['recipient_email'], 'admin-target@test.internal')

    def test_next_grading_tier_walks_the_ladder(self):
        self.assertEqual(
            quota_alerts.next_grading_tier('ai_grading_starter').module,
            'ai_grading_professional')
        self.assertEqual(
            quota_alerts.next_grading_tier('ai_grading_professional').module,
            'ai_grading_enterprise')
        self.assertIsNone(quota_alerts.next_grading_tier('ai_grading_enterprise'))

    @patch('classroom.email_service.send_templated_email', return_value=True)
    def test_heads_of_institute_are_emailed_alongside_the_admin(self, mock_email):
        """Roles are school-scoped through SchoolTeacher, not global UserRole."""
        from classroom.models import SchoolTeacher

        school = _school(slug='heads', used=750)
        head = CustomUser.objects.create_user(
            'heads-head', 'head@test.internal', 'pw1!')
        SchoolTeacher.objects.create(
            school=school, teacher=head, role='head_of_institute')

        quota_alerts.send_grading_quota_alert(
            school, percent=75, used=750, limit=1000,
            tier_slug='ai_grading_starter', stopped=False,
        )
        addressed = {c.kwargs['recipient_email'] for c in mock_email.call_args_list}
        self.assertEqual(addressed, {'heads@test.internal', 'head@test.internal'})

    @patch('classroom.email_service.send_templated_email', return_value=True)
    def test_a_duplicate_address_is_only_emailed_once(self, mock_email):
        """The admin is often also the head of institute."""
        from classroom.models import SchoolTeacher

        school = _school(slug='dupe', used=750)
        # Creating a School already links its admin as a SchoolTeacher, so this
        # promotes that existing row rather than adding a second one.
        SchoolTeacher.objects.update_or_create(
            school=school, teacher=school.admin,
            defaults={'role': 'head_of_institute'})

        quota_alerts.send_grading_quota_alert(
            school, percent=75, used=750, limit=1000,
            tier_slug='ai_grading_starter', stopped=False,
        )
        self.assertEqual(mock_email.call_count, 1)


class HeadOfInstituteLoginAlertTests(TestCase):
    """The in-app warning shown to the head of institute from 75% on."""

    def setUp(self):
        _seed_grading_products()
        self.school = _school(slug='hoi', used=0)
        self.head = self.school.admin   # School.save() makes its admin the HOI

    def _set_used(self, used):
        AIGradingUsage.objects.filter(school=self.school).update(answers_graded=used)

    def _alert(self, session=None):
        return quota_alerts.grading_alert_for_user(
            self.head, {} if session is None else session)

    def test_nothing_below_75_percent(self):
        self._set_used(740)
        self.assertIsNone(self._alert())

    def test_a_warning_from_75_percent(self):
        self._set_used(750)
        alert = self._alert()
        self.assertIsNotNone(alert)
        self.assertEqual(alert['percent'], 75)
        self.assertEqual((alert['used'], alert['limit']), (750, 1000))
        self.assertEqual(alert['remaining'], 250)
        self.assertFalse(alert['stopped'])
        self.assertEqual(alert['next_tier_name'], 'AI Grading - Professional')

    def test_at_the_limit_it_says_grading_has_stopped(self):
        self._set_used(1000)
        alert = self._alert()
        self.assertTrue(alert['stopped'])
        self.assertEqual(alert['percent'], 100)

    def test_an_acknowledged_rung_is_not_shown_again(self):
        self._set_used(750)
        session = {}
        alert = self._alert(session)
        session[quota_alerts.SESSION_KEY] = alert['token']
        self.assertIsNone(self._alert(session))

    def test_a_higher_rung_shows_again_despite_the_acknowledgement(self):
        """Dismissing 75% must not silence the one that says it stopped."""
        self._set_used(750)
        session = {quota_alerts.SESSION_KEY: self._alert({})['token']}
        self.assertIsNone(self._alert(session))

        self._set_used(1000)
        later = self._alert(session)
        self.assertIsNotNone(later)
        self.assertTrue(later['stopped'])

    def test_a_teacher_who_is_not_a_head_sees_nothing(self):
        from accounts.models import Role

        self._set_used(900)
        teacher = CustomUser.objects.create_user(
            'hoi-teacher', 'hoi-teacher@test.internal', 'pw1!')
        role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        teacher.roles.add(role)
        self.assertIsNone(
            quota_alerts.grading_alert_for_user(teacher, {}))

    def test_a_school_with_no_metered_tier_sees_nothing(self):
        from billing.models import ModuleSubscription

        self._set_used(900)
        ModuleSubscription.objects.filter(
            school_subscription__school=self.school).update(is_active=False)
        self.assertIsNone(self._alert())

    def test_an_anonymous_user_sees_nothing(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertIsNone(quota_alerts.grading_alert_for_user(AnonymousUser(), {}))


class AlertAckEndpointTests(TestCase):
    def setUp(self):
        _seed_grading_products()
        self.school = _school(slug='ack', used=750)

    def test_posting_a_token_records_it_in_the_session(self):
        from django.urls import reverse
        import json

        self.client.force_login(self.school.admin)
        response = self.client.post(
            reverse('ai_grading_alert_ack'),
            data=json.dumps({'token': '2026-09:75'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.session[quota_alerts.SESSION_KEY], '2026-09:75')

    def test_a_junk_body_is_not_an_error(self):
        from django.urls import reverse

        self.client.force_login(self.school.admin)
        response = self.client.post(
            reverse('ai_grading_alert_ack'),
            data='not json', content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(quota_alerts.SESSION_KEY, self.client.session)


class AlertModalRenderTests(TestCase):
    """The modal has to survive a real render — {% url %} and all."""

    def setUp(self):
        _seed_grading_products()
        self.school = _school(slug='render', used=0)

    def _set_used(self, used):
        AIGradingUsage.objects.filter(school=self.school).update(answers_graded=used)

    def _dashboard(self):
        from django.urls import reverse
        self.client.force_login(self.school.admin)
        return self.client.get(reverse('institute_subscription_dashboard'))

    def test_the_modal_is_absent_below_75_percent(self):
        self._set_used(500)
        self.assertNotContains(self._dashboard(), 'ai-grading-alert-modal')

    def test_the_modal_renders_with_the_usage_sentence(self):
        self._set_used(800)
        response = self._dashboard()
        self.assertContains(response, 'ai-grading-alert-modal')
        self.assertContains(response, '800/1000')

    def test_the_stopped_modal_explains_the_questions_have_gone(self):
        self._set_used(1000)
        response = self._dashboard()
        self.assertContains(response, 'AI grading has paused')
