"""The on-demand question check: filters, running, and fixing what it finds.

The health dashboard reports the nightly snapshot for the whole bank. This page
answers "what is wrong in Year 7 Fractions, right now?" and puts Edit/Delete
next to each finding, so a super-admin never needs a shell to act on it.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question

User = get_user_model()


class QuestionCheckTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='checkadmin', email='check@test.com', password='pass1234')
        cls.student = User.objects.create_user(
            username='checkstudent', email='cs@test.com', password='pass1234')

        cls.maths = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.science = Subject.objects.create(name='Science', slug='science')
        cls.y7 = Level.objects.create(level_number=7, display_name='Year 7')
        cls.y8 = Level.objects.create(level_number=8, display_name='Year 8')
        cls.fractions = Topic.objects.create(
            name='Fractions', slug='fractions', subject=cls.maths)
        cls.algebra = Topic.objects.create(
            name='Algebra', slug='algebra', subject=cls.maths)

    def _question(self, *, level=None, topic=None, text='What is 1/2 + 1/4?',
                  options=(('3/4', True), ('1/4', False)), image=''):
        q = Question.objects.create(
            level=level or self.y7, topic=topic or self.fractions,
            question_text=text, question_type='multiple_choice', image=image,
        )
        for order, (label, correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=label,
                                  is_correct=correct, order=order)
        return q

    def _run(self, **params):
        params.setdefault('run', '1')
        return self.client.get(reverse('question_check_admin_dashboard'), params)


class AccessTests(QuestionCheckTestBase):

    def test_superuser_can_open_the_page(self):
        self.client.login(username='checkadmin', password='pass1234')
        response = self.client.get(reverse('question_check_admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Check Questions')

    def test_non_superuser_is_refused(self):
        self.client.login(username='checkstudent', password='pass1234')
        response = self.client.get(reverse('question_check_admin_dashboard'))
        self.assertNotEqual(response.status_code, 200)

    def test_anonymous_is_refused(self):
        response = self.client.get(reverse('question_check_admin_dashboard'))
        self.assertNotEqual(response.status_code, 200)

    def test_the_health_dashboard_links_here(self):
        # Reachability, not just existence — this whole page shipped once with
        # no route to it from anywhere in the UI.
        self.client.login(username='checkadmin', password='pass1234')
        response = self.client.get(reverse('question_health_admin_dashboard'))
        self.assertContains(response, reverse('question_check_admin_dashboard'))


class FilterTests(QuestionCheckTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def test_the_form_offers_subject_level_and_topic(self):
        response = self.client.get(reverse('question_check_admin_dashboard'))
        self.assertContains(response, 'filter-subject')
        self.assertContains(response, 'filter-level')
        self.assertContains(response, 'filter-topic')
        self.assertContains(response, 'Mathematics')
        self.assertContains(response, 'Year 7')
        self.assertContains(response, 'Fractions')

    def test_level_filter_excludes_other_years(self):
        broken_y7 = self._question(level=self.y7, options=(('a', False), ('b', False)))
        broken_y8 = self._question(level=self.y8, options=(('a', False), ('b', False)))

        response = self._run(level=str(self.y7.id))
        ids = [row['q'].id for row in response.context['rows']]
        self.assertIn(broken_y7.id, ids)
        self.assertNotIn(broken_y8.id, ids)

    def test_topic_filter_excludes_other_topics(self):
        broken_fr = self._question(topic=self.fractions, options=(('a', False), ('b', False)))
        broken_al = self._question(topic=self.algebra, options=(('a', False), ('b', False)))

        response = self._run(topic=str(self.fractions.id))
        ids = [row['q'].id for row in response.context['rows']]
        self.assertIn(broken_fr.id, ids)
        self.assertNotIn(broken_al.id, ids)

    def test_several_levels_can_be_selected_at_once(self):
        a = self._question(level=self.y7, options=(('a', False), ('b', False)))
        b = self._question(level=self.y8, options=(('a', False), ('b', False)))

        response = self._run(level=[str(self.y7.id), str(self.y8.id)])
        ids = [row['q'].id for row in response.context['rows']]
        self.assertCountEqual([a.id, b.id], ids)

    def test_a_junk_filter_value_does_not_500(self):
        self._question(options=(('a', False), ('b', False)))
        response = self._run(level='not-a-number')
        self.assertEqual(response.status_code, 200)


class DetectionTests(QuestionCheckTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def test_a_question_with_no_correct_option_is_reported(self):
        q = self._question(options=(('a', False), ('b', False)))
        response = self._run()
        rows = {row['q'].id: row for row in response.context['rows']}
        self.assertIn(q.id, rows)
        self.assertTrue(any(i['code'] == 'NO-CORRECT' for i in rows[q.id]['issues']))

    def test_a_healthy_question_is_not_reported(self):
        self._question(options=(('3/4', True), ('1/4', False)))
        response = self._run()
        self.assertEqual(response.context['rows'], [])

    def test_advisory_issues_are_hidden_unless_asked_for(self):
        # DUPLICATE-VALUE cannot mismark anyone, so it must not pad the list by
        # default — but it has to be reachable when someone wants it.
        # Two DISTRACTORS that are the same value (0.5 == 1/2), with the correct
        # answer right — so the only finding is the advisory one.
        self._question(options=(('3/4', True), ('0.5', False), ('1/2', False)))

        default = self._run()
        with_advisory = self._run(advisory='1')

        self.assertEqual(default.context['rows'], [])
        self.assertTrue(with_advisory.context['rows'])

    def test_an_image_is_reported_next_to_the_finding(self):
        # A question that reads oddly alone may be fine with its diagram, so the
        # page shows the evidence rather than the reviewer having to go looking.
        q = self._question(options=(('a', False), ('b', False)),
                           image='questions/year7/fractions/pie.png')
        response = self._run()
        row = next(r for r in response.context['rows'] if r['q'].id == q.id)
        self.assertTrue(row['has_image'])

    def test_a_question_without_a_visual_says_so(self):
        q = self._question(options=(('a', False), ('b', False)))
        response = self._run()
        row = next(r for r in response.context['rows'] if r['q'].id == q.id)
        self.assertFalse(row['has_image'])
        self.assertEqual(row['specs'], [])


class CapTests(QuestionCheckTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def test_hitting_the_cap_is_announced_not_hidden(self):
        # A truncated run that looks complete is worse than no run: it reads as
        # "your bank is clean" when most of it was never opened.
        for _ in range(3):
            self._question(options=(('a', False), ('b', False)))

        response = self._run(limit='2')
        self.assertTrue(response.context['truncated'])
        self.assertEqual(response.context['scanned'], 2)
        self.assertContains(response, 'not checked')

    def test_a_complete_run_is_not_flagged_as_truncated(self):
        self._question(options=(('a', False), ('b', False)))
        response = self._run(limit='50')
        self.assertFalse(response.context['truncated'])

    def test_the_cap_cannot_be_raised_past_the_maximum(self):
        response = self._run(limit='999999')
        self.assertLessEqual(response.context['limit'], 5000)

    def test_nothing_runs_until_asked(self):
        self._question(options=(('a', False), ('b', False)))
        response = self.client.get(reverse('question_check_admin_dashboard'))
        self.assertFalse(response.context['ran'])
        self.assertEqual(response.context['scanned'], 0)


class DeleteReturnTests(QuestionCheckTestBase):
    """Deleting from the check page returns you to your filtered list."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def test_delete_returns_to_the_check_page(self):
        q = self._question(options=(('a', False), ('b', False)))
        back = reverse('question_check_admin_dashboard') + '?run=1&level=' + str(self.y7.id)

        response = self.client.post(
            reverse('delete_question', args=[q.id]), {'next': back})

        self.assertRedirects(response, back, fetch_redirect_response=False)
        self.assertFalse(Question.objects.filter(pk=q.id).exists())

    def test_an_offsite_next_is_ignored(self):
        # An unvalidated `next` is an open redirect; the delete must still work
        # but send the user somewhere on this site.
        q = self._question(options=(('a', False), ('b', False)))

        response = self.client.post(
            reverse('delete_question', args=[q.id]),
            {'next': 'https://evil.example.com/phish'})

        self.assertEqual(response.status_code, 302)
        self.assertNotIn('evil.example.com', response['Location'])
        self.assertFalse(Question.objects.filter(pk=q.id).exists())

    def test_delete_without_next_keeps_the_old_destination(self):
        q = self._question(options=(('a', False), ('b', False)))
        response = self.client.post(reverse('delete_question', args=[q.id]))
        self.assertRedirects(
            response,
            reverse('question_list', kwargs={'level_number': self.y7.level_number}),
            fetch_redirect_response=False)


