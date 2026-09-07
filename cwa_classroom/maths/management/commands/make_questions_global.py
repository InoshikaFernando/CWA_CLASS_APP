"""Move a school's maths questions into the global bank, in place.

The other route into the global bank — ``promote_school_questions`` — COPIES:
it leaves the school's row alone and creates a second, global row with the same
text. That is right when the source is a database dump, but on a live DB it
leaves two rows carrying one question, and the pools that union global with a
school's own rows (homework via ``visible_to_classroom``, level practice via
``_get_questions_for_level``) then offer both. Students see the question twice.

This command moves instead: one row stays one row, so nothing can duplicate.
The trade-off is deliberate — a moved question is global, and global questions
are edited by site admins only (``GlobalQuestionEditView`` requires
``Role.ADMIN``), so the school's teachers no longer edit it. Nothing else about
the row changes: its id, answers, images, and every StudentAnswer, homework
item and progress row pointing at it are untouched.

Safety
------
* A filter is required (``--year`` and/or ``--topic``), unless ``--all`` says
  otherwise — moving a whole school's bank in one unreviewed step should be a
  thing you asked for out loud.
* A question whose text already exists globally at that level is SKIPPED, so
  the move can't manufacture a duplicate inside the global bank itself.
* ``department`` and ``classroom`` are cleared on the rows that move. Every
  visibility query ORs ``school IS NULL`` first, so a global row that kept a
  department marker would be served to everyone while still claiming to belong
  to one department.
* Re-running is a no-op: the moved rows no longer match ``school=<school>``.
* The ids that moved are printed, so the move is reversible:
  ``Question.objects.filter(id__in=[...]).update(school_id=<id>)``.

Usage
-----
    python manage.py make_questions_global --school-slug maths-hub-melbourne-pty-ltd \
        --year 4 --topic "Number Patterns" --dry-run
    python manage.py make_questions_global --school 4 --year 4 --topic "Number Patterns"
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from maths.topic_lookup import matching_topics, topic_path


class Command(BaseCommand):
    help = ("Move a school's maths questions into the global bank in place "
            '(school -> NULL), without creating duplicate rows.')

    def add_arguments(self, parser):
        parser.add_argument('--school', type=int, help='School id to move questions from.')
        parser.add_argument('--school-slug', type=str, help='School slug, instead of --school.')
        parser.add_argument('--year', type=int,
                            help='Only this year level (Level.level_number).')
        parser.add_argument('--topic', type=str,
                            help='Only this topic — matched against the topic name, its '
                                 "parent strand's name, or its slug, so a strand pulls in "
                                 'its sub-topics.')
        parser.add_argument('--exact-topic', action='store_true',
                            help='Match --topic as a full name instead of a substring.')
        parser.add_argument('--all', action='store_true',
                            help="Move the school's ENTIRE maths bank. Required if you "
                                 'give no --year and no --topic.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would move, write nothing.')

    def handle(self, *args, **opts):
        from classroom.models import School
        from maths.models import Question

        if not opts['school'] and not opts['school_slug']:
            raise CommandError('Provide --school <id> or --school-slug <slug>.')
        try:
            school = (School.objects.get(pk=opts['school']) if opts['school']
                      else School.objects.get(slug=opts['school_slug']))
        except School.DoesNotExist:
            raise CommandError(
                f"School {opts['school'] or opts['school_slug']!r} not found.")

        year, term, dry_run = opts['year'], (opts['topic'] or '').strip(), opts['dry_run']
        if year is None and not term and not opts['all']:
            raise CommandError(
                'Refusing to move a whole school without being asked: pass --year '
                'and/or --topic to scope it, or --all if you really mean everything.')

        qs = (Question.objects.filter(school=school)
              .select_related('level', 'topic', 'topic__parent'))

        if term:
            topics = matching_topics(term, exact=opts['exact_topic'])
            if not topics:
                raise CommandError(f'No topic matches {term!r}.')
            self.stdout.write(f'Topic filter matches {len(topics)} topic row(s): '
                              + '; '.join(topic_path(t) for t in topics))
            qs = qs.filter(topic__in=topics)
        if year is not None:
            qs = qs.filter(level__level_number=year)

        scope = (f'{school.name} (id {school.id})'
                 + (f', year {year}' if year is not None else '')
                 + (f', topic {term!r}' if term else ''))
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'=== Move to global: {scope}{"  [DRY RUN]" if dry_run else ""} ==='))

        candidates = list(qs)
        if not candidates:
            raise CommandError('No school questions match these filters — nothing to move.')

        # A question whose text already sits in the global bank at the same
        # level would become a second global copy of itself. Skip those; the
        # global bank already has that content.
        global_texts = set(
            Question.objects.filter(
                school__isnull=True,
                level__in={q.level_id for q in candidates},
            ).values_list('level_id', 'question_text')
        )
        movable, duplicates = [], []
        for q in candidates:
            (duplicates if (q.level_id, q.question_text) in global_texts
             else movable).append(q)

        scoped = [q for q in movable if q.department_id or q.classroom_id]

        self.stdout.write(f'  matched          : {len(candidates)}')
        self.stdout.write(f'  already global   : {len(duplicates)}  (skipped)')
        for q in duplicates:
            self.stdout.write(f'      [{q.id}] {" ".join(q.question_text.split())[:64]}')
        if scoped:
            self.stdout.write(self.style.WARNING(
                f'  department/class-scoped: {len(scoped)} — those markers are cleared, '
                'since a global row is visible to everyone'))
        self.stdout.write(self.style.SUCCESS(f'  to move          : {len(movable)}'))

        if not movable:
            self.stdout.write(self.style.WARNING(
                'Nothing to move — every matching question is already in the global '
                'bank under the same text.'))
            return

        moved_ids = [q.id for q in movable]
        with transaction.atomic():
            Question.objects.filter(id__in=moved_ids).update(
                school=None, department=None, classroom=None)
            if dry_run:
                transaction.set_rollback(True)

        verb = 'Would move' if dry_run else 'Moved'
        self.stdout.write(self.style.SUCCESS(
            f'\n{verb} {len(moved_ids)} question(s) to the global bank'
            + ('  [DRY RUN — rolled back]' if dry_run else '')))
        self.stdout.write('  ids: ' + ', '.join(str(i) for i in moved_ids))
        if not dry_run:
            self.stdout.write(
                '  to undo: Question.objects.filter(id__in=[...]).update('
                f'school_id={school.id})')
