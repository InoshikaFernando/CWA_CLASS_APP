"""Opening one student's report from the preview list (CPP-388 follow-up).

The preview table answers "how did they do"; it could not answer "what will
they actually receive". These pages render the real report and the real PDF
from a report that is never saved, so a school can read exactly what a family
would get before deciding to send it.

Two properties carry the weight here:

* **Nothing is written.** Same reason the list writes nothing — a preview that
  created rows would stamp delivery state and leave the real send with nothing
  to do.
* **Access is the list's access.** The student must be in the same plan that
  builds the table, so the link can never open a report the table would not
  have shown this user.
"""

from datetime import datetime, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from classroom.models import SchoolTeacher
from progress import periods
from progress.models import PeriodReport
from progress.tests.factories import (
    enable_reports, enrol, make_classroom, make_homework, make_school,
    make_user, submit,
)

DETAIL_URL = '/progress/reports/preview/report/'
PDF_URL = '/progress/reports/preview/report/pdf/'


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


class PreviewDetailBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.hoi = make_user('pd_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )
        cls.student = make_user('pd_student', first_name='Ada', last_name='B')
        enrol(cls.classroom, cls.student)

        last_monday = periods.previous_week(periods.today())[0]
        cls.window_start = last_monday
        homework = make_homework(
            cls.classroom, due=at(last_monday), title='Practice',
        )
        submit(homework, cls.student, 1, 4, when=at(last_monday))
        submit(homework, cls.student, 2, 9, when=at(last_monday))

    def setUp(self):
        self.client.force_login(self.hoi)
        enable_reports(self.school, kind='school', weekly=True)

    def scope(self, student=None, **overrides):
        params = {
            'school': self.school.id,
            'period': periods.WEEKLY,
            'student': (student or self.student).id,
        }
        params.update(overrides)
        return '&'.join(f'{k}={v}' for k, v in params.items())


class PreviewDetailTests(PreviewDetailBase):
    def test_it_renders_the_report_the_family_would_receive(self):
        response = self.client.get(f'{DETAIL_URL}?{self.scope()}')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['preview'])
        self.assertEqual(response.context['student'], self.student)
        # The real figures, not a placeholder: best of 4/10 and 9/10.
        self.assertEqual(response.context['totals']['avg_best_pct'], 90)

    def test_it_says_the_report_has_not_been_sent(self):
        response = self.client.get(f'{DETAIL_URL}?{self.scope()}')

        self.assertContains(response, 'has not been generated or sent')

    def test_opening_the_preview_saves_nothing(self):
        self.client.get(f'{DETAIL_URL}?{self.scope()}')
        self.client.get(f'{PDF_URL}?{self.scope()}')

        self.assertFalse(PeriodReport.objects.exists())

    def test_the_pdf_is_the_same_report_as_a_download(self):
        response = self.client.get(f'{PDF_URL}?{self.scope()}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_the_list_links_to_it_for_a_student_with_activity(self):
        response = self.client.get(
            f'/progress/reports/preview/?school={self.school.id}'
            f'&period={periods.WEEKLY}'
        )

        self.assertContains(response, 'preview-view-report')
        self.assertContains(response, f'student={self.student.id}')

    def test_a_student_with_nothing_to_show_gets_no_link(self):
        quiet = make_user('pd_quiet', first_name='Quiet', last_name='One')
        enrol(self.classroom, quiet)

        response = self.client.get(
            f'/progress/reports/preview/?school={self.school.id}'
            f'&period={periods.WEEKLY}'
        )

        self.assertNotContains(response, f'student={quiet.id}')

    def test_no_template_syntax_leaks_into_the_page(self):
        # A multi-line {# … #} ends at the first line break and renders the
        # rest as body text. This has now happened twice.
        body = self.client.get(
            f'{DETAIL_URL}?{self.scope()}'
        ).content.decode()
        # Opening tokens only, matching the sibling test: a closing brace is
        # ordinary CSS, and base.html is full of it.
        for token in ('{#', '{%', '{{'):
            self.assertNotIn(token, body, f'unrendered {token} in the page')


class PreviewDetailAccessTests(PreviewDetailBase):
    def test_a_student_outside_the_scope_is_not_found(self):
        outsider = make_user('pd_outsider', first_name='Else', last_name='Where')
        other_school = make_school(name='Other Institute', slug='other-institute')
        enrol(make_classroom(other_school, code='RPT00002'), outsider)

        response = self.client.get(f'{DETAIL_URL}?{self.scope(student=outsider)}')

        self.assertEqual(response.status_code, 404)

    def test_a_head_of_another_institute_is_not_found(self):
        other_school = make_school(name='Rival Institute', slug='rival-institute')
        rival = make_user('pd_rival', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=other_school, teacher=rival, role='head_of_institute',
        )
        self.client.force_login(rival)

        response = self.client.get(f'{DETAIL_URL}?{self.scope()}')

        self.assertEqual(response.status_code, 404)

    def test_a_student_cannot_open_the_staff_preview(self):
        self.client.force_login(self.student)

        response = self.client.get(f'{DETAIL_URL}?{self.scope()}')

        self.assertNotEqual(response.status_code, 200)

    def test_a_class_with_reports_switched_off_has_nothing_to_preview(self):
        # Access follows the plan that builds the table: switch reporting off
        # and the row disappears, so the link must stop working too.
        enable_reports(self.school, kind='school', weekly=False)

        response = self.client.get(f'{DETAIL_URL}?{self.scope()}')

        self.assertEqual(response.status_code, 404)

    def test_the_bare_url_goes_back_to_the_list_rather_than_dead_ending(self):
        # Naming no student is not the same as naming one you may not see.
        # A truncated link or a bookmark should land on the page with the
        # links on it; test_url_sitemap walks every route with no arguments
        # and treats a 404 there as a missing route, which it would be.
        for url in (DETAIL_URL, PDF_URL):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 302)
                self.assertEqual(response['Location'], '/progress/reports/preview/')

    def test_a_hand_edited_student_id_is_not_found_rather_than_a_500(self):
        response = self.client.get(
            f'{DETAIL_URL}?school={self.school.id}'
            f'&period={periods.WEEKLY}&student=abc'
        )

        self.assertEqual(response.status_code, 404)

    def test_an_unknown_period_is_not_found(self):
        response = self.client.get(f'{DETAIL_URL}?{self.scope(period="decade")}')

        self.assertEqual(response.status_code, 404)


