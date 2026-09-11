"""The 0121 backfill: recover ids retired by merges that already ran.

``TopicAlias`` only helps future merges on its own. The merges already run —
32 of them in one ``merge_maths_topics`` pass, retiring 59 maths topic ids —
left links in bookmarks and browser history that have been 404ing ever since.
Their mapping survives in the ``topics_merged`` audit entries, so the
migration reads it back and seeds an alias per retired id.

The function is exercised directly rather than through the migration executor
because ``conftest.py`` builds the test database from the models
(``django_db_use_migrations``), so RunPython never runs here.
"""
from datetime import timedelta
from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase
from django.utils import timezone

from audit.models import AuditLog
from classroom.models import Subject, Topic, TopicAlias

backfill = import_module(
    'classroom.migrations.0121_topic_alias').backfill_from_audit


class BackfillFromAuditTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.maths = Subject.objects.create(name='Mathematics', slug='maths-bf')

    def _topic(self, name, slug):
        return Topic.objects.create(name=name, slug=slug, subject=self.maths)

    def _merge_entry(self, keep, absorbed, when=None):
        """An audit row shaped exactly as ``merge_topics`` writes it.

        ``AuditLog.created_at`` is ``auto_now_add``, which silently discards a
        value passed to ``create()`` — hence the follow-up ``update()``, which
        bypasses it. Getting that wrong makes every row look like "now" and
        the date assertion below vacuous.
        """
        entry = AuditLog.objects.create(
            user=None, category='data_change', action='topics_merged',
            detail={
                'keep_id': keep.id if hasattr(keep, 'id') else keep,
                'keep_name': getattr(keep, 'name', 'gone'),
                'absorbed': [{'id': i, 'name': n, 'slug': s}
                             for i, n, s in absorbed],
            },
        )
        if when is not None:
            AuditLog.objects.filter(pk=entry.pk).update(created_at=when)
            entry.refresh_from_db()
        return entry

    def _run(self):
        backfill(django_apps, None)

    def test_a_retired_id_resolves_to_its_survivor(self):
        """The production case: 198 'Rounding and Decimals' -> 160 'Decimals'."""
        keep = self._topic('Decimals', 'decimals-bf1')
        self._merge_entry(keep, [(9_000_198, 'Rounding and Decimals', 'rounding')])

        self._run()

        alias = TopicAlias.objects.get(old_topic_id=9_000_198)
        self.assertEqual(alias.topic_id, keep.id)
        self.assertEqual(alias.old_name, 'Rounding and Decimals')
        self.assertEqual(TopicAlias.resolve(9_000_198), keep)

    def test_it_dates_the_alias_from_the_merge_not_from_the_migration(self):
        keep = self._topic('Decimals', 'decimals-bf2')
        when = timezone.now() - timedelta(days=8)
        self._merge_entry(keep, [(9_000_199, 'Rounding', 'rounding2')], when=when)

        self._run()

        self.assertEqual(TopicAlias.objects.get(old_topic_id=9_000_199).merged_at,
                         when)

    def test_it_never_shadows_a_live_topic(self):
        """An id that resolves today is left alone, whatever the log claims."""
        keep = self._topic('Decimals', 'decimals-bf3')
        live = self._topic('Percentages', 'percentages-bf3')
        self._merge_entry(keep, [(live.id, 'Percentages', 'percentages-bf3')])

        self._run()

        self.assertFalse(TopicAlias.objects.filter(old_topic_id=live.id).exists())

    def test_it_follows_a_survivor_that_was_itself_absorbed(self):
        """A -> B, then B -> C. A must land on C, not on the deleted B."""
        final = self._topic('Decimals', 'decimals-bf4')
        earlier = timezone.now() - timedelta(days=2)
        later = timezone.now() - timedelta(days=1)
        self._merge_entry(9_000_300, [(9_000_301, 'Rounding', 'r-bf4')],
                          when=earlier)
        self._merge_entry(final, [(9_000_300, 'Rounding and Decimals', 'rd-bf4')],
                          when=later)

        self._run()

        self.assertEqual(TopicAlias.resolve(9_000_301), final)
        self.assertEqual(TopicAlias.resolve(9_000_300), final)

    def test_an_unmappable_id_is_skipped_not_written_broken(self):
        """A survivor that is gone with no onward hop keeps 404ing.

        Writing the alias anyway would point at a topic id that no longer
        exists, and the redirect would land the student on a second 404.
        """
        self._merge_entry(9_000_400, [(9_000_401, 'Orphaned', 'o-bf5')])

        self._run()

        self.assertFalse(TopicAlias.objects.filter(old_topic_id=9_000_401).exists())

    def test_a_cycle_in_the_history_does_not_hang(self):
        """Malformed history (A -> B and B -> A) must terminate, not spin."""
        self._merge_entry(9_000_500, [(9_000_501, 'One', 'one-bf6')])
        self._merge_entry(9_000_501, [(9_000_500, 'Two', 'two-bf6')])

        self._run()   # the assertion is that this returns at all

        self.assertEqual(
            TopicAlias.objects.filter(
                old_topic_id__in=[9_000_500, 9_000_501]).count(), 0)

    def test_it_is_idempotent(self):
        """Re-running must not raise on rows it already wrote."""
        keep = self._topic('Decimals', 'decimals-bf7')
        self._merge_entry(keep, [(9_000_600, 'Rounding', 'r-bf7')])

        self._run()
        self._run()

        self.assertEqual(
            TopicAlias.objects.filter(old_topic_id=9_000_600).count(), 1)

    def test_an_entry_with_no_keep_id_is_ignored(self):
        AuditLog.objects.create(
            user=None, category='data_change', action='topics_merged',
            detail={'absorbed': [{'id': 9_000_700, 'name': 'x', 'slug': 'x'}]})

        self._run()

        self.assertFalse(TopicAlias.objects.filter(old_topic_id=9_000_700).exists())
