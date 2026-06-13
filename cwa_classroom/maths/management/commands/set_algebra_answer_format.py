"""
set_algebra_answer_format
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Flag typed maths questions in the Algebra topic subtree as algebra-graded
(answer_format='algebra'), so they get the simplified-polynomial grader and the
x² input button without flagging each one by hand.

Scope (deliberately narrow — see WARNING below):
  - topic name matches the search term (default "Algebra", case-insensitive),
    PLUS every descendant topic (subtopics, recursively)
  - question_type in short_answer / calculation / fill_blank (typed answers only;
    MCQ / true_false ignore answer_format)

WARNING — algebra grading is for EXPAND-AND-SIMPLIFY answers (polynomials). It
will mis-grade two common algebra styles, so review the dry-run list first:
  - factorise (answer like "(x-3)(x+3)") — the grader rejects brackets → wrong
  - solve     (answer like "x = 3")      — the "=" is not parseable → wrong
Use --exclude-topic to skip such sub-topics.

Usage (run from the app dir, e.g. /home/cwa/CWA_CLASS_APP_TEST):
    python manage.py set_algebra_answer_format                 # dry run, term="Algebra"
    python manage.py set_algebra_answer_format --term "Algebra 2"
    python manage.py set_algebra_answer_format --exclude-topic Factorising --exclude-topic Solving
    python manage.py set_algebra_answer_format --apply         # actually write
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from classroom.models import Topic
from maths.models import Question

TYPED_TYPES = ['short_answer', 'calculation', 'fill_blank']


class Command(BaseCommand):
    help = "Set answer_format='algebra' on typed questions in the Algebra topic subtree."

    def add_arguments(self, parser):
        parser.add_argument(
            '--term', default='Algebra',
            help='Root topic name to match (case-insensitive contains). Default: "Algebra".',
        )
        parser.add_argument(
            '--exclude-topic', action='append', default=[], metavar='NAME',
            help='Topic name (contains, case-insensitive) to skip — repeatable. '
                 'Use for factorise / solve sub-topics.',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Write the changes. Without this the command only reports (dry run).',
        )

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

    def _subtree_topic_ids(self, term, excludes):
        """Topic ids in the subtree(s) rooted at topics whose name contains
        `term`, minus the subtree(s) of any topic whose name contains one of the
        `excludes` terms (excluding a topic prunes its descendants too)."""
        roots = Topic.objects.filter(name__icontains=term).values_list('id', flat=True)
        ids = self._with_descendants(list(roots))
        if excludes:
            ex = Q()
            for term_ in excludes:
                ex |= Q(name__icontains=term_)
            ex_roots = Topic.objects.filter(id__in=ids).filter(ex).values_list('id', flat=True)
            ids -= self._with_descendants(list(ex_roots))
        return ids

    def handle(self, *args, **opts):
        term = opts['term']
        excludes = opts['exclude_topic']
        apply = opts['apply']

        topic_ids = self._subtree_topic_ids(term, excludes)
        if not topic_ids:
            self.stderr.write(self.style.WARNING(f'No topics match {term!r}.'))
            return

        qs = (
            Question.objects
            .filter(topic_id__in=topic_ids, question_type__in=TYPED_TYPES)
            .exclude(answer_format='algebra')
        )
        total = qs.count()

        self.stdout.write(
            f'Topics in subtree: {len(topic_ids)} '
            f'(term={term!r}, excludes={excludes or "none"})'
        )
        self.stdout.write(f'Typed questions to flag as algebra: {total}')

        # Show a small sample so the operator can eyeball for factorise/solve answers.
        for q in qs.select_related('topic')[:8]:
            self.stdout.write(f'  • [{q.topic.name}] {q.question_text[:70]}')

        if not apply:
            self.stdout.write(self.style.NOTICE(
                'Dry run — re-run with --apply to write these changes.'
            ))
            return

        updated = qs.update(answer_format=Question.ANSWER_FORMAT_ALGEBRA)
        self.stdout.write(self.style.SUCCESS(
            f"Updated {updated} question(s) to answer_format='algebra'."
        ))
