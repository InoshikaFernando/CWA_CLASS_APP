"""Bank questions whose answer is a drawing must be teacher-graded.

The upload path routes these at classification time and the preview sweeps
sessions that predate that, but neither reaches questions already in the bank —
that is what ``fix_drawing_questions`` is for.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from classroom.models import Level, School, Subject, Topic
from maths.models import Answer, Question


class FixDrawingQuestionsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.subject, _ = Subject.objects.get_or_create(
            name='Mathematics', defaults={'slug': 'mathematics'})
        cls.level, _ = Level.objects.get_or_create(
            level_number=7, subject=cls.subject,
            defaults={'display_name': 'Year 7'})
        cls.topic = Topic.objects.get_or_create(
            name='fdq-probability', subject=cls.subject)[0]
        cls.school = School.objects.create(name='FDQ School', slug='fdq-school')

    def _q(self, text, *, validation='ai_graded', q_type='extended_answer',
           rubric='', school=None, answers=0):
        question = Question.objects.create(
            level=self.level, topic=self.topic, school=school,
            question_text=text, question_type=q_type,
            validation_type=validation, grading_rubric=rubric,
        )
        for i in range(answers):
            Answer.objects.create(
                question=question, answer_text=f'option {i}', is_correct=(i == 0))
        return question

    def _run(self, *args):
        out = StringIO()
        try:
            call_command('fix_drawing_questions', *args, stdout=out, stderr=out)
            code = 0
        except SystemExit as exc:
            code = exc.code
        return out.getvalue(), code

    # -- dry run ---------------------------------------------------------

    def test_dry_run_reports_without_writing_and_fails(self):
        drawing = self._q('Draw a tree diagram to illustrate this situation.')
        output, code = self._run()

        self.assertEqual(code, 1, output)          # drift is a failure signal
        self.assertIn(f'Q{drawing.id}', output)
        self.assertIn('--apply', output)
        drawing.refresh_from_db()
        self.assertEqual(drawing.validation_type, 'ai_graded')

    def test_clean_bank_succeeds(self):
        self._q('What is 24 divided by 6?', validation='auto',
                q_type='short_answer')
        output, code = self._run()

        self.assertEqual(code, 0, output)
        self.assertIn('0 ask for a drawing', output)

    # -- apply -----------------------------------------------------------

    def test_apply_sets_human_graded(self):
        drawing = self._q(
            'Suppose we are rolling a die, so the universal set U = {1, 2, 3, 4, 5, 6}. '
            'Illustrate on a Venn diagram the sets A = {1, 3, 5} and B = {2, 4, 6}.')
        output, code = self._run('--apply')

        self.assertEqual(code, 0, output)
        drawing.refresh_from_db()
        self.assertEqual(drawing.validation_type, 'human_graded')
        self.assertIn('draw', drawing.grading_rubric.lower())

    def test_apply_keeps_an_existing_rubric(self):
        drawing = self._q(
            'Show this information on a Venn diagram.',
            rubric='Full marks: two overlapping circles, 8 in the intersection.')
        self._run('--apply')

        drawing.refresh_from_db()
        self.assertEqual(drawing.validation_type, 'human_graded')
        self.assertIn('8 in the intersection', drawing.grading_rubric)

    def test_running_twice_changes_nothing_the_second_time(self):
        self._q('Draw a bar chart to display this data.')
        self._run('--apply')
        output, code = self._run('--apply')

        self.assertEqual(code, 0, output)
        self.assertIn('0 ask for a drawing', output)

    # -- what must NOT be touched ----------------------------------------

    def test_ordinary_questions_are_left_alone(self):
        auto = self._q('What is 24 divided by 6?', validation='auto',
                       q_type='short_answer')
        essay = self._q('Explain why Stefan cannot be correct.')
        self._run('--apply')

        auto.refresh_from_db()
        essay.refresh_from_db()
        self.assertEqual(auto.validation_type, 'auto')
        self.assertEqual(essay.validation_type, 'ai_graded')

    def test_types_the_app_renders_are_left_alone(self):
        # These say "draw"/"colour" and the app draws the answer surface for
        # them, so re-grading them would break working questions.
        rendered = [
            self._q('Draw a number line from -3 to 7 and show 2.',
                    validation='auto', q_type='number_line'),
            self._q('Draw the line of symmetry on the grid.',
                    validation='auto', q_type='draw_on_grid'),
            self._q('Colour the triangles in this picture.',
                    validation='auto', q_type='shape_select'),
            self._q('Complete the table of values for y = 3x.',
                    validation='auto', q_type='table_of_values'),
        ]
        output, code = self._run('--apply')

        self.assertEqual(code, 0, output)
        for question in rendered:
            question.refresh_from_db()
            self.assertEqual(question.validation_type, 'auto',
                             question.question_text)

    def test_a_table_saved_as_fill_blank_still_goes_to_the_teacher(self):
        # fill_blank renders a sentence with gaps, not a grid, so the table is
        # gone. table_of_values is the only type that can take one.
        gapped = self._q('Complete the table of values for y = 3x: 3, 6, ___, 12.',
                         validation='auto', q_type='fill_blank')
        real_table = self._q('Complete the table of values for y = 3x.',
                             validation='auto', q_type='table_of_values')
        self._run('--apply')

        gapped.refresh_from_db()
        real_table.refresh_from_db()
        self.assertEqual(gapped.validation_type, 'human_graded')
        self.assertEqual(real_table.validation_type, 'auto')

    def test_multiple_choice_with_options_is_left_alone(self):
        mcq = self._q('Which diagram shows the line drawn correctly?',
                      validation='auto', q_type='multiple_choice', answers=3)
        self._run('--apply')

        mcq.refresh_from_db()
        self.assertEqual(mcq.validation_type, 'auto')

    def test_a_teachers_own_human_graded_rubric_is_never_reread(self):
        teacher_marked = self._q(
            'Draw a Venn diagram to show the two sets.',
            validation='human_graded', rubric='My own marking notes.')
        self._run('--apply')

        teacher_marked.refresh_from_db()
        self.assertEqual(teacher_marked.grading_rubric, 'My own marking notes.')

    # -- scoping ---------------------------------------------------------

    def test_school_filter_limits_the_sweep(self):
        mine = self._q('Draw a tree diagram for this situation.', school=self.school)
        global_q = self._q('Draw a tree diagram for this other situation.')
        self._run('--apply', '--school', str(self.school.id))

        mine.refresh_from_db()
        global_q.refresh_from_db()
        self.assertEqual(mine.validation_type, 'human_graded')
        self.assertEqual(global_q.validation_type, 'ai_graded')

    def test_level_filter_limits_the_sweep(self):
        other_level, _ = Level.objects.get_or_create(
            level_number=9, subject=self.subject,
            defaults={'display_name': 'Year 9'})
        year7 = self._q('Draw a tree diagram for this situation.')
        year9 = Question.objects.create(
            level=other_level, topic=self.topic,
            question_text='Draw a Venn diagram for these sets.',
            question_type='extended_answer', validation_type='ai_graded',
        )
        self._run('--apply', '--level', '7')

        year7.refresh_from_db()
        year9.refresh_from_db()
        self.assertEqual(year7.validation_type, 'human_graded')
        self.assertEqual(year9.validation_type, 'ai_graded')

    def test_quiet_suppresses_rows_but_keeps_the_summary(self):
        drawing = self._q('Draw a tree diagram to illustrate this situation.')
        output, _ = self._run('--apply', '--quiet')

        self.assertNotIn(f'Q{drawing.id}', output)
        self.assertIn('1 ask for a drawing', output)
