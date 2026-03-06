"""
Management command: python manage.py import_backup <path/to/backup.sql>

Parses the old MySQL backup dump and migrates data into the current app's tables.

Column order assumed from CREATE TABLE in the backup:
  maths_customuser    : id, password, last_login, is_superuser, username, first_name,
                        last_name, email, is_staff, is_active, date_joined,
                        is_teacher, country, date_of_birth, region
  maths_level         : id, level_number, title
  maths_topic         : id, name
  maths_level_topics  : id, level_id, topic_id
  maths_classroom     : id, name, code, teacher_id
  maths_classroom_lvl : id, classroom_id, level_id
  maths_enrollment    : id, date_enrolled, classroom_id, student_id
  maths_question      : id, question_text, question_type, difficulty, points,
                        explanation, image, created_at, updated_at, level_id, topic_id
  maths_answer        : id, answer_text, is_correct, order, question_id
  maths_studentfinal  : id, session_id, attempt_number, points_earned,
                        last_updated_time, level_id, student_id, topic_id
  maths_basicfacts    : id, session_id, score, total_points, time_taken_seconds,
                        points, completed_at, level_id, student_id
  maths_timelog       : id, daily_total_seconds, weekly_total_seconds,
                        last_reset_date, last_reset_week, last_activity, student_id
  maths_toplevelstats : id, average_points, sigma, student_count,
                        last_updated, level_id, topic_id
  maths_studentanswer : id, text_answer, is_correct, points_earned, answered_at,
                        question_id, selected_answer_id, student_id, session_id,
                        time_taken_seconds
"""

import re
import uuid
from datetime import date, datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify


