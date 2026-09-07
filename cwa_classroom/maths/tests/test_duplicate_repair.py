"""Replacing a duplicated option with a distinct value (CPP-377).

The safety condition is narrow and checkable: multiple choice is graded purely
on ``Answer.is_correct``, so a generated distractor only has to differ from the
option the grader accepts. It never has to be proved mathematically wrong.
"""
from django.core.management import call_command
from django.test import TestCase

from classroom.models import Level, Subject, Topic
from maths.answer_values import parse_answer_value
from maths.answer_verification import verify_question
from maths.duplicate_repair import Skipped, plan_repair
from maths.models import Answer, Question


class RepairTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        cls.level = Level.objects.create(level_number=977, display_name='Repair')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Repair Addition', slug='repair-addition')

    def _question(self, text, options, qtype='multiple_choice'):
        question = Question.objects.create(
            level=self.level, topic=self.topic, question_text=text,
            question_type=qtype)
        for order, (label, correct) in enumerate(options):
            Answer.objects.create(question=question, answer_text=label,
                                  is_correct=correct, order=order)
        return question

    def _texts(self, question):
        return [a.answer_text for a in question.answers.order_by('order', 'id')]


class PlanRepairTests(RepairTestBase):

    def test_a_repeated_wrong_option_is_replaced_not_removed(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False),
                            ('14', False)])
        edits = plan_repair(q)

        self.assertEqual(len(edits), 1)
        _answer, old, new = edits[0]
        self.assertEqual(old, '14')
        self.assertNotEqual(new, '14')
        # The option count is preserved — that is the point of replacing.
        self.assertEqual(q.answers.count(), 4)

    def test_the_replacement_differs_from_every_other_option(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False),
                            ('14', False)])
        _answer, _old, new = plan_repair(q)[0]

        existing = {'15', '14', '16'}
        self.assertNotIn(new, existing)
        self.assertNotIn(parse_answer_value(new),
                         {parse_answer_value(t) for t in existing})

    def test_the_replacement_is_never_the_accepted_answer(self):
        # The whole safety condition, stated directly.
        q = self._question('What is 7 + 8?',
                           [('15', True), ('16', False), ('16', False)])
        _answer, _old, new = plan_repair(q)[0]
        self.assertNotEqual(parse_answer_value(new), parse_answer_value('15'))

    def test_the_unselected_copy_of_the_answer_is_the_one_replaced(self):
        # DUPLICATE-CORRECT: '3' correct and '3' as a distractor. The CORRECT
        # option must survive untouched; the copy that mismarks is replaced.
        q = self._question('How many factors does 9 have?',
                           [('3', True), ('3', False), ('4', False)])
        edits = plan_repair(q)

        self.assertEqual(len(edits), 1)
        answer, old, new = edits[0]
        self.assertFalse(answer.is_correct)
        self.assertEqual(old, '3')
        self.assertNotEqual(new, '3')

    def test_replacements_stay_whole_when_the_options_are_whole(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False),
                            ('14', False)])
        _answer, _old, new = plan_repair(q)[0]
        self.assertNotIn('.', new)
        self.assertNotIn('/', new)

    def test_a_negative_is_not_introduced_among_positives(self):
        q = self._question('What is 1 + 1?',
                           [('2', True), ('1', False), ('1', False)])
        _answer, _old, new = plan_repair(q)[0]
        self.assertFalse(new.startswith('-'))

    def test_a_clean_question_yields_no_edits(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False)])
        self.assertEqual(plan_repair(q), [])


class RefusalTests(RepairTestBase):
    """What it declines to touch, and why."""

    def test_text_options_are_refused(self):
        # A generated number among word answers would be nonsense.
        q = self._question('Which shape has three sides?',
                           [('triangle', True), ('square', False),
                            ('square', False)])
        with self.assertRaises(Skipped):
            plan_repair(q)

    def test_a_question_with_no_correct_option_is_refused(self):
        q = self._question('What is 7 + 8?',
                           [('14', False), ('14', False), ('16', False)])
        with self.assertRaises(Skipped):
            plan_repair(q)

    def test_a_question_with_two_correct_options_is_refused(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('15', True), ('16', False)])
        with self.assertRaises(Skipped):
            plan_repair(q)

    def test_a_two_option_question_is_refused(self):
        q = self._question('True or false?', [('14', True), ('14', False)])
        with self.assertRaises(Skipped):
            plan_repair(q)

    def test_a_blank_option_is_refused(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('', False), ('14', False),
                            ('14', False)])
        with self.assertRaises(Skipped):
            plan_repair(q)


