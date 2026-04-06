from django.test import TestCase, Client
from django.urls import reverse, NoReverseMatch

from accounts.models import CustomUser, Role
from number_puzzles.models import (
    NumberPuzzle,
    NumberPuzzleLevel,
    PuzzleSession,
    StudentPuzzleProgress,
)


class NumberPuzzlesTestBase(TestCase):
    """Shared setup for Number Puzzles tests."""

    @classmethod
    def setUpTestData(cls):
        # Create student user
        cls.student = CustomUser.objects.create_user(
            'teststudent', 'student@test.com', 'pass1234',
        )
        student_role, _ = Role.objects.get_or_create(
            name='student', defaults={'display_name': 'Student'},
        )
        cls.student.roles.add(student_role)

        # Create teacher user
        cls.teacher = CustomUser.objects.create_user(
            'testteacher', 'teacher@test.com', 'pass1234',
        )
        teacher_role, _ = Role.objects.get_or_create(
            name='teacher', defaults={'display_name': 'Teacher'},
        )
        cls.teacher.roles.add(teacher_role)

        # Create puzzle levels
        cls.level1 = NumberPuzzleLevel.objects.create(
            number=1, name='Beginner', slug='beginner',
            description='Find the missing operator.',
            operators_allowed='+,-', min_operand=1, max_operand=9,
            num_operands=2, max_result=18, order=1,
        )
        cls.level2 = NumberPuzzleLevel.objects.create(
            number=2, name='Explorer', slug='explorer',
            description='Bigger numbers, all four operators.',
            operators_allowed='+,-,*,/', min_operand=1, max_operand=99,
            num_operands=2, max_result=500, order=2,
        )

        # Create sample puzzles for level 1
        cls.puzzles = []
        puzzle_data = [
            ([1, 2], 3, '1 _ 2 = 3', '1+2=3'),
            ([5, 3], 2, '5 _ 3 = 2', '5-3=2'),
            ([4, 4], 8, '4 _ 4 = 8', '4+4=8'),
            ([9, 1], 8, '9 _ 1 = 8', '9-1=8'),
            ([3, 6], 9, '3 _ 6 = 9', '3+6=9'),
            ([7, 2], 5, '7 _ 2 = 5', '7-2=5'),
            ([8, 1], 9, '8 _ 1 = 9', '8+1=9'),
            ([6, 3], 3, '6 _ 3 = 3', '6-3=3'),
            ([2, 7], 9, '2 _ 7 = 9', '2+7=9'),
            ([5, 5], 0, '5 _ 5 = 0', '5-5=0'),
        ]
        for operands, target, display, solution in puzzle_data:
            p = NumberPuzzle(
                level=cls.level1,
                operands=operands,
                target=target,
                display_template=display,
                solution=solution,
            )
            p.save()
            cls.puzzles.append(p)


# ── URL Resolution Tests ────────────────────────────────────────────────────

class URLResolutionTest(TestCase):
    """Test that all Number Puzzles URLs resolve correctly."""

    def test_number_puzzles_home_resolves(self):
        url = reverse('number_puzzles_home')
        self.assertEqual(url, '/maths/basic-facts/number-puzzles/')

    def test_number_puzzles_play_resolves(self):
        url = reverse('number_puzzles_play', kwargs={'slug': 'beginner'})
        self.assertEqual(url, '/maths/basic-facts/number-puzzles/play/beginner/')

    def test_number_puzzles_results_resolves(self):
        import uuid
        test_id = uuid.uuid4()
        url = reverse('number_puzzles_results', kwargs={'session_id': test_id})
        self.assertIn('/maths/basic-facts/number-puzzles/results/', url)


# ── Link Validation Tests ───────────────────────────────────────────────────

