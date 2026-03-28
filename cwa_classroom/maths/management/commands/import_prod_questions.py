"""
Management command: python manage.py import_prod_questions <path/to/prod_dump.sql>

Imports maths Question + Answer records from a production MySQL dump into the
current (post-migration-0010) test database.

The dump still uses old maths.Topic / maths.Level FKs. This command:
  1. Parses maths_topic, maths_level, maths_question, maths_answer tables from
     the dump.
  2. Builds a topic map:  old maths_topic.id → classroom_topic.id  (name match)
  3. Builds a level map:  old maths_level.id → classroom_level.id  (level_number)
  4. Creates Question + Answer objects, skipping questions that already exist
     (idempotent — safe to run multiple times).

Usage
-----
    python manage.py import_prod_questions /path/to/prod_dump.sql
    python manage.py import_prod_questions /path/to/prod_dump.sql --dry-run
    python manage.py import_prod_questions /path/to/prod_dump.sql --overwrite
"""

import re
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Import maths questions + answers from a production MySQL dump.'

    def add_arguments(self, parser):
        parser.add_argument('sql_file', type=str,
                            help='Path to prod MySQL dump .sql file')
        parser.add_argument('--dry-run', action='store_true',
                            help='Parse and count rows without writing to DB')
        parser.add_argument('--overwrite', action='store_true',
                            help='Update existing questions (default: skip duplicates)')

    def handle(self, *args, **options):
        sql_file = options['sql_file']
        dry_run = options['dry_run']
        overwrite = options['overwrite']

        self.stdout.write(f'Reading {sql_file} …')
        try:
            with open(sql_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except FileNotFoundError:
            raise CommandError(f'File not found: {sql_file}')

        self.stdout.write('Parsing SQL …')

        topics_rows  = self._parse_table(content, 'maths_topic')
        levels_rows  = self._parse_table(content, 'maths_level')
        q_rows       = self._parse_table(content, 'maths_question')
        ans_rows     = self._parse_table(content, 'maths_answer')

        self.stdout.write(
            f'  maths_topic:    {len(topics_rows)} rows\n'
            f'  maths_level:    {len(levels_rows)} rows\n'
            f'  maths_question: {len(q_rows)} rows\n'
            f'  maths_answer:   {len(ans_rows)} rows'
        )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('Dry run — no DB writes.'))
            return

        # ── Build maps ────────────────────────────────────────────────────────
        topic_map = self._build_topic_map(topics_rows)
        level_map = self._build_level_map(levels_rows)

        unmapped_topics = set()
        unmapped_levels = set()

        # ── Import ────────────────────────────────────────────────────────────
        with transaction.atomic():
            created_q = skipped_q = updated_q = 0
            old_id_to_new_id = {}   # old maths_question.id → new Question.id

            for row in q_rows:
                # maths_question columns:
                # id(0) question_text(1) question_type(2) difficulty(3) points(4)
                # explanation(5) image(6) created_at(7) updated_at(8)
                # level_id(9) topic_id(10) school_id(11)
                if len(row) < 11:
                    skipped_q += 1
                    continue

                old_id       = row[0]
                question_text = row[1] or ''
                question_type = row[2] or 'multiple_choice'
                difficulty   = int(row[3]) if row[3] is not None else 1
                points       = int(row[4]) if row[4] is not None else 1
                explanation  = row[5] or ''
                old_level_id = row[9]
                old_topic_id = row[10]

                level_obj = level_map.get(old_level_id)
                topic_obj = topic_map.get(old_topic_id) if old_topic_id else None

                if level_obj is None:
                    unmapped_levels.add(old_level_id)
                    skipped_q += 1
                    continue

                if old_topic_id and topic_obj is None:
                    unmapped_topics.add(old_topic_id)
                    # still create question — just without topic

                new_q, new_q_id = self._upsert_question(
                    old_id=old_id,
                    question_text=question_text,
                    question_type=question_type,
                    difficulty=difficulty,
                    points=points,
                    explanation=explanation,
                    level=level_obj,
                    topic=topic_obj,
                    overwrite=overwrite,
                )
                if new_q == 'created':
                    created_q += 1
                elif new_q == 'updated':
                    updated_q += 1
                else:
                    skipped_q += 1
                old_id_to_new_id[old_id] = new_q_id

            # ── Answers ───────────────────────────────────────────────────────
            created_a = skipped_a = 0
            for row in ans_rows:
                # maths_answer columns:
                # id(0) answer_text(1) is_correct(2) order(3) question_id(4)
                if len(row) < 5:
                    skipped_a += 1
                    continue

                answer_text  = row[1] or ''
                is_correct   = bool(row[2])
                order        = int(row[3]) if row[3] is not None else 0
                old_q_id     = row[4]

                new_q_id = old_id_to_new_id.get(old_q_id)
                if new_q_id is None:
                    skipped_a += 1
                    continue

                result = self._upsert_answer(
                    question_id=new_q_id,
                    answer_text=answer_text,
                    is_correct=is_correct,
                    order=order,
                    overwrite=overwrite,
                )
                if result:
                    created_a += 1
                else:
                    skipped_a += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone!\n'
                f'  Questions: {created_q} created, {updated_q} updated, '
                f'{skipped_q} skipped\n'
                f'  Answers:   {created_a} created, {skipped_a} skipped'
            )
        )
        if unmapped_topics:
            self.stdout.write(
                self.style.WARNING(
                    f'  Unmapped maths_topic IDs (no classroom.Topic match): '
                    f'{sorted(unmapped_topics)}'
                )
            )
        if unmapped_levels:
            self.stdout.write(
                self.style.WARNING(
                    f'  Unmapped maths_level IDs (no classroom.Level match): '
                    f'{sorted(unmapped_levels)}'
                )
            )

    # ── SQL parser ────────────────────────────────────────────────────────────

    def _parse_table(self, content, table_name):
        """Extract all rows from INSERT INTO `table_name` VALUES (...)."""
        # Find the INSERT statement for this table
        pattern = (
            r"INSERT INTO `" + re.escape(table_name) + r"` VALUES\s+"
            r"(.*?);"
        )
        match = re.search(pattern, content, re.DOTALL)
        if not match:
            return []
        return self._extract_rows(match.group(1))

    def _extract_rows(self, values_str):
        rows = []
        i, n = 0, len(values_str)
        while i < n:
            # Skip whitespace and commas between rows
            while i < n and values_str[i] in ' \t\n\r,':
                i += 1
            if i >= n:
                break
            if values_str[i] != '(':
                i += 1
                continue
            i += 1  # skip '('
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

    def _build_topic_map(self, topic_rows):
        """
        Returns dict: old_maths_topic_id → classroom.Topic instance

        maths_topic columns: id(0), name(1)
        Matches by name (case-insensitive) within the Mathematics subject.
        """
        from classroom.models import Topic as ClassroomTopic, Subject

        try:
            math_subject = Subject.objects.get(slug='mathematics', school=None)
        except Subject.DoesNotExist:
            self.stdout.write(self.style.WARNING(
                'classroom.Subject slug=mathematics not found — topic map empty'))
            return {}

        topic_map = {}
        for row in topic_rows:
            if len(row) < 2:
                continue
            old_id = row[0]
            name   = row[1]
            ct = ClassroomTopic.objects.filter(
                subject=math_subject,
                name__iexact=name,
            ).first()
            if ct:
                topic_map[old_id] = ct
            else:
                self.stdout.write(
                    self.style.WARNING(f'  No classroom.Topic for "{name}" (old id {old_id})')
                )

        self.stdout.write(f'  Topic map: {len(topic_map)} / {len(topic_rows)} entries resolved')
        return topic_map

    def _build_level_map(self, level_rows):
        """
        Returns dict: old_maths_level_id → classroom.Level instance

        maths_level columns: id(0), level_number(1), title(2)
        Matches by level_number; creates missing levels.
        """
        from classroom.models import Level as ClassroomLevel

        level_map = {}
        for row in level_rows:
            if len(row) < 2:
                continue
            old_id      = row[0]
            level_num   = row[1]
            title       = row[2] if len(row) > 2 else ''
            cl, created = ClassroomLevel.objects.get_or_create(
                level_number=level_num,
                defaults={'display_name': title or f'Year {level_num}'},
            )
            level_map[old_id] = cl
            if created:
                self.stdout.write(f'  Created classroom.Level level_number={level_num}')

        self.stdout.write(f'  Level map: {len(level_map)} entries')
        return level_map

    # ── Upsert helpers ────────────────────────────────────────────────────────

    def _upsert_question(self, old_id, question_text, question_type,
                         difficulty, points, explanation, level, topic, overwrite):
        from maths.models import Question

        # Use original question_text as the unique identifier
        existing = Question.objects.filter(
            question_text=question_text,
            level=level,
        ).first()

        if existing:
            if overwrite:
                existing.question_type = question_type
                existing.difficulty    = difficulty
                existing.points        = points
                existing.explanation   = explanation
                existing.topic         = topic
                existing.save(update_fields=[
                    'question_type', 'difficulty', 'points',
                    'explanation', 'topic',
                ])
                return 'updated', existing.id
            return 'skipped', existing.id

        q = Question.objects.create(
            question_text=question_text,
            question_type=question_type,
            difficulty=difficulty,
            points=points,
            explanation=explanation,
            level=level,
            topic=topic,
        )
        return 'created', q.id

    def _upsert_answer(self, question_id, answer_text, is_correct, order, overwrite):
        from maths.models import Answer, Question

        try:
            question = Question.objects.get(id=question_id)
        except Question.DoesNotExist:
            return False

        existing = Answer.objects.filter(
            question=question,
            answer_text=answer_text,
        ).first()

        if existing:
            if overwrite:
                existing.is_correct = is_correct
                existing.order = order
                existing.save(update_fields=['is_correct', 'order'])
            return False  # no new record

        Answer.objects.create(
            question=question,
            answer_text=answer_text,
            is_correct=is_correct,
            order=order,
        )
        return True