class Command(BaseCommand):
    help = 'Import data from a MySQL backup SQL file into the current app.'

    def add_arguments(self, parser):
        parser.add_argument('sql_file', type=str, help='Path to MySQL backup .sql file')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Parse and count rows without writing to DB',
        )

    def handle(self, *args, **options):
        sql_file = options['sql_file']
        dry_run = options['dry_run']

        self.stdout.write(f'Reading {sql_file} ...')
        try:
            with open(sql_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise CommandError(f'File not found: {sql_file}')

        self.stdout.write('Parsing SQL INSERT statements ...')
        tables = self._parse_inserts(lines)
        for name in sorted(tables):
            self.stdout.write(f'  {name}: {len(tables[name])} rows')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('Dry run complete — no DB writes.'))
            return

        with transaction.atomic():
            user_map = self._import_users(tables.get('maths_customuser', []))
            level_map = self._build_level_map(tables.get('maths_level', []))
            topic_map = self._import_topics(tables.get('maths_topic', []))
            self._import_level_topics(
                tables.get('maths_level_topics', []), level_map, topic_map,
            )
            q_map, a_map = self._import_questions_answers(
                tables.get('maths_question', []),
                tables.get('maths_answer', []),
                level_map, topic_map,
            )
            self._import_classrooms(
                tables.get('maths_classroom', []),
                tables.get('maths_classroom_levels', []),
                tables.get('maths_enrollment', []),
                user_map, level_map,
            )
            self._import_final_answers(
                tables.get('maths_studentfinalanswer', []),
                user_map, level_map, topic_map,
            )
            self._import_basic_facts(
                tables.get('maths_basicfactsresult', []),
                user_map, level_map,
            )
            self._import_timelogs(tables.get('maths_timelog', []), user_map)
            self._import_statistics(
                tables.get('maths_topiclevelstatistics', []),
                level_map, topic_map,
            )
            self._import_student_answers(
                tables.get('maths_studentanswer', []),
                user_map, q_map, a_map,
            )
            self._assign_unlimited_promo(user_map)

        self.stdout.write(self.style.SUCCESS('\n✅  Import complete!'))

    # ── SQL PARSER ────────────────────────────────────────────────────────────

    def _parse_inserts(self, lines):
        """Read file lines and extract each table's INSERT rows."""
        tables = {}
        for line in lines:
            line = line.rstrip('\n')
            m = re.match(r"INSERT INTO `(\w+)` VALUES (.+);?\s*$", line)
            if not m:
                continue
            table = m.group(1)
            rows = self._extract_rows(m.group(2))
            tables.setdefault(table, []).extend(rows)
        return tables

    def _extract_rows(self, values_str):
        """Parse MySQL VALUES clause into a list of tuples."""
        rows = []
        i, n = 0, len(values_str)
        while i < n:
            while i < n and values_str[i] in ' \t\n\r,':
                i += 1
            if i >= n:
                break
            if values_str[i] != '(':
                i += 1
                continue
            i += 1  # skip opening '('
            row, i = self._parse_row(values_str, i, n)
            rows.append(tuple(row))
        return rows

    def _parse_row(self, s, i, n):
        """Parse comma-separated column values up to the closing ')'."""
        values = []
        while i < n:
            while i < n and s[i] == ' ':
                i += 1
            if i >= n:
                break
            if s[i] == ')':
                i += 1
                break
            if s[i] == ',':
                i += 1
                continue
            if s[i] == "'":
                val, i = self._parse_string(s, i + 1, n)
                values.append(val)
            elif s[i:i + 4].upper() == 'NULL':
                values.append(None)
                i += 4
            else:
                j = i
                while j < n and s[j] not in (',', ')'):
                    j += 1
                raw = s[i:j].strip()
                values.append(self._coerce_scalar(raw))
                i = j
        return values, i

    def _parse_string(self, s, i, n):
        """Consume a MySQL-escaped string up to the closing quote."""
        chars = []
        ESC = {"'": "'", '"': '"', 'n': '\n', 'r': '\r',
               't': '\t', '\\': '\\', '0': '\x00'}
        while i < n:
            c = s[i]
            if c == '\\' and i + 1 < n:
                chars.append(ESC.get(s[i + 1], s[i + 1]))
                i += 2
            elif c == "'":
                if i + 1 < n and s[i + 1] == "'":   # '' → '
                    chars.append("'")
                    i += 2
                else:
                    i += 1
                    break
            else:
                chars.append(c)
                i += 1
        return ''.join(chars), i

    def _coerce_scalar(self, raw):
        if not raw or raw.upper() == 'NULL':
            return None
        try:
            return int(raw)
        except ValueError:
            try:
                return float(raw)
            except ValueError:
                return raw

    # ── IMPORT METHODS ────────────────────────────────────────────────────────

    def _import_users(self, rows):
        """
        maths_customuser cols:
          id, password, last_login, is_superuser, username, first_name,
          last_name, email, is_staff, is_active, date_joined,
          is_teacher, country, date_of_birth, region
        """
        from accounts.models import CustomUser, Role, UserRole

        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher', 'is_active': True},
        )
        individual_student_role, _ = Role.objects.get_or_create(
            name=Role.INDIVIDUAL_STUDENT, defaults={'display_name': 'Individual Student', 'is_active': True},
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin', 'is_active': True},
        )

        user_map = {}
        created = skipped = 0
        for row in rows:
            (old_id, password, last_login, is_superuser, username,
             first_name, last_name, email, is_staff, is_active,
             date_joined, is_teacher_flag, country, dob, region) = row[:15]

            user, new = CustomUser.objects.get_or_create(
                username=username,
                defaults={
                    'email': email or '',
                    'first_name': first_name or '',
                    'last_name': last_name or '',
                    'is_staff': bool(is_staff),
                    'is_superuser': bool(is_superuser),
                    'is_active': bool(is_active),
                    'country': country or '',
                    'region': region or '',
                    'date_of_birth': self._to_date(dob),
                },
            )
            if new:
                # Preserve the hashed password from the backup
                user.password = password
                user.save(update_fields=['password'])
                if bool(is_superuser) or bool(is_staff):
                    UserRole.objects.get_or_create(user=user, role=admin_role)
                if bool(is_teacher_flag):
                    UserRole.objects.get_or_create(user=user, role=teacher_role)
                else:
                    UserRole.objects.get_or_create(user=user, role=individual_student_role)
                created += 1
            else:
                skipped += 1
            user_map[old_id] = user

        self.stdout.write(f'  Users: {created} created, {skipped} already existed')
        return user_map

    def _build_level_map(self, rows):
        """
        maths_level cols: id, level_number, title

        Maps old level IDs to Level objects matched by level_number.
        Creates missing levels if they don't exist yet.
        """
        from classroom.models import Level

        level_map = {}
        self._old_level_titles = {}   # old_id → title (used by basic facts import)
        created = matched = 0
        for row in rows:
            old_id, level_number, title = row[0], row[1], row[2]
            self._old_level_titles[old_id] = title or ''
            level, new = Level.objects.get_or_create(
                level_number=level_number,
                defaults={'display_name': title or f'Level {level_number}'},
            )
            level_map[old_id] = level
            if new:
                created += 1
            else:
                matched += 1

        self.stdout.write(f'  Levels: {matched} matched existing, {created} created new')
        return level_map

    def _import_topics(self, rows):
        """
        maths_topic cols: id, name
        """
        from classroom.models import Subject, Topic

        maths, _ = Subject.objects.get_or_create(
            name='Mathematics',
            defaults={'slug': 'mathematics', 'is_active': True},
        )
        topic_map = {}
        created = matched = 0
        for i, row in enumerate(rows):
            old_id, name = row[0], row[1]
            topic, new = Topic.objects.get_or_create(
                subject=maths,
                slug=slugify(name),
                defaults={'name': name, 'order': i, 'is_active': True},
            )
            topic_map[old_id] = topic
            if new:
                created += 1
            else:
                matched += 1

        self.stdout.write(f'  Topics: {matched} matched existing, {created} created new')
        return topic_map

    def _import_level_topics(self, rows, level_map, topic_map):
        """
        maths_level_topics cols: id, level_id, topic_id
        Adds levels to each topic's M2M.
        """
        added = skipped = 0
        for row in rows:
            _, old_level_id, old_topic_id = row[0], row[1], row[2]
            level = level_map.get(old_level_id)
            topic = topic_map.get(old_topic_id)
            if level and topic:
                topic.levels.add(level)
                added += 1
            else:
                skipped += 1
        self.stdout.write(f'  Topic-Level links: {added} added, {skipped} skipped')

    def _import_questions_answers(self, q_rows, a_rows, level_map, topic_map):
        """
        maths_question cols:
          id, question_text, question_type, difficulty, points, explanation,
          image, created_at, updated_at, level_id, topic_id
        maths_answer cols:
          id, answer_text, is_correct, order, question_id
        """
        from quiz.models import Question, Answer

        q_map = {}   # old_q_id → Question
        a_map = {}   # old_a_id → Answer
        q_created = q_skipped = 0

        # Build answer lookup by question_id for bulk creation
        answers_by_q = {}
        for row in a_rows:
            old_a_id, answer_text, is_correct, order, old_q_id = row[:5]
            answers_by_q.setdefault(old_q_id, []).append(row)

        for row in q_rows:
            (old_q_id, question_text, question_type, difficulty, points,
             explanation, image, created_at, updated_at, level_id, topic_id) = row[:11]

            level = level_map.get(level_id)
            topic = topic_map.get(topic_id) if topic_id else None
            if not level or not topic:
                q_skipped += 1
                continue

            q, new = Question.objects.get_or_create(
                topic=topic,
                level=level,
                question_text=self._sanitize(question_text),
                defaults={
                    'question_type': Question.MULTIPLE_CHOICE,
                    'difficulty': int(difficulty) if difficulty else 1,
                    'points': int(points) if points else 1,
                    'explanation': self._sanitize(explanation),
                    'image': image or '',
                },
            )
            q_map[old_q_id] = q

            # Always ensure question_type is multiple_choice
            if q.question_type != Question.MULTIPLE_CHOICE:
                q.question_type = Question.MULTIPLE_CHOICE
                q.save(update_fields=['question_type'])

            if new:
                q_created += 1

            # Import answers for this question (new or existing with no answers)
            existing_texts = set(q.answers.values_list('text', flat=True))
            for a_row in answers_by_q.get(old_q_id, []):
                old_a_id, answer_text, is_correct, order, _ = a_row[:5]
                text = self._sanitize(answer_text)
                if text not in existing_texts:
                    answer = Answer.objects.create(
                        question=q,
                        text=text,
                        is_correct=bool(is_correct),
                        display_order=int(order) if order is not None else 0,
                    )
                    a_map[old_a_id] = answer
                    existing_texts.add(text)
                else:
                    existing = q.answers.filter(text=text).first()
                    if existing:
                        a_map[old_a_id] = existing

            if not new:
                q_skipped += 1

        self.stdout.write(
            f'  Questions: {q_created} created, {q_skipped} already existed (answers patched)'
        )
        self.stdout.write(f'  Answers: {len(a_map)} mapped')
        return q_map, a_map

    def _import_classrooms(self, cr_rows, cl_rows, en_rows, user_map, level_map):
        """
        maths_classroom cols: id, name, code, teacher_id
        maths_classroom_levels cols: id, classroom_id, level_id
        maths_enrollment cols: id, date_enrolled, classroom_id, student_id
        """
        from classroom.models import ClassRoom, ClassTeacher, ClassStudent

        cr_map = {}
        for row in cr_rows:
            old_id, name, code, teacher_id = row[0], row[1], row[2], row[3]
            teacher = user_map.get(teacher_id)
            if not teacher:
                continue
            cr, _ = ClassRoom.objects.get_or_create(
                code=code,
                defaults={'name': name, 'created_by': teacher, 'is_active': True},
            )
            cr_map[old_id] = cr
            ClassTeacher.objects.get_or_create(classroom=cr, teacher=teacher)

        for row in cl_rows:
            _, old_cr_id, old_level_id = row[0], row[1], row[2]
            cr = cr_map.get(old_cr_id)
            level = level_map.get(old_level_id)
            if cr and level:
                cr.levels.add(level)

        enrolled = 0
        for row in en_rows:
            _, date_enrolled, old_cr_id, old_student_id = row[0], row[1], row[2], row[3]
            cr = cr_map.get(old_cr_id)
            student = user_map.get(old_student_id)
            if cr and student:
                ClassStudent.objects.get_or_create(classroom=cr, student=student)
                enrolled += 1

        self.stdout.write(
            f'  Classrooms: {len(cr_map)} | Student enrollments: {enrolled}'
        )

    def _import_final_answers(self, rows, user_map, level_map, topic_map):
        """
        maths_studentfinalanswer cols:
          id, session_id, attempt_number, points_earned, last_updated_time,
          level_id, student_id, topic_id
        """
        from progress.models import StudentFinalAnswer

        created = skipped = 0
        for row in rows:
            (old_id, session_id, attempt_number, points_earned,
             last_updated_time, level_id, student_id, topic_id) = row[:8]

            student = user_map.get(student_id)
            level = level_map.get(level_id)
            topic = topic_map.get(topic_id) if topic_id else None
            if not student or not level:
                skipped += 1
                continue

            try:
                sid = uuid.UUID(str(session_id))
            except (ValueError, AttributeError):
                sid = uuid.uuid4()

            obj, new = StudentFinalAnswer.objects.get_or_create(
                session_id=sid,
                defaults={
                    'student': student,
                    'topic': topic,
                    'level': level,
                    'quiz_type': StudentFinalAnswer.QUIZ_TYPE_TOPIC,
                    'attempt_number': int(attempt_number) if attempt_number else 1,
                    'points': float(points_earned) if points_earned is not None else 0.0,
                    'score': 0,
                    'total_questions': 0,
                    'time_taken_seconds': 0,
                },
            )
            if new:
                ts = self._to_datetime(last_updated_time)
                if ts:
                    StudentFinalAnswer.objects.filter(pk=obj.pk).update(completed_at=ts)
                created += 1
            else:
                skipped += 1

        self.stdout.write(f'  StudentFinalAnswer: {created} created, {skipped} skipped')

    def _import_basic_facts(self, rows, user_map, level_map):
        """
        maths_basicfactsresult cols:
          id, session_id, score, total_points, time_taken_seconds,
          points, completed_at, level_id, student_id
        """
        from progress.models import BasicFactsResult

        created = skipped = 0
        for row in rows:
            (old_id, session_id, score, total_points, time_taken_seconds,
             points, completed_at, level_id, student_id) = row[:9]

            student = user_map.get(student_id)
            level = level_map.get(level_id)
            if not student or not level:
                skipped += 1
                continue

            subtopic = self._subtopic_from_level(level)
            if not subtopic:
                skipped += 1
                continue

            try:
                sid = uuid.UUID(str(session_id))
            except (ValueError, AttributeError):
                sid = uuid.uuid4()

            obj, new = BasicFactsResult.objects.get_or_create(
                session_id=sid,
                defaults={
                    'student': student,
                    'subtopic': subtopic,
                    'level_number': level.level_number,
                    'score': int(score) if score is not None else 0,
                    'total_questions': int(total_points) if total_points is not None else 10,
                    'time_taken_seconds': int(time_taken_seconds) if time_taken_seconds is not None else 0,
                    'points': float(points) if points is not None else 0.0,
                    'questions_data': [],
                },
            )
            if new:
                ts = self._to_datetime(completed_at)
                if ts:
                    BasicFactsResult.objects.filter(pk=obj.pk).update(completed_at=ts)
                created += 1
            else:
                skipped += 1

        self.stdout.write(f'  BasicFactsResult: {created} created, {skipped} skipped')

    def _subtopic_from_level(self, level):
        """Determine BasicFacts subtopic from level_number or display_name."""
        num = level.level_number
        # Standard ranges in the new app
        if 100 <= num <= 106:
            return 'Addition'
        if 107 <= num <= 113:
            return 'Subtraction'
        if 114 <= num <= 120:
            return 'Multiplication'
        if 121 <= num <= 127:
            return 'Division'
        if 128 <= num <= 132:
            return 'PlaceValue'
        # Fall back to title-based detection for old level numbers
        title = level.display_name.lower()
        if 'addition' in title:
            return 'Addition'
        if 'subtraction' in title:
            return 'Subtraction'
        if 'multiplication' in title:
            return 'Multiplication'
        if 'division' in title:
            return 'Division'
        if 'place value' in title or 'placevalue' in title:
            return 'PlaceValue'
        return None

    def _import_timelogs(self, rows, user_map):
        """
        maths_timelog cols:
          id, daily_total_seconds, weekly_total_seconds,
          last_reset_date, last_reset_week, last_activity, student_id
        """
        from progress.models import TimeLog

        created = skipped = 0
        for row in rows:
            (old_id, daily_secs, weekly_secs,
             last_reset_date, last_reset_week, last_activity, student_id) = row[:7]

            student = user_map.get(student_id)
            if not student:
                skipped += 1
                continue

            _, new = TimeLog.objects.get_or_create(
                student=student,
                defaults={
                    'daily_seconds': int(daily_secs) if daily_secs is not None else 0,
                    'weekly_seconds': int(weekly_secs) if weekly_secs is not None else 0,
                    'last_daily_reset': self._to_date(last_reset_date),
                    'last_weekly_reset': None,
                },
            )
            if new:
                created += 1
            else:
                skipped += 1

        self.stdout.write(f'  TimeLog: {created} created, {skipped} skipped')

    def _import_statistics(self, rows, level_map, topic_map):
        """
        maths_topiclevelstatistics cols:
          id, average_points, sigma, student_count, last_updated, level_id, topic_id
        """
        from progress.models import TopicLevelStatistics

        created = skipped = 0
        for row in rows:
            (old_id, average_points, sigma, student_count,
             last_updated, level_id, topic_id) = row[:7]

            level = level_map.get(level_id)
            topic = topic_map.get(topic_id)
            if not level or not topic:
                skipped += 1
                continue

            _, new = TopicLevelStatistics.objects.get_or_create(
                topic=topic,
                level=level,
                defaults={
                    'avg_points': float(average_points) if average_points is not None else 0.0,
                    'sigma': float(sigma) if sigma is not None else 0.0,
                    'student_count': int(student_count) if student_count is not None else 0,
                },
            )
            if new:
                created += 1
            else:
                skipped += 1

        self.stdout.write(f'  TopicLevelStatistics: {created} created, {skipped} skipped')

    def _import_student_answers(self, rows, user_map, q_map, a_map):
        """
        maths_studentanswer cols:
          id, text_answer, is_correct, points_earned, answered_at,
          question_id, selected_answer_id, student_id, session_id, time_taken_seconds
        """
        from progress.models import StudentAnswer

        created = skipped = 0
        for row in rows:
            (old_id, text_answer, is_correct, points_earned, answered_at,
             question_id, selected_answer_id, student_id, session_id,
             time_taken_seconds) = row[:10]

            student = user_map.get(student_id)
            question = q_map.get(question_id)
            if not student or not question:
                skipped += 1
                continue

            selected = a_map.get(selected_answer_id) if selected_answer_id else None
            try:
                attempt_uuid = uuid.UUID(str(session_id))
            except (ValueError, AttributeError):
                attempt_uuid = uuid.uuid4()

            obj = StudentAnswer(
                student=student,
                question=question,
                topic=question.topic,
                level=question.level,
                selected_answer=selected,
                text_answer=text_answer or '',
                is_correct=bool(is_correct),
                attempt_id=attempt_uuid,
            )
            obj.save()
            ts = self._to_datetime(answered_at)
            if ts:
                StudentAnswer.objects.filter(pk=obj.pk).update(answered_at=ts)
            created += 1

        self.stdout.write(f'  StudentAnswer: {created} created, {skipped} skipped')

    def _assign_unlimited_promo(self, user_map):
        """Assign the UNLIMITED2026 promo code to all imported individual students."""
        from billing.models import PromoCode
        from accounts.models import Role

        try:
            promo = PromoCode.objects.get(code='UNLIMITED2026')
        except PromoCode.DoesNotExist:
            self.stdout.write(self.style.WARNING(
                '  Promo UNLIMITED2026 not found — skipping promo assignment. Run migrate first.'
            ))
            return

        individual_student_role = Role.objects.filter(name=Role.INDIVIDUAL_STUDENT).first()
        if not individual_student_role:
            return

        assigned = 0
        for user in user_map.values():
            if user.user_roles.filter(role=individual_student_role).exists():
                promo.redeemed_by.add(user)
                assigned += 1

        self.stdout.write(f'  Promo UNLIMITED2026 assigned to {assigned} individual student(s)')

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def _sanitize(self, text):
        """Strip 4-byte Unicode characters (e.g. math symbols) that MySQL utf8
        charset cannot store. Use utf8mb4 on the DB to preserve them instead."""
        if not text:
            return text or ''
        # Characters above U+FFFF require 4 bytes in UTF-8 and break MySQL utf8
        return ''.join(c for c in text if ord(c) <= 0xFFFF)

    def _to_datetime(self, val):
        if val is None:
            return None
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(str(val), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def _to_date(self, val):
        if val is None:
            return None
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, date):
            return val
        try:
            return datetime.strptime(str(val), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None
