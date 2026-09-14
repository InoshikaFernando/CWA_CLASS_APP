"""Addressing a promotion to the people it is for, and writing it once.

Two features on the compose page, both aimed at the same failure: sending the
right message to the wrong list, or the wrong message to the right list.

**The unsubscribed recipient groups.** Picking families out by hand does not
scale past a class or two, and the alternative that does scale — "All Students"
— mails an offer to start paying to the families who are already paying. That
is not a cosmetic mistake: it is the kind of email that gets a school a phone
call. So the list is resolved from the same definition of "subscribed" the rest
of the app uses, and it has to include the students who never subscribed at all
(see ``billing/tests_unsubscribed_selector.py`` for why that is the easy miss).

**The pre-written messages.** They carry placeholders the sender must replace —
``[[CODE]]``, ``[[PRICE]]``, ``[[LINK]]`` — and the one thing that must never
happen is two hundred families being told to enter the code ``[[CODE]]``. The
compose page refuses to send while one remains; these pin the pieces that
decision is built on.
"""
import json

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import Package, Subscription
from classroom.message_templates import (
    MESSAGE_TEMPLATES, SENDER_PLACEHOLDER_PATTERN, templates_for,
)
from classroom.models import ParentStudent, School, SchoolStudent


def _role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()})
    return role


def _user(username, role_name=None):
    user = CustomUser.objects.create_user(
        username=username, password='Testpass1!',
        email=f'{username}@test.local')
    if role_name:
        UserRole.objects.get_or_create(user=user, role=_role(role_name))
    return user


