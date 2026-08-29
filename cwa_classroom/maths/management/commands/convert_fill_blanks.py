"""
convert_fill_blanks
~~~~~~~~~~~~~~~~~~~
Turn existing typed questions whose text carries "___" gaps into real
fill-in-the-blank questions, so they render as a sentence with an input in each
gap instead of one box for the whole thing.

This is the BACKFILL. Questions arriving from now on are converted as they are
saved — the AI importer, the spreadsheet/ZIP upload and the teacher form all
route through ``Question.apply_blank_format``, the same entry point this command
uses. Run this once over what was already in the database; after that it should
find nothing.

The underscores ARE the identifier — a question written

    "Out of 100 000 births, 99 231 females are expected to survive to the age
     of ___. From that age, the survivors are expected to ___ for another 67.0
     years."

is a fill-in-the-blank question no matter what question_type it was saved under,
and nothing else in the database looks like that.

Scope:
  - question_type in short_answer / calculation / fill_blank (typed answers
    only; an MCQ with a gap in its stem is a choice question and is left alone)
  - question_text contains at least --min-blanks runs of two or more underscores
  - blank_spec not already set (re-running is a no-op unless --force)

What it writes: ``blank_spec`` (the accepted answers per gap, derived from the
question's existing correct Answer rows) and ``question_type='fill_blank'``.

What it does NOT write: the Answer rows. They are left exactly as they are —
BrainBuzz still snapshots them, exports still carry them, and keeping them is
what makes this reversible: clearing blank_spec returns a question to its
single-box form with its answer intact.

The one exception is --add-rule-blank, which appends a gap to question_text.
"Complete the pattern: 30, ___, 60, 75, ___, ___. What is the rule?" stores its
answer as the RULE ("+15"), so the gaps are filled from the sequence the
question prints and the rule takes a gap of its own — without one it would be
asked for in words and marked on nothing, which is worse than not converting at
all. --revert takes that gap back off with the spec.

Questions whose answers cannot be mapped onto their gaps unambiguously are
REPORTED, never guessed at. A gap filled from the wrong value marks a correct
student wrong and nobody would find out, so an unmappable question keeps working
exactly as it does today and is listed for a human to fix.

Start with the single-gap questions: there, every stored row becomes an accepted
spelling of the one gap, which cannot land on the wrong blank. Multi-gap
questions are only converted when their answers say unambiguously what goes in
each gap; the rest are reported for a content fix.

Usage (run from the app dir, e.g. /home/cwa/CWA_CLASS_APP_TEST):
    python manage.py convert_fill_blanks                    # dry run — report only
    python manage.py convert_fill_blanks --max-blanks 1     # the safe single-gap set
    python manage.py convert_fill_blanks --min-blanks 2     # only multi-gap ones
    python manage.py convert_fill_blanks --topic Statistics # one topic subtree
    python manage.py convert_fill_blanks --level 10
    python manage.py convert_fill_blanks --id 4021 --id 4022
    python manage.py convert_fill_blanks --add-bare-unit-answers  # "5300 mL" -> also "5300"
    python manage.py convert_fill_blanks --add-rule-blank    # pattern questions answered "+15"
    python manage.py convert_fill_blanks --apply            # actually write
    python manage.py convert_fill_blanks --revert --apply   # undo: clear the specs
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from classroom.models import Topic
from maths.blank_grading import (
    RULE_BLANK_SUFFIX, add_rule_blank, bare_unit_answers, count_blanks,
    describe_blank_spec, strip_rule_blank,
)
from maths.models import Answer, Question

# Only typed answers. An MCQ whose stem happens to contain a gap is still a
# question you pick an option for, and rendering an input into its stem would
# break it.
TYPED_TYPES = ['short_answer', 'calculation', 'fill_blank']


class _DryRun(Exception):
    """Unwinds the savepoint a dry-run repair was simulated inside."""


class Command(BaseCommand):
    help = (
        'Convert typed questions containing "___" gaps into fill-in-the-blank '
        'questions (writes blank_spec). Dry run unless --apply.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--min-blanks', type=int, default=1, metavar='N',
            help='Only convert questions with at least N gaps. Default 1. Use 2 '
                 'to target only the sentences a single box genuinely cannot ask.',
        )
        parser.add_argument(
            '--topic', default='', metavar='NAME',
            help='Limit to a topic (name contains, case-insensitive) and every '
                 'topic beneath it.',
        )
        parser.add_argument(
            '--level', type=int, default=None, metavar='N',
            help='Limit to one year level.',
        )
        parser.add_argument(
            '--id', type=int, action='append', default=[], metavar='PK',
            help='Limit to specific question ids — repeatable.',
        )
        parser.add_argument(
            '--max-blanks', type=int, default=None, metavar='N',
            help='Only convert questions with at most N gaps. Use 1 to take the '
                 'single-gap questions on their own — the mapping there is one '
                 'row per accepted spelling, which cannot land on the wrong gap.',
        )
        parser.add_argument(
            '--map-rows-to-gaps', action='store_true',
            help='Trust N answer rows on an N-gap question to be one value per '
                 'gap, in order. OFF by default: rows on legacy questions were '
                 'written to fill a single answer box, so three of them is no '
                 'evidence there is one per gap, and mapping them positionally '
                 'marks correct students wrong. Turn it on only for content you '
                 'know was authored gap by gap.',
        )
        parser.add_argument(
            '--add-bare-unit-answers', action='store_true',
            help='Repair the questions refused because every stored answer '
                 'repeats the unit printed after the gap ("= ___ mL" answered '
                 '"5300 mL"), by ALSO storing the bare value ("5300"), then '
                 'converting them. The existing row is kept, so a student who '
                 'writes the unit is still marked correct. Single-gap questions '
                 'only — which row feeds which gap is exactly what this command '
                 'refuses to guess at elsewhere.',
        )
        parser.add_argument(
            '--add-rule-blank', action='store_true',
            help='Repair the pattern questions refused because their stored '
                 'answer is the RULE ("+15") and the sentence has no gap for '
                 'it, by appending one on its own line ("The rule is: ___") '
                 'and '
                 'converting them. The gaps of the pattern itself are filled '
                 'from the sequence the question prints, not from the rows. '
                 'This EDITS question_text — the only thing here that does — '
                 'and --revert takes it back off again.',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Rebuild blank_spec on questions that already have one.',
        )
        parser.add_argument(
            '--revert', action='store_true',
            help='Undo: clear blank_spec on the matched questions, returning them '
                 'to the single-box form. Their answers are untouched, so this '
                 'loses nothing. Leaves question_type as fill_blank.',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Write the changes. Without this the command only reports (dry run).',
        )

    # ------------------------------------------------------------------
    def _with_descendants(self, seed_ids):
        """seed_ids plus every descendant topic id (breadth-first)."""
        ids, frontier = set(), list(seed_ids)
        while frontier:
            ids.update(frontier)
            frontier = list(
                Topic.objects.filter(parent_id__in=frontier)
                .exclude(id__in=ids)
                .values_list('id', flat=True)
            )
        return ids

    def _queryset(self, opts):
        qs = Question.objects.filter(question_type__in=TYPED_TYPES)

        if opts['id']:
            qs = qs.filter(pk__in=opts['id'])
        if opts['topic']:
            roots = Topic.objects.filter(
                name__icontains=opts['topic']).values_list('id', flat=True)
            topic_ids = self._with_descendants(list(roots))
            if not topic_ids:
                raise CommandError(f'No topic matches {opts["topic"]!r}.')
            qs = qs.filter(topic_id__in=topic_ids)
        if opts['level'] is not None:
            qs = qs.filter(level__level_number=opts['level'])

        if opts['revert']:
            return qs.filter(blank_spec__isnull=False).order_by('pk')

        # The database cannot count underscore runs, so narrow to text that has
        # any underscore at all and do the real count in Python.
        qs = qs.filter(question_text__contains='__')
        if not opts['force'] and not opts['add_rule_blank']:
            qs = qs.filter(blank_spec__isnull=True)
        # --add-rule-blank also has business with questions that ALREADY
        # converted: sixteen of them ask "State the rule and the three missing
        # numbers", and the row rules filled their number gaps and dropped the
        # rule, which no gap now holds. Those are reached only by including
        # them here — and the loop gives them the rule gap and nothing else.
        return qs.select_related('topic', 'level').prefetch_related('answers').order_by('pk')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        apply_changes = opts['apply']
        min_blanks = opts['min_blanks']
        if min_blanks < 1:
            raise CommandError('--min-blanks must be at least 1.')

        if opts['revert']:
            return self._revert(opts, apply_changes)

        max_blanks = opts['max_blanks']
        if max_blanks is not None and max_blanks < min_blanks:
            raise CommandError('--max-blanks must not be below --min-blanks.')

        def _in_range(q):
            gaps = count_blanks(q.question_text)
            return gaps >= min_blanks and (max_blanks is None or gaps <= max_blanks)

        candidates = [q for q in self._queryset(opts) if _in_range(q)]

        if not candidates:
            self.stdout.write(self.style.WARNING(
                'No questions matched. Nothing with "___" gaps in scope — '
                'widen the filters, or lower --min-blanks.'
            ))
            return

        converted, skipped, repaired, rule_blanks = [], [], [], []
        edited_text = set()

        def fields_for(question):
            fields = ['blank_spec', 'question_type']
            if question.pk in edited_text:
                fields.append('question_text')
            return fields

        for q in candidates:
            was = q.question_type

            if q.blank_spec is not None and not opts['force']:
                # Already converted, so the only thing wanted here is the rule
                # gap it never got. Adding one re-derives the whole spec from
                # the question and its answer rows — the same thing every save
                # through the teacher form and the importer does — so a gap
                # edited out of band comes back as the derivation reads it.
                # For these sixteen that is the values they already hold.
                text, changed, reason = self._add_rule_blank_and_retry(q, opts)
                if not text:
                    continue
                rule_blanks.append((q, text))
                edited_text.add(q.pk)
                if apply_changes:
                    q.save(update_fields=fields_for(q))
                converted.append((q, was))
                continue

            # The same entry point the AI importer, the spreadsheet upload and
            # the teacher form use, so a question converted in bulk comes out
            # identical to one that arrived already marked up.
            changed, reason = q.apply_blank_format(
                positional_rows=opts['map_rows_to_gaps'])
            if reason and opts['add_bare_unit_answers']:
                # The one refusal with a mechanical fix: store the bare value
                # beside the one that repeats the unit, then ask again. Every
                # other refusal is a judgement call about which value fills
                # which gap and stays a human's.
                added, retried, retry_reason = self._repair_and_retry(
                    q, opts, apply_changes)
                # Only when something was actually added. A question this
                # cannot repair keeps the reason it was refused for, rather
                # than being re-reported as "nothing to convert".
                if added:
                    repaired.append((q, added))
                    changed, reason = retried, retry_reason
            if reason and opts['add_rule_blank']:
                # The other refusal with a mechanical fix: the question prints
                # the pattern that fills its gaps, and its answer is the rule,
                # which has nowhere to be typed. Give the rule a gap and ask
                # again. Nothing is guessed at — the values come out of the
                # sequence, and the rows have to be that sequence's rule.
                text, retried, retry_reason = self._add_rule_blank_and_retry(
                    q, opts)
                if text:
                    rule_blanks.append((q, text))
                    edited_text.add(q.pk)
                    changed, reason = retried, retry_reason
            if reason or not changed:
                skipped.append((q, reason or 'nothing to convert'))
                continue
            if apply_changes:
                q.save(update_fields=fields_for(q))
            converted.append((q, was))

        self._report(converted, skipped, repaired, rule_blanks, apply_changes)

    # ------------------------------------------------------------------
    def _repair_and_retry(self, question, opts, apply_changes):
        """Add the bare-value answers, then ask ``apply_blank_format`` again.

        Returns ``(added, changed, reason)``.

        A dry run really writes the rows and then rolls them back, rather than
        attaching them in memory: ``rebuild_blank_spec`` re-reads the correct
        answers from the database, so a row that existed only on the instance
        would not be seen and the dry run would report the same refusal it is
        offering to fix. The spec built during the savepoint stays on the
        instance after the rollback, which is what the report prints — the same
        "changed in memory, saved only under --apply" the ordinary conversion
        path already uses.
        """
        added, changed, reason = [], False, ''
        try:
            with transaction.atomic():
                added = self._add_bare_units(question)
                if added:
                    changed, reason = question.apply_blank_format(
                        positional_rows=opts['map_rows_to_gaps'])
                if not apply_changes:
                    raise _DryRun
        except _DryRun:
            pass
        return added, changed, reason

    def _add_rule_blank_and_retry(self, question, opts):
        """Append a gap for the rule, then ask ``apply_blank_format`` again.

        Returns ``(text, changed, reason)`` — ``text`` is the new question text
        when one was written onto the instance, ``''`` when this question was
        not the shape the repair is for (and then the caller keeps the refusal
        it already had).

        The edit is made on the instance only; the caller saves it under
        ``--apply``, so a dry run reports exactly what a real run would write.
        Nothing is written to the database here at all — unlike the bare-unit
        repair, the derivation reads this text off the instance, not the rows
        off the database.
        """
        correct = [a.answer_text for a in question.answers.filter(is_correct=True)]
        text, _ = add_rule_blank(question.question_text, correct)
        if not text:
            return '', False, ''
        question.question_text = text
        changed, reason = question.apply_blank_format(
            positional_rows=opts['map_rows_to_gaps'])
        if reason or not changed:
            # It did not convert after all — put the sentence back rather than
            # leaving a gap nothing grades on a question that stays a box.
            question.question_text = text[:-len(RULE_BLANK_SUFFIX)]
            return '', changed, reason
        return text, changed, reason

    def _add_bare_units(self, question):
        """Store the bare value beside answers that repeat their gap's unit.

        Returns the texts written (``[]`` when there was nothing to add). Adds
        rows rather than editing them: "5300 mL" was a correct answer before
        the gap went inline and stays one.
        """
        correct = [a.answer_text for a in question.answers.filter(is_correct=True)]
        extra = bare_unit_answers(question.question_text, correct)
        if not extra:
            return []

        order = question.answers.aggregate(top=Max('order'))['top'] or 0
        Answer.objects.bulk_create([
            Answer(question=question, answer_text=text,
                   is_correct=True, order=order + offset)
            for offset, text in enumerate(extra, start=1)
        ])
        return extra

    # ------------------------------------------------------------------
    def _report(self, converted, skipped, repaired, rule_blanks, apply_changes):
        for q, was in converted:
            self.stdout.write(
                f'  Q{q.pk} [{was}] {count_blanks(q.question_text)} gap(s): '
                f'{describe_blank_spec(q.blank_spec)}'
            )
            self.stdout.write(self.style.HTTP_INFO(
                f'        {q.question_text[:110]}'))

        # Not a footnote: these are questions that LOOK like fill-in-the-blank
        # and are staying as they are. Naming each one and why is the whole
        # point — the alternative is a silent partial conversion nobody audits.
        if skipped:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'{len(skipped)} question(s) have gaps but were NOT converted — '
                f'each needs its answer fixed by hand first:'))
            for q, reason in skipped:
                self.stdout.write(self.style.WARNING(f'  Q{q.pk}: {reason}'))
                self.stdout.write(f'        {q.question_text[:110]}')

        if repaired:
            self.stdout.write('')
            wrote = 'Added' if apply_changes else 'Would add'
            self.stdout.write(self.style.SUCCESS(
                f'{wrote} a bare-value answer to {len(repaired)} question(s) '
                f'whose only stored answer repeated the unit after the gap '
                f'(the existing answer is kept):'))
            for q, added in repaired:
                self.stdout.write(f'  Q{q.pk}: + {", ".join(repr(t) for t in added)}')

        if rule_blanks:
            self.stdout.write('')
            wrote = 'Gave' if apply_changes else 'Would give'
            self.stdout.write(self.style.SUCCESS(
                f'{wrote} {len(rule_blanks)} pattern question(s) a gap for the '
                f'rule they ask for in words, so it is still marked (their '
                f'other gaps are filled from the sequence they print):'))
            for q, text in rule_blanks:
                self.stdout.write(f'  Q{q.pk}: {text[:110]}')

        self.stdout.write('')
        verb = 'Converted' if apply_changes else 'Would convert'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {len(converted)} question(s); {len(skipped)} skipped.'))
        if not apply_changes:
            self.stdout.write('Dry run — nothing was written. Re-run with --apply.')

    # ------------------------------------------------------------------
    def _revert(self, opts, apply_changes):
        rows = list(self._queryset(opts))
        if not rows:
            self.stdout.write(self.style.WARNING(
                'No converted questions in scope — nothing to revert.'))
            return
        for q in rows:
            self.stdout.write(f'  Q{q.pk}: clearing {describe_blank_spec(q.blank_spec)}')
            # A gap this command appended for a rule goes back off with the
            # spec: left behind, it would be an input on a question that has
            # returned to a single box, and nothing would grade it.
            restored = strip_rule_blank(q.question_text)
            fields = ['blank_spec']
            if restored is not None:
                self.stdout.write(f'        and the rule gap it added: {restored[:100]}')
                fields.append('question_text')
            if apply_changes:
                q.blank_spec = None
                if restored is not None:
                    q.question_text = restored
                q.save(update_fields=fields)
        verb = 'Reverted' if apply_changes else 'Would revert'
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'{verb} {len(rows)} question(s).'))
        if not apply_changes:
            self.stdout.write('Dry run — nothing was written. Re-run with --apply.')
