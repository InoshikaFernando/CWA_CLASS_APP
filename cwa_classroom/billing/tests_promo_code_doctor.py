"""The read-only report that answers "did Student (Promo) codes ever work?"

The question is about live data, not code, so the command's job is to separate
the three states that look alike from the outside and are wrong in different
ways: a counter with no members (never took effect for anyone), members the
promo gave nothing new to (worked, but was a no-op), and members whose class
access exists because of it.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from billing.models import Package, PromoCode

User = get_user_model()


def run(*args):
    out = StringIO()
    call_command('promo_code_doctor', *args, stdout=out, stderr=out)
    return out.getvalue()


class PromoCodeDoctorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.one_class = Package.objects.create(name='Solo', class_limit=1)
        cls.unlimited = Package.objects.create(name='All In', class_limit=0)

    def _student(self, username, package):
        return User.objects.create_user(
            username=username, password='pass1234',
            email=f'{username}@test.com', package=package)

    def test_it_says_so_when_there_are_no_codes(self):
        self.assertIn('No promo codes found', run())

    def test_a_counter_with_no_members_is_called_out(self):
        """The counter is decoration; redeemed_by is what the limit reads."""
        PromoCode.objects.create(code='PHANTOM', discount_percent=100,
                                 class_limit=0, uses=26)
        output = run()
        self.assertIn('NOBODY is a member', output)
        self.assertIn('never taken effect', output)

    def test_a_promo_that_beats_the_package_is_counted_as_working(self):
        promo = PromoCode.objects.create(code='UNLIMITED', discount_percent=100,
                                         class_limit=0, uses=1)
        promo.redeemed_by.add(self._student('capped', self.one_class))
        output = run()
        self.assertIn('gives more than their package to: 1 of 1', output)
        self.assertIn('codes doing real work for someone: 1', output)

    def test_a_promo_that_adds_nothing_is_reported_as_such(self):
        """Redeemed and working, but the student already had unlimited."""
        promo = PromoCode.objects.create(code='REDUNDANT', discount_percent=100,
                                         class_limit=0, uses=1)
        promo.redeemed_by.add(self._student('already-free', self.unlimited))
        output = run()
        self.assertIn('gives more than their package to: 0 of 1', output)
        self.assertIn('No promo code is currently raising', output)

    def test_a_counter_that_disagrees_with_membership_is_flagged(self):
        promo = PromoCode.objects.create(code='DRIFTED', discount_percent=100,
                                         class_limit=0, uses=9)
        promo.redeemed_by.add(self._student('one-member', self.one_class))
        self.assertIn('counter and membership disagree', run())

    def test_students_flag_names_each_redeemer(self):
        promo = PromoCode.objects.create(code='NAMED', discount_percent=100,
                                         class_limit=0, uses=1)
        promo.redeemed_by.add(self._student('visible-kid', self.one_class))
        output = run('--students')
        self.assertIn('visible-kid', output)
        self.assertIn('unlimited', output)

    def test_it_can_be_narrowed_to_one_code(self):
        PromoCode.objects.create(code='WANTED', discount_percent=100,
                                 class_limit=0)
        PromoCode.objects.create(code='OTHER', discount_percent=100,
                                 class_limit=0)
        output = run('--code', 'wanted')
        self.assertIn('WANTED', output)
        self.assertNotIn('OTHER', output)

    def test_it_writes_nothing(self):
        promo = PromoCode.objects.create(code='READONLY', discount_percent=100,
                                         class_limit=0, uses=4)
        promo.redeemed_by.add(self._student('untouched', self.one_class))
        run('--students')
        promo.refresh_from_db()
        self.assertEqual(promo.uses, 4)
        self.assertEqual(promo.redeemed_by.count(), 1)

    def test_an_inactive_code_is_still_reported(self):
        """A deactivated code stops applying — that alone can look like
        'it never worked', so it must be visible rather than filtered out."""
        PromoCode.objects.create(code='SWITCHEDOFF', discount_percent=100,
                                 class_limit=0, uses=3, is_active=False)
        self.assertIn('INACTIVE', run())