class CommandTests(RepairTestBase):

    def test_a_dry_run_changes_nothing(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False),
                            ('14', False)])
        call_command('repair_duplicate_options', '--level', 977)
        self.assertEqual(self._texts(q), ['15', '14', '16', '14'])

    def test_apply_writes_the_replacement(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False),
                            ('14', False)])
        call_command('repair_duplicate_options', '--level', 977, '--apply')

        texts = self._texts(q)
        self.assertEqual(len(texts), 4)
        self.assertEqual(len(set(texts)), 4, f'still has a duplicate: {texts}')
        self.assertIn('15', texts)

    def test_apply_records_what_it_replaced(self):
        # Reversible without a database backup.
        from audit.models import AuditLog

        self._question('What is 7 + 8?',
                       [('15', True), ('14', False), ('16', False),
                        ('14', False)])
        call_command('repair_duplicate_options', '--level', 977, '--apply')

        event = AuditLog.objects.filter(
            action='duplicate_option_repaired').first()
        self.assertIsNotNone(event)
        self.assertEqual(event.detail['edits'][0]['was'], '14')

    def test_blocking_only_leaves_the_cosmetic_ones_alone(self):
        mismark = self._question('How many factors does 9 have?',
                                 [('3', True), ('3', False), ('4', False)])
        cosmetic = self._question('What is 7 + 8?',
                                  [('15', True), ('14', False), ('16', False),
                                   ('14', False)])

        call_command('repair_duplicate_options', '--level', 977,
                     '--blocking-only', '--apply')

        self.assertEqual(len(set(self._texts(mismark))), 3)
        self.assertEqual(self._texts(cosmetic), ['15', '14', '16', '14'])

    def test_a_question_with_another_blocking_fault_is_left_alone(self):
        # WRONG-ANSWER-KEY as well as a duplicate: repairing the duplicate
        # would make the row look handled while the real fault remains.
        q = self._question('Calculate: 7 + 8',
                           [('12', True), ('14', False), ('16', False),
                            ('14', False)])
        call_command('repair_duplicate_options', '--level', 977, '--apply')
        self.assertEqual(self._texts(q), ['12', '14', '16', '14'])

    def test_the_repaired_question_no_longer_verifies_as_broken(self):
        from maths.answer_verification import verify_question

        q = self._question('How many factors does 9 have?',
                           [('3', True), ('3', False), ('4', False)])
        call_command('repair_duplicate_options', '--level', 977, '--apply')

        q.refresh_from_db()
        issues, _ = verify_question(q)
        self.assertEqual([i.code for i in issues], [])


