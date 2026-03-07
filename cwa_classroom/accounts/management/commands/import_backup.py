"""
Management command: python manage.py import_backup <path/to/backup.sql>

Reads a mysqldump backup of CWA_CLASS_APP and imports data into the current
database, mapping progress_* / quiz_* tables → maths_* models.

Table → Model mapping:
  accounts_customuser          → accounts.CustomUser
  classroom_level              → classroom.Level  +  maths.Level
  classroom_topic              → classroom.Topic  +  maths.Topic
  classroom_topic_levels       → classroom.Topic.levels  +  maths.Level.topics
  quiz_question                → maths.Question
  quiz_answer                  → maths.Answer  (text→answer_text, display_order→order)
  classroom_classroom          → classroom.ClassRoom
  classroom_classteacher       → classroom.ClassTeacher
  classroom_classstudent       → classroom.ClassStudent
  classroom_classroom_levels   → ClassRoom.levels
  progress_studentfinalanswer  → maths.StudentFinalAnswer
  progress_basicfactsresult    → maths.BasicFactsResult
  progress_timelog             → maths.TimeLog
  progress_topiclevelstatistics→ maths.TopicLevelStatistics
  progress_studentanswer       → maths.StudentAnswer

Usage:
  python manage.py import_backup ../backup.sql
  python manage.py import_backup ../backup.sql --dry-run
"""

import re
import uuid
from datetime import date, datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify


