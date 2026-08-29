"""The on-demand question check: filters, running, and fixing what it finds.

The health dashboard reports the nightly snapshot for the whole bank. This page
answers "what is wrong in Year 7 Fractions, right now?" and puts Edit/Delete
next to each finding, so a super-admin never needs a shell to act on it.
"""
import re

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


class BulkSelectionUiTests(QuestionCheckTestBase):
    """The check page offers selection and a choice of fix."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def test_each_result_row_can_be_selected(self):
        q = self._question(options=(('a', False), ('b', False)))
        response = self._run()
        self.assertContains(response, f'value="{q.id}"')
        self.assertContains(response, 'select-all')

    def test_the_fix_options_are_offered(self):
        self._question(options=(('a', False), ('b', False)))
        response = self._run()
        self.assertContains(response, 'bulk-action')
        self.assertContains(response, 'replace_duplicates')
        self.assertContains(response, 'pad_options')
        self.assertContains(response, 'to_short_answer')

    def test_the_checkboxes_are_not_nested_in_the_delete_form(self):
        # Each row carries its own Delete <form>. A nested form is invalid HTML
        # and browsers drop the inner one, so the boxes bind to the toolbar by
        # id instead. This pins that, since the failure is silent in a browser.
        q = self._question(options=(('a', False), ('b', False)))
        response = self._run()
        self.assertContains(response, 'form="bulk-fix"')


class ProblemFilterTests(QuestionCheckTestBase):
    """The Problem filter narrows a long list to the fault being worked on.

    A run over 500 questions returning 149 findings of six different kinds is
    not a work queue. Picking the problem turns it into one — and, because the
    bulk fixer acts on the rows shown, it also means "replace duplicates"
    operates on exactly the questions that have duplicates.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def test_the_form_offers_a_problem_filter(self):
        response = self.client.get(reverse('question_check_admin_dashboard'))
        self.assertContains(response, 'filter-problem')
        self.assertContains(response, 'No correct option')
        self.assertContains(response, 'Correct answer also listed as a distractor')

    def test_selecting_a_problem_excludes_the_other_kinds(self):
        no_correct = self._question(options=(('a', False), ('b', False)))
        dup_correct = self._question(options=(('3/4', True), ('3/4', False),
                                              ('1/4', False)))

        response = self._run(problem='NO-CORRECT')
        ids = [row['q'].id for row in response.context['rows']]
        self.assertEqual([no_correct.id], ids)
        self.assertNotIn(dup_correct.id, ids)

    def test_several_problems_can_be_selected_at_once(self):
        no_correct = self._question(options=(('a', False), ('b', False)))
        dup_correct = self._question(options=(('3/4', True), ('3/4', False),
                                              ('1/4', False)))

        response = self._run(problem=['NO-CORRECT', 'DUPLICATE-CORRECT'])
        ids = [row['q'].id for row in response.context['rows']]
        self.assertCountEqual([no_correct.id, dup_correct.id], ids)

    def test_only_the_selected_problem_is_listed_on_a_row(self):
        # A question with two faults must not smuggle the unselected one into
        # the Problem column — the reader would think the filter had leaked.
        q = self._question(options=(('3/4', True), ('3/4', False), ('', False)))
        response = self._run(problem='BLANK-OPTION')
        row = next(r for r in response.context['rows'] if r['q'].id == q.id)
        self.assertEqual(['BLANK-OPTION'], [i['code'] for i in row['issues']])

    def test_asking_for_an_advisory_problem_overrides_the_checkbox(self):
        # Selecting "Two distractors are the same value" and being shown
        # nothing — because the advisory checkbox was left unticked — would
        # read as "there are none". The explicit request wins.
        q = self._question(options=(('3/4', True), ('0.5', False), ('1/2', False)))

        response = self._run(problem='DUPLICATE-VALUE')
        ids = [row['q'].id for row in response.context['rows']]
        self.assertIn(q.id, ids)
        self.assertTrue(response.context['include_advisory'])

    def test_no_problem_selected_still_means_everything(self):
        q = self._question(options=(('a', False), ('b', False)))
        response = self._run()
        self.assertIn(q.id, [row['q'].id for row in response.context['rows']])

    def test_an_unknown_problem_code_is_ignored_rather_than_500ing(self):
        q = self._question(options=(('a', False), ('b', False)))
        response = self._run(problem='NOT-A-CODE')
        self.assertEqual(response.status_code, 200)
        self.assertIn(q.id, [row['q'].id for row in response.context['rows']])

    def test_the_selection_survives_the_round_trip(self):
        response = self._run(problem='NO-CORRECT')
        self.assertEqual(['NO-CORRECT'], response.context['selected_problems'])


