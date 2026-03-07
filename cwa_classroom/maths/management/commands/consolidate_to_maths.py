"""
consolidate_to_maths
====================
Migrates all question/progress data from the shared quiz and progress apps
into the maths app, which becomes the single source of truth for maths content.

After this command runs successfully:
  - maths.Question  holds all questions (was in quiz.Question)
  - maths.Answer    holds all answers   (was in quiz.Answer)
  - maths.StudentAnswer, StudentFinalAnswer, BasicFactsResult, TimeLog,
    TopicLevelStatistics all hold the progress data (was in progress.*)
  - quiz and progress models can then be safely removed

Usage
-----
    # Preview -- no writes
    python manage.py consolidate_to_maths --dry-run

    # Full consolidation
    python manage.py consolidate_to_maths

    # Skip question migration (e.g. already done)
    python manage.py consolidate_to_maths --skip-questions

    # Skip progress migration
    python manage.py consolidate_to_maths --skip-progress
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Consolidate quiz.Question/Answer and progress.* data into the maths app."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--skip-questions", action="store_true")
        parser.add_argument("--skip-progress", action="store_true")

    def handle(self, *args, **options):
        # ── COMPLETED: source tables (quiz.Question/Answer, progress.*) have been
        # dropped by migrations.  Do NOT re-run this command.
        from django.core.management.base import CommandError as _CE
        raise _CE(
            "consolidate_to_maths has already been run and the source tables "
            "(quiz.Question/Answer, all progress.*) have been removed by migrations. "
            "Re-running is not possible. See git history for the original command."
        )

        dry_run        = options["dry_run"]
        skip_questions = options["skip_questions"]
        skip_progress  = options["skip_progress"]

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{prefix}Consolidating quiz + progress data into maths...\n"
        ))

        try:
            if dry_run:
                self._run(dry_run, skip_questions, skip_progress)
            else:
                with transaction.atomic():
                    self._run(dry_run, skip_questions, skip_progress)
                self.stdout.write(self.style.SUCCESS("\nConsolidation complete.\n"))
        except Exception as exc:
            raise CommandError(f"Consolidation failed and was rolled back.\nError: {exc}")

    # ------------------------------------------------------------------
    def _run(self, dry_run, skip_questions, skip_progress):
        # Build lookup maps: classroom.Topic.name -> maths.Topic
        #                    classroom.Level.level_number -> maths.Level
        from maths.models import Topic as MT, Level as ML
        from classroom.models import Topic as CT, Level as CL

        topic_map = {t.name: t for t in MT.objects.all()}
        level_map = {l.level_number: l for l in ML.objects.all()}

        self.stdout.write(
            f"  Loaded {len(topic_map)} maths topics, {len(level_map)} maths levels\n"
        )

        quiz_q_map = {}   # quiz.Question.id -> maths.Question instance
        quiz_a_map = {}   # quiz.Answer.id   -> maths.Answer  instance

        if not skip_questions:
            quiz_q_map, quiz_a_map = self._migrate_questions(dry_run, topic_map, level_map)

        if not skip_progress:
            self._migrate_student_answers(dry_run, quiz_q_map, quiz_a_map, topic_map, level_map)
            self._migrate_student_final_answers(dry_run, topic_map, level_map)
            self._migrate_basic_facts_results(dry_run)
            self._migrate_time_logs(dry_run)
            self._migrate_topic_level_statistics(dry_run, topic_map, level_map)

    # ------------------------------------------------------------------
    # A+B  quiz.Question + quiz.Answer -> maths
    # ------------------------------------------------------------------

    def _migrate_questions(self, dry_run, topic_map, level_map):
        from quiz.models import Question as QQ, Answer as QA
        from maths.models import Question as MQ, Answer as MA

        q_rows = list(QQ.objects.select_related("topic", "level").all())
        self._section("Questions (quiz -> maths)", len(q_rows))

        quiz_q_map = {}
        created_q = skipped_q = 0

        for qq in q_rows:
            m_topic = topic_map.get(qq.topic.name) if qq.topic else None
            m_level = level_map.get(qq.level.level_number) if qq.level else None
            if not m_level:
                skipped_q += 1
                continue

            if dry_run:
                quiz_q_map[qq.id] = None
                created_q += 1
                continue

            mq, created = MQ.objects.get_or_create(
                question_text=qq.question_text,
                level=m_level,
                defaults={
                    "topic":         m_topic,
                    "question_type": qq.question_type,
                    "difficulty":    qq.difficulty,
                    "points":        qq.points,
                    "explanation":   qq.explanation or "",
                    "image":         qq.image or "",
                },
            )
            quiz_q_map[qq.id] = mq
            if created:
                created_q += 1

        self.stdout.write(
            f"  -> {created_q} questions added, {skipped_q} skipped (no matching level)"
        )

        # -- Answers --
        a_rows = list(QA.objects.select_related("question").all())
        self._section("Answers (quiz -> maths)", len(a_rows))

        quiz_a_map = {}
        created_a = skipped_a = 0

        for qa in a_rows:
            if qa.question_id not in quiz_q_map:
                skipped_a += 1
                continue
            m_question = quiz_q_map[qa.question_id]

            if dry_run:
                quiz_a_map[qa.id] = None
                created_a += 1
                continue

            ma, created = MA.objects.get_or_create(
                question=m_question,
                answer_text=qa.text,
                defaults={
                    "is_correct": qa.is_correct,
                    "order":      qa.display_order,
                },
            )
            quiz_a_map[qa.id] = ma
            if created:
                created_a += 1

        self.stdout.write(
            f"  -> {created_a} answers added, {skipped_a} skipped"
        )

        return quiz_q_map, quiz_a_map

    # ------------------------------------------------------------------
    # C  progress.StudentAnswer -> maths.StudentAnswer
    # ------------------------------------------------------------------

    def _migrate_student_answers(self, dry_run, quiz_q_map, quiz_a_map, topic_map, level_map):
        from progress.models import StudentAnswer as PSA
        from maths.models import StudentAnswer as MSA

        rows = list(PSA.objects.select_related("student", "question", "selected_answer", "topic", "level").all())
        self._section("StudentAnswers (progress -> maths)", len(rows))

        ok = skip = 0
        for psa in rows:
            if psa.question_id not in quiz_q_map:
                skip += 1
                continue
            m_question = quiz_q_map[psa.question_id]

            m_answer = quiz_a_map.get(psa.selected_answer_id) if psa.selected_answer_id else None
            m_topic  = topic_map.get(psa.topic.name)  if psa.topic  else None
            m_level  = level_map.get(psa.level.level_number) if psa.level else None

            if dry_run:
                ok += 1
                continue

            MSA.objects.update_or_create(
                student=psa.student,
                question=m_question,
                defaults={
                    "selected_answer":    m_answer,
                    "text_answer":        psa.text_answer or "",
                    "ordered_answer_ids": psa.ordered_answer_ids,
                    "is_correct":         psa.is_correct,
                    "points_earned":      0,
                    "session_id":         str(psa.attempt_id),
                    "attempt_id":         psa.attempt_id,
                    "time_taken_seconds": 0,
                },
            )
            ok += 1

        self.stdout.write(f"  -> {ok} student answers migrated, {skip} skipped")

    # ------------------------------------------------------------------
    # D  progress.StudentFinalAnswer -> maths.StudentFinalAnswer
    # ------------------------------------------------------------------

    def _migrate_student_final_answers(self, dry_run, topic_map, level_map):
        from progress.models import StudentFinalAnswer as PSFA
        from maths.models import StudentFinalAnswer as MSFA

        rows = list(PSFA.objects.select_related("student", "topic", "level").all())
        self._section("StudentFinalAnswers (progress -> maths)", len(rows))

        ok = skip = 0
        for psfa in rows:
            m_topic = topic_map.get(psfa.topic.name) if psfa.topic else None
            m_level = level_map.get(psfa.level.level_number) if psfa.level else None

            if not m_topic or not m_level:
                skip += 1
                continue

            if dry_run:
                ok += 1
                continue

            MSFA.objects.update_or_create(
                student=psfa.student,
                session_id=str(psfa.session_id),
                defaults={
                    "topic":          m_topic,
                    "level":          m_level,
                    "attempt_number": psfa.attempt_number,
                    "points_earned":  psfa.points or 0,
                },
            )
            ok += 1

        self.stdout.write(f"  -> {ok} final answers migrated, {skip} skipped")

    # ------------------------------------------------------------------
    # E  progress.BasicFactsResult -> maths.BasicFactsResult
    # ------------------------------------------------------------------

    def _migrate_basic_facts_results(self, dry_run):
        from progress.models import BasicFactsResult as PBFR
        from maths.models import BasicFactsResult as MBFR

        rows = list(PBFR.objects.select_related("student").all())
        self._section("BasicFactsResults (progress -> maths)", len(rows))

        ok = 0
        for pbfr in rows:
            if dry_run:
                ok += 1
                continue

            MBFR.objects.get_or_create(
                student=pbfr.student,
                session_id=str(pbfr.session_id),
                defaults={
                    "level":              None,
                    "subtopic":           pbfr.subtopic or "",
                    "level_number":       pbfr.level_number,
                    "score":              pbfr.score,
                    "total_points":       pbfr.total_questions,
                    "time_taken_seconds": pbfr.time_taken_seconds,
                    "points":             pbfr.points or 0,
                },
            )
            ok += 1

        self.stdout.write(f"  -> {ok} basic facts results migrated")

    # ------------------------------------------------------------------
    # F  progress.TimeLog -> maths.TimeLog
    # ------------------------------------------------------------------

    def _migrate_time_logs(self, dry_run):
        from progress.models import TimeLog as PTL
        from maths.models import TimeLog as MTL

        rows = list(PTL.objects.select_related("student").all())
        self._section("TimeLogs (progress -> maths)", len(rows))

        ok = 0
        for ptl in rows:
            if dry_run:
                ok += 1
                continue

            MTL.objects.update_or_create(
                student=ptl.student,
                defaults={
                    "daily_total_seconds":  ptl.daily_seconds,
                    "weekly_total_seconds": ptl.weekly_seconds,
                    # last_reset_date and last_activity use auto_now so can't be set directly
                },
            )
            ok += 1

        self.stdout.write(f"  -> {ok} time logs migrated")

    # ------------------------------------------------------------------
    # G  progress.TopicLevelStatistics -> maths.TopicLevelStatistics
    # ------------------------------------------------------------------

    def _migrate_topic_level_statistics(self, dry_run, topic_map, level_map):
        from progress.models import TopicLevelStatistics as PTLS
        from maths.models import TopicLevelStatistics as MTLS

        rows = list(PTLS.objects.select_related("topic", "level").all())
        self._section("TopicLevelStatistics (progress -> maths)", len(rows))

        ok = skip = 0
        for ptls in rows:
            m_topic = topic_map.get(ptls.topic.name) if ptls.topic else None
            m_level = level_map.get(ptls.level.level_number) if ptls.level else None

            if not m_topic or not m_level:
                skip += 1
                continue

            if dry_run:
                ok += 1
                continue

            MTLS.objects.update_or_create(
                topic=m_topic,
                level=m_level,
                defaults={
                    "average_points": ptls.avg_points or 0,
                    "sigma":          ptls.sigma or 0,
                    "student_count":  ptls.student_count,
                },
            )
            ok += 1

        self.stdout.write(f"  -> {ok} statistics migrated, {skip} skipped")

    # ------------------------------------------------------------------
    def _section(self, name, total):
        self.stdout.write(self.style.MIGRATE_LABEL(f"\n  {name}") + f"  ({total} rows)")