class TopicAndSubtopicTests(QuestionCheckTestBase):
    """Both the strand and the subtopic are shown, as in Global Questions.

    A question's own topic is the SUBTOPIC ("Addition"); its parent is the
    TOPIC ("Number"). Showing only the former left the reader guessing which
    strand a flagged question belonged to.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')
        self.number = Topic.objects.create(
            name='Number', slug='number', subject=self.maths)
        self.addition = Topic.objects.create(
            name='Addition', slug='addition', subject=self.maths,
            parent=self.number)

    def test_a_subtopic_shows_its_parent_too(self):
        self._question(topic=self.addition, options=(('a', False), ('b', False)))
        response = self._run()
        self.assertContains(response, 'Number')
        self.assertContains(response, 'Addition')

    def test_a_top_level_topic_still_renders(self):
        # No parent — must not print an empty "›" crumb.
        self._question(topic=self.number, options=(('a', False), ('b', False)))
        response = self._run()
        self.assertContains(response, 'Number')


class EditLinkTests(QuestionCheckTestBase):
    """Edit sends you to the editor that can actually open the question."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def test_a_global_question_links_to_the_global_questions_modal(self):
        q = self._question(options=(('a', False), ('b', False)))
        response = self._run()
        self.assertContains(
            response, reverse('admin_global_questions') + '?edit=' + str(q.id))

    def test_a_school_question_does_not_link_to_that_modal(self):
        # GlobalQuestionEditView filters school__isnull=True, so pointing a
        # school-scoped question at it would 404 the moment anyone clicked.
        from classroom.models import School

        school = School.objects.create(
            name='Scoped School', slug='scoped-school', admin=self.superuser)
        q = self._question(options=(('a', False), ('b', False)))
        Question.objects.filter(pk=q.pk).update(school=school)

        response = self._run()
        self.assertNotContains(
            response, reverse('admin_global_questions') + '?edit=' + str(q.id))
        self.assertContains(response, reverse('edit_question', args=[q.id]))


