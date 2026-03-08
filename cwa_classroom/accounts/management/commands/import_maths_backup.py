"""
Management command: python manage.py import_maths_backup <path/to/backup.sql>

Imports progress data from a backup that already uses maths_* table names
(i.e. a backup taken FROM the new app's database, not the old CWA_SCHOOL site).

Column analysis from backup inspection:
  maths_customuser (15 cols):
    id(0), password(1), last_login(2), is_superuser(3), username(4),
    first_name(5), last_name(6), email(7), is_staff(8), is_active(9),
    date_joined(10), country(11), date_of_birth(12), region(13), ...

  maths_basicfactsresult (9 cols):
    id(0), session_id(1), score(2), total_points(3), time_taken_seconds(4),
    points(5), completed_at(6), student_id(7), level_id(8)
    → missing: subtopic, level_number, questions_data  (default to '', None, [])

  maths_studentfinalanswer (8 cols):
    id(0), session_id(1), attempt_number(2), points(3), completed_at(4),
    level_id(5), student_id(6), topic_id(7)
    → missing: quiz_type, score, total_questions, time_taken_seconds, operation

  maths_timelog (7 cols):
    id(0), daily_total_seconds(1), weekly_total_seconds(2),
    last_reset_date(3), last_reset_week(4), last_activity(5), student_id(6)

  maths_topiclevelstatistics (7 cols):
    id(0), average_points(1), sigma(2), student_count(3),
    updated_at(4), level_id(5), topic_id(6)

  maths_studentanswer (10 cols):
    id(0), text_answer(1), ordered_answer_ids(2), is_correct(3),
    answered_at(4), level_id(5), question_id(6), selected_answer_id(7),
    attempt_id(8), student_id(9)

NOTE: maths_level, maths_topic, maths_question, maths_answer were already
imported directly via MySQL with original IDs preserved, so all FK references
to those tables work as-is. Only student_id needs remapping via user_map.
"""