class ShortAnswerIsNotJudgedAsChoiceTests(QuestionCheckTestBase):
    """Converting a broken MCQ to Short Answer must clear it from this page.

    It did not: the page kept reporting "Too few options — 1 option(s)", and
    re-applying the fix answered "nothing to change" — the page contradicting
    itself about a repair that had in fact worked.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def _short_answer(self, options=(('3', True),)):
        q = Question.objects.create(
            level=self.y7, topic=self.fractions, question_text='1 + 2 = ?',
            question_type='short_answer',
        )
        for order, (label, correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=label,
                                  is_correct=correct, order=order)
        return q

    def test_a_converted_question_no_longer_appears(self):
        q = self._short_answer()
        response = self._run()
        self.assertNotIn(q.id, [row['q'].id for row in response.context['rows']])

    def test_a_short_answer_with_no_correct_row_still_appears(self):
        q = self._short_answer(options=(('3', False),))
        response = self._run()
        row = next(r for r in response.context['rows'] if r['q'].id == q.id)
        self.assertEqual(['NO-CORRECT'], [i['code'] for i in row['issues']])


class ScanCursorTests(QuestionCheckTestBase):
    """Running the check twice must move THROUGH the bank, not re-scan its head.

    The cap stops one request from walking the whole bank, but without a cursor
    every "Run check" re-scanned the same first N questions — the rest of the
    bank was unreachable from this page, and a clean first page read as a clean
    bank.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')
        # Five broken questions, so a limit of 2 gives three pages.
        self.broken = [self._question(options=(('a', False), ('b', False)))
                       for _ in range(5)]

    def test_the_first_page_reports_it_stopped_early(self):
        response = self._run(limit='2')
        self.assertTrue(response.context['truncated'])
        self.assertIsNotNone(response.context['next_url'])
        self.assertContains(response, 'check-next')

    def test_the_next_page_continues_where_the_last_one_stopped(self):
        first = self._run(limit='2')
        first_ids = [row['q'].id for row in first.context['rows']]

        second = self.client.get(first.context['next_url'])
        second_ids = [row['q'].id for row in second.context['rows']]

        self.assertEqual(2, len(second_ids))
        self.assertFalse(set(first_ids) & set(second_ids))
        self.assertTrue(min(second_ids) > max(first_ids))

    def test_walking_to_the_end_covers_every_question_exactly_once(self):
        seen = []
        response = self._run(limit='2')
        while True:
            seen.extend(row['q'].id for row in response.context['rows'])
            next_url = response.context['next_url']
            if not next_url:
                break
            response = self.client.get(next_url)

        self.assertCountEqual([q.id for q in self.broken], seen)
        self.assertEqual(len(seen), len(set(seen)))

    def test_the_last_page_says_the_bank_is_exhausted(self):
        response = self._run(limit='4')
        last = self.client.get(response.context['next_url'])
        self.assertFalse(last.context['truncated'])
        self.assertIsNone(last.context['next_url'])
        self.assertContains(last, 'Reached the end')

    def test_progress_counts_the_pages_already_walked(self):
        first = self._run(limit='2')
        self.assertEqual(2, first.context['checked_through'])
        self.assertEqual(5, first.context['total_matching'])

        second = self.client.get(first.context['next_url'])
        self.assertEqual(4, second.context['checked_through'])
        self.assertEqual(5, second.context['total_matching'])

    def test_a_continued_run_can_be_restarted_from_the_beginning(self):
        first = self._run(limit='2')
        second = self.client.get(first.context['next_url'])
        self.assertIsNotNone(second.context['restart_url'])

        restarted = self.client.get(second.context['restart_url'])
        self.assertEqual(0, restarted.context['after'])
        self.assertEqual(
            [row['q'].id for row in first.context['rows']],
            [row['q'].id for row in restarted.context['rows']])

    def test_the_cursor_keeps_the_filters(self):
        # Continuing must not quietly widen the scan to the whole bank.
        other = self._question(level=self.y8,
                               options=(('a', False), ('b', False)))
        first = self._run(limit='2', level=str(self.y7.id))
        rest = []
        response = first
        while response.context['next_url']:
            response = self.client.get(response.context['next_url'])
            rest.extend(row['q'].id for row in response.context['rows'])
        self.assertNotIn(other.id, rest)

    def test_a_junk_cursor_does_not_500(self):
        response = self._run(limit='2', after='not-a-number')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(0, response.context['after'])


