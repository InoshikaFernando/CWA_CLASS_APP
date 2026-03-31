"""
Management command: python manage.py import_prod_progress <path/to/prod_dump.sql>

Imports StudentFinalAnswer (quiz results) from a production MySQL dump into the
current (post-migration-0010) test database.

The dump uses old maths.Topic / maths.Level FKs.  This command:
  1. Parses maths_topic, maths_level, maths_studentfinalanswer from the dump.
  2. Maps old topic/level IDs to classroom.Topic / classroom.Level (same logic
     as migration 0010 — name + level_number matching).
  3. Maps old student IDs to current accounts.CustomUser by username.
  4. Creates StudentFinalAnswer records (skips duplicates by session_id).

Usage
-----
    python manage.py import_prod_progress /path/to/prod_dump.sql
    python manage.py import_prod_progress /path/to/prod_dump.sql --dry-run
"""

import re
import uuid
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Import StudentFinalAnswer progress records from a production MySQL dump.'

    def add_arguments(self, parser):
        parser.add_argument('sql_file', type=str,
                            help='Path to prod MySQL dump .sql file')
        parser.add_argument('--dry-run', action='store_true',
                            help='Parse and report without writing')

    def handle(self, *args, **options):
        sql_file = options['sql_file']
        dry_run  = options['dry_run']

        self.stdout.write(f'Reading {sql_file} …')
        try:
            with open(sql_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except FileNotFoundError:
            raise CommandError(f'File not found: {sql_file}')

        self.stdout.write('Parsing SQL …')
        user_rows   = self._parse_table(content, 'accounts_customuser')
        topic_rows  = self._parse_table(content, 'maths_topic')
        level_rows  = self._parse_table(content, 'maths_level')
        sfa_rows    = self._parse_table(content, 'maths_studentfinalanswer')

        self.stdout.write(
            f'  accounts_customuser:    {len(user_rows)}\n'
            f'  maths_topic:            {len(topic_rows)}\n'
            f'  maths_level:            {len(level_rows)}\n'
            f'  maths_studentfinalanswer: {len(sfa_rows)}'
        )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('Dry run — no DB writes.'))
            return

        user_map  = self._build_user_map(user_rows)
        topic_map = self._build_topic_map(topic_rows)
        level_map = self._build_level_map(level_rows)

        with transaction.atomic():
            created = skipped = 0

            for row in sfa_rows:
                # maths_studentfinalanswer columns (production dump order):
                # id(0) session_id(1) attempt_number(2) points_earned(3)
                # last_updated_time(4) level_id(5) student_id(6) topic_id(7)
                # completed_at(8) points(9) quiz_type(10) score(11)
                # time_taken_seconds(12) total_questions(13) operation(14)
                # table_number(15)
                if len(row) < 10:
                    skipped += 1
                    continue

                session_id     = row[1]
                attempt_number = int(row[2]) if row[2] is not None else 1
                points_earned  = float(row[3]) if row[3] is not None else 0.0
                old_level_id   = row[5]
                old_student_id = row[6]
                old_topic_id   = row[7]
                completed_at   = row[8]
                points         = float(row[9]) if row[9] is not None else 0.0
                quiz_type      = row[10] or 'topic'
                score          = int(row[11]) if row[11] is not None else 0
                time_taken     = int(row[12]) if row[12] is not None else 0
                total_q        = int(row[13]) if row[13] is not None else 0
                operation      = row[14] or ''

                student = user_map.get(old_student_id)
                if not student:
                    skipped += 1
                    continue

                level = level_map.get(old_level_id)
                topic = topic_map.get(old_topic_id) if old_topic_id else None

                # Normalise session_id to a valid string
                try:
                    sid = str(uuid.UUID(str(session_id))) if session_id else str(uuid.uuid4())
                except (ValueError, AttributeError):
                    sid = str(uuid.uuid4())

                from maths.models import StudentFinalAnswer as SFA
                obj, new = SFA.objects.get_or_create(
                    session_id=sid,
                    defaults={
                        'student':          student,
                        'level':            level,
                        'topic':            topic,
                        'quiz_type':        quiz_type,
                        'attempt_number':   attempt_number,
                        'score':            score,
                        'total_questions':  total_q,
                        'points':           points,
                        'points_earned':    points_earned,
                        'time_taken_seconds': time_taken,
                        'operation':        operation,
                    },
                )
                if new:
                    if completed_at:
                        from django.utils.timezone import make_aware
                        from datetime import datetime, timezone as _tz
                        try:
                            dt = datetime.strptime(str(completed_at), '%Y-%m-%d %H:%M:%S.%f')
                        except ValueError:
                            try:
                                dt = datetime.strptime(str(completed_at), '%Y-%m-%d %H:%M:%S')
                            except ValueError:
                                dt = None
                        if dt:
                            SFA.objects.filter(pk=obj.pk).update(
                                completed_at=dt.replace(tzinfo=_tz.utc)
                            )
                    created += 1
                else:
                    skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nDone!  StudentFinalAnswer: {created} created, {skipped} skipped'
        ))

    # ── SQL parser (same as import_prod_questions) ────────────────────────────

    def _parse_table(self, content, table_name):
        pattern = (
            r"INSERT INTO `" + re.escape(table_name) + r"` VALUES\s+(.*?);"
        )
        match = re.search(pattern, content, re.DOTALL)
        if not match:
            return []
        return self._extract_rows(match.group(1))

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

    # ── Map builders ─────────────────────────────────────────────────────────

    def _build_user_map(self, user_rows):
        """old_user_id → CustomUser — matched by username."""
        from accounts.models import CustomUser
        user_map = {}
        for row in user_rows:
            if len(row) < 5:
                continue
            old_id   = row[0]
            username = row[4]
            user = CustomUser.objects.filter(username=username).first()
            if user:
                user_map[old_id] = user
        matched = len(user_map)
        self.stdout.write(f'  User map: {matched} / {len(user_rows)} matched by username')
        return user_map

    def _build_topic_map(self, topic_rows):
        from classroom.models import Topic as ClassroomTopic, Subject
        try:
            math_subject = Subject.objects.get(slug='mathematics', school=None)
        except Subject.DoesNotExist:
            self.stdout.write(self.style.WARNING('Mathematics subject not found'))
            return {}
        topic_map = {}
        for row in topic_rows:
            if len(row) < 2:
                continue
            old_id, name = row[0], row[1]
            ct = ClassroomTopic.objects.filter(
                subject=math_subject, name__iexact=name
            ).first()
            if ct:
                topic_map[old_id] = ct
        self.stdout.write(f'  Topic map: {len(topic_map)} / {len(topic_rows)} resolved')
        return topic_map

    def _build_level_map(self, level_rows):
        from classroom.models import Level as ClassroomLevel
        level_map = {}
        for row in level_rows:
            if len(row) < 2:
                continue
            old_id, level_num = row[0], row[1]
            title = row[2] if len(row) > 2 else ''
            cl, _ = ClassroomLevel.objects.get_or_create(
                level_number=level_num,
                defaults={'display_name': title or f'Year {level_num}'},
            )
            level_map[old_id] = cl
        self.stdout.write(f'  Level map: {len(level_map)} entries')
        return level_map