class Command(BaseCommand):
    help = 'Import data from a CWA_CLASS_APP MySQL backup into the current schema.'

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
            # 1. Users
            user_map = self._import_users(tables.get('accounts_customuser', []))

            # 2. Levels — builds self._maths_level_map {backup_level_id → maths.Level}
            level_map = self._build_level_map(tables.get('classroom_level', []))

            # 3. Topics — builds self._maths_topic_map {backup_topic_id → maths.Topic}
            topic_map = self._import_topics(tables.get('classroom_topic', []))

            # 4. Topic ↔ Level links
            self._import_level_topics(
                tables.get('classroom_topic_levels', []), level_map, topic_map,
            )

            # 5. Questions + Answers (quiz_* → maths_*)
            q_map, a_map = self._import_questions_answers(
                tables.get('quiz_question', []),
                tables.get('quiz_answer', []),
                level_map, topic_map,
            )

            # 6. Classrooms
            self._import_classrooms(
                tables.get('classroom_classroom', []),
                tables.get('classroom_classroom_levels', []),
                tables.get('classroom_classstudent', []),
                tables.get('classroom_classteacher', []),
                user_map, level_map,
            )

            # 7. Progress data (progress_* → maths_*)
            self._import_final_answers(
                tables.get('progress_studentfinalanswer', []),
                user_map, level_map, topic_map,
            )
            self._import_basic_facts(
                tables.get('progress_basicfactsresult', []),
                user_map,
            )
            self._import_timelogs(tables.get('progress_timelog', []), user_map)
            self._import_statistics(
                tables.get('progress_topiclevelstatistics', []),
                level_map, topic_map,
            )
            self._import_student_answers(
                tables.get('progress_studentanswer', []),
                user_map, q_map, a_map, level_map, topic_map,
            )

            # 8. Promo codes
            self._assign_unlimited_promo(user_map)

        self.stdout.write(self.style.SUCCESS('\nImport complete!'))

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
                values.append(self._coerce_scalar(raw))
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
        accounts_customuser cols (AbstractUser + custom):
          id, password, last_login, is_superuser, username, first_name,
          last_name, email, is_staff, is_active, date_joined,
          country, date_of_birth, region  [+ any extra fields]
        """
        from accounts.models import CustomUser, Role, UserRole

        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher', 'is_active': True},
        )
        individual_student_role, _ = Role.objects.get_or_create(
            name=Role.INDIVIDUAL_STUDENT,
            defaults={'display_name': 'Individual Student', 'is_active': True},
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin', 'is_active': True},
        )

        user_map = {}
        created = skipped = 0
        for row in rows:
            # Positional: id(0) password(1) last_login(2) is_superuser(3) username(4)
            #             first_name(5) last_name(6) email(7) is_staff(8) is_active(9)
            #             date_joined(10) country(11) date_of_birth(12) region(13)
            old_id      = row[0]
            password    = row[1]
            is_superuser = row[3]
            username    = row[4]
            first_name  = row[5] if len(row) > 5 else ''
            last_name   = row[6] if len(row) > 6 else ''
            email       = row[7] if len(row) > 7 else ''
            is_staff    = row[8] if len(row) > 8 else False
            is_active   = row[9] if len(row) > 9 else True
            country     = row[11] if len(row) > 11 else ''
            dob         = row[12] if len(row) > 12 else None
            region      = row[13] if len(row) > 13 else ''

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
                user.password = password
                user.save(update_fields=['password'])
                if bool(is_superuser) or bool(is_staff):
                    UserRole.objects.get_or_create(user=user, role=admin_role)
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
        classroom_level cols: id, level_number, display_name

        Returns {backup_level_id → classroom.Level}.
        Also builds self._maths_level_map {backup_level_id → maths.Level}.
        """
        from classroom.models import Level as ClassroomLevel
        from maths.models import Level as MathsLevel

        level_map = {}
        self._maths_level_map = {}
        created = matched = 0
        for row in rows:
            old_id, level_number, display_name = row[0], row[1], (row[2] if len(row) > 2 else '')

            # classroom.Level
            cl, new = ClassroomLevel.objects.get_or_create(
                level_number=level_number,
                defaults={'display_name': display_name or f'Level {level_number}'},
            )
            level_map[old_id] = cl
            if new:
                created += 1
            else:
                matched += 1

            # maths.Level (parallel — same level_number)
            ml, _ = MathsLevel.objects.get_or_create(
                level_number=level_number,
                defaults={'title': display_name or f'Year {level_number}'},
            )
            self._maths_level_map[old_id] = ml

        self.stdout.write(f'  Levels: {matched} matched existing, {created} created new')
        return level_map

    def _import_topics(self, rows):
        """
        classroom_topic cols: id, name, slug, order, is_active, parent_id, subject_id

        Returns {backup_topic_id → classroom.Topic}.
        Also builds self._maths_topic_map {backup_topic_id → maths.Topic}.
        """
        from classroom.models import Subject, Topic as ClassroomTopic
        from maths.models import Topic as MathsTopic

        maths_subject, _ = Subject.objects.get_or_create(
            name='Mathematics',
            defaults={'slug': 'mathematics', 'is_active': True},
        )

        topic_map = {}
        self._maths_topic_map = {}
        created = matched = 0

        for i, row in enumerate(rows):
            old_id      = row[0]
            name        = row[1]
            slug        = row[2] if len(row) > 2 else slugify(name)
            order       = row[3] if len(row) > 3 else i
            is_active   = row[4] if len(row) > 4 else True
            parent_id   = row[5] if len(row) > 5 else None
            subject_id  = row[6] if len(row) > 6 else None

            ct, new = ClassroomTopic.objects.get_or_create(
                subject=maths_subject,
                slug=slug or slugify(name),
                defaults={'name': name, 'order': order or i, 'is_active': bool(is_active)},
            )
            topic_map[old_id] = ct
            if new:
                created += 1
            else:
                matched += 1

            # maths.Topic (flat — just name)
            mt, _ = MathsTopic.objects.get_or_create(name=name)
            self._maths_topic_map[old_id] = mt

        self.stdout.write(f'  Topics: {matched} matched existing, {created} created new')
        return topic_map

    def _import_level_topics(self, rows, level_map, topic_map):
        """
        classroom_topic_levels cols: id, topic_id, level_id
        Links topics to levels in both classroom and maths models.
        """
        added = skipped = 0
        for row in rows:
            _, old_topic_id, old_level_id = row[0], row[1], row[2]
            cl_topic = topic_map.get(old_topic_id)
            cl_level = level_map.get(old_level_id)
            ml_topic = self._maths_topic_map.get(old_topic_id)
            ml_level = self._maths_level_map.get(old_level_id)

            if cl_topic and cl_level:
                cl_topic.levels.add(cl_level)
            if ml_topic and ml_level:
                ml_level.topics.add(ml_topic)
                added += 1
            else:
                skipped += 1

        self.stdout.write(f'  Topic-Level links: {added} added, {skipped} skipped')

    def _import_questions_answers(self, q_rows, a_rows, level_map, topic_map):
        """
        quiz_question actual backup column order (FK created_by_id / level / topic at end):
          id(0), question_text(1), question_type(2), difficulty(3), points(4),
          explanation(5), image(6), created_at(7), updated_at(8),
          created_by_id(9), level_id(10), topic_id(11)

        quiz_answer cols (question_id FK at end):
          id(0), text(1), is_correct(2), display_order(3), question_id(4)

        Imports into maths.Question / maths.Answer using maths level/topic maps.
        """
        from maths.models import Question as MQ, Answer as MA

        q_map = {}
        a_map = {}
        q_created = q_skipped = 0

        answers_by_q = {}
        for row in a_rows:
            old_a_id, text, is_correct, display_order, old_q_id = (
                row[0], row[1], row[2], row[3], row[4],
            )
            answers_by_q.setdefault(old_q_id, []).append(row)

        for row in q_rows:
            old_q_id      = row[0]
            question_text = row[1]
            question_type = row[2] if len(row) > 2 else 'multiple_choice'
            difficulty    = row[3] if len(row) > 3 else 1
            points        = row[4] if len(row) > 4 else 1
            explanation   = row[5] if len(row) > 5 else ''
            image         = row[6] if len(row) > 6 else ''
            # Actual backup column order (FKs added at end via migrations):
            # id, question_text, question_type, difficulty, points, explanation,
            # image, created_at, updated_at, created_by_id, level_id, topic_id
            level_id      = row[10] if len(row) > 10 else None
            topic_id      = row[11] if len(row) > 11 else None

            # Bridge: classroom.Level.id → maths.Level
            ml = self._maths_level_map.get(level_id)
            mt = self._maths_topic_map.get(topic_id) if topic_id else None
            if not ml or not mt:
                q_skipped += 1
                continue

            q, new = MQ.objects.get_or_create(
                topic=mt, level=ml,
                question_text=self._sanitize(question_text),
                defaults={
                    'question_type': question_type or MQ.MULTIPLE_CHOICE,
                    'difficulty': int(difficulty) if difficulty else 1,
                    'points': int(points) if points else 1,
                    'explanation': self._sanitize(explanation) or '',
                    'image': image or '',
                },
            )
            q_map[old_q_id] = q
            if new:
                q_created += 1
            else:
                q_skipped += 1

            # Answers
            existing_texts = set(q.answers.values_list('answer_text', flat=True))
            for a_row in answers_by_q.get(old_q_id, []):
                old_a_id, text, is_correct, display_order, _ = (
                    a_row[0], a_row[1], a_row[2], a_row[3], a_row[4],
                )
                text = self._sanitize(text) or ''
                if text not in existing_texts:
                    answer = MA.objects.create(
                        question=q,
                        answer_text=text,
                        is_correct=bool(is_correct),
                        order=int(display_order) if display_order is not None else 0,
                    )
                    a_map[old_a_id] = answer
                    existing_texts.add(text)
                else:
                    existing = q.answers.filter(answer_text=text).first()
                    if existing:
                        a_map[old_a_id] = existing

        self.stdout.write(
            f'  Questions: {q_created} created, {q_skipped} already existed/skipped'
        )
        self.stdout.write(f'  Answers: {len(a_map)} mapped')
        return q_map, a_map

    def _import_classrooms(self, cr_rows, cl_rows, en_rows, ct_rows, user_map, level_map):
        """
        classroom_classroom cols: id, name, code, is_active, created_at, created_by_id
        classroom_classteacher cols: id, classroom_id, teacher_id
        classroom_classstudent cols: id, classroom_id, student_id, date_enrolled (approx)
        classroom_classroom_levels cols: id, classroom_id, level_id
        """
        from classroom.models import ClassRoom, ClassTeacher, ClassStudent

        cr_map = {}

        # Create classrooms
        for row in cr_rows:
            old_id = row[0]
            name   = row[1]
            code   = row[2]
            # is_active at row[3], created_at at row[4], created_by_id at row[5]
            created_by_id = row[5] if len(row) > 5 else None
            creator = user_map.get(created_by_id)

            cr, _ = ClassRoom.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'is_active': bool(row[3]) if len(row) > 3 else True,
                    'created_by': creator,
                },
            )
            cr_map[old_id] = cr

        # Teacher assignments
        for row in ct_rows:
            _, old_cr_id, old_teacher_id = row[0], row[1], row[2]
            cr = cr_map.get(old_cr_id)
            teacher = user_map.get(old_teacher_id)
            if cr and teacher:
                ClassTeacher.objects.get_or_create(classroom=cr, teacher=teacher)

        # Level links
        for row in cl_rows:
            _, old_cr_id, old_level_id = row[0], row[1], row[2]
            cr = cr_map.get(old_cr_id)
            level = level_map.get(old_level_id)
            if cr and level:
                cr.levels.add(level)

        # Student enrollments
        # Actual backup column order: id, joined_at, classroom_id, student_id
        enrolled = 0
        for row in en_rows:
            old_id     = row[0]
            old_cr_id  = row[2]
            old_stu_id = row[3]
            cr = cr_map.get(old_cr_id)
            student = user_map.get(old_stu_id)
            if cr and student:
                ClassStudent.objects.get_or_create(classroom=cr, student=student)
                enrolled += 1

        self.stdout.write(
            f'  Classrooms: {len(cr_map)} | Student enrollments: {enrolled}'
        )

    def _import_final_answers(self, rows, user_map, level_map, topic_map):
        """
        progress_studentfinalanswer actual backup column order (FKs at end):
          id(0), quiz_type(1), session_id(2), attempt_number(3), score(4),
          total_questions(5), points(6), time_taken_seconds(7), completed_at(8),
          level_id(9), student_id(10), topic_id(11), operation(12)

        topic_id/level_id are classroom IDs → bridge to maths via _maths_*_map.
        """
        from maths.models import StudentFinalAnswer as MSFA

        created = skipped = 0
        for row in rows:
            old_id         = row[0]
            quiz_type      = row[1] if len(row) > 1 else 'topic'
            session_id     = row[2] if len(row) > 2 else None
            attempt_number = row[3] if len(row) > 3 else 1
            score          = row[4] if len(row) > 4 else 0
            total_q        = row[5] if len(row) > 5 else 0
            points         = row[6] if len(row) > 6 else 0.0
            time_taken     = row[7] if len(row) > 7 else 0
            completed_at   = row[8] if len(row) > 8 else None
            level_id       = row[9] if len(row) > 9 else None
            student_id     = row[10] if len(row) > 10 else None
            topic_id       = row[11] if len(row) > 11 else None
            operation      = row[12] if len(row) > 12 else ''

            student = user_map.get(student_id)
            ml = self._maths_level_map.get(level_id)
            mt = self._maths_topic_map.get(topic_id) if topic_id else None
            if not student or not ml:
                skipped += 1
                continue

            try:
                sid = str(uuid.UUID(str(session_id))) if session_id else str(uuid.uuid4())
            except (ValueError, AttributeError):
                sid = str(uuid.uuid4())

            obj, new = MSFA.objects.get_or_create(
                session_id=sid,
                defaults={
                    'student': student,
                    'topic': mt,
                    'level': ml,
                    'quiz_type': quiz_type or 'topic',
                    'attempt_number': int(attempt_number) if attempt_number else 1,
                    'score': int(score) if score is not None else 0,
                    'total_questions': int(total_q) if total_q is not None else 0,
                    'points': float(points) if points is not None else 0.0,
                    'time_taken_seconds': int(time_taken) if time_taken is not None else 0,
                    'operation': operation or '',
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
        progress_basicfactsresult actual backup column order (student_id FK at end):
          id(0), subtopic(1), level_number(2), session_id(3), score(4),
          total_questions(5), points(6), time_taken_seconds(7),
          questions_data(8), completed_at(9), student_id(10)

        Maps directly to maths.BasicFactsResult (subtopic+level_number already correct).
        Note: maths field is total_points, not total_questions.
        """
        from maths.models import BasicFactsResult as MBFR

        created = skipped = 0
        for row in rows:
            old_id       = row[0]
            subtopic     = row[1]
            level_number = row[2]
            session_id   = row[3] if len(row) > 3 else None
            score        = row[4] if len(row) > 4 else 0
            total_q      = row[5] if len(row) > 5 else 10
            points       = row[6] if len(row) > 6 else 0.0
            time_taken   = row[7] if len(row) > 7 else 0
            q_data       = row[8] if len(row) > 8 else None
            completed_at = row[9] if len(row) > 9 else None
            student_id   = row[10] if len(row) > 10 else None

            student = user_map.get(student_id)
            if not student or not subtopic or level_number is None:
                skipped += 1
                continue

            try:
                sid = str(uuid.UUID(str(session_id))) if session_id else str(uuid.uuid4())
            except (ValueError, AttributeError):
                sid = str(uuid.uuid4())

            import json as _json
            if isinstance(q_data, str):
                try:
                    q_data = _json.loads(q_data)
                except Exception:
                    q_data = []
            elif q_data is None:
                q_data = []

            obj, new = MBFR.objects.get_or_create(
                session_id=sid,
                defaults={
                    'student': student,
                    'subtopic': subtopic,
                    'level_number': int(level_number),
                    'score': int(score) if score is not None else 0,
                    'total_points': int(total_q) if total_q is not None else 10,
                    'points': float(points) if points is not None else 0.0,
                    'time_taken_seconds': int(time_taken) if time_taken is not None else 0,
                    'questions_data': q_data,
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
        progress_timelog actual backup column order (student_id FK at end):
          id(0), daily_seconds(1), weekly_seconds(2), last_daily_reset(3),
          last_weekly_reset(4), last_updated(5), student_id(6)

        Maps to maths.TimeLog (daily_total_seconds, weekly_total_seconds).
        last_reset_date / last_activity are auto_now — not set manually.
        """
        from maths.models import TimeLog as MTL

        created = skipped = 0
        for row in rows:
            old_id      = row[0]
            daily_secs  = row[1] if len(row) > 1 else 0
            weekly_secs = row[2] if len(row) > 2 else 0
            student_id  = row[6] if len(row) > 6 else None

            student = user_map.get(student_id)
            if not student:
                skipped += 1
                continue

            _, new = MTL.objects.get_or_create(
                student=student,
                defaults={
                    'daily_total_seconds': int(daily_secs) if daily_secs is not None else 0,
                    'weekly_total_seconds': int(weekly_secs) if weekly_secs is not None else 0,
                },
            )
            if new:
                created += 1
            else:
                skipped += 1

        self.stdout.write(f'  TimeLog: {created} created, {skipped} skipped')

    def _import_statistics(self, rows, level_map, topic_map):
        """
        progress_topiclevelstatistics actual backup column order (FKs at end):
          id(0), avg_points(1), sigma(2), student_count(3), updated_at(4),
          level_id(5), topic_id(6)

        Maps to maths.TopicLevelStatistics (average_points field name).
        topic_id/level_id are classroom IDs → bridge to maths via _maths_*_map.
        """
        from maths.models import TopicLevelStatistics as MTLS

        created = skipped = 0
        for row in rows:
            old_id        = row[0]
            avg_points    = row[1] if len(row) > 1 else 0.0
            sigma         = row[2] if len(row) > 2 else 0.0
            student_count = row[3] if len(row) > 3 else 0
            # row[4] = updated_at (skip)
            level_id      = row[5] if len(row) > 5 else None
            topic_id      = row[6] if len(row) > 6 else None

            ml = self._maths_level_map.get(level_id)
            mt = self._maths_topic_map.get(topic_id)
            if not ml or not mt:
                skipped += 1
                continue

            _, new = MTLS.objects.get_or_create(
                topic=mt,
                level=ml,
                defaults={
                    'average_points': float(avg_points) if avg_points is not None else 0.0,
                    'sigma': float(sigma) if sigma is not None else 0.0,
                    'student_count': int(student_count) if student_count is not None else 0,
                },
            )
            if new:
                created += 1
            else:
                skipped += 1

        self.stdout.write(f'  TopicLevelStatistics: {created} created, {skipped} skipped')

    def _import_student_answers(self, rows, user_map, q_map, a_map, level_map, topic_map):
        """
        progress_studentanswer actual backup column order (FKs at end):
          id(0), text_answer(1), ordered_answer_ids(2), is_correct(3),
          attempt_id(4), answered_at(5), level_id(6), question_id(7),
          selected_answer_id(8), student_id(9), topic_id(10)

        question_id / selected_answer_id → q_map / a_map (quiz_* → maths_*)
        topic_id / level_id → maths maps
        """
        from maths.models import StudentAnswer as MSA
        import json as _json

        created = skipped = 0
        for row in rows:
            old_id            = row[0]
            text_answer       = row[1] if len(row) > 1 else ''
            ordered_ans_ids   = row[2] if len(row) > 2 else None
            is_correct        = row[3] if len(row) > 3 else False
            attempt_id        = row[4] if len(row) > 4 else None
            answered_at       = row[5] if len(row) > 5 else None
            level_id          = row[6] if len(row) > 6 else None
            question_id       = row[7] if len(row) > 7 else None
            selected_ans_id   = row[8] if len(row) > 8 else None
            student_id        = row[9] if len(row) > 9 else None
            topic_id          = row[10] if len(row) > 10 else None

            student  = user_map.get(student_id)
            question = q_map.get(question_id)
            if not student or not question:
                skipped += 1
                continue

            ml = self._maths_level_map.get(level_id)
            mt = self._maths_topic_map.get(topic_id) if topic_id else None
            selected = a_map.get(selected_ans_id) if selected_ans_id else None

            try:
                attempt_uuid = uuid.UUID(str(attempt_id)) if attempt_id else uuid.uuid4()
            except (ValueError, AttributeError):
                attempt_uuid = uuid.uuid4()

            if isinstance(ordered_ans_ids, str):
                try:
                    ordered_ans_ids = _json.loads(ordered_ans_ids)
                except Exception:
                    ordered_ans_ids = None

            try:
                obj = MSA.objects.create(
                    student=student,
                    question=question,
                    topic=mt,
                    level=ml,
                    selected_answer=selected,
                    text_answer=text_answer or '',
                    ordered_answer_ids=ordered_ans_ids,
                    is_correct=bool(is_correct),
                    attempt_id=attempt_uuid,
                )
                ts = self._to_datetime(answered_at)
                if ts:
                    MSA.objects.filter(pk=obj.pk).update(answered_at=ts)
                created += 1
            except Exception:
                skipped += 1

        self.stdout.write(f'  StudentAnswer: {created} created, {skipped} skipped')

    def _assign_unlimited_promo(self, user_map):
        """Assign the UNLIMITED2026 promo code to all imported individual students."""
        from billing.models import PromoCode
        from accounts.models import Role

        try:
            promo = PromoCode.objects.get(code='UNLIMITED2026')
        except PromoCode.DoesNotExist:
            self.stdout.write(self.style.WARNING(
                '  Promo UNLIMITED2026 not found — skipping.'
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
        if not text:
            return text or ''
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