class AnswerAddRemoveTests(TestCase):
    """The editor has to be able to add and remove options, not just retype them.

    A question stored with EIGHT options flagged correct, or with no answer
    rows at all, cannot be repaired by editing text: the first needs correct
    flags cleared and surplus options deleted, the second needs a row created.
    Neither was possible — the Answers block only rendered when rows already
    existed, and nothing could ever be added or deleted.
    """

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Role as R

        cls.admin = User.objects.create_superuser(
            username='answeradmin', email='ans@test.com', password='pass1234')
        role, _ = R.objects.get_or_create(
            name=R.ADMIN, defaults={'display_name': 'Admin'})
        cls.admin.roles.add(role)

        cls.subject = Subject.objects.create(name='Maths Ans', slug='maths-ans')
        cls.level = Level.objects.create(level_number=11, display_name='Year 11')
        cls.topic = Topic.objects.create(
            name='Angles Ans', slug='angles-ans', subject=cls.subject)

    def setUp(self):
        self.client = Client()
        self.client.login(username='answeradmin', password='pass1234')

    def _question(self, options=(('15', True), ('14', False)),
                  question_type='multiple_choice'):
        q = Question.objects.create(
            level=self.level, topic=self.topic, question_text='7 + 8 = ?',
            question_type=question_type)
        for order, (text, correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=text,
                                  is_correct=correct, order=order)
        return q

    def _url(self, q):
        return reverse('admin_global_question_edit', args=[q.id])

    def _existing(self, q, **overrides):
        data = {'question_text': q.question_text, 'answer_id': [], }
        for answer in q.answers.all():
            data['answer_id'].append(str(answer.id))
            data[f'answer_text_{answer.id}'] = answer.answer_text
            if answer.is_correct:
                data[f'is_correct_{answer.id}'] = 'on'
        data.update(overrides)
        return data

    # ---- the form itself -------------------------------------------------

    def test_the_editor_offers_add_and_remove(self):
        q = self._question()
        body = self.client.get(self._url(q)).content.decode()
        self.assertIn('add-answer', body)
        self.assertIn('delete-answer', body)

    def test_a_question_with_no_answers_says_so_and_can_still_add(self):
        # The case that had nothing to show: an empty block read as a missing
        # feature rather than a broken question.
        q = self._question(options=(), question_type='short_answer')
        body = self.client.get(self._url(q)).content.decode()
        self.assertIn('no answers stored', body)
        self.assertIn('add-answer', body)

    # ---- adding ----------------------------------------------------------

    def test_a_new_answer_is_created(self):
        q = self._question()
        self.client.post(self._url(q), self._existing(q, **{
            'new_answer_index': ['1'],
            'new_answer_text_1': '16',
        }))
        self.assertTrue(q.answers.filter(answer_text='16').exists())

    def test_a_new_answer_can_be_the_correct_one(self):
        q = self._question(options=(('14', False),))
        self.client.post(self._url(q), self._existing(q, **{
            'new_answer_index': ['1'],
            'new_answer_text_1': '15',
            'new_is_correct_1': 'on',
        }))
        added = q.answers.get(answer_text='15')
        self.assertTrue(added.is_correct)

    def test_several_answers_can_be_added_at_once(self):
        q = self._question()
        self.client.post(self._url(q), self._existing(q, **{
            'new_answer_index': ['1', '2'],
            'new_answer_text_1': '16',
            'new_answer_text_2': '17',
        }))
        self.assertEqual(4, q.answers.count())

    def test_a_blank_new_row_is_ignored(self):
        # "+ Add answer" clicked and not filled in must cost nothing.
        q = self._question()
        self.client.post(self._url(q), self._existing(q, **{
            'new_answer_index': ['1'],
            'new_answer_text_1': '   ',
        }))
        self.assertEqual(2, q.answers.count())

    def test_a_new_answer_goes_after_the_existing_ones(self):
        q = self._question()
        self.client.post(self._url(q), self._existing(q, **{
            'new_answer_index': ['1'],
            'new_answer_text_1': '16',
        }))
        added = q.answers.get(answer_text='16')
        self.assertEqual(2, added.order)

    # ---- removing --------------------------------------------------------

    def test_a_ticked_answer_is_removed(self):
        q = self._question(options=(('15', True), ('14', False), ('13', False)))
        doomed = q.answers.get(answer_text='13')
        self.client.post(self._url(q),
                         self._existing(q, delete_answer=[str(doomed.id)]))
        self.assertFalse(q.answers.filter(id=doomed.id).exists())
        self.assertEqual(2, q.answers.count())

    def test_removing_leaves_the_others_alone(self):
        q = self._question(options=(('15', True), ('14', False), ('13', False)))
        doomed = q.answers.get(answer_text='13')
        self.client.post(self._url(q),
                         self._existing(q, delete_answer=[str(doomed.id)]))
        self.assertTrue(q.answers.get(answer_text='15').is_correct)
        self.assertTrue(q.answers.filter(answer_text='14').exists())

    def test_the_removed_text_is_recorded_before_it_is_deleted(self):
        # An option deleted by mistake cannot be recovered from the row.
        from audit.models import AuditLog

        q = self._question(options=(('15', True), ('14', False)))
        doomed = q.answers.get(answer_text='14')
        self.client.post(self._url(q),
                         self._existing(q, delete_answer=[str(doomed.id)]))

        entry = AuditLog.objects.filter(
            action='global_question_answers_removed').first()
        self.assertIsNotNone(entry)
        self.assertIn('14', str(entry.detail))

    def test_emptying_a_multiple_choice_question_is_refused(self):
        q = self._question(options=(('15', True), ('14', False)))
        ids = [str(a.id) for a in q.answers.all()]
        response = self.client.post(self._url(q),
                                    self._existing(q, delete_answer=ids))

        self.assertContains(response, 'nothing to pick')
        self.assertEqual(2, q.answers.count())

    def test_emptying_is_allowed_when_a_replacement_is_added(self):
        q = self._question(options=(('15', True), ('14', False)))
        ids = [str(a.id) for a in q.answers.all()]
        self.client.post(self._url(q), self._existing(q, **{
            'delete_answer': ids,
            'new_answer_index': ['1'],
            'new_answer_text_1': '23',
            'new_is_correct_1': 'on',
        }))
        self.assertEqual(['23'], list(q.answers.values_list('answer_text',
                                                            flat=True)))

    def test_a_short_answer_question_may_be_left_with_no_rows(self):
        # Those rows are accepted typed answers, not options to pick between;
        # the choice-type rule does not apply.
        q = self._question(options=(('42', True),), question_type='short_answer')
        ids = [str(a.id) for a in q.answers.all()]
        self.client.post(self._url(q), self._existing(q, delete_answer=ids))
        self.assertEqual(0, q.answers.count())

    # ---- the multi-correct repair, end to end ----------------------------

    def test_the_eight_correct_question_can_be_repaired(self):
        # The real row from the check page: 8 options all flagged correct.
        q = self._question(options=[(str(v), True) for v in
                                    (18, 82, 106, 34, 92, 83, 57, 148)])
        keep = q.answers.get(answer_text='82')
        # Keep '82' plus three distractors; delete the remaining four.
        surplus = [str(a.id) for a in q.answers.exclude(id=keep.id)[3:]]

        payload = {'question_text': q.question_text, 'answer_id': [],
                   'delete_answer': surplus}
        for answer in q.answers.all():
            payload['answer_id'].append(str(answer.id))
            payload[f'answer_text_{answer.id}'] = answer.answer_text
        payload[f'is_correct_{keep.id}'] = 'on'   # only this one stays correct

        self.client.post(self._url(q), payload)

        self.assertEqual(4, q.answers.count())
        self.assertEqual([True], [a.is_correct for a in q.answers.all()
                                  if a.is_correct])

    def test_saving_with_nothing_correct_warns_rather_than_going_quiet(self):
        q = self._question()
        payload = self._existing(q)
        payload.pop(f'is_correct_{q.answers.get(answer_text="15").id}')
        response = self.client.post(self._url(q), payload)
        self.assertContains(response, 'No option is marked correct')

    def test_saving_with_several_correct_warns(self):
        q = self._question()
        payload = self._existing(q, **{
            f'is_correct_{q.answers.get(answer_text="14").id}': 'on'})
        response = self.client.post(self._url(q), payload)
        self.assertContains(response, 'still marked correct')


