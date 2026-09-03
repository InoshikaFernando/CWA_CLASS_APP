"""Who is on the free Student Basic edition, and how they got there.

The AI-graded half of the question bank costs a model call to mark. Student
Basic is the promotional edition sold without it: the questions the app marks
for itself, and none of the ones a model has to mark.

Everything here exists to pin one property, because getting it wrong takes
paid-for questions away from students who already have them:

    **A student with no ``StudentModule`` rows is on no tier at all.**

That is every student on the site the moment this ships, and every student who
subscribes afterwards. The tier is granted — by the owner, in the admin or with
``manage.py student_modules``, or by a promotion code the owner flagged. There
is no student-facing route onto it.
"""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from io import StringIO
from unittest.mock import patch

from billing.entitlements import (
    active_student_modules, apply_code_student_modules, grant_student_module,
    revoke_student_module, student_has_module, student_module_ai_verdict,
)
from billing.models import (
    DiscountCode, Package, PromoCode, StudentModule, Subscription,
)
from classroom.models import School
from worksheets.grading_service import ai_grading_offer, student_can_be_ai_graded

User = get_user_model()


def make_student(username, with_subscription=True):
    user = User.objects.create_user(
        username=username, password='pass1234', email=f'{username}@test.com')
    if with_subscription:
        package, _ = Package.objects.get_or_create(
            name='Free', defaults={'price': 0, 'class_limit': 0})
        Subscription.objects.create(
            user=user, package=package, status=Subscription.STATUS_ACTIVE)
    return user


class NobodyIsOnATierByDefaultTests(TestCase):
    """The property the whole design rests on."""

    def test_a_student_with_no_rows_has_no_modules(self):
        self.assertEqual(active_student_modules(make_student('plain')), set())

    def test_their_modules_have_no_opinion_about_ai_grading(self):
        self.assertIsNone(student_module_ai_verdict(make_student('quiet')))

    def test_so_an_individual_student_is_still_ai_graded(self):
        self.assertTrue(student_can_be_ai_graded(make_student('individual')))

    def test_a_student_who_never_subscribed_is_unaffected_too(self):
        user = make_student('nosub', with_subscription=False)
        self.assertEqual(active_student_modules(user), set())
        self.assertTrue(student_can_be_ai_graded(user))

    def test_a_school_student_still_answers_to_their_school(self):
        """The school rules are untouched — CWA's own students included.

        A student at a school without the module was not AI-graded before this
        existed and still is not; one at a school the owner granted free access
        to was and still is. Their 100%-discount code never had anything to do
        with it.
        """
        user = make_student('school-kid')
        paying = School.objects.create(name='Paid', slug='paid-sm',
                                       free_ai_grading=True)
        unpaid = School.objects.create(name='Unpaid', slug='unpaid-sm')

        with patch('billing.entitlements.get_all_schools_for_user',
                   return_value=[unpaid]), \
             patch('worksheets.grading_service.get_ai_grading_tier',
                   return_value=None):
            self.assertFalse(student_can_be_ai_graded(user))

        with patch('billing.entitlements.get_all_schools_for_user',
                   return_value=[paying]), \
             patch('worksheets.grading_service.get_ai_grading_tier',
                   return_value=None):
            self.assertTrue(student_can_be_ai_graded(user))