import re
import uuid
from datetime import date, datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Import progress data from a maths_* schema MySQL backup.'

    def add_arguments(self, parser):
        parser.add_argument('sql_file', type=str, help='Path to MySQL backup .sql file')
        parser.add_argument('--dry-run', action='store_true',
                            help='Parse and count rows without writing to DB')

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
            # 1. Users
            user_map = self._import_users(tables.get('maths_customuser', []))

            # 2. StudentFinalAnswer
            self._import_final_answers(
                tables.get('maths_studentfinalanswer', []), user_map)

            # 3. BasicFactsResult
            self._import_basic_facts(
                tables.get('maths_basicfactsresult', []), user_map)

            # 4. TimeLog
            self._import_timelogs(
                tables.get('maths_timelog', []), user_map)

            # 5. TopicLevelStatistics
            self._import_statistics(
                tables.get('maths_topiclevelstatistics', []))

            # 6. StudentAnswer
            self._import_student_answers(
                tables.get('maths_studentanswer', []), user_map)

        self.stdout.write(self.style.SUCCESS('\nImport complete!'))

    # ── SQL PARSER ────────────────────────────────────────────────────────────

    def _parse_inserts(self, lines):
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
            i += 1
            row, i = self._parse_row(values_str, i, n)
            rows.append(tuple(row))
        return rows

    def _parse_row(self, s, i, n):
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
                values.append(self._coerce(raw))
                i = j
        return values, i

    def _parse_string(self, s, i, n):
        chars = []
        ESC = {"'": "'", '"': '"', 'n': '\n', 'r': '\r',
               't': '\t', '\\': '\\', '0': '\x00'}
        while i < n:
            c = s[i]
            if c == '\\' and i + 1 < n:
                chars.append(ESC.get(s[i + 1], s[i + 1]))
                i += 2
            elif c == "'":
                if i + 1 < n and s[i + 1] == "'":
                    chars.append("'")
                    i += 2
                else:
                    i += 1
                    break
            else:
                chars.append(c)
                i += 1
        return ''.join(chars), i

    def _coerce(self, raw):
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
          id(0), password(1), last_login(2), is_superuser(3), username(4),
          first_name(5), last_name(6), email(7), is_staff(8), is_active(9),
          date_joined(10), country(11), date_of_birth(12), region(13), ...
        """
        from accounts.models import CustomUser, Role, UserRole

        individual_role, _ = Role.objects.get_or_create(
            name=Role.INDIVIDUAL_STUDENT,
            defaults={'display_name': 'Individual Student', 'is_active': True},
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN,
            defaults={'display_name': 'Admin', 'is_active': True},
        )

        user_map = {}
        created = skipped = 0
        for row in rows:
            old_id      = row[0]
            password    = row[1]
            is_superuser = bool(row[3]) if len(row) > 3 else False
            username    = row[4] if len(row) > 4 else ''
            first_name  = row[5] if len(row) > 5 else ''
            last_name   = row[6] if len(row) > 6 else ''
            email       = row[7] if len(row) > 7 else ''
            is_staff    = bool(row[8]) if len(row) > 8 else False
            is_active   = bool(row[9]) if len(row) > 9 else True
            country     = row[11] if len(row) > 11 else ''
            dob         = row[12] if len(row) > 12 else None
            region      = row[13] if len(row) > 13 else ''

            if not username:
                continue

            user, new = CustomUser.objects.get_or_create(
                username=username,
                defaults={
                    'email': email or '',
                    'first_name': first_name or '',
                    'last_name': last_name or '',
                    'is_staff': is_staff,
                    'is_superuser': is_superuser,
                    'is_active': is_active,
                    'country': country or '',
                    'region': region or '',
                    'date_of_birth': self._to_date(dob),
                },
            )
            if new:
                user.password = password
                user.save(update_fields=['password'])
                role = admin_role if (is_superuser or is_staff) else individual_role
                UserRole.objects.get_or_create(user=user, role=role)
                created += 1
            else:
                skipped += 1
            user_map[old_id] = user

        self.stdout.write(f'  Users: {created} created, {skipped} already existed')
        return user_map

    def _import_final_answers(self, rows, user_map):
        """
        maths_studentfinalanswer (8 cols):
          id(0), session_id(1), attempt_number(2), points(3), completed_at(4),
          level_id(5), student_id(6), topic_id(7)
        level_id and topic_id reference maths_level/maths_topic already imported.
        """
        from maths.models import StudentFinalAnswer as MSFA, Level, Topic

        created = skipped = 0
        for row in rows:
            session_id     = row[1] if len(row) > 1 else None
            attempt_number = row[2] if len(row) > 2 else 1
            points         = row[3] if len(row) > 3 else 0.0
            completed_at   = row[4] if len(row) > 4 else None
            level_id       = row[5] if len(row) > 5 else None
            student_id     = row[6] if len(row) > 6 else None
            topic_id       = row[7] if len(row) > 7 else None

            student = user_map.get(student_id)
            if not student:
                skipped += 1
                continue

            # level and topic IDs are already production IDs (imported directly)
            level = Level.objects.filter(pk=level_id).first() if level_id else None
            topic = Topic.objects.filter(pk=topic_id).first() if topic_id else None

            try:
                sid = str(uuid.UUID(str(session_id))) if session_id else str(uuid.uuid4())
            except (ValueError, AttributeError):
                sid = str(uuid.uuid4())

            obj, new = MSFA.objects.get_or_create(
                session_id=sid,
                defaults={
                    'student': student,
                    'level': level,
                    'topic': topic,
                    'quiz_type': 'topic',
                    'attempt_number': int(attempt_number) if attempt_number else 1,
                    'score': 0,
                    'total_questions': 0,
                    'points': float(points) if points is not None else 0.0,
                    'time_taken_seconds': 0,
                    'operation': '',
                },
            )
            if new:
                ts = self._to_datetime(completed_at)
                if ts:
                    MSFA.objects.filter(pk=obj.pk).update(completed_at=ts)
                created += 1
            else:
                skipped += 1

        self.stdout.write(f'  StudentFinalAnswer: {created} created, {skipped} skipped')

    def _import_basic_facts(self, rows, user_map):
        """
        maths_basicfactsresult (9 cols):
          id(0), session_id(1), score(2), total_points(3), time_taken_seconds(4),
          points(5), completed_at(6), student_id(7), level_id(8)
        """
        from maths.models import BasicFactsResult as MBFR

        created = skipped = 0
        for row in rows:
            session_id   = row[1] if len(row) > 1 else None
            score        = row[2] if len(row) > 2 else 0
            total_points = row[3] if len(row) > 3 else 10
            time_taken   = row[4] if len(row) > 4 else 0
            points       = row[5] if len(row) > 5 else 0.0
            completed_at = row[6] if len(row) > 6 else None
            student_id   = row[7] if len(row) > 7 else None

            student = user_map.get(student_id)
            if not student:
                skipped += 1
                continue

            try:
                sid = str(uuid.UUID(str(session_id))) if session_id else str(uuid.uuid4())
            except (ValueError, AttributeError):
                sid = str(uuid.uuid4())

            obj, new = MBFR.objects.get_or_create(
                session_id=sid,
                defaults={
                    'student': student,
                    'subtopic': '',
                    'level_number': None,
                    'score': int(score) if score is not None else 0,
                    'total_points': int(total_points) if total_points is not None else 10,
                    'time_taken_seconds': int(time_taken) if time_taken is not None else 0,
                    'points': float(points) if points is not None else 0.0,
                    'questions_data': [],
                },
            )
            if new:
                ts = self._to_datetime(completed_at)
                if ts:
                    MBFR.objects.filter(pk=obj.pk).update(completed_at=ts)
                created += 1
            else:
                skipped += 1

        self.stdout.write(f'  BasicFactsResult: {created} created, {skipped} skipped')

    def _import_timelogs(self, rows, user_map):
        """
        maths_timelog (7 cols):
          id(0), daily_total_seconds(1), weekly_total_seconds(2),
          last_reset_date(3), last_reset_week(4), last_activity(5), student_id(6)
        """
        from maths.models import TimeLog as MTL

        created = updated = skipped = 0
        for row in rows:
            daily_secs  = row[1] if len(row) > 1 else 0
            weekly_secs = row[2] if len(row) > 2 else 0
            student_id  = row[6] if len(row) > 6 else None

            student = user_map.get(student_id)
            if not student:
                skipped += 1
                continue

            tl, new = MTL.objects.get_or_create(
                student=student,
                defaults={
                    'daily_total_seconds': int(daily_secs) if daily_secs else 0,
                    'weekly_total_seconds': int(weekly_secs) if weekly_secs else 0,
                },
            )
            if new:
                created += 1
            else:
                # Update if backup has more data
                tl.daily_total_seconds = int(daily_secs) if daily_secs else 0
                tl.weekly_total_seconds = int(weekly_secs) if weekly_secs else 0
                tl.save(update_fields=['daily_total_seconds', 'weekly_total_seconds'])
                updated += 1

        self.stdout.write(f'  TimeLog: {created} created, {updated} updated, {skipped} skipped')

    def _import_statistics(self, rows):
        """
        maths_topiclevelstatistics (7 cols):
          id(0), average_points(1), sigma(2), student_count(3),
          updated_at(4), level_id(5), topic_id(6)
        level_id/topic_id already reference production IDs.
        """
        from maths.models import TopicLevelStatistics as MTLS, Level, Topic

        created = skipped = 0
        for row in rows:
            avg_points    = row[1] if len(row) > 1 else 0.0
            sigma         = row[2] if len(row) > 2 else 0.0
            student_count = row[3] if len(row) > 3 else 0
            level_id      = row[5] if len(row) > 5 else None
            topic_id      = row[6] if len(row) > 6 else None

            level = Level.objects.filter(pk=level_id).first() if level_id else None
            topic = Topic.objects.filter(pk=topic_id).first() if topic_id else None

            if not level or not topic:
                skipped += 1
                continue

            _, new = MTLS.objects.get_or_create(
                topic=topic,
                level=level,
                defaults={
                    'average_points': float(avg_points) if avg_points else 0.0,
                    'sigma': float(sigma) if sigma else 0.0,
                    'student_count': int(student_count) if student_count else 0,
                },
            )
            if new:
                created += 1
            else:
                skipped += 1

        self.stdout.write(f'  TopicLevelStatistics: {created} created, {skipped} skipped')

    def _import_student_answers(self, rows, user_map):
        """
        maths_studentanswer (10 cols) — actual backup column order:
          id(0), text_answer(1), is_correct(2), points_earned(3),
          answered_at(4), question_id(5), selected_answer_id(6),
          student_id(7), attempt_id(8), level_or_topic_id(9)
        question_id/selected_answer_id already reference production IDs.
        """
        from maths.models import StudentAnswer as MSA, Question, Answer

        created = skipped = 0
        for row in rows:
            text_answer      = row[1] if len(row) > 1 else ''
            is_correct       = row[2] if len(row) > 2 else False
            answered_at      = row[4] if len(row) > 4 else None
            question_id      = row[5] if len(row) > 5 else None
            selected_ans_id  = row[6] if len(row) > 6 else None
            student_id       = row[7] if len(row) > 7 else None
            attempt_id_raw   = row[8] if len(row) > 8 else None
            ordered_ans_ids  = None  # not present in this backup version

            student  = user_map.get(student_id)
            question = Question.objects.filter(pk=question_id).first() if question_id else None
            if not student or not question:
                skipped += 1
                continue

            selected = Answer.objects.filter(pk=selected_ans_id).first() if selected_ans_id else None

            try:
                attempt_uuid = uuid.UUID(str(attempt_id_raw)) if attempt_id_raw else uuid.uuid4()
            except (ValueError, AttributeError):
                attempt_uuid = uuid.uuid4()

            if isinstance(ordered_ans_ids, str):
                import json as _json
                try:
                    ordered_ans_ids = _json.loads(ordered_ans_ids)
                except Exception:
                    ordered_ans_ids = None

            try:
                obj, new = MSA.objects.get_or_create(
                    student=student,
                    question=question,
                    defaults={
                        'selected_answer': selected,
                        'text_answer': text_answer or '',
                        'ordered_answer_ids': ordered_ans_ids,
                        'is_correct': bool(is_correct),
                        'attempt_id': attempt_uuid,
                    },
                )
                if new:
                    ts = self._to_datetime(answered_at)
                    if ts:
                        MSA.objects.filter(pk=obj.pk).update(answered_at=ts)
                    created += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1

        self.stdout.write(f'  StudentAnswer: {created} created, {skipped} skipped')

    # ── HELPERS ───────────────────────────────────────────────────────────────

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