class FillMissingAnswerTests(QuestionCheckTestBase):
    """"No correct option" is the worst fault in the bank and had no repair.

    Every student answering such a question is marked wrong, whatever they
    type or pick. Q5709 — "5531 - 4414 = ?" — had no answer rows at all: the
    check page could report it and do nothing else.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def _question(self, text, options=(), qtype='short_answer'):
        q = Question.objects.create(
            level=self.y7, topic=self.fractions, question_text=text,
            question_type=qtype)
        for order, (label, correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=label,
                                  is_correct=correct, order=order)
        return q

    def _fix(self, question):
        return self.client.post(
            reverse('question_bulk_fix_admin_dashboard'),
            {'action': 'fill_answer', 'question_id': [str(question.id)]},
            follow=True)

    def test_the_page_offers_the_fix(self):
        # The fix dropdown only renders once a run has findings to act on.
        self._question('5531 - 4414 = ?')
        response = self.client.get(
            reverse('question_check_admin_dashboard'), {'run': '1'})
        self.assertContains(response, 'Work out the missing answer')

    def test_production_q5709_gets_its_answer(self):
        q = self._question('5531 - 4414 = ?')

        self._fix(q)

        q.refresh_from_db()
        correct = q.answers.filter(is_correct=True)
        self.assertEqual(1, correct.count())
        self.assertEqual('1117', correct.first().answer_text)

    def test_an_existing_option_holding_the_answer_is_flagged_not_duplicated(self):
        # Adding a second copy would leave the correct answer listed twice —
        # the very fault this dashboard exists to find.
        q = self._question('5531 - 4414 = ?', qtype='multiple_choice',
                           options=(('1117', False), ('1127', False),
                                    ('9945', False), ('1017', False)))

        self._fix(q)

        q.refresh_from_db()
        self.assertEqual(4, q.answers.count())
        self.assertEqual(['1117'],
                         [a.answer_text for a in q.answers.filter(is_correct=True)])

    def test_a_word_problem_is_refused_rather_than_guessed(self):
        q = self._question('How many apples does Sam have left?')

        response = self._fix(q)

        q.refresh_from_db()
        self.assertEqual(0, q.answers.filter(is_correct=True).count())
        self.assertContains(response, 'not a plain arithmetic expression')

    def test_algebra_is_refused(self):
        # '3x + 2 = ?' must never be evaluated as arithmetic.
        q = self._question('3x + 2 = ?')

        self._fix(q)

        q.refresh_from_db()
        self.assertEqual(0, q.answers.filter(is_correct=True).count())

    def test_a_question_that_already_has_an_answer_is_left_alone(self):
        q = self._question('5531 - 4414 = ?', options=(('1117', True),))

        response = self._fix(q)

        q.refresh_from_db()
        self.assertEqual(1, q.answers.count())
        self.assertContains(response, 'nothing to change')

    def test_the_repaired_question_stops_being_flagged(self):
        q = self._question('5531 - 4414 = ?')
        self._fix(q)

        q.refresh_from_db()
        from maths.answer_verification import verify_question
        issues, _ = verify_question(q)
        self.assertEqual([], [i.code for i in issues])


class HouseRuleVisibilityTests(QuestionCheckTestBase):
    """One correct answer, at most three wrong ones.

    Every part of that rule was already checked — TOO-MANY-OPTIONS for the
    count, MULTI-CORRECT for two answers, NO-CORRECT for none — and
    "Trim to four options" already repaired it. But TOO-MANY-OPTIONS was
    filtered out unless the reviewer ticked "include advisory issues", so a
    question with eight options looked unflagged and the rule read as
    unenforced.

    Severity and visibility are different questions: it still cannot mismark
    anybody, so it stays out of the blocking count while being shown.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def _mcq(self, options):
        return self._question(options=options)

    def test_a_five_option_question_is_reported_without_asking_for_advisories(self):
        q = self._mcq((('3/4', True), ('1/4', False), ('2/4', False),
                       ('5/4', False), ('6/4', False)))

        response = self._run()

        row = next(r for r in response.context['rows'] if r['q'].id == q.id)
        self.assertIn('TOO-MANY-OPTIONS', [i['code'] for i in row['issues']])

    def test_four_options_are_within_the_rule(self):
        q = self._mcq((('3/4', True), ('1/4', False), ('2/4', False),
                       ('5/4', False)))
        response = self._run()
        self.assertNotIn(q.id, [r['q'].id for r in response.context['rows']])

    def test_it_is_still_badged_advisory_rather_than_a_mismark(self):
        # Padding the "can mismark a student" figure with presentation faults
        # is what made that number ten times too large once before.
        q = self._mcq((('3/4', True), ('1/4', False), ('2/4', False),
                       ('5/4', False), ('6/4', False)))

        response = self._run()

        row = next(r for r in response.context['rows'] if r['q'].id == q.id)
        issue = next(i for i in row['issues'] if i['code'] == 'TOO-MANY-OPTIONS')
        self.assertTrue(issue['advisory'])

    def test_the_other_advisories_stay_behind_the_checkbox(self):
        # Only the house rule is promoted; the rest still need asking for.
        q = self._mcq((('3/4', True), ('0.5', False), ('1/2', False)))

        default = self._run()
        asked = self._run(advisory='1')

        self.assertNotIn(q.id, [r['q'].id for r in default.context['rows']])
        self.assertIn(q.id, [r['q'].id for r in asked.context['rows']])

    def test_trimming_leaves_one_correct_and_three_wrong(self):
        q = self._mcq((('3/4', True), ('1/4', False), ('2/4', False),
                       ('5/4', False), ('6/4', False), ('7/4', False)))

        self.client.post(
            reverse('question_bulk_fix_admin_dashboard'),
            {'action': 'trim_options', 'question_id': [str(q.id)]}, follow=True)

        q.refresh_from_db()
        self.assertEqual(4, q.answers.count())
        self.assertEqual(1, q.answers.filter(is_correct=True).count())
        self.assertEqual(3, q.answers.filter(is_correct=False).count())

    def test_two_correct_options_are_reported_as_a_mismark_not_a_count(self):
        # 4 options but 2 correct still breaks the rule — and this one DOES
        # mismark a student, so it is blocking rather than advisory.
        q = self._mcq((('3/4', True), ('6/8', True), ('1/4', False),
                       ('2/4', False)))

        response = self._run()

        row = next(r for r in response.context['rows'] if r['q'].id == q.id)
        codes = [i['code'] for i in row['issues']]
        self.assertIn('MULTI-CORRECT', codes)
        issue = next(i for i in row['issues'] if i['code'] == 'MULTI-CORRECT')
        self.assertFalse(issue['advisory'])