class StudentBasicWithholdsAIGradingTests(TestCase):
    def setUp(self):
        self.user = make_student('promo-kid')
        grant_student_module(self.user, StudentModule.MODULE_BASIC)

    def test_the_module_is_recorded(self):
        self.assertTrue(
            student_has_module(self.user, StudentModule.MODULE_BASIC))

    def test_they_are_not_ai_graded(self):
        self.assertFalse(student_can_be_ai_graded(self.user))

    def test_it_withholds_from_a_school_student_too(self):
        """A per-student withhold beats the school's grant.

        The promotion is given to named students, so it has to work whether or
        not they happen to sit inside a school that bought the module.
        """
        generous = School.objects.create(name='Generous', slug='generous-sm',
                                         free_ai_grading=True)
        with patch('billing.entitlements.get_all_schools_for_user',
                   return_value=[generous]):
            self.assertFalse(student_can_be_ai_graded(self.user))

    def test_the_add_on_puts_the_questions_back(self):
        grant_student_module(self.user, StudentModule.MODULE_AI_GRADING)
        self.assertTrue(student_can_be_ai_graded(self.user))

    def test_the_add_on_wins_even_at_a_school_without_the_module(self):
        revoke_student_module(self.user, StudentModule.MODULE_BASIC)
        grant_student_module(self.user, StudentModule.MODULE_AI_GRADING)
        broke = School.objects.create(name='No Module', slug='nomodule-sm')
        with patch('billing.entitlements.get_all_schools_for_user',
                   return_value=[broke]), \
             patch('worksheets.grading_service.get_ai_grading_tier',
                   return_value=None):
            self.assertTrue(student_can_be_ai_graded(self.user))

    def test_revoking_it_hands_the_questions_back(self):
        revoke_student_module(self.user, StudentModule.MODULE_BASIC)
        self.assertTrue(student_can_be_ai_graded(self.user))

    def test_a_revoked_module_keeps_its_record(self):
        """Who had what, and when, survives the promotion ending."""
        revoke_student_module(self.user, StudentModule.MODULE_BASIC)
        row = StudentModule.objects.get(subscription__user=self.user,
                                        module=StudentModule.MODULE_BASIC)
        self.assertFalse(row.is_active)
        self.assertIsNotNone(row.deactivated_at)


class GrantIsIdempotentTests(TestCase):
    def test_granting_twice_changes_nothing_the_second_time(self):
        user = make_student('twice')
        _row, first = grant_student_module(user, StudentModule.MODULE_BASIC)
        _row, second = grant_student_module(user, StudentModule.MODULE_BASIC)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(StudentModule.objects.filter(
            subscription__user=user).count(), 1)

    def test_re_granting_a_revoked_module_switches_it_back_on(self):
        user = make_student('again')
        grant_student_module(user, StudentModule.MODULE_BASIC)
        revoke_student_module(user, StudentModule.MODULE_BASIC)
        _row, changed = grant_student_module(user, StudentModule.MODULE_BASIC)
        self.assertTrue(changed)
        self.assertFalse(student_can_be_ai_graded(user))

    def test_a_student_with_no_subscription_cannot_carry_one(self):
        """Reported as a skip, not a crash and not a silent success."""
        user = make_student('unsubscribed', with_subscription=False)
        row, changed = grant_student_module(user, StudentModule.MODULE_BASIC)
        self.assertIsNone(row)
        self.assertFalse(changed)

    def test_revoking_something_they_never_had_is_a_no_op(self):
        user = make_student('nothing')
        row, changed = revoke_student_module(user, StudentModule.MODULE_BASIC)
        self.assertIsNone(row)
        self.assertFalse(changed)


class PromotionCodesTests(TestCase):
    """A code carries the tier the OWNER put on it — never one a student picks."""

    def test_an_ordinary_code_grants_nothing(self):
        user = make_student('ordinary')
        code = DiscountCode.objects.create(code='WELCOME', discount_percent=100)
        apply_code_student_modules(user, code)
        self.assertEqual(active_student_modules(user), set())
        self.assertTrue(student_can_be_ai_graded(user))

    def test_the_flag_defaults_to_off_on_both_code_types(self):
        self.assertFalse(DiscountCode.objects.create(
            code='D1', discount_percent=100).grants_student_basic)
        self.assertFalse(PromoCode.objects.create(
            code='P1', discount_percent=100).grants_student_basic)

    def test_a_flagged_code_puts_the_student_on_basic(self):
        user = make_student('cohort')
        code = DiscountCode.objects.create(
            code='PROMO2026', discount_percent=100, grants_student_basic=True)
        apply_code_student_modules(user, code)
        self.assertFalse(student_can_be_ai_graded(user))

    def test_the_code_is_recorded_on_the_module(self):
        user = make_student('traceable')
        code = PromoCode.objects.create(
            code='TRACE', discount_percent=100, grants_student_basic=True)
        apply_code_student_modules(user, code)
        row = StudentModule.objects.get(subscription__user=user)
        self.assertEqual(row.source_code, 'TRACE')

    def test_no_code_at_all_is_harmless(self):
        user = make_student('nocode')
        self.assertIsNone(apply_code_student_modules(user, None))