class BulkFixViewTests(RepairTestBase):
    """Selecting questions on the check page and applying one fix."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from django.contrib.auth import get_user_model

        User = get_user_model()
        cls.superuser = User.objects.create_superuser(
            username='bulkadmin', email='bulk@test.com', password='pass1234')
        cls.student = User.objects.create_user(
            username='bulkstudent', email='bs@test.com', password='pass1234')

    def setUp(self):
        from django.test import Client
        from django.urls import reverse

        self.client = Client()
        self.client.login(username='bulkadmin', password='pass1234')
        self.url = reverse('question_bulk_fix_admin_dashboard')

    def _post(self, action, ids):
        return self.client.post(
            self.url, {'action': action, 'question_id': [str(i) for i in ids]},
            follow=True)

    def _notes(self, response):
        return [m.message for m in response.context['messages']]

    def test_replace_duplicates_across_a_selection(self):
        a = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False),
                            ('14', False)])
        b = self._question('How many factors does 9 have?',
                           [('3', True), ('3', False), ('4', False)])

        self._post('replace_duplicates', [a.id, b.id])

        for question in (a, b):
            texts = self._texts(question)
            self.assertEqual(len(set(texts)), len(texts),
                             f'Q{question.id} still has a duplicate: {texts}')

    def test_padding_brings_a_lone_option_up_to_four(self):
        # The Q3761 case: a "multiple choice" left with one option.
        q = self._question('1 + 2 = ?', [('3', True)])

        self._post('pad_options', [q.id])

        texts = self._texts(q)
        self.assertEqual(len(texts), 4)
        self.assertEqual(len(set(texts)), 4)
        self.assertEqual(q.answers.filter(is_correct=True).count(), 1)
        self.assertIn('3', texts)

    def test_padding_never_adds_the_accepted_answer_again(self):
        q = self._question('1 + 2 = ?', [('3', True)])
        self._post('pad_options', [q.id])

        wrong = [a.answer_text for a in q.answers.filter(is_correct=False)]
        self.assertNotIn('3', wrong)

    def test_converting_to_short_answer(self):
        q = self._question('1 + 2 = ?', [('3', True)])

        self._post('to_short_answer', [q.id])

        q.refresh_from_db()
        self.assertEqual(q.question_type, 'short_answer')
        # The stored option survives — it is what a typed answer grades against.
        self.assertEqual(self._texts(q), ['3'])

    def test_only_the_selected_questions_are_touched(self):
        selected = self._question('What is 7 + 8?',
                                  [('15', True), ('14', False), ('16', False),
                                   ('14', False)])
        other = self._question('What is 6 + 8?',
                               [('14', True), ('13', False), ('16', False),
                                ('13', False)])

        self._post('replace_duplicates', [selected.id])

        self.assertEqual(self._texts(other), ['14', '13', '16', '13'])

    def test_a_question_it_cannot_fix_is_named_not_silently_skipped(self):
        q = self._question('Which shape has three sides?',
                           [('triangle', True), ('square', False),
                            ('square', False)])

        response = self._post('replace_duplicates', [q.id])

        notes = ' '.join(self._notes(response))
        self.assertIn(f'Q{q.id}', notes)
        self.assertIn('not all single numbers', notes)

    def test_an_unknown_action_changes_nothing(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False),
                            ('14', False)])
        self._post('drop_the_table', [q.id])
        self.assertEqual(self._texts(q), ['15', '14', '16', '14'])

    def test_an_empty_selection_is_refused(self):
        response = self._post('replace_duplicates', [])
        self.assertIn('Nothing to do', ' '.join(self._notes(response)))

    def test_a_non_superuser_cannot_apply_fixes(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False),
                            ('14', False)])
        self.client.login(username='bulkstudent', password='pass1234')

        self.client.post(self.url, {'action': 'replace_duplicates',
                                    'question_id': [str(q.id)]})

        self.assertEqual(self._texts(q), ['15', '14', '16', '14'])

    def test_the_fix_is_recorded_in_the_audit_log(self):
        from audit.models import AuditLog

        q = self._question('1 + 2 = ?', [('3', True)])
        self._post('pad_options', [q.id])

        event = AuditLog.objects.filter(action='bulk_fix_pad_options').first()
        self.assertIsNotNone(event)
        self.assertEqual(event.detail['question_id'], q.id)


class TrimOptionsTests(BulkFixViewTests):
    """Trimming a question back to four options, correct one kept."""

    def test_a_six_option_question_is_cut_to_four(self):
        q = self._question('Calculate the area of this shape.',
                           [('120', True), ('49', False), ('69', False),
                            ('39', False), ('984', False), ('12', False)])

        self._post('trim_options', [q.id])

        texts = self._texts(q)
        self.assertEqual(len(texts), 4)
        self.assertIn('120', texts)

    def test_the_correct_option_always_survives(self):
        # Even when it is last in the display order — dropping from the end
        # must never take the answer with it.
        q = self._question('Calculate the area of this shape.',
                           [('49', False), ('69', False), ('39', False),
                            ('984', False), ('120', True)])

        self._post('trim_options', [q.id])

        self.assertEqual(q.answers.filter(is_correct=True).count(), 1)
        self.assertIn('120', self._texts(q))
        self.assertEqual(len(self._texts(q)), 4)

    def test_a_four_option_question_is_left_alone(self):
        q = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False),
                            ('13', False)])
        self._post('trim_options', [q.id])
        self.assertEqual(self._texts(q), ['15', '14', '16', '13'])

    def test_two_correct_options_are_refused(self):
        # Choosing which to drop would be choosing the answer.
        q = self._question('What is 7 + 8?',
                           [('15', True), ('15', True), ('14', False),
                            ('16', False), ('13', False)])

        response = self._post('trim_options', [q.id])

        self.assertEqual(len(self._texts(q)), 5)
        self.assertIn('exactly one correct option',
                      ' '.join(self._notes(response)))

    def test_what_was_removed_is_recorded(self):
        from audit.models import AuditLog

        q = self._question('Calculate the area of this shape.',
                           [('120', True), ('49', False), ('69', False),
                            ('39', False), ('984', False)])

        self._post('trim_options', [q.id])

        event = AuditLog.objects.filter(action='bulk_fix_trim_options').first()
        self.assertIsNotNone(event)
        self.assertEqual([r['was'] for r in event.detail['removed']], ['984'])


class TooManyOptionsFlagTests(RepairTestBase):
    """A question with surplus options has to be findable before it can be fixed."""

    def test_more_than_four_options_is_reported(self):
        from maths.answer_verification import verify_question

        q = self._question('Calculate the area of this shape.',
                           [('120', True), ('49', False), ('69', False),
                            ('39', False), ('984', False)])
        issues, _ = verify_question(q)
        self.assertIn('TOO-MANY-OPTIONS', [i.code for i in issues])

    def test_four_options_is_not_reported(self):
        from maths.answer_verification import verify_question

        q = self._question('What is 7 + 8?',
                           [('15', True), ('14', False), ('16', False),
                            ('13', False)])
        self.assertEqual([i.code for i in verify_question(q)[0]], [])

    def test_it_is_advisory_not_a_mismark(self):
        # An extra choice cannot mark anyone wrong, so it must not inflate the
        # headline count the way duplicated options did.
        from maths.management.commands.verify_question_answers import (
            ADVISORY_CODES)
        self.assertIn('TOO-MANY-OPTIONS', ADVISORY_CODES)


class EquivalentOptionRepairTests(TestCase):
    """A distractor that is the correct answer written differently.

    This is the CPP-377 defect itself — '6/10' offered against a correct
    '3/5' marks a student wrong for a right answer. The bulk fixer used to
    answer "nothing to change" on it, because it only looked for repeated
    TEXT and these two strings differ.
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=989, defaults={'display_name': 'equiv fixture'})

    def _question(self, options, text='Calculate: 4/5 - 2/10'):
        q = Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1)
        for order, (answer_text, is_correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=is_correct, order=order)
        return q

    def _apply(self, question):
        edits = plan_repair(question)
        for answer, _old, new in edits:
            answer.answer_text = new
            answer.save(update_fields=['answer_text'])
        return edits

    def test_production_q6065_is_repaired(self):
        # The exact question from the check page: 3/5 correct, 6/10 the same
        # number wearing a different face.
        q = self._question([('3/5', True), ('6/10', False),
                            ('2/5', False), ('1/5', False)])

        edits = self._apply(q)

        self.assertEqual(1, len(edits))
        answer, old, _new = edits[0]
        self.assertEqual('6/10', old)
        self.assertFalse(answer.is_correct)

    def test_the_correct_option_is_never_the_one_rewritten(self):
        q = self._question([('3/5', True), ('6/10', False),
                            ('2/5', False), ('1/5', False)])
        self._apply(q)

        correct = q.answers.get(is_correct=True)
        self.assertEqual('3/5', correct.answer_text)

    def test_after_repair_no_option_equals_the_answer(self):
        q = self._question([('3/5', True), ('6/10', False),
                            ('2/5', False), ('1/5', False)])
        self._apply(q)

        values = [parse_answer_value(a.answer_text)
                  for a in q.answers.order_by('order')]
        correct_value = parse_answer_value(
            q.answers.get(is_correct=True).answer_text)
        self.assertEqual(1, values.count(correct_value))

    def test_the_verifier_stops_flagging_the_repaired_question(self):
        # The real test of a repair: the check page no longer reports it.
        q = self._question([('3/5', True), ('6/10', False),
                            ('2/5', False), ('1/5', False)])
        self._apply(q)

        q.refresh_from_db()
        issues, _ = verify_question(q)
        self.assertEqual([], [i.code for i in issues])

    def test_a_decimal_written_as_a_fraction_is_caught(self):
        q = self._question([('0.5', True), ('1/2', False),
                            ('0.25', False), ('0.75', False)],
                           text='What is half?')
        edits = self._apply(q)
        self.assertEqual(['1/2'], [old for _a, old, _n in edits])

    def test_two_distractors_sharing_a_value_are_separated(self):
        # Nobody is mismarked here — both are wrong — but the question offers
        # three real choices while appearing to offer four.
        q = self._question([('3/5', True), ('1/2', False),
                            ('2/4', False), ('1/5', False)])

        self._apply(q)
        q.refresh_from_db()

        values = [parse_answer_value(a.answer_text) for a in q.answers.all()]
        self.assertEqual(len(values), len(set(values)))

    def test_a_literal_repeat_and_a_value_clash_are_both_repaired(self):
        q = self._question([('3/5', True), ('6/10', False),
                            ('1/5', False), ('1/5', False)])

        self._apply(q)
        q.refresh_from_db()

        values = [parse_answer_value(a.answer_text) for a in q.answers.all()]
        self.assertEqual(4, len(set(values)))

    def test_a_question_with_no_clash_is_still_left_alone(self):
        q = self._question([('3/5', True), ('2/5', False),
                            ('1/5', False), ('4/5', False)])
        self.assertEqual([], plan_repair(q))

    def test_text_options_are_still_refused_rather_than_guessed(self):
        q = self._question([('north', True), ('North', False),
                            ('south', False), ('east', False)])
        with self.assertRaises(Skipped):
            plan_repair(q)