class EveryProblemHasAFixTests(QuestionCheckTestBase):
    """A problem the page reports but offers no route out of is a dead end."""

    def test_every_reported_code_maps_to_a_fix(self):
        from maths.views_admin import BULK_ACTIONS, CODE_LABELS, FIXES_FOR_CODE
        actions = {value for value, _label in BULK_ACTIONS}
        for code in CODE_LABELS:
            with self.subTest(code):
                self.assertIn(code, FIXES_FOR_CODE,
                              f'{code} is reported with no fix offered')
                self.assertTrue(FIXES_FOR_CODE[code],
                                f'{code} maps to an empty list of fixes')
                for fix in FIXES_FOR_CODE[code]:
                    self.assertIn(fix, actions)

    def test_every_code_keeps_a_fix_that_worded_answers_can_use(self):
        """The arithmetic-only fixes are not enough on their own.

        Most of the bank's options are words, so a code whose ONLY fix refuses
        anything non-numeric is reported with no usable route out — which is
        the dead end this class exists to prevent, dressed up as a mapping.
        """
        from maths.views_admin import CODE_LABELS, FIXES_FOR_CODE
        arithmetic_only = {'fill_answer', 'fix_answer_key',
                           'replace_duplicates', 'pad_options'}
        for code in CODE_LABELS:
            with self.subTest(code):
                general = [f for f in FIXES_FOR_CODE[code]
                           if f not in arithmetic_only]
                self.assertTrue(
                    general,
                    f'{code} only offers arithmetic-only fixes '
                    f'({FIXES_FOR_CODE[code]}) — a worded question is stuck')

    def test_auto_never_runs_a_fix_that_needs_a_human_pick(self):
        from maths.views_admin import MANUAL_FIXES, auto_fix_sequence
        for code in ('NO-CORRECT', 'MULTI-CORRECT', 'WRONG-ANSWER-KEY'):
            with self.subTest(code):
                self.assertFalse(set(auto_fix_sequence({code})) & MANUAL_FIXES)

    def test_auto_clears_blank_rows_before_anything_else(self):
        """Nearly every planner refuses outright on a blank row."""
        from maths.views_admin import auto_fix_sequence
        sequence = auto_fix_sequence({'DUPLICATE-OPTION', 'BLANK-OPTION'})
        self.assertEqual(sequence[0], 'drop_blank_options')

    def test_every_fix_is_offered_in_the_dropdown(self):
        from maths.views_admin import BULK_ACTIONS
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')
        self._question(options=(('a', False), ('b', False)))
        response = self.client.get(
            reverse('question_check_admin_dashboard'), {'run': '1'})
        for value, label in BULK_ACTIONS:
            with self.subTest(value):
                self.assertContains(response, label)


