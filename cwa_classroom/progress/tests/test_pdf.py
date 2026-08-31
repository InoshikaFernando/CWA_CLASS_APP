"""The downloadable PDF (CPP-388 §3).

The PDF is the artifact a parent keeps, and it is generated from the same
frozen snapshot as the page — so what is worth asserting is that it renders at
all for each shape of report, and that the reader's own numbers make it in.
"""

from datetime import date, datetime, time

from django.test import TestCase
from django.utils import timezone

from progress import periods
from progress.models import PeriodReport
from progress.pdf import render_report_pdf
from progress.reports import build_report_data
from progress.tests.factories import (
    answer, enrol, make_classroom, make_homework, make_question, make_school,
    make_topic, make_user, submit,
)

START = date(2026, 8, 17)
END = date(2026, 8, 23)


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


def text_of(pdf_bytes):
    """Every text run in the PDF, flattened.

    ReportLab writes its page streams ASCII85-encoded over Flate, so this
    reverses both and pulls the strings out of the text operators — enough to
    prove a figure reached the page without adding a PDF-parsing dependency for
    the sake of six assertions.
    """
    import re
    import zlib

    found = []
    for stream in re.findall(rb'stream\r?\n(.*?)endstream', pdf_bytes, re.S):
        payload = stream.strip(b'\r\n')
        for decode in (_ascii85_flate, zlib.decompress, lambda raw: raw):
            try:
                payload = decode(payload)
                break
            except Exception:
                continue
        text = payload.decode('latin-1', 'replace')
        found += re.findall(r'\((.*?)\)\s*Tj', text)
        # A TJ array splits one run across several strings — join them back up.
        for array in re.findall(r'\[(.*?)\]\s*TJ', text):
            found.append(''.join(re.findall(r'\((.*?)\)', array)))
    return ' '.join(found)


def _ascii85_flate(payload):
    import base64
    import zlib

    return zlib.decompress(base64.a85decode(payload, adobe=True))


class PdfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.student = make_user('pdf_student', first_name='Ada', last_name='Byron')
        cls.rival = make_user('pdf_rival')
        enrol(cls.classroom, cls.student)
        enrol(cls.classroom, cls.rival)

        topic = make_topic('Fractions')
        homework = make_homework(cls.classroom, due=at(date(2026, 8, 21)))
        first = submit(homework, cls.student, 1, 4, when=at(date(2026, 8, 18)))
        submit(homework, cls.student, 2, 9, when=at(date(2026, 8, 19)))
        submit(homework, cls.rival, 1, 3, when=at(date(2026, 8, 18)))
        answer(first, make_question(topic), True)
        answer(first, make_question(topic, text='q2'), False)

        cls.report = cls._report(cls, periods.WEEKLY, START, END)

    def _report(self, period_type, start, end):
        return PeriodReport.objects.create(
            student=self.student, school=self.school,
            period_type=period_type, period_start=start, period_end=end,
            data=build_report_data(self.student, period_type, start, end),
        )

    def test_it_produces_a_real_pdf(self):
        pdf = render_report_pdf(self.report)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertTrue(pdf.rstrip().endswith(b'%%EOF'))
        self.assertGreater(len(pdf), 2000)

    def test_the_headline_numbers_reach_the_page(self):
        content = text_of(render_report_pdf(self.report))

        self.assertIn('Ada Byron', content)
        self.assertIn('Week of 17 Aug 2026', content)
        self.assertIn('90%', content)   # best-attempt average
        self.assertIn('40%', content)   # first-attempt average

    def test_the_topic_and_attempt_tables_are_included(self):
        content = text_of(render_report_pdf(self.report))

        self.assertIn('Fractions', content)
        self.assertIn('By topic', content)
        self.assertIn('Effort and attempts', content)

    def test_awards_are_written_out_with_their_evidence(self):
        content = text_of(render_report_pdf(self.report))
        self.assertIn('Recognition', content)
        self.assertIn('Top Scorer', content)

    def test_an_empty_report_renders_a_short_honest_page(self):
        empty = self._report(
            periods.MONTHLY, date(2026, 7, 1), date(2026, 7, 31),
        )
        content = text_of(render_report_pdf(empty))

        self.assertIn('No homework was submitted', content)
        self.assertNotIn('By topic', content)

    def test_a_term_report_renders_with_a_week_bucketed_trend(self):
        homework = make_homework(
            self.classroom, due=at(date(2026, 9, 10)), title='Later',
        )
        submit(homework, self.student, 1, 8, when=at(date(2026, 9, 8)))
        term = self._report(periods.TERM, date(2026, 7, 20), date(2026, 9, 25))

        self.assertGreater(len(term.trend), 1)
        self.assertTrue(render_report_pdf(term).startswith(b'%PDF'))

    def test_a_long_homework_title_wraps_instead_of_overflowing(self):
        """ReportLab prints a bare string straight over the next column.

        Real homework titles are long enough to do it, and the value it would
        run over is the student's score.
        """
        long_title = (
            'Fractions, decimals and percentages — end of unit consolidation '
            'and revision worksheet number three'
        )
        homework = make_homework(
            self.classroom, due=at(date(2026, 8, 22)), title=long_title,
        )
        submit(homework, self.student, 1, 6, when=at(date(2026, 8, 20)))
        report = self._report(periods.MONTHLY, date(2026, 8, 1), date(2026, 8, 31))

        content = text_of(render_report_pdf(report))

        # The title survives in full — a truncated one would silently rename
        # the homework in the copy the parent keeps.
        self.assertIn('consolidation', content)
        self.assertIn('worksheet number three', content)


