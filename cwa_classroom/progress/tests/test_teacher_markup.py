"""The teacher-comment markup filter.

A teacher wrote "**for** loops" and a parent read the asterisks. The body is a
plain TextField shown to families, so the fix has to render the markup WITHOUT
letting anything else typed into that box reach the page as HTML.
"""

from django.test import TestCase

from progress.templatetags.report_text import teacher_markup


class TeacherMarkupTests(TestCase):

    def test_bold_renders(self):
        self.assertEqual(
            teacher_markup('understands **for** loops'),
            'understands <strong>for</strong> loops',
        )

    def test_italic_renders(self):
        self.assertEqual(teacher_markup('*really* good'), '<em>really</em> good')

    def test_bold_is_not_read_as_two_italics(self):
        """'**x**' must not become '<em><em>x</em></em>'."""
        self.assertEqual(teacher_markup('**x**'), '<strong>x</strong>')

    def test_newlines_become_breaks(self):
        self.assertEqual(teacher_markup('one\ntwo'), 'one<br>two')

    def test_html_a_teacher_types_is_inert(self):
        """The load-bearing one: escape first, convert after."""
        self.assertEqual(
            teacher_markup('<script>alert(1)</script>'),
            '&lt;script&gt;alert(1)&lt;/script&gt;',
        )

    def test_an_img_onerror_cannot_survive_the_bold_rule(self):
        out = teacher_markup('**<img src=x onerror=alert(1)>**')

        self.assertIn('&lt;img', out)
        self.assertNotIn('<img', out)

    def test_a_lone_asterisk_is_left_alone(self):
        self.assertEqual(teacher_markup('2 * 3 = 6'), '2 * 3 = 6')

    def test_empty_and_none_are_safe(self):
        self.assertEqual(teacher_markup(''), '')
        self.assertEqual(teacher_markup(None), '')
