"""
Unit tests for classroom/views_messaging.py (CPP-349 – CPP-352).

CPP-349: URL resolution, access control, redirect behaviour.
CPP-350: RecipientSearchAPIView — scoping, search, role labels, email filter.
CPP-351: Compose page — subject, body, attachments, toolbar.
CPP-352: Schedule picker UI + POST handler + ScheduledMessage model.
"""
import json

from django.test import TestCase, Client
from django.urls import reverse, resolve

from accounts.models import CustomUser, Role, UserRole
from classroom.models import ParentStudent, ScheduledMessage, School, SchoolStudent, SchoolTeacher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return role


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)


def _make_user(username, email, role_name=None, password='Testpass1!'):
    user = CustomUser.objects.create_user(
        username=username, password=password, email=email,
    )
    if role_name:
        _assign_role(user, role_name)
    return user


def _make_admin_with_school():
    user = _make_user('admin_msg', 'wlhtestmails+admin_msg@gmail.com', Role.ADMIN)
    school = School.objects.create(name='Msg Test School', slug='msg-test-school', admin=user)
    return user, school


def _make_admin_school_student(school, email, first='Student', last='One'):
    """Create a student user and link them to the school."""
    uname = email.split('@')[0].replace('+', '_').replace('.', '_')
    user = _make_user(uname, email, Role.STUDENT)
    user.first_name = first
    user.last_name = last
    user.save()
    SchoolStudent.objects.create(school=school, student=user, is_active=True)
    return user


def _make_admin_school_teacher(school, email, first='Teacher', last='One', role='teacher'):
    uname = email.split('@')[0].replace('+', '_').replace('.', '_')
    user = _make_user(uname, email, Role.TEACHER)
    user.first_name = first
    user.last_name = last
    user.save()
    SchoolTeacher.objects.create(school=school, teacher=user, role=role, is_active=True)
    return user


def _make_parent_linked_to_student(school, parent_email, student, first='Parent', last='One'):
    uname = parent_email.split('@')[0].replace('+', '_').replace('.', '_')
    user = _make_user(uname, parent_email)
    user.first_name = first
    user.last_name = last
    user.save()
    ParentStudent.objects.create(parent=user, student=student, school=school, is_active=True)
    return user


# ---------------------------------------------------------------------------
# CPP-349: URL resolution
# ---------------------------------------------------------------------------

class TestMessagingURLs(TestCase):
    """URL names resolve to correct paths and views."""

    def test_messaging_dashboard_url_reverses(self):
        self.assertEqual(reverse('messaging_dashboard'), '/admin-dashboard/messaging/')

    def test_messaging_compose_url_reverses(self):
        self.assertEqual(reverse('messaging_compose'), '/admin-dashboard/messaging/compose/')

    def test_messaging_recipient_search_url_reverses(self):
        self.assertEqual(
            reverse('messaging_recipient_search'),
            '/admin-dashboard/messaging/api/recipients/',
        )

    def test_messaging_dashboard_resolves_to_view(self):
        self.assertEqual(resolve('/admin-dashboard/messaging/').url_name, 'messaging_dashboard')

    def test_messaging_compose_resolves_to_view(self):
        self.assertEqual(resolve('/admin-dashboard/messaging/compose/').url_name, 'messaging_compose')

    def test_messaging_recipient_search_resolves_to_view(self):
        self.assertEqual(
            resolve('/admin-dashboard/messaging/api/recipients/').url_name,
            'messaging_recipient_search',
        )


# ---------------------------------------------------------------------------
# CPP-349: MessagingDashboardView
# ---------------------------------------------------------------------------