class PdfCarriesEverySectionTests(TestCase):
    """CPP-400: the downloaded report was missing whole sections.

    The PDF never rendered subject practice at all, and it built the teacher's
    assessment and comment nowhere — so beside the page it was linked from, a
    parent's download read as a truncated document. For a coding report, where
    practice IS the content, it was close to empty.

    These assert against the RENDERED BYTES, not the flowables, because a
    section that is built and then not appended is exactly the failure mode
    here. Compression is turned off for the assertion — reportlab's default
    deflates the text stream, and the alternative was a PDF-parsing dependency
    in requirements-test.txt, which the `shared` CI filter watches.
    """

    @classmethod
    def setUpTestData(cls):
        from classroom.models import (
            ProgressCriteria, ProgressRecord, ProgressReportComment, Subject,
        )

        cls.school = make_school(name='PDF Sections', slug='pdf-sections')
        cls.student = make_user('pdfsec_student', first_name='Aadya')
        cls.subject, _ = Subject.objects.get_or_create(
            slug='coding', school=None, defaults={'name': 'Coding'},
        )
        cls.room = make_classroom(cls.school, name='Web Prog', code='PS000099')
        cls.room.subject = cls.subject
        cls.room.save(update_fields=['subject'])
        enrol(cls.room, cls.student)

        ProgressRecord.objects.create(
            student=cls.student, classroom=cls.room, status='confident',
            criteria=ProgressCriteria.objects.create(
                school=cls.school, name='Writes a loop', status='approved',
            ),
        )
        cls.comment = ProgressReportComment.objects.create(
            student=cls.student, school=cls.school,
            body='Strong term. **Loops** are solid.',
        )

        cls.start, cls.end = periods.previous_week(periods.today())

    def _render(self, data):
        import reportlab.rl_config as rl_config

        from progress.models import PeriodReport
        from progress.pdf import render_report_pdf

        report = PeriodReport(
            student=self.student, school=self.school, subject=self.subject,
            period_type=periods.WEEKLY,
            period_start=self.start, period_end=self.end,
            data=data,
        )
        previous = rl_config.pageCompression
        rl_config.pageCompression = 0
        try:
            return render_report_pdf(report).decode('latin-1')
        finally:
            rl_config.pageCompression = previous

    def _data(self, **over):
        data = {
            'scope': {'classroom_ids': [self.room.id], 'classrooms': ['Web Prog']},
            'totals': {'submissions': 0, 'activity_items': 6, 'assigned': 5,
                       'completed': 3, 'avg_best_pct': 0, 'avg_first_pct': 0},
            'sections_included': {'include_rubric': True,
                                  'include_teacher_comment': True},
            'subject_practice': {
                'items': 6, 'scored_items': 0, 'attempts': 9,
                'sections': [{
                    'label': 'Coding practice', 'items': 6, 'attempts': 9,
                    'rows': [],
                    'topics': [{
                        'name': 'Loops', 'items': 6, 'attempts': 9,
                        'exercises': 6, 'finished': 5, 'scored_items': 0,
                        'first_pct': None, 'best_pct': None,
                    }],
                }],
            },
            'worksheets': {'assigned': 4, 'completed': 2, 'items': []},
            'topics': [], 'attempts': {}, 'trend': [], 'awards': [],
            'quizzes': {}, 'times_tables': {}, 'basic_facts': {},
        }
        data.update(over)
        return data

    def test_the_pdf_carries_the_coding_practice_section(self):
        pdf = self._render(self._data())

        self.assertIn('Coding practice', pdf)
        self.assertIn('Loops', pdf)
        self.assertIn('5 of 6', pdf)

    def test_the_pdf_carries_the_teachers_assessment_and_comment(self):
        pdf = self._render(self._data())

        self.assertIn("Teacher's assessment", pdf)
        self.assertIn('1 of 1 criteria', pdf)
        self.assertIn("Teacher's comment", pdf)
        self.assertIn('Strong term', pdf)

    def test_they_survive_a_report_with_no_submissions(self):
        """The case they matter most, and the one the PDF used to drop.

        has_activity is false here, and the old code returned immediately
        after the empty note — losing exactly the sections a parent needs when
        there is no work to show.
        """
        pdf = self._render(self._data(
            totals={'submissions': 0, 'activity_items': 0},
            subject_practice={},
        ))

        self.assertIn("Teacher's assessment", pdf)
        self.assertIn("Teacher's comment", pdf)

    def test_the_kpi_block_says_how_much_was_set_not_only_how_much_was_done(self):
        """A bare "3 worksheets" cannot be read: three of three, or of ten?"""
        pdf = self._render(self._data())

        self.assertIn('Homework due', pdf)
        self.assertIn('3 of 5', pdf)
        self.assertIn('Worksheets set', pdf)
        self.assertIn('2 of 4', pdf)

    def test_a_capped_topic_chart_says_it_is_capped(self):
        """The other half of CPP-400: the chart silently showed a subset.

        Ten bars is a rendering limit, not a finding. Drawn without a word,
        it reads as the whole picture with topics missing.
        """
        topics = [
            {'topic': f'Topic {index}', 'answered': 4, 'correct': 2,
             'accuracy_pct': 50 + index}
            for index in range(14)
        ]
        pdf = self._render(self._data(topics=topics))

        self.assertIn('The 10 weakest of 14 topics', pdf)

    def test_an_uncapped_topic_chart_makes_no_such_claim(self):
        topics = [
            {'topic': f'Topic {index}', 'answered': 4, 'correct': 2,
             'accuracy_pct': 50 + index}
            for index in range(3)
        ]
        pdf = self._render(self._data(topics=topics))

        self.assertNotIn('weakest of', pdf)
        self.assertIn('weakest topic first', pdf)

    def test_a_zero_scoring_topic_is_still_visible_on_the_chart(self):
        """CPP-400's original title: "Report has incomplete chart".

        A 0% bar has zero height and draws nothing, so its category label sat
        under empty space and the chart read as broken. The chart shows the
        WEAKEST topics, so it selects exactly the bars most likely to vanish —
        three of ten were invisible on the report that raised this.

        Rendered ALONE, deliberately. Asserting "0%" against the whole report
        proves nothing: the at-a-glance block and the topic table below the
        chart both print it, so that version of this test passed against the
        unfixed code. Only the chart is drawn here, so the figure can have
        come from nowhere else.
        """
        from io import BytesIO

        import reportlab.rl_config as rl_config
        from reportlab.platypus import SimpleDocTemplate

        from progress.pdf import _topic_chart

        chart = _topic_chart([
            {'topic': 'Forming and Solving Equations', 'answered': 4,
             'correct': 0, 'accuracy_pct': 0},
            {'topic': 'Money', 'answered': 7, 'correct': 1, 'accuracy_pct': 14},
        ])
        buffer = BytesIO()
        previous = rl_config.pageCompression
        rl_config.pageCompression = 0
        try:
            SimpleDocTemplate(buffer).build([chart])
        finally:
            rl_config.pageCompression = previous
        drawn = buffer.getvalue().decode('latin-1')

        self.assertIn('0%', drawn)
        self.assertIn('14%', drawn)

    def test_a_long_topic_name_is_not_clipped_to_nothing(self):
        """The axis labels are shortened; they must still name the topic."""
        from progress.pdf import _shorten

        self.assertEqual(
            _shorten('Forming and Solving Equations'),
            'Forming and Solving Equat\u2026',
        )
        self.assertEqual(_shorten('Money'), 'Money')
