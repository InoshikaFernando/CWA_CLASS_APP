"""Shipping unfinished code safely: the flag has to be off by default and off when unsure.

The whole value is that merging stops being a decision. Code lands on master
while it is still settling, and something other than the branch decides when a
customer sees it. That only holds if every uncertain answer is "off" — an
unknown slug, a missing table, a pilot with nobody in it. A flag that fails
open is worse than no flag, because it ships unfinished work believing it is
protected.

The environment axis is the half with no code behind it: test and production
have separate databases, so a row on one says nothing about the other. What is
tested here is that nothing *else* leaks across — no env var that has to match,
no default that reads "on".
"""
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template import Context, Template
from django.test import TestCase, override_settings

from accounts.models import CustomUser
from classroom.models import School
from ops import flags
from ops.models import FeatureFlag


def _school(name):
    admin = CustomUser.objects.create_user(f'{name}-admin', f'{name}@t.test', 'pw1!')
    return School.objects.create(name=name, slug=name.lower(), admin=admin)


class FeatureFlagResolutionTests(TestCase):

    def setUp(self):
        cache.clear()
        self.cwa = _school('CWA')
        self.other = _school('Other')
        flags._warned_unknown.clear()

    def tearDown(self):
        cache.clear()

    # -- the default ------------------------------------------------------

    def test_an_unknown_flag_is_off(self):
        """A typo, or a migration that has not run. Failing open here would
        ship unfinished code to every customer believing it was gated."""
        self.assertFalse(flags.feature_enabled('never_created', self.cwa))

    def test_a_new_flag_is_off_for_everyone(self):
        FeatureFlag.objects.create(slug='language')
        self.assertFalse(flags.feature_enabled('language', self.cwa))
        self.assertFalse(flags.feature_enabled('language', self.other))

    # -- the three states -------------------------------------------------

    def test_off_is_off_even_for_a_listed_school(self):
        """Off outranks the pilot list, so switching off is one field rather
        than remembering to empty the list too."""
        flag = FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.OFF)
        flag.schools.add(self.cwa)
        self.assertFalse(flags.feature_enabled('language', self.cwa))

    def test_pilot_is_on_for_a_listed_school_only(self):
        flag = FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.PILOT)
        flag.schools.add(self.cwa)
        self.assertTrue(flags.feature_enabled('language', self.cwa))
        self.assertFalse(flags.feature_enabled('language', self.other))

    def test_pilot_with_no_schools_is_on_for_nobody(self):
        FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.PILOT)
        self.assertFalse(flags.feature_enabled('language', self.cwa))

    def test_pilot_with_no_school_given_is_off(self):
        """A background job or console script has no school. A piloted feature
        running unattended across every tenant is what the pilot avoids."""
        flag = FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.PILOT)
        flag.schools.add(self.cwa)
        self.assertFalse(flags.feature_enabled('language'))

    def test_on_is_on_for_everyone_including_no_school(self):
        FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.ON)
        self.assertTrue(flags.feature_enabled('language', self.cwa))
        self.assertTrue(flags.feature_enabled('language', self.other))
        self.assertTrue(flags.feature_enabled('language'))

    def test_a_school_id_works_as_well_as_an_instance(self):
        flag = FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.PILOT)
        flag.schools.add(self.cwa)
        self.assertTrue(flags.feature_enabled('language', self.cwa.pk))

    # -- the emergency brake ---------------------------------------------

    @override_settings(FEATURE_FLAGS_OFF='language')
    def test_the_env_var_beats_the_database(self):
        """For when production needs it dark now and a DB round trip is not
        the path you want to be on."""
        FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.ON)
        self.assertFalse(flags.feature_enabled('language', self.cwa))

    @override_settings(FEATURE_FLAGS_OFF='language, other_thing')
    def test_the_env_var_takes_a_list_and_tolerates_spaces(self):
        FeatureFlag.objects.create(slug='other_thing', rollout=FeatureFlag.ON)
        self.assertFalse(flags.feature_enabled('other_thing', self.cwa))

    @override_settings(FEATURE_FLAGS_OFF='something_else')
    def test_the_env_var_only_touches_what_it_names(self):
        FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.ON)
        self.assertTrue(flags.feature_enabled('language', self.cwa))

    # -- caching ----------------------------------------------------------

    def test_repeated_checks_do_not_re_query(self):
        FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.ON)
        flags.feature_enabled('language', self.cwa)          # warms it
        with self.assertNumQueries(0):
            for _ in range(5):
                flags.feature_enabled('language', self.cwa)

    def test_invalidate_makes_a_change_visible(self):
        flag = FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.OFF)
        self.assertFalse(flags.feature_enabled('language', self.cwa))
        flag.rollout = FeatureFlag.ON
        flag.save()
        flags.invalidate()
        self.assertTrue(flags.feature_enabled('language', self.cwa))

    def test_an_unreadable_table_reads_as_off_rather_than_raising(self):
        """Checks run on half-deployed boxes and inside data migrations. The
        answer there is "no", never a 500."""
        with self.settings():
            from unittest.mock import patch
            with patch('ops.models.FeatureFlag.objects') as objects:
                objects.prefetch_related.side_effect = Exception('no such table')
                self.assertEqual(flags.all_flags(use_cache=False), {})
        self.assertFalse(flags.feature_enabled('language', self.cwa, use_cache=False))