class AnswerKeyFixTests(QuestionCheckTestBase):
    """Several options flagged correct, or the wrong one flagged.

    Single-select grading accepts ANY option flagged correct, so a second flag
    marks a WRONG answer right — the mirror image of CPP-377.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def _q(self, text, options):
        return self._question(text=text, options=options)

    def _fix(self, question, action='fix_answer_key'):
        return self.client.post(
            reverse('question_bulk_fix_admin_dashboard'),
            {'action': action, 'question_id': [str(question.id)]}, follow=True)

    def test_a_second_correct_flag_is_removed(self):
        q = self._q('What is 12 + 5?', (('17', True), ('16', True),
                                        ('18', False), ('20', False)))

        self._fix(q)

        q.refresh_from_db()
        self.assertEqual(['17'],
                         [a.answer_text for a in q.answers.filter(is_correct=True)])

    def test_a_wrong_answer_key_is_moved_to_the_right_option(self):
        q = self._q('What is 12 + 5?', (('16', True), ('17', False),
                                        ('18', False), ('20', False)))

        self._fix(q)

        q.refresh_from_db()
        self.assertEqual(['17'],
                         [a.answer_text for a in q.answers.filter(is_correct=True)])

    def test_the_repaired_question_stops_being_flagged(self):
        q = self._q('What is 12 + 5?', (('17', True), ('16', True),
                                        ('18', False), ('20', False)))
        self._fix(q)

        q.refresh_from_db()
        from maths.answer_verification import verify_question
        issues, _ = verify_question(q)
        self.assertEqual([], [i.code for i in issues])

    def test_a_judgement_call_is_refused_rather_than_guessed(self):
        # Production #12525: 'Square' and '6' both flagged on "What is the name
        # of this shape?". Choosing between them is choosing the answer.
        q = self._q('What is the name of this shape?',
                    (('Square', True), ('6', True), ('Circle', False)))

        response = self._fix(q)

        q.refresh_from_db()
        self.assertEqual(2, q.answers.filter(is_correct=True).count())
        self.assertContains(response, 'not a plain arithmetic expression')

    def test_a_missing_answer_is_named_as_such(self):
        # None of the options is right — that is NO-CORRECT territory, not a
        # mis-flag, and saying so sends the reviewer to the right fix.
        q = self._q('What is 12 + 5?', (('16', True), ('19', True),
                                        ('20', False)))

        response = self._fix(q)

        self.assertContains(response, 'the answer is missing')


class BlankOptionFixTests(QuestionCheckTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def _fix(self, question):
        return self.client.post(
            reverse('question_bulk_fix_admin_dashboard'),
            {'action': 'drop_blank_options',
             'question_id': [str(question.id)]}, follow=True)

    def test_blank_rows_are_deleted(self):
        q = self._question(options=(('3/4', True), ('1/4', False),
                                    ('', False), ('   ', False)))

        self._fix(q)

        q.refresh_from_db()
        self.assertEqual(2, q.answers.count())

    def test_the_correct_option_survives(self):
        q = self._question(options=(('3/4', True), ('', False)))
        self._fix(q)

        q.refresh_from_db()
        self.assertEqual(['3/4'],
                         [a.answer_text for a in q.answers.filter(is_correct=True)])

    def test_deleting_the_only_correct_option_is_refused(self):
        # A blank flagged correct is broken, but removing it would leave the
        # question unanswerable — that needs a human.
        q = self._question(options=(('', True), ('1/4', False)))

        response = self._fix(q)

        q.refresh_from_db()
        self.assertEqual(2, q.answers.count())
        self.assertContains(response, 'would leave nothing to answer')

    def test_a_question_with_no_blanks_is_left_alone(self):
        q = self._question(options=(('3/4', True), ('1/4', False)))
        response = self._fix(q)
        self.assertContains(response, 'nothing to change')


class WordedAnswerFixTests(QuestionCheckTestBase):
    """The fixes that work when the options are words, not numbers.

    Every generator-based fix refuses non-numeric options by design — it
    cannot invent a plausible worded distractor. These are the routes that
    remain, and they are what makes "a fix for every problem" true for a bank
    whose options are mostly prose.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def _fix(self, action, question, **extra):
        return self.client.post(
            reverse('question_bulk_fix_admin_dashboard'),
            {'action': action, 'question_id': [question.id], **extra},
            follow=True)

    def test_delete_duplicates_removes_a_repeated_worded_option(self):
        q = self._question(
            text='Which shape has four equal sides?',
            options=(('Square', True), ('Circle', False),
                     ('Circle', False), ('Triangle', False)))
        self._fix('delete_duplicates', q)
        texts = sorted(a.answer_text for a in q.answers.all())
        self.assertEqual(texts, ['Circle', 'Square', 'Triangle'])
        self.assertEqual(
            [a.answer_text for a in q.answers.filter(is_correct=True)],
            ['Square'])

    def test_delete_duplicates_keeps_the_correct_copy(self):
        """Deleting the flagged copy would rewrite the answer key."""
        q = self._question(
            text='Name the capital of New Zealand.',
            options=(('Wellington', False), ('Wellington', True),
                     ('Auckland', False)))
        self._fix('delete_duplicates', q)
        survivors = list(q.answers.order_by('order', 'id'))
        self.assertEqual(len(survivors), 2)
        kept = next(a for a in survivors if a.answer_text == 'Wellington')
        self.assertTrue(kept.is_correct)

    def test_delete_duplicates_refuses_to_leave_one_option(self):
        q = self._question(
            text='Is the sky blue?',
            options=(('Yes', True), ('Yes', False)))
        response = self._fix('delete_duplicates', q)
        self.assertEqual(q.answers.count(), 2)
        self.assertContains(response, 'too few to choose from')

    def test_set_answer_key_applies_the_option_the_reviewer_ticked(self):
        """The escape hatch for a key no evaluator will settle."""
        q = self._question(
            text='What is 666 in expanded form?',
            options=(('6x100 + 6x10 + 6', True), ('600+70+6', True),
                     ('666 + 0', False)))
        keep = q.answers.get(answer_text='6x100 + 6x10 + 6')
        self._fix('set_answer_key', q, **{f'answer_key_{q.id}': str(keep.id)})
        self.assertEqual(
            [a.answer_text for a in q.answers.filter(is_correct=True)],
            ['6x100 + 6x10 + 6'])

    def test_set_answer_key_refuses_a_blank_pick(self):
        q = self._question(
            text='Name a prime number.',
            options=(('', False), ('7', True)))
        blank = q.answers.get(answer_text='')
        response = self._fix('set_answer_key', q,
                             **{f'answer_key_{q.id}': str(blank.id)})
        self.assertContains(response, 'cannot be the answer')
        self.assertTrue(q.answers.get(answer_text='7').is_correct)

    def test_set_answer_key_says_so_when_nothing_was_ticked(self):
        q = self._question(
            text='Which is a mammal?',
            options=(('Cat', True), ('Cat', True), ('Frog', False)))
        response = self._fix('set_answer_key', q)
        self.assertContains(response, 'no answer was ticked')

    def test_to_short_answer_refuses_an_unanswerable_question(self):
        """Retyping a question with no key hides the worse fault."""
        q = self._question(
            text='Explain why the sum is even.',
            options=(('Because it is', False),))
        response = self._fix('to_short_answer', q)
        q.refresh_from_db()
        self.assertEqual(q.question_type, 'multiple_choice')
        self.assertContains(response, 'no correct answer is stored')

    def test_to_short_answer_rescues_a_worded_question_padding_cannot(self):
        q = self._question(
            text='What is the name of this shape?',
            options=(('Rhombus', True),))
        self._fix('to_short_answer', q)
        q.refresh_from_db()
        self.assertEqual(q.question_type, 'short_answer')


