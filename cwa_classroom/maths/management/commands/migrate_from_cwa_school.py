"""
migrate_from_cwa_school
=======================
Management command to import all maths data from the legacy CWA_SCHOOL backup
into the new unified CWA_CLASS_APP maths app.

Source: the src_maths_* staging tables already imported into the 'default'
(cwa_classroom) database by running import_backup.py beforehand.

Usage
-----
    # Preview -- no writes
    python manage.py migrate_from_cwa_school --dry-run

    # Full migration
    python manage.py migrate_from_cwa_school

    # Skip user creation (if users already exist)
    python manage.py migrate_from_cwa_school --skip-users

What it migrates
----------------
1.  Users  (maths_customuser -> accounts.CustomUser + Role assignment)
2.  Topics
3.  Levels  (+ Level-Topic M2M)
4.  ClassRooms  (+ ClassRoom-Level M2M)
5.  Enrollments
6.  Questions
7.  Answers
8.  StudentAnswers
9.  BasicFactsResults
10. TimeLogs
11. TopicLevelStatistics
12. StudentFinalAnswers

Safety
------
- Idempotent: uses get_or_create / update_or_create keyed on natural identifiers.
- Source database is never written to.
- Target writes are wrapped in a single atomic transaction (rolled back on error).
- Use --dry-run to preview row counts without writing anything.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction


class Command(BaseCommand):
    help = "Import maths data from the legacy CWA_SCHOOL MySQL database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be migrated without writing anything.",
        )
        parser.add_argument(
            "--skip-users",
            action="store_true",
            help="Skip user migration (useful if users already exist in the target).",
        )

    def handle(self, *args, **options):
        dry_run    = options["dry_run"]
        skip_users = options["skip_users"]

        # Use the default DB -- src_maths_* staging tables live there
        src = connections["default"]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'[DRY RUN] ' if dry_run else ''}Migrating from src_maths_* "
            f"staging tables in: {src.settings_dict['NAME']}\n"
        ))

        try:
            if dry_run:
                self._run(src, dry_run=True, skip_users=skip_users)
            else:
                with transaction.atomic(using="default"):
                    self._run(src, dry_run=False, skip_users=skip_users)
                self.stdout.write(self.style.SUCCESS("\nOK Migration complete.\n"))
        except Exception as exc:
            raise CommandError(f"Migration failed and was rolled back.\nError: {exc}")

    # ──────────────────────────────────────────────────────
    # Main migration sequence
    # ──────────────────────────────────────────────────────

    def _run(self, src, dry_run, skip_users):
        if skip_users:
            user_map = self._build_user_map_from_existing(src)
        else:
            user_map = self._migrate_users(src, dry_run)

        topic_map = self._migrate_topics(src, dry_run)
        level_map = self._migrate_levels(src, dry_run, topic_map)
        class_map = self._migrate_classrooms(src, dry_run, user_map, level_map)
        self._migrate_enrollments(src, dry_run, user_map, class_map)
        q_map, a_map = self._migrate_questions_and_answers(src, dry_run, level_map, topic_map)
        self._migrate_student_answers(src, dry_run, user_map, q_map, a_map)
        self._migrate_basic_facts_results(src, dry_run, user_map, level_map)
        self._migrate_time_logs(src, dry_run, user_map)
        self._migrate_topic_level_statistics(src, dry_run, level_map, topic_map)
        self._migrate_student_final_answers(src, dry_run, user_map, topic_map, level_map)

    # ──────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────

    def _fetch_all(self, src, sql, params=None):
        """Execute SQL against the legacy DB and return list of dicts."""
        with src.cursor() as cur:
            cur.execute(sql, params or [])
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _table_exists(self, src, table_name):
        rows = self._fetch_all(
            src,
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            [src.settings_dict["NAME"], table_name],
        )
        return bool(rows)

    def _section(self, name, total):
        self.stdout.write(
            self.style.MIGRATE_LABEL(f"\n  {name}") + f"  ({total} rows)"
        )

    # ──────────────────────────────────────────────────────
    # Optional: map legacy user IDs to existing accounts
    # ──────────────────────────────────────────────────────

    def _build_user_map_from_existing(self, src):
        """
        When --skip-users is passed, build user_map by matching legacy usernames
        to already-existing accounts.CustomUser records.
        """
        from accounts.models import CustomUser

        self._section("Users (mapping existing)", 0)
        rows = self._fetch_all(src, "SELECT id, username FROM src_maths_customuser")
        user_map = {}
        missing  = []
        for row in rows:
            try:
                user_map[row["id"]] = CustomUser.objects.get(username=row["username"])
            except CustomUser.DoesNotExist:
                missing.append(row["username"])

        if missing:
            self.stdout.write(
                self.style.WARNING(
                    f"  [WARN] {len(missing)} legacy users have no matching account "
                    f"(their data will be skipped): {missing[:10]}"
                )
            )
        self.stdout.write(f"  -> {len(user_map)} users mapped")
        return user_map

    # ──────────────────────────────────────────────────────
    # 1. Users
    # ──────────────────────────────────────────────────────

    def _migrate_users(self, src, dry_run):
        from accounts.models import CustomUser, Role, UserRole

        rows = self._fetch_all(
            src,
            "SELECT id, username, email, password, first_name, last_name, "
            "is_staff, is_superuser, is_active, date_joined, last_login, "
            "is_teacher, date_of_birth, country, region "
            "FROM src_maths_customuser"
        )
        self._section("Users", len(rows))
        user_map = {}

        for row in rows:
            if dry_run:
                role_label = "teacher" if row["is_teacher"] else "student"
                self.stdout.write(
                    f"  [dry] user '{row['username']}' ({role_label})"
                )
                continue

            user, created = CustomUser.objects.get_or_create(
                username=row["username"],
                defaults={
                    "email":         row["email"] or "",
                    "first_name":    row["first_name"] or "",
                    "last_name":     row["last_name"] or "",
                    "is_staff":      bool(row["is_staff"]),
                    "is_superuser":  bool(row["is_superuser"]),
                    "is_active":     bool(row["is_active"]),
                    "date_of_birth": row["date_of_birth"] or None,
                    "country":       row["country"] or "",
                    "region":        row["region"] or "",
                },
            )

            if created:
                # Copy hashed password directly (preserves pbkdf2/bcrypt hash)
                user.password = row["password"]
                user.save(update_fields=["password"])

            # Assign role
            role_name = Role.TEACHER if row["is_teacher"] else Role.STUDENT
            display   = "Teacher"   if row["is_teacher"] else "Student"
            role, _   = Role.objects.get_or_create(
                name=role_name, defaults={"display_name": display}
            )
            UserRole.objects.get_or_create(user=user, role=role)
            user_map[row["id"]] = user

        if not dry_run:
            self.stdout.write(f"  -> {len(user_map)} users migrated")
        return user_map

    # ──────────────────────────────────────────────────────
    # 2. Topics
    # ──────────────────────────────────────────────────────

    def _migrate_topics(self, src, dry_run):
        from maths.models import Topic

        rows = self._fetch_all(src, "SELECT id, name FROM src_maths_topic")
        self._section("Topics", len(rows))
        topic_map = {}

        for row in rows:
            if dry_run:
                self.stdout.write(f"  [dry] topic '{row['name']}'")
                continue
            obj, _ = Topic.objects.get_or_create(name=row["name"])
            topic_map[row["id"]] = obj

        if not dry_run:
            self.stdout.write(f"  -> {len(topic_map)} topics migrated")
        return topic_map

    # ──────────────────────────────────────────────────────
    # 3. Levels (+ M2M topics)
    # ──────────────────────────────────────────────────────

    def _migrate_levels(self, src, dry_run, topic_map):
        from maths.models import Level

        rows = self._fetch_all(
            src, "SELECT id, level_number, title FROM src_maths_level"
        )
        self._section("Levels", len(rows))
        level_map = {}

        for row in rows:
            if dry_run:
                self.stdout.write(f"  [dry] level {row['level_number']} -- {row['title']}")
                continue
            obj, _ = Level.objects.get_or_create(
                level_number=row["level_number"],
                defaults={"title": row["title"] or ""},
            )
            level_map[row["id"]] = obj

        # M2M: level ↔ topics
        m2m = self._fetch_all(src, "SELECT level_id, topic_id FROM src_maths_level_topics")
        if not dry_run:
            for r in m2m:
                lvl = level_map.get(r["level_id"])
                tpc = topic_map.get(r["topic_id"])
                if lvl and tpc:
                    lvl.topics.add(tpc)
            self.stdout.write(f"  -> {len(level_map)} levels migrated")

        return level_map

    # ──────────────────────────────────────────────────────
    # 4. ClassRooms (+ M2M levels)
    # ──────────────────────────────────────────────────────

    def _migrate_classrooms(self, src, dry_run, user_map, level_map):
        from maths.models import ClassRoom

        rows = self._fetch_all(
            src, "SELECT id, name, teacher_id, code FROM src_maths_classroom"
        )
        self._section("ClassRooms", len(rows))
        class_map = {}

        for row in rows:
            teacher = user_map.get(row["teacher_id"])
            if not teacher and not dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [WARN] Skipping classroom '{row['name']}' -- teacher not found"
                    )
                )
                continue

            if dry_run:
                self.stdout.write(f"  [dry] classroom '{row['name']}' code={row['code']}")
                continue

            obj, _ = ClassRoom.objects.get_or_create(
                code=row["code"],
                defaults={"name": row["name"], "teacher": teacher},
            )
            class_map[row["id"]] = obj

        m2m = self._fetch_all(src, "SELECT classroom_id, level_id FROM src_maths_classroom_levels")
        if not dry_run:
            for r in m2m:
                cls = class_map.get(r["classroom_id"])
                lvl = level_map.get(r["level_id"])
                if cls and lvl:
                    cls.levels.add(lvl)
            self.stdout.write(f"  -> {len(class_map)} classrooms migrated")

        return class_map

    # ──────────────────────────────────────────────────────
    # 5. Enrollments
    # ──────────────────────────────────────────────────────

    def _migrate_enrollments(self, src, dry_run, user_map, class_map):
        from maths.models import Enrollment

        rows = self._fetch_all(
            src,
            "SELECT id, student_id, classroom_id FROM src_maths_enrollment"
        )
        self._section("Enrollments", len(rows))
        count = 0

        for row in rows:
            student   = user_map.get(row["student_id"])
            classroom = class_map.get(row["classroom_id"])
            if not student or not classroom:
                continue
            if dry_run:
                self.stdout.write(
                    f"  [dry] enroll {student.username} -> classroom {row['classroom_id']}"
                )
                continue
            Enrollment.objects.get_or_create(student=student, classroom=classroom)
            count += 1

        if not dry_run:
            self.stdout.write(f"  -> {count} enrollments migrated")

    # ──────────────────────────────────────────────────────
    # 6. Questions & Answers
    # ──────────────────────────────────────────────────────

    def _migrate_questions_and_answers(self, src, dry_run, level_map, topic_map):
        from maths.models import Question, Answer

        q_rows = self._fetch_all(
            src,
            "SELECT id, level_id, topic_id, question_text, question_type, "
            "difficulty, points, explanation, image "
            "FROM src_maths_question"
        )
        self._section("Questions", len(q_rows))
        q_map = {}

        for row in q_rows:
            level = level_map.get(row["level_id"])
            topic = topic_map.get(row["topic_id"]) if row["topic_id"] else None
            if not level:
                continue
            if dry_run:
                self.stdout.write(f"  [dry] question pk={row['id']}")
                continue
            obj, _ = Question.objects.get_or_create(
                level=level,
                question_text=row["question_text"],
                defaults={
                    "topic":         topic,
                    "question_type": row["question_type"],
                    "difficulty":    row["difficulty"],
                    "points":        row["points"],
                    "explanation":   row["explanation"] or "",
                    "image":         row["image"] or "",
                },
            )
            q_map[row["id"]] = obj

        a_rows = self._fetch_all(
            src,
            "SELECT id, question_id, answer_text, is_correct, `order` "
            "FROM src_maths_answer"
        )
        self._section("Answers", len(a_rows))
        a_map = {}

        for row in a_rows:
            question = q_map.get(row["question_id"])
            if not question:
                continue
            if dry_run:
                self.stdout.write(f"  [dry] answer pk={row['id']}")
                continue
            obj, _ = Answer.objects.get_or_create(
                question=question,
                answer_text=row["answer_text"],
                defaults={
                    "is_correct": bool(row["is_correct"]),
                    "order":      row["order"] or 0,
                },
            )
            a_map[row["id"]] = obj

        if not dry_run:
            self.stdout.write(
                f"  -> {len(q_map)} questions, {len(a_map)} answers migrated"
            )

        return q_map, a_map

    # ──────────────────────────────────────────────────────
    # 7. StudentAnswers
    # ──────────────────────────────────────────────────────

    def _migrate_student_answers(self, src, dry_run, user_map, q_map, a_map):
        from maths.models import StudentAnswer

        rows = self._fetch_all(
            src,
            "SELECT id, student_id, question_id, selected_answer_id, text_answer, "
            "is_correct, points_earned, session_id, time_taken_seconds "
            "FROM src_maths_studentanswer"
        )
        self._section("StudentAnswers", len(rows))
        count = 0

        for row in rows:
            student  = user_map.get(row["student_id"])
            question = q_map.get(row["question_id"])
            answer   = a_map.get(row["selected_answer_id"]) if row["selected_answer_id"] else None
            if not student or not question:
                continue
            if dry_run:
                self.stdout.write(f"  [dry] student_answer pk={row['id']}")
                continue
            StudentAnswer.objects.update_or_create(
                student=student,
                question=question,
                defaults={
                    "selected_answer":    answer,
                    "text_answer":        row["text_answer"] or "",
                    "is_correct":         bool(row["is_correct"]),
                    "points_earned":      row["points_earned"] or 0,
                    "session_id":         row["session_id"] or "",
                    "time_taken_seconds": row["time_taken_seconds"] or 0,
                },
            )
            count += 1

        if not dry_run:
            self.stdout.write(f"  -> {count} student answers migrated")

    # ──────────────────────────────────────────────────────
    # 8. BasicFactsResults
    # ──────────────────────────────────────────────────────

    def _migrate_basic_facts_results(self, src, dry_run, user_map, level_map):
        from maths.models import BasicFactsResult

        if not self._table_exists(src, "src_maths_basicfactsresult"):
            self.stdout.write("  src_maths_basicfactsresult not found -- skipping")
            return

        rows = self._fetch_all(
            src,
            "SELECT id, student_id, level_id, session_id, score, total_points, "
            "time_taken_seconds, points "
            "FROM src_maths_basicfactsresult"
        )
        self._section("BasicFactsResults", len(rows))
        count = 0

        for row in rows:
            student = user_map.get(row["student_id"])
            level   = level_map.get(row["level_id"])
            if not student or not level:
                continue
            if dry_run:
                self.stdout.write(f"  [dry] basic_facts pk={row['id']}")
                continue
            BasicFactsResult.objects.get_or_create(
                student=student,
                level=level,
                session_id=row["session_id"],
                defaults={
                    "score":              row["score"],
                    "total_points":       row["total_points"],
                    "time_taken_seconds": row["time_taken_seconds"],
                    "points":             row["points"],
                },
            )
            count += 1

        if not dry_run:
            self.stdout.write(f"  -> {count} basic facts results migrated")

    # ──────────────────────────────────────────────────────
    # 9. TimeLogs
    # ──────────────────────────────────────────────────────

    def _migrate_time_logs(self, src, dry_run, user_map):
        from maths.models import TimeLog

        if not self._table_exists(src, "src_maths_timelog"):
            self.stdout.write("  src_maths_timelog not found -- skipping")
            return

        rows = self._fetch_all(
            src,
            "SELECT id, student_id, daily_total_seconds, "
            "weekly_total_seconds, last_reset_week "
            "FROM src_maths_timelog"
        )
        self._section("TimeLogs", len(rows))
        count = 0

        for row in rows:
            student = user_map.get(row["student_id"])
            if not student:
                continue
            if dry_run:
                self.stdout.write(f"  [dry] timelog pk={row['id']}")
                continue
            TimeLog.objects.update_or_create(
                student=student,
                defaults={
                    "daily_total_seconds":  row["daily_total_seconds"] or 0,
                    "weekly_total_seconds": row["weekly_total_seconds"] or 0,
                    "last_reset_week":      row["last_reset_week"] or 0,
                },
            )
            count += 1

        if not dry_run:
            self.stdout.write(f"  -> {count} time logs migrated")

    # ──────────────────────────────────────────────────────
    # 10. TopicLevelStatistics
    # ──────────────────────────────────────────────────────

    def _migrate_topic_level_statistics(self, src, dry_run, level_map, topic_map):
        from maths.models import TopicLevelStatistics

        # Table name is known (case-insensitive on MySQL)
        tls_table = "src_maths_topiclevelstatistics"
        if not self._table_exists(src, tls_table):
            self.stdout.write("  src_maths_topiclevelstatistics not found -- skipping")
            return

        rows = self._fetch_all(
            src,
            f"SELECT id, level_id, topic_id, average_points, sigma, student_count "
            f"FROM `{tls_table}`"
        )
        self._section("TopicLevelStatistics", len(rows))
        count = 0

        for row in rows:
            level = level_map.get(row["level_id"])
            topic = topic_map.get(row["topic_id"])
            if not level or not topic:
                continue
            if dry_run:
                self.stdout.write(f"  [dry] topic_level_stat pk={row['id']}")
                continue
            TopicLevelStatistics.objects.update_or_create(
                level=level,
                topic=topic,
                defaults={
                    "average_points": row["average_points"] or 0,
                    "sigma":          row["sigma"] or 0,
                    "student_count":  row["student_count"] or 0,
                },
            )
            count += 1

        if not dry_run:
            self.stdout.write(f"  -> {count} statistics migrated")

    # ──────────────────────────────────────────────────────
    # 11. StudentFinalAnswers
    # ──────────────────────────────────────────────────────

    def _migrate_student_final_answers(self, src, dry_run, user_map, topic_map, level_map):
        from maths.models import StudentFinalAnswer

        if not self._table_exists(src, "src_maths_studentfinalanswer"):
            self.stdout.write("  src_maths_studentfinalanswer not found -- skipping")
            return

        rows = self._fetch_all(
            src,
            "SELECT id, student_id, session_id, topic_id, level_id, "
            "attempt_number, points_earned "
            "FROM src_maths_studentfinalanswer"
        )
        self._section("StudentFinalAnswers", len(rows))
        count = 0

        for row in rows:
            student = user_map.get(row["student_id"])
            topic   = topic_map.get(row["topic_id"])
            level   = level_map.get(row["level_id"])
            if not student or not topic or not level:
                continue
            if dry_run:
                self.stdout.write(f"  [dry] final_answer pk={row['id']}")
                continue
            StudentFinalAnswer.objects.update_or_create(
                student=student,
                session_id=row["session_id"],
                defaults={
                    "topic":          topic,
                    "level":          level,
                    "attempt_number": row["attempt_number"],
                    "points_earned":  row["points_earned"],
                },
            )
            count += 1

        if not dry_run:
            self.stdout.write(f"  -> {count} final answers migrated")