class FeatureFlagTemplateTagTests(TestCase):

    def setUp(self):
        cache.clear()
        self.cwa = _school('CWA')

    def tearDown(self):
        cache.clear()

    def _render(self, school):
        t = Template(
            "{% load feature_tags %}"
            "{% feature_enabled 'language' school as on %}"
            "{% if on %}YES{% else %}NO{% endif %}"
        )
        return t.render(Context({'school': school})).strip()

    def test_the_tag_follows_the_flag(self):
        flag = FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.PILOT)
        flag.schools.add(self.cwa)
        self.assertEqual(self._render(self.cwa), 'YES')

    def test_the_tag_is_off_for_a_school_not_in_the_pilot(self):
        other = _school('Other')
        flag = FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.PILOT)
        flag.schools.add(self.cwa)
        self.assertEqual(self._render(other), 'NO')


class FeatureFlagCommandTests(TestCase):

    def setUp(self):
        cache.clear()
        self.cwa = _school('CWA')

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command('feature_flag', *args, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def test_listing_an_empty_environment_says_so(self):
        self.assertIn('No feature flags', self._run())

    def test_showing_an_unknown_flag_explains_it_reads_as_off(self):
        with self.assertRaises(CommandError):
            self._run('language')

    def test_a_flag_is_created_off_on_first_write(self):
        self._run('language', '--off')
        self.assertEqual(FeatureFlag.objects.get(slug='language').rollout,
                         FeatureFlag.OFF)

    def test_pilot_with_a_school_sets_both(self):
        self._run('language', '--pilot', '--school', str(self.cwa.pk))
        flag = FeatureFlag.objects.get(slug='language')
        self.assertEqual(flag.rollout, FeatureFlag.PILOT)
        self.assertEqual(list(flag.schools.all()), [self.cwa])

    def test_pilot_with_no_schools_warns_that_it_is_on_for_nobody(self):
        out = self._run('language', '--pilot')
        self.assertIn('on for nobody', out)

    def test_an_unknown_school_id_is_an_error_not_a_silent_skip(self):
        with self.assertRaises(CommandError):
            self._run('language', '--pilot', '--school', '99999')

    def test_the_cache_is_dropped_so_the_change_takes_effect(self):
        FeatureFlag.objects.create(slug='language', rollout=FeatureFlag.OFF)
        self.assertFalse(flags.feature_enabled('language', self.cwa))
        self._run('language', '--on')
        self.assertTrue(flags.feature_enabled('language', self.cwa))
