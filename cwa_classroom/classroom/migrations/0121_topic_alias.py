"""Record where every merged-away topic went, and recover the ones already gone.

``topic_merge.merge_topics`` deletes each absorbed topic once its rows are
re-pointed at the survivor. Links already out in the world — a bookmark, an
open tab, a history entry — are the one thing it cannot re-point, so each of
them has been 404ing ever since. ``TopicAlias`` fixes that going forward.

The backfill fixes it backwards. The merge writes its map to the audit log
(``topics_merged``, holding ``keep_id`` and the absorbed rows), so the ids
retired by merges that ALREADY ran can be recovered from there and start
resolving the moment this migration lands, rather than only helping whoever
merges next.

Two things it refuses to do:

* shadow a live topic — an id that resolves today is left alone, whatever the
  audit log says about it;
* point at a topic that is itself gone — a survivor absorbed by a later merge
  is followed to ITS survivor, and an id whose chain dead-ends is skipped
  rather than written as a broken redirect.

The audit log is not guaranteed complete (``merge_topics`` swallows audit
failures on purpose), so this recovers what it can and says how much. An id it
cannot map keeps 404ing, which is the honest answer for one we cannot place.
"""
import logging

from django.db import migrations, models
import django.db.models.deletion

logger = logging.getLogger(__name__)


def backfill_from_audit(apps, schema_editor):
    """Seed an alias for every id retired by a merge that already ran."""
    AuditLog = apps.get_model("audit", "AuditLog")
    Topic = apps.get_model("classroom", "Topic")
    TopicAlias = apps.get_model("classroom", "TopicAlias")

    live = set(Topic.objects.values_list("id", flat=True))

    # Oldest merge first, so a survivor that was itself absorbed later is
    # overwritten by the later hop rather than the other way round.
    retired = {}
    for entry in AuditLog.objects.filter(
            action="topics_merged").order_by("created_at", "pk").iterator():
        detail = entry.detail or {}
        keep_id = detail.get("keep_id")
        if not keep_id:
            continue
        for row in detail.get("absorbed") or []:
            old_id = row.get("id")
            if not old_id or old_id in live:
                continue   # never shadow an id that resolves today
            retired[old_id] = (keep_id, row.get("name") or "",
                               row.get("slug") or "", entry.created_at)

    aliases, unresolved = [], 0
    for old_id, (keep_id, name, slug, when) in retired.items():
        # Follow A->B->C when B was absorbed by a later merge. ``seen``
        # stops a cycle in malformed history from spinning forever.
        target, seen = keep_id, {old_id}
        while target not in live and target in retired and target not in seen:
            seen.add(target)
            target = retired[target][0]
        if target not in live:
            unresolved += 1
            continue
        aliases.append(TopicAlias(
            old_topic_id=old_id, topic_id=target,
            old_name=name[:100], old_slug=slug[:100], merged_at=when,
        ))

    TopicAlias.objects.bulk_create(aliases, ignore_conflicts=True)
    logger.info(
        "topic_alias backfill: %d retired id(s) now resolve, %d could not be "
        "mapped to a surviving topic and will keep 404ing.",
        len(aliases), unresolved,
    )


def drop_backfill(apps, schema_editor):
    """No-op: reversing the CreateModel drops the table and every row in it."""
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("classroom", "0120_repair_classroom_subject"),
        ("audit", "0003_add_revertible_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="TopicAlias",
            fields=[
                (
                    "old_topic_id",
                    models.PositiveIntegerField(
                        help_text="The id the absorbed topic had before the merge deleted it.",
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("old_name", models.CharField(blank=True, max_length=100)),
                ("old_slug", models.SlugField(blank=True, max_length=100)),
                ("merged_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "topic",
                    models.ForeignKey(
                        help_text="The surviving topic this id now resolves to.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="aliases",
                        to="classroom.topic",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "topic aliases",
                "ordering": ["-merged_at", "-old_topic_id"],
            },
        ),
        migrations.RunPython(backfill_from_audit, drop_backfill),
    ]
