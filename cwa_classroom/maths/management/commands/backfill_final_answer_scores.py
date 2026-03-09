"""
Backfill score and total_questions on StudentFinalAnswer records where
total_questions == 0 (created before we started saving these fields).

Since StudentAnswer is unique per (student, question), we group by
student + topic + level to get the current correct/total counts, then
apply those to all matching StudentFinalAnswer records.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count, Q


class Command(BaseCommand):
    help = 'Backfill score/total_questions on StudentFinalAnswer from StudentAnswer data'

    def handle(self, *args, **options):
        from maths.models import StudentFinalAnswer, StudentAnswer

        # Find distinct (student, topic, level) combos that need backfilling
        stale = (
            StudentFinalAnswer.objects
            .filter(total_questions=0)
            .values_list('student_id', 'topic_id', 'level_id')
            .distinct()
        )
        combos = list(stale)
        self.stdout.write(f'Found {len(combos)} (student, topic, level) combos to backfill.')

        updated = 0
        skipped = 0

        for student_id, topic_id, level_id in combos:
            if not topic_id or not level_id:
                skipped += 1
                continue

            # Count answers for this student+topic+level from StudentAnswer
            answers = StudentAnswer.objects.filter(
                student_id=student_id,
                question__topic_id=topic_id,
                question__level_id=level_id,
            )
            total_q = answers.count()
            if total_q == 0:
                skipped += 1
                continue

            correct = answers.filter(is_correct=True).count()

            # Update all SFA records for this combo
            records = StudentFinalAnswer.objects.filter(
                student_id=student_id,
                topic_id=topic_id,
                level_id=level_id,
                total_questions=0,
            )
            for sfa in records:
                sfa.score = correct
                sfa.total_questions = total_q
                if not sfa.points:
                    sfa.points = float(sfa.points_earned)
                sfa.save(update_fields=['score', 'total_questions', 'points'])
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done. Updated {updated} records, skipped {skipped} combos (no matching answers).'
        ))