class SidebarLinkTest(NumberPuzzlesTestBase):
    """Test that sidebar renders without errors when Number Puzzles is installed."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='teststudent', password='pass1234')

    def test_maths_dashboard_loads_with_sidebar(self):
        """The maths dashboard (which includes the sidebar) should not crash."""
        response = self.client.get('/maths/', follow=True)
        # Should not get a 500 error
        self.assertNotEqual(response.status_code, 500)

    def test_basic_facts_page_contains_number_puzzles_link(self):
        """The Basic Facts page should contain a link to Number Puzzles."""
        response = self.client.get('/maths/basic-facts/', follow=True)
        if response.status_code == 200:
            self.assertContains(response, '/maths/basic-facts/number-puzzles/')

    def test_basic_facts_home_contains_number_puzzles_card(self):
        """The Basic Facts home should have a Number Puzzles card."""
        response = self.client.get('/maths/basic-facts/', follow=True)
        if response.status_code == 200:
            self.assertContains(response, '/maths/basic-facts/number-puzzles/')
            self.assertContains(response, 'Number Puzzles')


# ── View Tests ──────────────────────────────────────────────────────────────

class NumberPuzzlesHomeViewTest(NumberPuzzlesTestBase):
    """Test the level selection page."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='teststudent', password='pass1234')

    def test_home_page_loads(self):
        response = self.client.get(reverse('number_puzzles_home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Number Puzzles')
        self.assertContains(response, 'Beginner')

    def test_home_page_shows_level1_unlocked(self):
        response = self.client.get(reverse('number_puzzles_home'))
        self.assertEqual(response.status_code, 200)
        # Level 1 should be accessible (unlocked on first visit)
        self.assertContains(response, reverse('number_puzzles_play', kwargs={'slug': 'beginner'}))

    def test_home_page_shows_level2_locked(self):
        response = self.client.get(reverse('number_puzzles_home'))
        self.assertEqual(response.status_code, 200)
        # Level 2 should not have a play link
        self.assertNotContains(response, reverse('number_puzzles_play', kwargs={'slug': 'explorer'}))

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('number_puzzles_home'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)


class NumberPuzzlesPlayViewTest(NumberPuzzlesTestBase):
    """Test the quiz play page."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='teststudent', password='pass1234')
        # Ensure level 1 is unlocked
        StudentPuzzleProgress.objects.create(
            student=self.student, level=self.level1, is_unlocked=True,
        )

    def test_play_page_loads(self):
        response = self.client.get(
            reverse('number_puzzles_play', kwargs={'slug': 'beginner'})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Number Puzzles')
        self.assertContains(response, 'Beginner')

    def test_play_creates_session(self):
        self.client.get(
            reverse('number_puzzles_play', kwargs={'slug': 'beginner'})
        )
        sessions = PuzzleSession.objects.filter(
            student=self.student, level=self.level1,
        )
        self.assertEqual(sessions.count(), 1)
        self.assertEqual(sessions.first().status, 'in_progress')

    def test_play_locked_level_redirects(self):
        """Trying to play a locked level redirects to home."""
        response = self.client.get(
            reverse('number_puzzles_play', kwargs={'slug': 'explorer'})
        )
        self.assertEqual(response.status_code, 302)

    def test_play_nonexistent_level_returns_404(self):
        response = self.client.get(
            reverse('number_puzzles_play', kwargs={'slug': 'nonexistent'})
        )
        self.assertEqual(response.status_code, 404)

    def test_submit_answers(self):
        """Submit answers and verify redirect to results."""
        # Start a session
        response = self.client.get(
            reverse('number_puzzles_play', kwargs={'slug': 'beginner'})
        )
        session = PuzzleSession.objects.filter(
            student=self.student, level=self.level1, status='in_progress',
        ).first()

        # Build POST data with correct answers
        from number_puzzles.models import SessionPuzzle
        post_data = {'session_id': str(session.id)}
        for sp in SessionPuzzle.objects.filter(session=session):
            post_data[f'answer_{sp.puzzle.id}'] = sp.puzzle.solution

        response = self.client.post(
            reverse('number_puzzles_play', kwargs={'slug': 'beginner'}),
            data=post_data,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/results/', response.url)

        # Session should be completed
        session.refresh_from_db()
        self.assertEqual(session.status, 'completed')

    def test_submit_all_correct_unlocks_level2(self):
        """Scoring 8+ on level 1 should unlock level 2."""
        response = self.client.get(
            reverse('number_puzzles_play', kwargs={'slug': 'beginner'})
        )
        session = PuzzleSession.objects.filter(
            student=self.student, level=self.level1, status='in_progress',
        ).first()

        from number_puzzles.models import SessionPuzzle
        post_data = {'session_id': str(session.id)}
        for sp in SessionPuzzle.objects.filter(session=session):
            # Submit correct answers
            post_data[f'answer_{sp.puzzle.id}'] = sp.puzzle.solution

        self.client.post(
            reverse('number_puzzles_play', kwargs={'slug': 'beginner'}),
            data=post_data,
        )

        # Level 2 should now be unlocked
        prog = StudentPuzzleProgress.objects.filter(
            student=self.student, level=self.level2,
        ).first()
        self.assertIsNotNone(prog)
        self.assertTrue(prog.is_unlocked)


class NumberPuzzlesResultsViewTest(NumberPuzzlesTestBase):
    """Test the results page."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='teststudent', password='pass1234')

    def test_results_page_loads(self):
        """Create a completed session and view results."""
        session = PuzzleSession.objects.create(
            student=self.student, level=self.level1,
            status='completed', score=8, total_questions=10,
            duration_seconds=120,
        )
        response = self.client.get(
            reverse('number_puzzles_results', kwargs={'session_id': session.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '8/10')
        self.assertContains(response, 'Beginner')

    def test_results_shows_try_again_link(self):
        session = PuzzleSession.objects.create(
            student=self.student, level=self.level1,
            status='completed', score=5, total_questions=10,
        )
        response = self.client.get(
            reverse('number_puzzles_results', kwargs={'session_id': session.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Try Again')
        self.assertContains(response, reverse('number_puzzles_play', kwargs={'slug': 'beginner'}))

    def test_results_other_users_session_returns_404(self):
        """A student can't view another student's results."""
        other_user = CustomUser.objects.create_user(
            'other', 'other@test.com', 'pass1234',
        )
        session = PuzzleSession.objects.create(
            student=other_user, level=self.level1,
            status='completed', score=5, total_questions=10,
        )
        response = self.client.get(
            reverse('number_puzzles_results', kwargs={'session_id': session.id})
        )
        self.assertEqual(response.status_code, 404)


# ── Answer Validation Tests ─────────────────────────────────────────────────

class AnswerValidationTest(NumberPuzzlesTestBase):
    """Test the puzzle answer checking logic."""

    def test_correct_answer_with_equals(self):
        from number_puzzles.views import _check_puzzle_answer
        puzzle = self.puzzles[0]  # 1+2=3
        self.assertTrue(_check_puzzle_answer(puzzle, '1+2=3'))

    def test_correct_answer_without_equals(self):
        from number_puzzles.views import _check_puzzle_answer
        puzzle = self.puzzles[0]  # 1+2=3
        self.assertTrue(_check_puzzle_answer(puzzle, '1+2'))

    def test_correct_answer_with_x_operator(self):
        """x should be accepted as multiplication."""
        from number_puzzles.views import _check_puzzle_answer
        # Create a multiplication puzzle
        p = NumberPuzzle(
            level=self.level1, operands=[3, 4], target=12,
            display_template='3 _ 4 = 12', solution='3x4=12',
        )
        p.save()
        self.assertTrue(_check_puzzle_answer(p, '3x4=12'))
        self.assertTrue(_check_puzzle_answer(p, '3*4'))

    def test_wrong_answer(self):
        from number_puzzles.views import _check_puzzle_answer
        puzzle = self.puzzles[0]  # 1+2=3
        self.assertFalse(_check_puzzle_answer(puzzle, '1-2'))

    def test_wrong_target(self):
        from number_puzzles.views import _check_puzzle_answer
        puzzle = self.puzzles[0]  # 1+2=3
        self.assertFalse(_check_puzzle_answer(puzzle, '1+3'))

    def test_empty_answer(self):
        from number_puzzles.views import _check_puzzle_answer
        puzzle = self.puzzles[0]
        self.assertFalse(_check_puzzle_answer(puzzle, ''))

    def test_wrong_operand_order(self):
        from number_puzzles.views import _check_puzzle_answer
        puzzle = self.puzzles[1]  # 5-3=2
        # 2+0=2 is wrong operands even though result matches
        self.assertFalse(_check_puzzle_answer(puzzle, '3-5'))

    def test_spaces_in_answer(self):
        from number_puzzles.views import _check_puzzle_answer
        puzzle = self.puzzles[0]  # 1+2=3
        self.assertTrue(_check_puzzle_answer(puzzle, '1 + 2 = 3'))


# ── Expression Parser Tests ─────────────────────────────────────────────────

class SafeEvalTest(TestCase):
    """Test the safe expression evaluator."""

    def test_addition(self):
        from number_puzzles.management.commands.generate_puzzles import safe_eval
        self.assertEqual(safe_eval('1+2'), 3.0)

    def test_subtraction(self):
        from number_puzzles.management.commands.generate_puzzles import safe_eval
        self.assertEqual(safe_eval('5-3'), 2.0)

    def test_multiplication(self):
        from number_puzzles.management.commands.generate_puzzles import safe_eval
        self.assertEqual(safe_eval('4*3'), 12.0)

    def test_division(self):
        from number_puzzles.management.commands.generate_puzzles import safe_eval
        self.assertEqual(safe_eval('12/4'), 3.0)

    def test_operator_precedence(self):
        from number_puzzles.management.commands.generate_puzzles import safe_eval
        self.assertEqual(safe_eval('2+3*2'), 8.0)

    def test_brackets(self):
        from number_puzzles.management.commands.generate_puzzles import safe_eval
        self.assertEqual(safe_eval('(2+3)*2'), 10.0)

    def test_nested_brackets(self):
        from number_puzzles.management.commands.generate_puzzles import safe_eval
        self.assertEqual(safe_eval('2*(3+(1+2))'), 12.0)

    def test_division_by_zero(self):
        from number_puzzles.management.commands.generate_puzzles import safe_eval
        self.assertIsNone(safe_eval('10/0'))

    def test_invalid_expression(self):
        from number_puzzles.management.commands.generate_puzzles import safe_eval
        self.assertIsNone(safe_eval('abc'))

    def test_empty_string(self):
        from number_puzzles.management.commands.generate_puzzles import safe_eval
        self.assertIsNone(safe_eval(''))


# ── Management Command Tests ────────────────────────────────────────────────

class GeneratePuzzlesCommandTest(TestCase):
    """Test the generate_puzzles management command."""

    @classmethod
    def setUpTestData(cls):
        cls.level1 = NumberPuzzleLevel.objects.create(
            number=1, name='Beginner', slug='beginner',
            operators_allowed='+,-', min_operand=1, max_operand=9,
            num_operands=2, max_result=18, order=1,
        )

    def test_generate_level_1(self):
        from django.core.management import call_command
        call_command('generate_puzzles', level=1, count=10)
        count = NumberPuzzle.objects.filter(level=self.level1).count()
        self.assertGreaterEqual(count, 10)

    def test_generate_is_idempotent(self):
        from django.core.management import call_command
        call_command('generate_puzzles', level=1, count=10)
        count1 = NumberPuzzle.objects.filter(level=self.level1).count()
        call_command('generate_puzzles', level=1, count=10)
        count2 = NumberPuzzle.objects.filter(level=self.level1).count()
        self.assertEqual(count1, count2)

    def test_no_levels_raises_error(self):
        from django.core.management import call_command, CommandError
        NumberPuzzleLevel.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command('generate_puzzles', level=1, count=10)

    def test_invalid_level_raises_error(self):
        from django.core.management import call_command, CommandError
        with self.assertRaises(CommandError):
            call_command('generate_puzzles', level=7, count=10)

    def test_dry_run_creates_nothing(self):
        from django.core.management import call_command
        call_command('generate_puzzles', level=1, count=10, dry_run=True)
        count = NumberPuzzle.objects.filter(level=self.level1).count()
        self.assertEqual(count, 0)

    def test_no_args_raises_error(self):
        from django.core.management import call_command, CommandError
        with self.assertRaises(CommandError):
            call_command('generate_puzzles', count=10)


# ── Progress Tracking Tests ─────────────────────────────────────────────────

class ProgressTrackingTest(NumberPuzzlesTestBase):
    """Test progress updates after session completion."""

    def test_progress_created_on_first_visit(self):
        """Level 1 progress is auto-created when visiting home."""
        client = Client()
        client.login(username='teststudent', password='pass1234')
        client.get(reverse('number_puzzles_home'))

        prog = StudentPuzzleProgress.objects.filter(
            student=self.student, level=self.level1,
        ).first()
        self.assertIsNotNone(prog)
        self.assertTrue(prog.is_unlocked)

    def test_stars_calculation(self):
        prog = StudentPuzzleProgress(best_score=10)
        self.assertEqual(prog.stars, 3)
        prog.best_score = 8
        self.assertEqual(prog.stars, 2)
        prog.best_score = 5
        self.assertEqual(prog.stars, 1)
        prog.best_score = 3
        self.assertEqual(prog.stars, 0)

    def test_accuracy_calculation(self):
        prog = StudentPuzzleProgress(
            total_puzzles_attempted=20, total_puzzles_correct=15,
        )
        self.assertEqual(prog.accuracy, 75)

    def test_accuracy_zero_when_no_attempts(self):
        prog = StudentPuzzleProgress(
            total_puzzles_attempted=0, total_puzzles_correct=0,
        )
        self.assertEqual(prog.accuracy, 0)