class DuplicateSeverityTests(QuestionCheckTestBase):
    """A repeated option is only dangerous when it repeats the ANSWER.

    The first production run reported 2073 questions that "can mismark a
    student". Most were a wrong distractor listed twice — sloppy, but nobody is
    ever marked wrong for it. Counting those as blocking inflated the figure
    roughly tenfold, and a backlog that size gets ignored rather than fixed.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def test_a_repeated_wrong_option_is_advisory(self):
        # "What is 7 + 8?" with 15 correct and '14' twice: the duplicate is a
        # distractor, so no student is mismarked.
        self._question(text='What is 7 + 8?',
                       options=(('15', True), ('14', False), ('14', False)))

        default = self._run()
        with_advisory = self._run(advisory='1')

        self.assertEqual(default.context['rows'], [])
        codes = {i['code'] for r in with_advisory.context['rows']
                 for i in r['issues']}
        self.assertIn('DUPLICATE-OPTION', codes)

    def test_a_repeated_correct_answer_is_blocking(self):
        # "How many factors does 9 have?" with '3' correct and '3' again as a
        # distractor: picking the second copy is marked wrong. CPP-377 exactly.
        q = self._question(text='How many factors does 9 have?',
                           options=(('3', True), ('3', False), ('4', False)))

        response = self._run()
        rows = {r['q'].id: r for r in response.context['rows']}
        self.assertIn(q.id, rows)
        self.assertTrue(
            any(i['code'] == 'DUPLICATE-CORRECT' for i in rows[q.id]['issues']))

    def test_the_blocking_duplicate_explains_the_harm(self):
        q = self._question(text='How many factors does 9 have?',
                           options=(('3', True), ('3', False), ('4', False)))
        response = self._run()
        row = next(r for r in response.context['rows'] if r['q'].id == q.id)
        detail = next(i['detail'] for i in row['issues']
                      if i['code'] == 'DUPLICATE-CORRECT')
        self.assertIn('marked wrong', detail)

    def test_two_correct_copies_are_not_reported_as_a_mismark(self):
        # Both copies flagged correct: whichever the student picks is accepted,
        # so this is MULTI-CORRECT's business, not a mismark.
        self._question(text='What is 7 + 8?',
                       options=(('15', True), ('15', True), ('14', False)))
        response = self._run()
        codes = {i['code'] for r in response.context['rows']
                 for i in r['issues']}
        self.assertNotIn('DUPLICATE-CORRECT', codes)


class NoLeakedTemplateCommentsTests(QuestionCheckTestBase):
    """Template comments must not reach the browser.

    Django's ``{# #}`` is SINGLE-LINE only. A multi-line one is not parsed as a
    comment at all — it renders as literal text. Three of them shipped to
    production this way, printing an explanation of the is_global link logic
    into the middle of the flagged-questions table. Every test passed, because
    they all asserted what the page contains and none asserted what it must
    NOT contain.
    """

    MARKERS = ['{#', '#}', '{% comment %}', '{% endcomment %}']

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def _assert_clean(self, response):
        body = response.content.decode()
        for marker in self.MARKERS:
            self.assertNotIn(
                marker, body,
                f'Template comment syntax {marker!r} rendered into the page')

    def test_the_check_form_has_no_leaked_comments(self):
        self._assert_clean(
            self.client.get(reverse('question_check_admin_dashboard')))

    def test_the_results_table_has_no_leaked_comments(self):
        self._question(options=(('a', False), ('b', False)))
        self._assert_clean(self._run())

    def test_the_health_dashboard_has_no_leaked_comments(self):
        from maths.models import QuestionHealthSnapshot

        QuestionHealthSnapshot.objects.create(
            total_questions=2, choice_questions=2,
            questions_blocking=1, questions_advisory=0,
            arithmetic_verified=1, issue_counts={'NO-CORRECT': 1},
            flagged_questions=[{
                'id': 1, 'codes': ['NO-CORRECT'], 'detail': 'no correct option',
                'text': 'What is 7 + 8?', 'level': 1, 'topic': 'Number',
                'subtopic': 'Addition', 'is_global': True,
            }],
        )
        self._assert_clean(
            self.client.get(reverse('question_health_admin_dashboard')))


class GlobalQuestionEditSaveTests(TestCase):
    """Saving from the editor must work however the editor was opened.

    The form used to target the listing row (``#question-row-<id>``). Opened by
    the ?edit=<id> deep link from question health, that row is usually not on
    the current page — htmx raised targetError, never sent the POST, and the
    edit silently did nothing. Nothing failed loudly; the modal just sat there.
    """

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Role as R

        cls.admin = User.objects.create_superuser(
            username='editadmin', email='edit@test.com', password='pass1234')
        admin_role, _ = R.objects.get_or_create(
            name=R.ADMIN, defaults={'display_name': 'Admin'})
        cls.admin.roles.add(admin_role)

        cls.subject = Subject.objects.create(name='Maths Edit', slug='maths-edit')
        cls.level = Level.objects.create(level_number=9, display_name='Year 9')
        cls.topic = Topic.objects.create(
            name='Addition Edit', slug='addition-edit', subject=cls.subject)

    def setUp(self):
        self.client = Client()
        self.client.login(username='editadmin', password='pass1234')
        self.question = Question.objects.create(
            level=self.level, topic=self.topic, question_text='What is 7 + 8?',
            question_type='multiple_choice')
        self.right = Answer.objects.create(
            question=self.question, answer_text='15', is_correct=True, order=0)
        self.wrong = Answer.objects.create(
            question=self.question, answer_text='14', is_correct=False, order=1)
        self.url = reverse('admin_global_question_edit', args=[self.question.id])

    def _payload(self, **overrides):
        data = {
            'question_text': self.question.question_text,
            'answer_id': [str(self.right.id), str(self.wrong.id)],
            f'answer_text_{self.right.id}': '15',
            f'answer_text_{self.wrong.id}': '14',
            f'is_correct_{self.right.id}': 'on',
        }
        data.update(overrides)
        return data

    def test_editing_an_answer_persists(self):
        response = self.client.post(
            self.url, self._payload(**{f'answer_text_{self.wrong.id}': '13'}))

        self.assertEqual(response.status_code, 200)
        self.wrong.refresh_from_db()
        self.assertEqual(self.wrong.answer_text, '13')

    def test_the_response_does_not_require_the_listing_row(self):
        # The form posts into the modal, so the reply must be addressed to the
        # modal; the row update rides along out-of-band and is skipped when the
        # row is absent.
        response = self.client.post(self.url, self._payload())
        body = response.content.decode()
        self.assertIn('edit-saved', body)
        self.assertIn('hx-swap-oob', body)

    def test_moving_the_correct_flag_persists(self):
        response = self.client.post(self.url, self._payload(**{
            f'is_correct_{self.right.id}': '',
            f'is_correct_{self.wrong.id}': 'on',
        }))

        self.assertEqual(response.status_code, 200)
        self.right.refresh_from_db()
        self.wrong.refresh_from_db()
        self.assertFalse(self.right.is_correct)
        self.assertTrue(self.wrong.is_correct)

    def test_editing_the_question_text_persists(self):
        self.client.post(self.url, self._payload(question_text='What is 8 + 7?'))
        self.question.refresh_from_db()
        self.assertEqual(self.question.question_text, 'What is 8 + 7?')