class PreviewDetailSubjectTests(TestCase):
    """"View report" must open the subject whose row was clicked.

    The preview table fans out per subject; for a while the link back into it
    did not carry the subject, so clicking through showed a combined report
    that matched no row on the page and nothing the send would produce.
    """

    @classmethod
    def setUpTestData(cls):
        from classroom.models import Subject
        from classroom.models import SchoolTeacher
        from progress.tests.factories import (
            enable_reports, enrol, make_classroom, make_homework,
            make_school, make_user, submit,
        )
        from django.utils import timezone
        from datetime import timedelta

        cls.school = make_school()
        cls.hoi = make_user('pd_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )
        cls.student = make_user('pd_student', first_name='Avisha')

        def subject(slug, name):
            row, _ = Subject.objects.get_or_create(
                slug=slug, school=None, defaults={'name': name},
            )
            return row

        cls.maths = subject('mathematics', 'Mathematics')
        cls.coding = subject('coding', 'Coding')

        cls.maths_class = make_classroom(cls.school, name='Maths', code='PD000001')
        cls.maths_class.subject = cls.maths
        cls.maths_class.save(update_fields=['subject'])
        cls.coding_class = make_classroom(cls.school, name='Web', code='PD000002')
        cls.coding_class.subject = cls.coding
        cls.coding_class.save(update_fields=['subject'])
        enrol(cls.maths_class, cls.student)
        enrol(cls.coding_class, cls.student)

        cls.start, cls.end = periods.previous_week(periods.today())
        when = timezone.make_aware(timezone.datetime.combine(
            cls.start + timedelta(days=1),
            timezone.datetime.min.time().replace(hour=10),
        ))
        maths_hw = make_homework(cls.maths_class, due=when, title='Fractions')
        submit(maths_hw, cls.student, 1, 6, when=when)
        coding_hw = make_homework(cls.coding_class, due=when, title='Loops')
        coding_hw.subject_slug = 'coding'
        coding_hw.save(update_fields=['subject_slug'])
        submit(coding_hw, cls.student, 1, 9, when=when)

        enable_reports(cls.school, kind='school', weekly=True)

    def setUp(self):
        self.client.force_login(self.hoi)

    def _get(self, **extra):
        params = {
            'school': self.school.id, 'period': periods.WEEKLY,
            'student': self.student.id,
        }
        params.update(extra)
        return self.client.get('/progress/reports/preview/report/', params)

    def test_it_opens_the_subject_that_was_asked_for(self):
        response = self._get(subject=self.coding.id)

        self.assertEqual(response.status_code, 200)
        report = response.context['report']
        self.assertEqual(report.subject, self.coding)
        self.assertEqual(report.data['totals']['homework_attempted'], 1)

    def test_the_other_subject_is_a_different_report(self):
        response = self._get(subject=self.maths.id)

        self.assertEqual(response.context['report'].subject, self.maths)

    def test_no_subject_still_opens_the_combined_report(self):
        """A link written before CPP-395 must not 404."""
        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['report'].subject)
        self.assertEqual(
            response.context['report'].data['totals']['homework_attempted'], 2,
        )

    def test_a_subject_this_student_does_not_take_falls_back(self):
        other = self.maths.__class__.objects.create(
            name='Science', slug='science-x', school=None,
        )
        response = self._get(subject=other.id)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['report'].subject)