class UpsellIsOnlyOfferedToPeopleWhoCanActTests(TestCase):
    """A promotion pointed at a purchase the reader cannot make is worse than none."""

    def test_a_student_basic_student_is_offered_the_upgrade(self):
        user = make_student('offer-me')
        grant_student_module(user, StudentModule.MODULE_BASIC)
        entitled, can_upgrade = ai_grading_offer(user)
        self.assertFalse(entitled)
        self.assertTrue(can_upgrade)

    def test_a_school_student_without_the_module_is_not(self):
        user = make_student('not-my-call')
        unpaid = School.objects.create(name='Unpaid2', slug='unpaid2-sm')
        with patch('billing.entitlements.get_all_schools_for_user',
                   return_value=[unpaid]), \
             patch('worksheets.grading_service.get_ai_grading_tier',
                   return_value=None):
            entitled, can_upgrade = ai_grading_offer(user)
        self.assertFalse(entitled)
        self.assertFalse(can_upgrade)

    def test_a_student_who_already_has_it_is_not(self):
        entitled, can_upgrade = ai_grading_offer(make_student('has-it'))
        self.assertTrue(entitled)
        self.assertFalse(can_upgrade)


class StudentModulesCommandTests(TestCase):
    def _run(self, *args):
        out = StringIO()
        call_command('student_modules', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_it_grants_to_named_students(self):
        user = make_student('cli-kid')
        self._run('--grant', 'basic', '--user', 'cli-kid')
        self.assertFalse(student_can_be_ai_graded(user))

    def test_it_accepts_an_email(self):
        user = make_student('by-email')
        self._run('--grant', 'basic', '--user', 'by-email@test.com')
        self.assertTrue(student_has_module(user, StudentModule.MODULE_BASIC))

    def test_a_dry_run_writes_nothing(self):
        user = make_student('rehearsal')
        output = self._run('--grant', 'basic', '--user', 'rehearsal',
                           '--dry-run')
        self.assertIn('DRY RUN', output)
        self.assertEqual(StudentModule.objects.count(), 0)
        self.assertTrue(student_can_be_ai_graded(user))

    def test_it_revokes(self):
        user = make_student('done-with-promo')
        grant_student_module(user, StudentModule.MODULE_BASIC)
        self._run('--revoke', 'basic', '--user', 'done-with-promo')
        self.assertTrue(student_can_be_ai_graded(user))

    def test_an_unknown_student_is_reported_not_swallowed(self):
        output = self._run('--grant', 'basic', '--user', 'ghost')
        self.assertIn('NOT FOUND', output)

    def test_a_student_without_a_subscription_is_reported(self):
        make_student('cli-nosub', with_subscription=False)
        output = self._run('--grant', 'basic', '--user', 'cli-nosub')
        self.assertIn('NO SUBSCRIPTION', output)

    def test_it_reads_a_cohort_file(self):
        import tempfile
        import os
        make_student('file-a')
        make_student('file-b')
        handle = tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False)
        handle.write('# promo cohort\nfile-a\n\nfile-b\nfile-a\n')
        handle.close()
        try:
            self._run('--grant', 'basic', '--file', handle.name)
        finally:
            os.unlink(handle.name)
        self.assertEqual(StudentModule.objects.filter(
            module=StudentModule.MODULE_BASIC, is_active=True).count(), 2)

    def test_listing_says_plainly_when_nobody_is_on_a_tier(self):
        self.assertIn('No student is on any module', self._run('--list'))

    def test_listing_names_who_is(self):
        user = make_student('listed')
        grant_student_module(user, StudentModule.MODULE_BASIC)
        self.assertIn('listed', self._run('--list'))

    def test_it_refuses_a_call_with_neither_grant_nor_revoke(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self._run('--user', 'anyone')

    def test_it_refuses_to_name_nobody(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self._run('--grant', 'basic')