class RepairCommandEquivalenceTests(TestCase):
    """The CLI must repair the same questions the UI does.

    The command gated on the issue code BEFORE planning a repair, so a
    question whose only fault was EQUIVALENT-OPTION never reached plan_repair
    — the fix worked from the check page and silently skipped from a shell.
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=988, defaults={'display_name': 'cmd equiv fixture'})

    def _question(self, options, text='Calculate: 4/5 - 2/10'):
        q = Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1)
        for order, (answer_text, is_correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=is_correct, order=order)
        return q

    def test_apply_repairs_an_equivalent_distractor(self):
        q = self._question([('3/5', True), ('6/10', False),
                            ('2/5', False), ('1/5', False)])

        call_command('repair_duplicate_options', '--apply', '--level', 988)

        q.refresh_from_db()
        texts = {a.answer_text for a in q.answers.all()}
        self.assertNotIn('6/10', texts)
        self.assertIn('3/5', texts)

    def test_a_dry_run_still_changes_nothing(self):
        q = self._question([('3/5', True), ('6/10', False),
                            ('2/5', False), ('1/5', False)])

        call_command('repair_duplicate_options', '--level', 988)

        q.refresh_from_db()
        self.assertIn('6/10', {a.answer_text for a in q.answers.all()})

    def test_blocking_only_includes_an_equivalent_distractor(self):
        # A student picking it is marked wrong for a right answer, so it
        # belongs in the same pass as a duplicated correct answer.
        q = self._question([('3/5', True), ('6/10', False),
                            ('2/5', False), ('1/5', False)])

        call_command('repair_duplicate_options', '--apply', '--blocking-only',
                     '--level', 988)

        q.refresh_from_db()
        self.assertNotIn('6/10', {a.answer_text for a in q.answers.all()})

    def test_blocking_only_still_skips_a_merely_untidy_question(self):
        # Two distractors sharing a value cannot mismark anyone.
        q = self._question([('3/5', True), ('1/2', False),
                            ('2/4', False), ('1/5', False)])

        call_command('repair_duplicate_options', '--apply', '--blocking-only',
                     '--level', 988)

        q.refresh_from_db()
        self.assertIn('2/4', {a.answer_text for a in q.answers.all()})


class UnitAwareRepairTests(TestCase):
    """The repair must never rewrite an option whose unit makes it distinct.

    An estimation question repeats the number on purpose — '4 kg' against
    '4 g' — so a repair that treated them as duplicates would replace a good
    distractor and destroy the question it was asked to fix.
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=986, defaults={'display_name': 'unit repair fixture'})

    def _question(self, options, text='The mass of a pet cat would be about:'):
        q = Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1)
        for order, (answer_text, is_correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=is_correct, order=order)
        return q

    def test_the_same_number_in_different_units_is_left_alone(self):
        q = self._question([('4 kg', True), ('4 g', False),
                            ('40 g', False), ('400 g', False)])
        self.assertEqual([], plan_repair(q))

    def test_the_same_number_in_the_same_unit_is_still_repaired(self):
        q = self._question([('3 kg', True), ('9/3 kg', False),
                            ('4 kg', False), ('5 kg', False)])
        edits = plan_repair(q)
        self.assertEqual(['9/3 kg'], [old for _a, old, _n in edits])

    def test_a_bulk_fix_over_the_pet_cat_question_changes_nothing(self):
        # End to end: the exact production question, through the code path the
        # check page's "Replace duplicated options" uses.
        q = self._question([('4 t', False), ('4 kg', True),
                            ('400 g', False), ('4 g', False)])
        before = [a.answer_text for a in q.answers.order_by('order')]

        try:
            edits = plan_repair(q)
        except Skipped:
            edits = []
        for answer, _old, new in edits:
            answer.answer_text = new
            answer.save(update_fields=['answer_text'])

        q.refresh_from_db()
        after = [a.answer_text for a in q.answers.order_by('order')]
        self.assertEqual(before, after)