class RubricSectionRenderTests(TestCase):
    """The rubric block must RENDER, not merely be built.

    It shipped reading rubric.confident|add:rubric.advanced. The dict has no
    such keys — it is {total, achieved, in_progress, not_started}, where
    'achieved' already counts Confident + Advanced — so the page raised
    VariableDoesNotExist on the test site. Every test at the time built the
    context and none rendered the block with a rubric present, which is how a
    500 got past a green suite.
    """

    @classmethod
    def setUpTestData(cls):
        from classroom.models import (
            ProgressCriteria, ProgressRecord, SchoolTeacher, Subject,
        )
        from progress.tests.factories import (
            enable_reports, enrol, make_classroom, make_school, make_user,
        )

        cls.school = make_school()
        cls.hoi = make_user('rb_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )
        cls.student = make_user('rb_student', first_name='Avisha')
        subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None, defaults={'name': 'Mathematics'},
        )
        cls.room = make_classroom(cls.school, name='Maths', code='RB000001')
        cls.room.subject = subject
        cls.room.save(update_fields=['subject'])
        enrol(cls.room, cls.student)

        for index in range(3):
            ProgressRecord.objects.create(
                student=cls.student, classroom=cls.room, status='confident',
                criteria=ProgressCriteria.objects.create(
                    school=cls.school, name=f'criterion {index}',
                    status='approved',
                ),
            )

        cls.start, cls.end = periods.previous_week(periods.today())
        enable_reports(cls.school, kind='school', weekly=True)

    def setUp(self):
        self.client.force_login(self.hoi)

    def test_the_rubric_section_renders(self):
        response = self.client.get('/progress/reports/preview/report/', {
            'school': self.school.id, 'period': periods.WEEKLY,
            'student': self.student.id,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'report-rubric')
        self.assertContains(response, "Teacher's assessment")
        # 3 criteria, all confident -> achieved == 3.
        self.assertContains(response, 'of 3 criteria at confident or above')


class PracticeSectionRenderTests(TestCase):
    """The coding-practice block must RENDER, with its topic table.

    Same lesson as RubricSectionRenderTests above: the section was fully
    covered by unit tests that built the dict and never rendered it, which is
    how a template reading a key that does not exist reaches the test site as
    a 500. This one exercises `{% if topic.best_pct is not None %}`, which is
    the branch a dict-only test cannot reach.
    """

    @classmethod
    def setUpTestData(cls):
        from classroom.models import SchoolTeacher, Subject
        from coding.models import (
            CodingExercise, CodingLanguage, CodingTopic,
            StudentExerciseSubmission, TopicLevel,
        )
        from progress.tests.factories import (
            enable_reports, enrol, make_classroom, make_school, make_user,
        )

        cls.school = make_school(name='Practice School', slug='practice-school')
        cls.hoi = make_user('pr_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )
        cls.student = make_user('pr_student', first_name='Aadya')
        subject, _ = Subject.objects.get_or_create(
            slug='coding', school=None, defaults={'name': 'Coding'},
        )
        cls.room = make_classroom(cls.school, name='Web Prog', code='PR000001')
        cls.room.subject = subject
        cls.room.save(update_fields=['subject'])
        enrol(cls.room, cls.student)

        cls.start, cls.end = periods.previous_week(periods.today())
        when = timezone.make_aware(timezone.datetime.combine(
            cls.start + timedelta(days=1),
            timezone.datetime.min.time().replace(hour=10),
        ))

        language = CodingLanguage.objects.create(name='Python', slug='py-pr')
        topic = CodingTopic.objects.create(
            name='Loops', slug='pr-loops', language=language,
        )
        level = TopicLevel.objects.create(
            topic=topic, level_choice=TopicLevel.BEGINNER,
        )
        for title in ('Count to 5', 'Even or Odd'):
            exercise = CodingExercise.objects.create(
                title=title, topic_level=level, description='d',
            )
            row = StudentExerciseSubmission.objects.create(
                student=cls.student, exercise=exercise, code_submitted='x',
                is_completed=True,
            )
            StudentExerciseSubmission.objects.filter(pk=row.pk).update(
                submitted_at=when,
            )

        enable_reports(cls.school, kind='school', weekly=True)

    def setUp(self):
        self.client.force_login(self.hoi)

    def _get(self):
        return self.client.get('/progress/reports/preview/report/', {
            'school': self.school.id, 'period': periods.WEEKLY,
            'student': self.student.id,
        })

    def test_the_practice_section_renders_by_topic(self):
        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'report-subject-practice')
        self.assertContains(response, 'Loops')
        self.assertContains(response, '2 of 2')

    def test_the_exercise_names_are_kept_behind_the_summary(self):
        """Grouping summarises; it must not throw the detail away."""
        response = self._get()

        self.assertContains(response, 'Show all 2 exercises')
        self.assertContains(response, 'Count to 5')
        self.assertContains(response, 'Even or Odd')

    def test_an_unmarked_topic_shows_a_dash_not_a_percentage(self):
        """Both exercises are completion-only, so there is no mark to show.

        Asserted against the block itself rather than the whole page: a
        page-wide "no 100% anywhere" check passes for the wrong reasons and
        fails for them too.
        """
        response = self._get()
        html = response.content.decode()
        block = html.split('report-subject-practice', 1)[1].split('</table>', 1)[0]

        self.assertIn('&mdash;', block)
        self.assertNotIn('100%', block)
        self.assertIn('all completion-based, so there is no average mark', html)


class NextStepsRenderTests(TestCase):
    """The suggestions must reach the page, not merely be computed."""

    @classmethod
    def setUpTestData(cls):
        from classroom.models import SchoolTeacher
        from progress.tests.factories import (
            enable_reports, enrol, make_classroom, make_homework,
            make_school, make_user, submit,
        )

        cls.school = make_school(name='Next Steps', slug='next-steps')
        cls.hoi = make_user('ns_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )
        cls.student = make_user('ns_student', first_name='Aadya')
        cls.room = make_classroom(cls.school, name='Year 5', code='NS000001')
        enrol(cls.room, cls.student)

        cls.start, cls.end = periods.previous_week(periods.today())
        when = timezone.make_aware(timezone.datetime.combine(
            cls.start + timedelta(days=1),
            timezone.datetime.min.time().replace(hour=10),
        ))
        homework = make_homework(cls.room, due=when, title='Fractions')
        submit(homework, cls.student, 1, 4, when=when)
        submit(homework, cls.student, 2, 9, when=when)

        enable_reports(cls.school, kind='school', weekly=True)

    def setUp(self):
        self.client.force_login(self.hoi)

    def test_the_section_renders_on_the_report_page(self):
        response = self.client.get('/progress/reports/preview/report/', {
            'school': self.school.id, 'period': periods.WEEKLY,
            'student': self.student.id,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'report-next-steps')
        # Literal in the template, so it is not autoescaped.
        self.assertContains(response, "What's next")
        self.assertContains(response, 'Retrying is working')