class TestMessagingDashboardView(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('messaging_dashboard')

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])

    def test_admin_role_redirects_to_compose(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('messaging_compose'), fetch_redirect_response=False)

    def test_institute_owner_redirects_to_compose(self):
        user = _make_user('owner_msg', 'wlhtestmails+owner_msg@gmail.com', Role.INSTITUTE_OWNER)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('messaging_compose'), fetch_redirect_response=False)

    def test_head_of_institute_redirects_to_compose(self):
        user = _make_user('hoi_msg', 'wlhtestmails+hoi_msg@gmail.com', Role.HEAD_OF_INSTITUTE)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('messaging_compose'), fetch_redirect_response=False)

    def test_student_role_denied(self):
        user = _make_user('student_msg', 'wlhtestmails+student_msg@gmail.com', Role.STUDENT)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('/messaging', response['Location'])

    def test_teacher_role_denied(self):
        user = _make_user('teacher_msg', 'wlhtestmails+teacher_msg@gmail.com', Role.TEACHER)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('/messaging', response['Location'])

    def test_superuser_redirects_to_compose(self):
        user = CustomUser.objects.create_superuser(
            username='super_msg', password='Testpass1!', email='wlhtestmails+super_msg@gmail.com',
        )
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('messaging_compose'), fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# CPP-349: MessagingComposeView
# ---------------------------------------------------------------------------

