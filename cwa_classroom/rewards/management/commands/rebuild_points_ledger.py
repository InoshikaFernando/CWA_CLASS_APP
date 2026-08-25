"""Derive the points ledger from the activity tables that already exist.

Run once after deploying the rewards app so every student who has been using
the site arrives on the leaderboard with the points they have already earned,
rather than everyone starting from zero. Safe to re-run at any time: it goes
through ``award_points``, which keeps the better of the stored and computed
score per unit, so it repairs a drifted ledger without ever lowering anyone.

    python manage.py rebuild_points_ledger
    python manage.py rebuild_points_ledger --student alice --dry-run

What it can and cannot recover
------------------------------
Attempt history is pruned to the last 10 per series
(``classroom.attempt_retention``), so a unit whose every surviving attempt is
worse than a deleted one is rebuilt at the best score still on record. Going
forward the ledger is written at submit time and never loses that.
"""

from django.core.management.base import BaseCommand
from django.db.models import Max, Sum

from rewards.models import PointsSource
from rewards.services import award_points, normalise, recalculate_total


class Command(BaseCommand):
    help = 'Rebuild the cross-subject points ledger from existing activity records.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--student', default=None,
            help='Limit to one username (default: every student with activity).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be awarded without writing anything.',
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.only = options['student']
        self.counts = {}

        if self.dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — nothing will be written.\n'))

        self._maths_quizzes()
        self._basic_facts()
        self._homework()
        self._coding_problems()
        self._coding_exercises()
        self._worksheets()
        self._number_puzzles()
        self._brainbuzz()

        total = sum(self.counts.values())
        self.stdout.write('')
        for source, n in sorted(self.counts.items()):
            self.stdout.write(f'  {source:<18} {n:>7} units')
        self.stdout.write(self.style.SUCCESS(f'\n{total} units of work processed.'))

        if not self.dry_run:
            self._refresh_totals()

    # -- helpers ---------------------------------------------------------

    def _wanted(self, student):
        """True if this student is in scope for the run."""
        if student is None:
            return False
        return self.only is None or student.username == self.only

    def _award(self, student, source, unit_key, points, label=''):
        if not self._wanted(student):
            return
        self.counts[source] = self.counts.get(source, 0) + 1
        if not self.dry_run:
            award_points(student, source, unit_key, points, label=label)

    def _refresh_totals(self):
        """Recompute every total the run touched.

        ``award_points`` already does this per call; this second pass exists so
        a student whose *every* award was skipped (no activity left after
        pruning) still ends up with a row, and so a total that drifted from its
        ledger is corrected even when no new award landed.
        """
        from accounts.models import CustomUser, Role
        students = CustomUser.objects.filter(
            is_active=True,
            user_roles__role__name__in=[Role.STUDENT, Role.INDIVIDUAL_STUDENT],
        ).distinct()
        if self.only:
            students = students.filter(username=self.only)
        for student in students.iterator():
            recalculate_total(student)
        self.stdout.write(f'Totals refreshed for {students.count()} students.')

    # -- sources ---------------------------------------------------------

    def _maths_quizzes(self):
        """Topic, mixed and times-table quiz attempts (incl. global questions)."""
        from maths.models import StudentFinalAnswer

        best = (
            StudentFinalAnswer.objects
            .values('student_id', 'quiz_type', 'topic_id', 'level_id',
                    'operation', 'table_number', 'shuffled')
            .annotate(best=Max('points'))
        )
        students = self._student_map(r['student_id'] for r in best)
        for row in best:
            student = students.get(row['student_id'])
            if row['quiz_type'] == StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE:
                order = 'shuffled' if row['shuffled'] else 'in-order'
                self._award(
                    student, PointsSource.TIMES_TABLES,
                    f"{row['operation']}:{row['table_number']}:{order}",
                    row['best'], label=f"{(row['operation'] or '').title()} "
                                       f"table {row['table_number']}",
                )
            elif row['quiz_type'] == StudentFinalAnswer.QUIZ_TYPE_MIXED:
                # The subject slug is not stored on the attempt. 'maths' is the
                # only subject with a live mixed quiz, and the key only has to
                # be stable — a later subject writes its own distinct key.
                self._award(
                    student, PointsSource.MATHS_QUIZ,
                    f"mixed:maths:level:{row['level_id'] or 0}",
                    row['best'], label='Mixed quiz',
                )
            else:
                self._award(
                    student, PointsSource.MATHS_QUIZ,
                    f"topic:{row['topic_id']}:level:{row['level_id'] or 0}",
                    row['best'], label='Topic quiz',
                )

    def _basic_facts(self):
        from maths.models import BasicFactsResult

        best = (
            BasicFactsResult.objects
            .values('student_id', 'subtopic', 'level_number')
            .annotate(best=Max('points'))
        )
        students = self._student_map(r['student_id'] for r in best)
        for row in best:
            self._award(
                students.get(row['student_id']), PointsSource.BASIC_FACTS,
                f"{row['subtopic']}:{row['level_number']}", row['best'],
                label=f"Basic facts — {row['subtopic']} level {row['level_number']}",
            )

    def _homework(self):
        """Scored on percentage — see ``_award_homework_points`` for why."""
        from homework.models import HomeworkSubmission

        rows = (
            HomeworkSubmission.objects
            .select_related('student', 'homework')
            .filter(total_questions__gt=0)
        )
        seen = {}
        for sub in rows.iterator():
            pct = normalise(sub.score, sub.total_questions)
            key = (sub.student_id, sub.homework_id)
            if pct > seen.get(key, (-1, None))[0]:
                seen[key] = (pct, sub)
        for (_student_id, homework_id), (pct, sub) in seen.items():
            self._award(
                sub.student, PointsSource.HOMEWORK, str(homework_id), pct,
                label=f'Homework — {sub.homework.title}',
            )

    def _coding_problems(self):
        from coding.models import StudentProblemSubmission

        best = (
            StudentProblemSubmission.objects
            .values('student_id', 'problem_id', 'problem__title')
            .annotate(best=Max('points'))
        )
        students = self._student_map(r['student_id'] for r in best)
        for row in best:
            self._award(
                students.get(row['student_id']), PointsSource.CODING_PROBLEM,
                str(row['problem_id']), row['best'],
                label=f"Coding problem — {row['problem__title']}",
            )

    def _coding_exercises(self):
        from rewards.services import POINTS_PER_UNIT
        from coding.models import StudentExerciseSubmission

        done = (
            StudentExerciseSubmission.objects
            .filter(is_completed=True)
            .values('student_id', 'exercise_id', 'exercise__title')
            .distinct()
        )
        students = self._student_map(r['student_id'] for r in done)
        for row in done:
            self._award(
                students.get(row['student_id']), PointsSource.CODING_EXERCISE,
                str(row['exercise_id']), POINTS_PER_UNIT,
                label=f"Coding exercise — {row['exercise__title']}",
            )

    def _worksheets(self):
        from worksheets.models import WorksheetSubmission

        rows = (
            WorksheetSubmission.objects
            .select_related('student', 'assignment__worksheet')
            .filter(total_questions__gt=0)
        )
        for sub in rows.iterator():
            self._award(
                sub.student, PointsSource.WORKSHEET, str(sub.assignment_id),
                normalise(sub.score, sub.total_questions),
                label=f'Worksheet — {sub.assignment.worksheet.name}',
            )

    def _number_puzzles(self):
        from number_puzzles.models import PuzzleSession, StudentPuzzleProgress

        # StudentPuzzleProgress keeps best_score but not the question count it
        # was out of, so take that from the student's own sessions at that level.
        totals = {
            (row['student_id'], row['level_id']): row['out_of']
            for row in PuzzleSession.objects
            .values('student_id', 'level_id')
            .annotate(out_of=Max('total_questions'))
        }
        rows = StudentPuzzleProgress.objects.select_related('student', 'level')
        for prog in rows.iterator():
            out_of = totals.get((prog.student_id, prog.level_id), 0)
            if not out_of:
                continue
            self._award(
                prog.student, PointsSource.NUMBER_PUZZLE, str(prog.level_id),
                normalise(prog.best_score, out_of),
                label=f'Number puzzles — level {prog.level.number}',
            )

    def _brainbuzz(self):
        from brainbuzz.models import BrainBuzzParticipant, BrainBuzzSessionQuestion

        rows = (
            BrainBuzzParticipant.objects
            .filter(student__isnull=False)
            .select_related('student', 'session')
        )
        for part in rows.iterator():
            max_possible = BrainBuzzSessionQuestion.objects.filter(
                answers__participant=part,
            ).aggregate(total=Sum('points_base'))['total'] or 0
            if not max_possible:
                continue
            self._award(
                part.student, PointsSource.BRAINBUZZ, str(part.session_id),
                normalise(part.score, max_possible),
                label=f'BrainBuzz — {part.session.code}',
            )

    def _student_map(self, ids):
        from accounts.models import CustomUser
        ids = {i for i in ids if i}
        return CustomUser.objects.in_bulk(ids)