class UnsubscribedRecipientGroups(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.package = Package.objects.create(
            name='Wizard', price=19.90, stripe_price_id='price_group_test')
        cls.admin = _user('group_admin', Role.ADMIN)
        cls.school = School.objects.create(
            name='Group School', slug='group-school', admin=cls.admin)
        cls.other_school = School.objects.create(
            name='Other School', slug='other-school',
            admin=_user('other_admin', Role.ADMIN))

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse('messaging_recipient_group')

    def _student(self, username, status=None, school=None):
        user = _user(username, Role.STUDENT)
        SchoolStudent.objects.create(
            school=school or self.school, student=user, is_active=True)
        if status is not None:
            Subscription.objects.create(
                user=user, package=self.package, status=status)
        return user

    def _parent_of(self, student, username, school=None):
        parent = _user(username, Role.PARENT)
        ParentStudent.objects.create(
            parent=parent, student=student,
            school=school or self.school, is_active=True)
        return parent

    def _emails(self, role):
        response = self.client.get(self.url, {'role': role})
        self.assertEqual(response.status_code, 200)
        return {r['email'] for r in response.json()['results']}

    # -- the students -------------------------------------------------------

    def test_it_returns_the_students_who_are_not_paying(self):
        self._student('grp_expired', Subscription.STATUS_EXPIRED)
        self._student('grp_never')
        self._student('grp_paying', Subscription.STATUS_ACTIVE)

        self.assertEqual(
            self._emails('student_unsubscribed'),
            {'grp_expired@test.local', 'grp_never@test.local'})

    def test_a_paying_family_is_never_offered_a_subscription(self):
        """The mistake that makes a school stop using the feature."""
        self._student('grp_paying', Subscription.STATUS_ACTIVE)
        self._student('grp_trialing', Subscription.STATUS_TRIALING)

        self.assertEqual(self._emails('student_unsubscribed'), set())

    def test_a_student_who_never_subscribed_is_included(self):
        self._student('grp_never')
        self.assertEqual(self._emails('student_unsubscribed'),
                         {'grp_never@test.local'})

    def test_another_school_is_never_reachable(self):
        self._student('grp_theirs', school=self.other_school)
        self._student('grp_ours')

        self.assertEqual(self._emails('student_unsubscribed'),
                         {'grp_ours@test.local'})

    def test_a_student_with_no_email_is_skipped_rather_than_failing(self):
        student = self._student('grp_noemail')
        CustomUser.objects.filter(pk=student.pk).update(email='')

        self.assertEqual(self._emails('student_unsubscribed'), set())

    def test_an_inactive_enrolment_is_not_reachable(self):
        student = self._student('grp_left')
        SchoolStudent.objects.filter(student=student).update(is_active=False)

        self.assertEqual(self._emails('student_unsubscribed'), set())

    # -- their parents ------------------------------------------------------

    def test_it_returns_the_parents_of_exactly_those_students(self):
        """The parent is the one who can actually pay."""
        unpaid = self._student('grp_kid_unpaid')
        paid = self._student('grp_kid_paid', Subscription.STATUS_ACTIVE)
        self._parent_of(unpaid, 'grp_mum')
        self._parent_of(paid, 'grp_paying_dad')

        self.assertEqual(self._emails('parent_unsubscribed'),
                         {'grp_mum@test.local'})

    def test_a_parent_with_two_unsubscribed_children_appears_once(self):
        """Two copies of the same offer reads as a mistake."""
        one = self._student('grp_twin_a')
        two = self._student('grp_twin_b')
        parent = _user('grp_twin_parent', Role.PARENT)
        for child in (one, two):
            ParentStudent.objects.create(
                parent=parent, student=child, school=self.school,
                is_active=True)

        results = self.client.get(
            self.url, {'role': 'parent_unsubscribed'}).json()['results']
        self.assertEqual(
            [r['email'] for r in results], ['grp_twin_parent@test.local'])

    def test_a_parent_of_one_paying_and_one_unpaid_child_is_included(self):
        """They still have a child to subscribe."""
        unpaid = self._student('grp_mixed_unpaid')
        paid = self._student('grp_mixed_paid', Subscription.STATUS_ACTIVE)
        parent = _user('grp_mixed_parent', Role.PARENT)
        for child in (unpaid, paid):
            ParentStudent.objects.create(
                parent=parent, student=child, school=self.school,
                is_active=True)

        self.assertEqual(self._emails('parent_unsubscribed'),
                         {'grp_mixed_parent@test.local'})

    # -- the chips still work, and access is unchanged ----------------------

    def test_the_original_groups_are_untouched(self):
        self._student('grp_all_a', Subscription.STATUS_ACTIVE)
        self._student('grp_all_b')

        self.assertEqual(
            self._emails('student'),
            {'grp_all_a@test.local', 'grp_all_b@test.local'})

    def test_an_unknown_group_is_refused_and_names_the_valid_ones(self):
        response = self.client.get(self.url, {'role': 'everybody'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('student_unsubscribed', response.json()['error'])

    def test_a_teacher_cannot_pull_the_school_mailing_list(self):
        teacher = _user('grp_teacher', Role.TEACHER)
        client = Client()
        client.force_login(teacher)

        response = client.get(self.url, {'role': 'student_unsubscribed'})
        self.assertEqual(response.status_code, 403)

    def test_an_anonymous_caller_gets_json_not_a_redirect(self):
        response = Client().get(self.url, {'role': 'student_unsubscribed'})
        self.assertEqual(response.status_code, 401)


class PreWrittenMessages(TestCase):
    """The copy itself, and the placeholders that keep it from being sent raw."""

    def test_every_template_has_what_the_page_needs_to_render_it(self):
        for template in MESSAGE_TEMPLATES:
            with self.subTest(template=template.get('key')):
                for field in ('key', 'name', 'description', 'subject',
                              'body_html'):
                    self.assertTrue(template.get(field),
                                    f'{field} is missing or empty')

    def test_the_keys_are_unique(self):
        keys = [t['key'] for t in MESSAGE_TEMPLATES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_school_name_is_filled_in_and_never_reaches_a_recipient(self):
        school = School.objects.create(
            name='St Jude & Co', slug='st-jude',
            admin=_user('tpl_admin', Role.ADMIN))

        for template in templates_for(school):
            with self.subTest(template=template['key']):
                self.assertNotIn('{{school_name}}', template['subject'])
                self.assertNotIn('{{school_name}}', template['body_html'])

    def test_a_school_name_with_an_ampersand_is_escaped_once(self):
        """It is pasted into innerHTML, so it has to arrive already safe."""
        school = School.objects.create(
            name='St Jude & Co', slug='st-jude-amp',
            admin=_user('tpl_admin2', Role.ADMIN))

        body = next(t for t in templates_for(school)
                    if t['key'] == 'free_trial_invite')['body_html']
        self.assertIn('St Jude &amp; Co', body)
        self.assertNotIn('St Jude & Co', body)

    def test_with_no_school_it_still_produces_readable_copy(self):
        for template in templates_for(None):
            with self.subTest(template=template['key']):
                self.assertNotIn('{{', template['subject'])
                self.assertNotIn('{{', template['body_html'])

    def test_the_sender_placeholders_survive_substitution(self):
        """They are the sender's job, so nothing may quietly fill them in."""
        import re

        school = School.objects.create(
            name='Placeholder School', slug='placeholder-school',
            admin=_user('tpl_admin3', Role.ADMIN))
        pattern = re.compile(SENDER_PLACEHOLDER_PATTERN)

        for template in templates_for(school):
            with self.subTest(template=template['key']):
                blob = template['subject'] + template['body_html']
                self.assertTrue(
                    pattern.search(blob),
                    'a template with nothing for the sender to fill in would '
                    'send itself unread')

    def test_the_pattern_matches_the_placeholders_actually_used(self):
        """A pattern that matched nothing would disable the Send guard
        silently — the button would simply never object."""
        import re

        pattern = re.compile(SENDER_PLACEHOLDER_PATTERN)
        for marker in ('[[CODE]]', '[[PRICE]]', '[[LINK]]', '[[DATE]]'):
            self.assertTrue(pattern.fullmatch(marker), marker)

    def test_the_pattern_does_not_match_ordinary_prose(self):
        import re

        pattern = re.compile(SENDER_PLACEHOLDER_PATTERN)
        for text in ('a [link] here', 'costs $19.90', 'see [[lowercase]]',
                     '{{school_name}}'):
            self.assertIsNone(pattern.search(text), text)


class ComposePageOffersTheTools(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user('compose_admin', Role.ADMIN)
        cls.school = School.objects.create(
            name='Compose School', slug='compose-school', admin=cls.admin)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_the_templates_reach_the_page_as_usable_json(self):
        response = self.client.get(reverse('messaging_compose'))
        self.assertEqual(response.status_code, 200)

        payload = json.loads(response.context['message_templates_json'])
        self.assertEqual(len(payload), len(MESSAGE_TEMPLATES))
        self.assertIn('Compose School', payload[0]['body_html'])

    def test_the_placeholder_pattern_reaches_the_page(self):
        response = self.client.get(reverse('messaging_compose'))
        self.assertEqual(response.context['placeholder_pattern'],
                         SENDER_PLACEHOLDER_PATTERN)

    def test_the_unsubscribed_chips_are_rendered(self):
        response = self.client.get(reverse('messaging_compose'))
        self.assertContains(response, 'student_unsubscribed')
        self.assertContains(response, 'parent_unsubscribed')