class TestMessagingComposeView(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('messaging_compose')

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])

    def test_admin_role_returns_200(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_institute_owner_returns_200(self):
        user = _make_user('owner2_msg', 'wlhtestmails+owner2_msg@gmail.com', Role.INSTITUTE_OWNER)
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_head_of_institute_returns_200(self):
        user = _make_user('hoi2_msg', 'wlhtestmails+hoi2_msg@gmail.com', Role.HEAD_OF_INSTITUTE)
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_student_role_denied(self):
        user = _make_user('student2_msg', 'wlhtestmails+student2_msg@gmail.com', Role.STUDENT)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('/messaging', response['Location'])

    def test_teacher_role_denied(self):
        user = _make_user('teacher2_msg', 'wlhtestmails+teacher2_msg@gmail.com', Role.TEACHER)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('/messaging', response['Location'])

    def test_uses_correct_template(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertTemplateUsed(self.client.get(self.url), 'messaging/compose.html')

    def test_extends_base_template(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertTemplateUsed(self.client.get(self.url), 'base.html')

    def test_school_in_context_when_admin_has_school(self):
        user, school = _make_admin_with_school()
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).context['school'], school)

    def test_school_none_in_context_when_no_school(self):
        user = _make_user('noschl_msg', 'wlhtestmails+noschl_msg@gmail.com', Role.ADMIN)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['school'])

    def test_page_title_contains_messaging(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'Messaging')

    def test_page_contains_new_message_heading(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'New Message')

    def test_page_shows_email_channel_option(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'Email')

    def test_page_shows_sms_disabled(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'SMS')

    def test_post_unauthenticated_redirects_to_login(self):
        """POST without login should redirect to login (not 405)."""
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])

    def test_page_shows_to_field(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), '/admin-dashboard/messaging/api/recipients/')

    def test_page_has_cc_bcc_toggle(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertContains(response, '+ CC')
        self.assertContains(response, '+ BCC')

    # -- CPP-351: Subject + body + attachments --------------------------------

    def test_page_has_subject_input(self):
        """Compose page renders a subject input field."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'name="subject"')

    def test_page_subject_has_maxlength_255(self):
        """Subject input enforces 255-char limit."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'maxlength="255"')

    def test_page_has_body_editor(self):
        """Compose page renders a contenteditable body editor."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'contenteditable="true"')

    def test_page_has_body_hidden_input(self):
        """Body HTML is synced to a hidden form input named 'body'."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'name="body"')

    def test_page_has_attachment_file_input(self):
        """Compose page renders a file input for attachments."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'type="file"')

    def test_page_has_attach_accept_types(self):
        """File input accepts PDF, DOCX, PNG, JPG."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertContains(response, '.pdf')
        self.assertContains(response, '.docx')

    def test_page_has_csrf_token(self):
        """Form includes CSRF token."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'csrfmiddlewaretoken')

    def test_page_has_save_draft_button(self):
        """Compose page has a Save Draft submit button."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'Save Draft')

    def test_page_has_send_button(self):
        """Compose page has a submit button with action value 'send'."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'value="send"')

    def test_page_has_body_toolbar(self):
        """Compose page renders formatting toolbar with Bold, Link buttons."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertContains(response, "execFormat('bold')")
        self.assertContains(response, 'insertLink()')

    def test_page_form_has_post_action(self):
        """Form targets the compose URL via POST."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertContains(response, 'method="post"')

    # -- CPP-352: Schedule picker UI ------------------------------------------

    def test_page_shows_schedule_section(self):
        """Compose page renders a Schedule section."""
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'Schedule')

    def test_page_shows_send_now_option(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'Send Now')

    def test_page_shows_one_time_option(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'One Time')

    def test_page_shows_weekly_option(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'Weekly')

    def test_page_shows_monthly_option(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'Monthly')

    def test_page_has_frequency_hidden_input(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'name="frequency"')

    def test_page_has_schedule_date_hidden_input(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'name="schedule_date"')

    def test_page_has_schedule_time_input(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        self.assertContains(self.client.get(self.url), 'name="schedule_time"')


# ---------------------------------------------------------------------------
# CPP-352: ScheduledMessage model
# ---------------------------------------------------------------------------

class TestScheduledMessage(TestCase):

    def setUp(self):
        self.user, self.school = _make_admin_with_school()

    def test_create_with_defaults(self):
        msg = ScheduledMessage.objects.create(
            school=self.school,
            created_by=self.user,
            subject='Hello',
        )
        self.assertEqual(msg.status, ScheduledMessage.STATUS_DRAFT)
        self.assertEqual(msg.frequency, ScheduledMessage.FREQUENCY_NOW)
        self.assertEqual(msg.channel, 'email')

    def test_str_representation(self):
        msg = ScheduledMessage.objects.create(
            school=self.school,
            created_by=self.user,
            subject='Test Subject',
            frequency='once',
            status='scheduled',
        )
        self.assertIn('Test Subject', str(msg))

    def test_recipients_stored_as_json(self):
        tags = [{'id': 1, 'name': 'Alice', 'email': 'alice@example.com', 'role': 'staff'}]
        msg = ScheduledMessage.objects.create(
            school=self.school, created_by=self.user, subject='x',
            recipients_to=tags,
        )
        msg.refresh_from_db()
        self.assertEqual(msg.recipients_to[0]['email'], 'alice@example.com')

    def test_scheduled_at_stored(self):
        from django.utils import timezone as tz
        at = tz.now()
        msg = ScheduledMessage.objects.create(
            school=self.school, created_by=self.user, subject='x',
            frequency='once', scheduled_at=at, status='scheduled',
        )
        msg.refresh_from_db()
        self.assertAlmostEqual(msg.scheduled_at.timestamp(), at.timestamp(), delta=1)

    def test_weekly_send_day_stored(self):
        msg = ScheduledMessage.objects.create(
            school=self.school, created_by=self.user, subject='x',
            frequency='weekly', send_day=1,
        )
        msg.refresh_from_db()
        self.assertEqual(msg.send_day, 1)

    def test_monthly_send_day_stored(self):
        msg = ScheduledMessage.objects.create(
            school=self.school, created_by=self.user, subject='x',
            frequency='monthly', send_day=15,
        )
        msg.refresh_from_db()
        self.assertEqual(msg.send_day, 15)


# ---------------------------------------------------------------------------
# CPP-352: MessagingComposeView POST
# ---------------------------------------------------------------------------

def _post_data(**kwargs):
    """Return a minimal valid POST payload, overridable via kwargs."""
    data = {
        'action': 'send',
        'subject': 'Test Subject',
        'body': '<p>Hello</p>',
        'recipients_to': json.dumps([{'id': 1, 'name': 'Alice', 'email': 'alice@example.com', 'role': 'staff'}]),
        'recipients_cc': '[]',
        'recipients_bcc': '[]',
        'frequency': 'now',
        'schedule_date': '',
        'schedule_time': '09:00',
        'weekly_day': '1',
        'monthly_day': '1',
        'starts_at': '',
        'ends_at': '',
    }
    data.update(kwargs)
    return data


class TestMessagingComposeViewPost(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('messaging_compose')
        self.user, self.school = _make_admin_with_school()

    def test_post_send_now_creates_scheduled_message(self):
        self.client.force_login(self.user)
        self.client.post(self.url, _post_data(frequency='now'))
        msg = ScheduledMessage.objects.filter(school=self.school).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.frequency, 'now')
        self.assertEqual(msg.status, ScheduledMessage.STATUS_SCHEDULED)
        self.assertIsNone(msg.send_time)

    def test_post_draft_creates_draft_message(self):
        self.client.force_login(self.user)
        self.client.post(self.url, _post_data(action='draft'))
        msg = ScheduledMessage.objects.filter(school=self.school).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.status, ScheduledMessage.STATUS_DRAFT)

    def test_post_once_stores_scheduled_at(self):
        from django.utils import timezone as tz
        self.client.force_login(self.user)
        self.client.post(self.url, _post_data(
            frequency='once', schedule_date='2030-12-25', schedule_time='10:00',
        ))
        msg = ScheduledMessage.objects.filter(school=self.school).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.frequency, 'once')
        self.assertIsNotNone(msg.scheduled_at)
        # Compare in local timezone so the test passes regardless of UTC offset.
        local_dt = tz.localtime(msg.scheduled_at)
        self.assertEqual(local_dt.date().isoformat(), '2030-12-25')
        self.assertEqual(local_dt.hour, 10)

    def test_post_weekly_stores_send_day(self):
        self.client.force_login(self.user)
        self.client.post(self.url, _post_data(
            frequency='weekly', weekly_day='3', schedule_time='08:00',
            starts_at='2030-01-06',
        ))
        msg = ScheduledMessage.objects.filter(school=self.school).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.frequency, 'weekly')
        self.assertEqual(msg.send_day, 3)

    def test_post_monthly_stores_send_day(self):
        self.client.force_login(self.user)
        self.client.post(self.url, _post_data(
            frequency='monthly', monthly_day='15', schedule_time='07:00',
            starts_at='2030-01-15',
        ))
        msg = ScheduledMessage.objects.filter(school=self.school).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.frequency, 'monthly')
        self.assertEqual(msg.send_day, 15)

    def test_post_stores_recipients_to(self):
        self.client.force_login(self.user)
        tags = [{'id': 5, 'name': 'Bob', 'email': 'bob@example.com', 'role': 'student'}]
        self.client.post(self.url, _post_data(recipients_to=json.dumps(tags)))
        msg = ScheduledMessage.objects.filter(school=self.school).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.recipients_to[0]['email'], 'bob@example.com')

    def test_post_stores_subject_and_body(self):
        self.client.force_login(self.user)
        self.client.post(self.url, _post_data(subject='Hello World', body='<p>Body</p>'))
        msg = ScheduledMessage.objects.filter(school=self.school).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.subject, 'Hello World')
        self.assertEqual(msg.body_html, '<p>Body</p>')

    def test_post_redirects_on_success(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, _post_data())
        self.assertRedirects(response, self.url, fetch_redirect_response=False)

    def test_post_invalid_frequency_defaults_to_now(self):
        self.client.force_login(self.user)
        self.client.post(self.url, _post_data(frequency='bogus'))
        msg = ScheduledMessage.objects.filter(school=self.school).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.frequency, 'now')

    def test_post_no_school_redirects_without_creating_record(self):
        user = _make_user('noschl_post', 'wlhtestmails+noschl_post@gmail.com', Role.ADMIN)
        self.client.force_login(user)
        self.client.post(self.url, _post_data())
        self.assertEqual(ScheduledMessage.objects.filter(created_by=user).count(), 0)


# ---------------------------------------------------------------------------
# CPP-350: RecipientSearchAPIView
# ---------------------------------------------------------------------------

class TestRecipientSearchAPIView(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('messaging_recipient_search')
        self.admin, self.school = _make_admin_with_school()

    # -- Access control --

    def test_unauthenticated_returns_401_json(self):
        response = self.client.get(self.url, {'q': 'test'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_student_role_denied(self):
        user = _make_user('api_student', 'wlhtestmails+api_student@gmail.com', Role.STUDENT)
        self.client.force_login(user)
        response = self.client.get(self.url, {'q': 'test'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_teacher_role_denied(self):
        user = _make_user('api_teacher', 'wlhtestmails+api_teacher@gmail.com', Role.TEACHER)
        self.client.force_login(user)
        response = self.client.get(self.url, {'q': 'test'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_admin_role_returns_200(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url, {'q': 'te'})
        self.assertEqual(response.status_code, 200)

    def test_hoi_role_returns_200(self):
        user = _make_user('hoi_api', 'wlhtestmails+hoi_api@gmail.com', Role.HEAD_OF_INSTITUTE)
        self.client.force_login(user)
        response = self.client.get(self.url, {'q': 'te'})
        self.assertEqual(response.status_code, 200)

    # -- Query length --

    def test_returns_empty_for_q_length_0(self):
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': ''}).content)
        self.assertEqual(data['results'], [])

    def test_returns_empty_for_q_length_1(self):
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'a'}).content)
        self.assertEqual(data['results'], [])

    def test_returns_results_for_q_length_2(self):
        _make_admin_school_student(self.school, 'wlhtestmails+stu350a@gmail.com', 'Alice', 'Anders')
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Al'}).content)
        self.assertGreaterEqual(len(data['results']), 1)

    # -- No school --

    def test_returns_empty_when_admin_has_no_school(self):
        user = _make_user('noschl_api', 'wlhtestmails+noschl_api@gmail.com', Role.ADMIN)
        self.client.force_login(user)
        data = json.loads(self.client.get(self.url, {'q': 'test'}).content)
        self.assertEqual(data['results'], [])

    # -- Search matching --

    def test_matches_student_by_first_name(self):
        _make_admin_school_student(self.school, 'wlhtestmails+stu350b@gmail.com', 'Roberto', 'Morales')
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Rober'}).content)
        emails = [r['email'] for r in data['results']]
        self.assertIn('wlhtestmails+stu350b@gmail.com', emails)

    def test_matches_student_by_last_name(self):
        _make_admin_school_student(self.school, 'wlhtestmails+stu350c@gmail.com', 'Carlos', 'Zambrano')
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Zam'}).content)
        emails = [r['email'] for r in data['results']]
        self.assertIn('wlhtestmails+stu350c@gmail.com', emails)

    def test_matches_student_by_email(self):
        _make_admin_school_student(self.school, 'wlhtestmails+stu350d@gmail.com', 'Dana', 'Fox')
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'stu350d'}).content)
        emails = [r['email'] for r in data['results']]
        self.assertIn('wlhtestmails+stu350d@gmail.com', emails)

    def test_matches_teacher_by_name(self):
        _make_admin_school_teacher(self.school, 'wlhtestmails+tch350a@gmail.com', 'Ferdinand', 'Beck')
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Ferdi'}).content)
        emails = [r['email'] for r in data['results']]
        self.assertIn('wlhtestmails+tch350a@gmail.com', emails)

    # -- Role labels --

    def test_student_result_has_role_student(self):
        _make_admin_school_student(self.school, 'wlhtestmails+stu350e@gmail.com', 'Ellen', 'Park')
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Ellen'}).content)
        match = next((r for r in data['results'] if r['email'] == 'wlhtestmails+stu350e@gmail.com'), None)
        self.assertIsNotNone(match)
        self.assertEqual(match['role'], 'student')

    def test_staff_result_has_role_staff(self):
        _make_admin_school_teacher(self.school, 'wlhtestmails+tch350b@gmail.com', 'George', 'Hall')
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'George'}).content)
        match = next((r for r in data['results'] if r['email'] == 'wlhtestmails+tch350b@gmail.com'), None)
        self.assertIsNotNone(match)
        self.assertEqual(match['role'], 'staff')

    def test_parent_result_has_role_parent(self):
        student = _make_admin_school_student(self.school, 'wlhtestmails+stu350f@gmail.com', 'Iris', 'Nolan')
        _make_parent_linked_to_student(self.school, 'wlhtestmails+par350a@gmail.com', student, 'Helen', 'Nolan')
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Helen'}).content)
        match = next((r for r in data['results'] if r['email'] == 'wlhtestmails+par350a@gmail.com'), None)
        self.assertIsNotNone(match)
        self.assertEqual(match['role'], 'parent')

    # -- Result shape --

    def test_result_contains_required_fields(self):
        _make_admin_school_student(self.school, 'wlhtestmails+stu350g@gmail.com', 'Jack', 'Stone')
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Jack'}).content)
        self.assertTrue(len(data['results']) >= 1)
        r = data['results'][0]
        for field in ('id', 'name', 'email', 'role'):
            self.assertIn(field, r, msg=f'Missing field: {field}')

    # -- Email filter --

    def test_users_without_email_excluded(self):
        """Students with no email address must not appear in results."""
        uname = 'no_email_stu'
        user = CustomUser.objects.create_user(username=uname, password='Testpass1!', email=None)
        user.first_name = 'NoEmail'
        user.last_name = 'Person'
        user.save()
        SchoolStudent.objects.create(school=self.school, student=user, is_active=True)
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'NoEmail'}).content)
        emails = [r.get('email') for r in data['results']]
        self.assertNotIn(None, emails)
        self.assertNotIn('', emails)

    # -- School scoping --

    def test_results_scoped_to_own_school(self):
        """A student at a different school must not appear in results."""
        other_admin = _make_user('other_admin', 'wlhtestmails+other_admin@gmail.com', Role.ADMIN)
        other_school = School.objects.create(
            name='Other School', slug='other-school-350', admin=other_admin,
        )
        _make_admin_school_student(other_school, 'wlhtestmails+stu350h@gmail.com', 'OtherSchool', 'Student')
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'OtherSchool'}).content)
        emails = [r['email'] for r in data['results']]
        self.assertNotIn('wlhtestmails+stu350h@gmail.com', emails)

    # -- Limit --

    def test_default_limit_respected(self):
        for i in range(12):
            _make_admin_school_student(
                self.school, f'wlhtestmails+limit_stu{i}@gmail.com', f'Limit{i:02d}', 'User',
            )
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Limit'}).content)
        self.assertLessEqual(len(data['results']), 8)

    def test_custom_limit_respected(self):
        for i in range(6):
            _make_admin_school_student(
                self.school, f'wlhtestmails+climit_stu{i}@gmail.com', f'Climit{i:02d}', 'User',
            )
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Climit', 'limit': '3'}).content)
        self.assertLessEqual(len(data['results']), 3)

    def test_limit_capped_at_max(self):
        for i in range(20):
            _make_admin_school_student(
                self.school, f'wlhtestmails+maxlimit{i}@gmail.com', f'Maxlim{i:02d}', 'User',
            )
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Maxlim', 'limit': '100'}).content)
        self.assertLessEqual(len(data['results']), 15)

    # -- De-duplication --

    def test_no_duplicate_emails_in_results(self):
        """Same email must not appear twice even if user is teacher AND student."""
        student = _make_admin_school_student(self.school, 'wlhtestmails+dual350@gmail.com', 'Dual', 'Role')
        SchoolTeacher.objects.create(school=self.school, teacher=student, role='teacher', is_active=True)
        self.client.force_login(self.admin)
        data = json.loads(self.client.get(self.url, {'q': 'Dual'}).content)
        emails = [r['email'] for r in data['results']]
        self.assertEqual(len(emails), len(set(emails)))