class AutoFixTests(QuestionCheckTestBase):
    """One button that tries each fix suited to what the question reports."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def _auto(self, *questions):
        return self.client.post(
            reverse('question_bulk_fix_admin_dashboard'),
            {'action': 'auto',
             'question_id': [q.id for q in questions]},
            follow=True)

    def test_auto_falls_through_to_the_fix_that_works(self):
        """replace_duplicates refuses words; delete_duplicates does not."""
        q = self._question(
            text='Which animal barks?',
            options=(('Dog', True), ('Cat', False),
                     ('Cat', False), ('Bird', False)))
        self._auto(q)
        self.assertEqual(
            sorted(a.answer_text for a in q.answers.all()),
            ['Bird', 'Cat', 'Dog'])

    def test_auto_reports_what_each_fix_refused(self):
        """A question needing a person is named, with the reasons."""
        q = self._question(
            text='Flooring comes in lengths which are multiples of 300 mm.',
            options=(('900mm', True), ('1800mm', True),
                     ('2700mm', True), ('3600mm', True)))
        response = self._auto(q)
        self.assertContains(response, f'Q{q.id}')
        self.assertContains(response, 'Tick the right answer in the row')

    def test_auto_re_verifies_rather_than_trusting_a_stale_row(self):
        q = self._question(
            text='What is 1/2 + 1/4?',
            options=(('3/4', True), ('1/4', False), ('2/4', False)))
        response = self._auto(q)
        self.assertContains(response, 'nothing wrong with it now')


class TypedAnswerEditorTests(QuestionCheckTestBase):
    """A typed question's rows are accepted spellings, not rival options."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='checkadmin', password='pass1234')

    def test_several_accepted_spellings_all_grade_correct(self):
        """Graded through the model, which is what every quiz path calls."""
        q = Question.objects.create(
            level=self.y7, topic=self.fractions,
            question_text='Calculate the surface area of the half-cylinder.',
            question_type='calculation')
        for order, text in enumerate(('593 cm^2', '593', '593 cm2')):
            Answer.objects.create(question=q, answer_text=text,
                                  is_correct=True, order=order)

        self.assertEqual(q.answers.filter(is_correct=True).count(), 3)
        for typed in ('593 cm^2', '593', '593 cm2'):
            with self.subTest(typed):
                self.assertTrue(q.grade_text_answer(typed))

    def test_multi_correct_is_not_reported_on_a_typed_question(self):
        """Only choice questions are single-select, so only they can break."""
        from maths.answer_verification import verify_question

        q = Question.objects.create(
            level=self.y7, topic=self.fractions,
            question_text='Calculate the surface area of the half-cylinder.',
            question_type='calculation')
        for order, text in enumerate(('593 cm^2', '593')):
            Answer.objects.create(question=q, answer_text=text,
                                  is_correct=True, order=order)

        issues, _ = verify_question(q)
        self.assertNotIn('MULTI-CORRECT', [i.code for i in issues])

    def test_editor_offers_a_checkbox_for_a_typed_question(self):
        q = Question.objects.create(
            level=self.y7, topic=self.fractions,
            question_text='Calculate the surface area of the half-cylinder.',
            question_type='calculation')
        Answer.objects.create(question=q, answer_text='593 cm^2',
                              is_correct=True, order=0)

        response = self.client.get(
            reverse('edit_question', kwargs={'question_id': q.id}))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        # The mode switch is what turns the radio group into checkboxes on
        # load; without it a second accepted spelling cannot be ticked.
        self.assertIn('applyCorrectMode', body)
        self.assertIn('toggleCorrectAnswer', body)

    def test_saving_two_ticked_rows_keeps_both(self):
        q = Question.objects.create(
            level=self.y7, topic=self.fractions,
            question_text='Calculate the surface area of the half-cylinder.',
            question_type='calculation')
        Answer.objects.create(question=q, answer_text='593 cm^2',
                              is_correct=True, order=0)
        Answer.objects.create(question=q, answer_text='593',
                              is_correct=False, order=1)

        self.client.post(
            reverse('edit_question', kwargs={'question_id': q.id}),
            {
                'topic': q.topic_id,
                'question_type': 'calculation',
                'question_text': q.question_text,
                'difficulty': 2,
                'points': 2,
                'answer_text_1': '593 cm^2',
                'answer_correct_1': 'true',
                'answer_order_1': 1,
                'answer_text_2': '593',
                'answer_correct_2': 'true',
                'answer_order_2': 2,
            },
            follow=True)

        self.assertEqual(
            sorted(a.answer_text for a in q.answers.filter(is_correct=True)),
            ['593', '593 cm^2'])


