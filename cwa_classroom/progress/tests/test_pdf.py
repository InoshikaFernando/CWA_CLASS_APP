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
