"""The school's letterhead on a progress report.

Resolved through School.get_effective_settings — the same resolver the
invoices render from — so a school that has set a letterhead for its invoices
already has one here, and the school -> department cascade that settings
already provides applies without a second notion of "the letterhead".
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from classroom.models import Department, School, SchoolTeacher
from progress import periods
from progress.models import PeriodReport
from progress.tests.factories import enrol, make_classroom, make_school, make_user
from progress.views_reports import letterhead_for

# Smallest valid GIF, so the field has a real file without a fixture on disk.
GIF = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!'
    b'\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00'
    b'\x00\x02\x02D\x01\x00;'
)


class LetterheadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school(name='Wizards', slug='wizards')
        cls.student = make_user('lh_student', first_name='Avisha')
        cls.start, cls.end = periods.previous_week(periods.today())

    def _report(self, school=None, classroom_ids=None):
        return PeriodReport(
            student=self.student, school=school if school is not None else self.school,
            period_type=periods.WEEKLY,
            period_start=self.start, period_end=self.end,
            data={'scope': {'classroom_ids': classroom_ids or []}},
        )

    def _logo(self, name='logo.gif'):
        return SimpleUploadedFile(name, GIF, content_type='image/gif')

    def test_a_school_with_no_logo_and_no_address_has_no_letterhead(self):
        """Better a plain heading than an empty bar pretending to be one."""
        self.assertIsNone(letterhead_for(self._report()))

    def test_an_address_alone_is_a_letterhead(self):
        self.school.street_address = '12 Wizard Lane'
        self.school.city = 'Auckland'
        self.school.save(update_fields=['street_address', 'city'])

        head = letterhead_for(self._report())

        self.assertEqual(head['name'], 'Wizards')
        self.assertEqual(head['address'], '12 Wizard Lane, Auckland')
        self.assertIsNone(head['logo'])

    def test_a_logo_alone_is_a_letterhead(self):
        self.school.logo = self._logo()
        self.school.save(update_fields=['logo'])

        head = letterhead_for(self._report())

        self.assertTrue(head['logo'])

    def test_an_individual_learner_has_none(self):
        self.assertIsNone(letterhead_for(self._report(school=None)))

    def test_a_department_letterhead_overrides_the_schools(self):
        """The cascade settings already provide — not a new rule."""
        self.school.logo = self._logo('school.gif')
        self.school.street_address = 'School Street'
        self.school.save(update_fields=['logo', 'street_address'])

        dept = Department.objects.create(
            name='Coding', slug='coding-lh', school=self.school,
            street_address='Coding Street',
        )
        room = make_classroom(self.school, name='Web', code='LH000001')
        room.department = dept
        room.save(update_fields=['department'])

        head = letterhead_for(self._report(classroom_ids=[room.id]))

        self.assertEqual(head['address'], 'Coding Street')
        self.assertEqual(head['department'], 'Coding')

    def test_two_departments_fall_back_to_the_school(self):
        """No single letterhead to print, so print the school's rather than
        picking one of them."""
        self.school.street_address = 'School Street'
        self.school.save(update_fields=['street_address'])

        rooms = []
        for index, name in enumerate(['Coding', 'Maths']):
            dept = Department.objects.create(
                name=name, slug=f'{name.lower()}-two', school=self.school,
                street_address=f'{name} Street',
            )
            room = make_classroom(self.school, name=name, code=f'LH00001{index}')
            room.department = dept
            room.save(update_fields=['department'])
            rooms.append(room)

        head = letterhead_for(self._report(classroom_ids=[r.id for r in rooms]))

        self.assertEqual(head['address'], 'School Street')
        self.assertEqual(head['department'], '')


class LetterheadPdfTests(TestCase):
    """The PDF is the copy a family keeps; it carries the same letterhead."""

    @classmethod
    def setUpTestData(cls):
        cls.school = make_school(name='Wizards PDF', slug='wizards-pdf')
        cls.student = make_user('lhp_student', first_name='Avisha')
        cls.start, cls.end = periods.previous_week(periods.today())

    def _report(self):
        return PeriodReport(
            student=self.student, school=self.school,
            period_type=periods.WEEKLY,
            period_start=self.start, period_end=self.end,
            data={'scope': {'classroom_ids': []}, 'totals': {}},
        )

    def test_the_pdf_renders_with_a_letterhead(self):
        from progress.pdf import render_report_pdf

        self.school.street_address = '12 Wizard Lane'
        self.school.save(update_fields=['street_address'])

        pdf = render_report_pdf(self._report())

        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_an_unreadable_logo_does_not_stop_the_download(self):
        """A missing image file must not deny a parent their child's report."""
        from progress.pdf import render_report_pdf

        self.school.logo = 'school_logos/does-not-exist.png'
        self.school.save(update_fields=['logo'])

        pdf = render_report_pdf(self._report())

        self.assertTrue(pdf.startswith(b'%PDF'))