class GlobalQuestionStudentPreviewTests(TestCase):
    """"Preview as student" inside the global question editor.

    The editor shows what is STORED. What decides whether a question is any
    good is what a child MEETS — the options they can pick, whether the marker
    accepts the answer — and that is exactly what the review screens' preview
    shows for a question being imported. The same button belongs here, over the
    questions that already reached children, with two rules: it previews the
    edits held unsaved in the form, and it writes nothing at all.
    """

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Role as R

        cls.admin = User.objects.create_superuser(
            username='previewadmin', email='preview@test.com', password='pass1234')
        admin_role, _ = R.objects.get_or_create(
            name=R.ADMIN, defaults={'display_name': 'Admin'})
        cls.admin.roles.add(admin_role)
        cls.teacher = User.objects.create_user(
            username='previewteacher', email='pt@test.com', password='pass1234')

        cls.subject = Subject.objects.create(name='Maths Prev', slug='maths-prev')
        cls.level = Level.objects.create(level_number=5, display_name='Year 5')
        cls.topic = Topic.objects.create(
            name='Coordinates Prev', slug='coordinates-prev', subject=cls.subject)

    def setUp(self):
        self.client = Client()
        self.client.login(username='previewadmin', password='pass1234')

    def _question(self, options=(('15', True), ('14', False)),
                  question_type='multiple_choice', text='7 + 8 = ?'):
        q = Question.objects.create(
            level=self.level, topic=self.topic, question_text=text,
            question_type=question_type)
        for order, (answer_text, correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=correct, order=order)
        return q

    def _url(self, q):
        return reverse('admin_global_question_preview', args=[q.id])

    @staticmethod
    def _options(body):
        """The option labels the preview drew, in order.

        Read out of the rendered take partial rather than matched as bare
        strings: "15" appears in the page for other reasons, and a preview that
        drew no options at all would pass a substring check.
        """
        return [text.strip() for text in re.findall(
            r'<label for="ans_\d+_\d+"[^>]*>(.*?)</label>', body, re.S)]

    def _form(self, q, **overrides):
        """The modal's fields, exactly as the browser posts them."""
        data = {
            'question_text': q.question_text,
            'question_type': q.question_type,
            'answer_id': [],
        }
        for answer in q.answers.order_by('order', 'id'):
            data['answer_id'].append(str(answer.id))
            data[f'answer_text_{answer.id}'] = answer.answer_text
            if answer.is_correct:
                data[f'is_correct_{answer.id}'] = 'on'
        data.update(overrides)
        return data

    # ---- the button ------------------------------------------------------

    def test_the_editor_offers_the_preview(self):
        q = self._question()
        body = self.client.get(
            reverse('admin_global_question_edit', args=[q.id])).content.decode()
        self.assertIn('preview-as-student', body)
        # It posts the open form, to this question's own endpoint — without
        # both, the button previews the row on disk instead of the edit.
        self.assertIn(self._url(q), body)
        self.assertIn('#question-edit-form', body)

    def test_the_listing_offers_the_preview_on_every_row(self):
        q = self._question()
        body = self.client.get(reverse('admin_global_questions')).content.decode()
        self.assertIn(self._url(q), body)
        # The modal the row buttons open, and the token the fetch needs — the
        # row is not inside a form, so without it every preview would 403.
        self.assertIn('id="student-preview"', body)
        self.assertIn('csrfmiddlewaretoken', body)

    def test_the_row_previews_the_stored_question(self):
        # The row posts no form. Treating that as "an edit with empty fields"
        # would blank the very question it was asked to show.
        q = self._question()
        body = self.client.post(self._url(q), {}).content.decode()
        self.assertIn('7 + 8 = ?', body)
        self.assertEqual(self._options(body), ['15', '14'])
        q.refresh_from_db()
        self.assertEqual(q.question_text, '7 + 8 = ?')
        self.assertEqual(q.answers.count(), 2)

    # ---- what it shows ---------------------------------------------------

    def test_it_renders_the_question_the_student_would_meet(self):
        q = self._question()
        body = self.client.post(self._url(q), self._form(q)).content.decode()
        self.assertIn('7 + 8 = ?', body)
        # The real take partial: one radio per option, named the way the
        # student page names it.
        self.assertIn(f'name="answer_{q.id}"', body)
        self.assertEqual(self._options(body), ['15', '14'])

    def test_it_previews_the_unsaved_edit_not_the_stored_row(self):
        q = self._question()
        body = self.client.post(self._url(q), self._form(
            q, question_text='8 + 8 = ?')).content.decode()
        self.assertIn('8 + 8 = ?', body)
        self.assertNotIn('7 + 8 = ?', body)

    def test_an_unsaved_new_option_appears(self):
        q = self._question()
        body = self.client.post(self._url(q), self._form(q, **{
            'new_answer_index': ['1'],
            'new_answer_text_1': '16',
        })).content.decode()
        self.assertEqual(self._options(body), ['15', '14', '16'])

    def test_an_unsaved_removal_disappears(self):
        q = self._question()
        body = self.client.post(self._url(q), self._form(
            q, delete_answer=[str(q.answers.get(answer_text='14').id)],
        )).content.decode()
        self.assertEqual(self._options(body), ['15'])

    # ---- and changes nothing --------------------------------------------

    def test_previewing_writes_nothing(self):
        # The whole safety of the feature. Previewing an edit must not be a
        # back door that saves it — the teacher has not pressed Save.
        q = self._question()
        removed = q.answers.get(answer_text='14')

        self.client.post(self._url(q), self._form(q, **{
            'question_text': '8 + 8 = ?',
            'question_type': 'short_answer',
            f'answer_text_{q.answers.get(answer_text="15").id}': 'fifteen',
            'delete_answer': [str(removed.id)],
            'new_answer_index': ['1'],
            'new_answer_text_1': '16',
        }))

        q.refresh_from_db()
        self.assertEqual(q.question_text, '7 + 8 = ?')
        self.assertEqual(q.question_type, 'multiple_choice')
        self.assertEqual(
            sorted(a.answer_text for a in q.answers.all()), ['14', '15'])

    # ---- trying an answer ------------------------------------------------

    def test_a_picked_option_is_marked_by_the_real_grader(self):
        q = self._question()
        body = self.client.post(self._url(q), self._form(
            q, preview_answer_index='0')).content.decode()
        self.assertIn('Marked correct', body)

    def test_a_wrong_pick_is_marked_wrong(self):
        q = self._question()
        body = self.client.post(self._url(q), self._form(
            q, preview_answer_index='1')).content.decode()
        self.assertIn('Marked wrong', body)

    def test_a_typed_answer_is_marked_against_the_edited_answers(self):
        # The repair this editor exists for: a one-option "multiple choice"
        # switched to short answer. The preview proves the switch grades.
        q = self._question(options=(('15', True),))
        body = self.client.post(self._url(q), self._form(
            q, question_type='short_answer', preview_answer='15',
        )).content.decode()
        self.assertIn('Marked correct', body)

    def test_the_notes_name_the_trap(self):
        q = self._question(options=(('15', True), ('14', True)))
        body = self.client.post(self._url(q), self._form(q)).content.decode()
        self.assertIn('ticked correct', body)

    # ---- a state that cannot be saved -----------------------------------

    def test_an_unsaveable_edit_says_so_instead_of_previewing(self):
        # Removing every option is refused on save; the preview says the same
        # thing rather than drawing a question with nothing to pick.
        q = self._question()
        body = self.client.post(self._url(q), self._form(
            q, delete_answer=[str(a.id) for a in q.answers.all()],
        )).content.decode()
        self.assertIn('nothing to pick', body)
        self.assertEqual(q.answers.count(), 2)

    # ---- who may ---------------------------------------------------------

    def test_a_non_admin_cannot_preview(self):
        q = self._question()
        self.client.logout()
        self.client.login(username='previewteacher', password='pass1234')
        response = self.client.post(self._url(q), self._form(q))
        self.assertNotEqual(response.status_code, 200)

    def test_a_school_owned_question_is_not_reachable_here(self):
        # This editor is the GLOBAL bank; a school's own question is another
        # screen's business, and 404 says so rather than editing it silently.
        q = self._question()
        response = self.client.post(
            reverse('admin_global_question_preview', args=[q.id + 9999]),
            self._form(q))
        self.assertEqual(response.status_code, 404)
