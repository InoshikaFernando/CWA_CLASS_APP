"""
Migration 0015: State-only cleanup — remove three orphaned index entries.

Root cause
----------
Migration 0001 registered three indexes in the migration state:

  maths_stude_student_ad30a8_idx  — StudentFinalAnswer (student, topic, level)
  maths_stude_student_2e8b01_idx  — StudentFinalAnswer (student, topic, level, attempt_number)
  maths_topic_level_i_267d9e_idx  — TopicLevelStatistics (level, topic)

Migration 0010 removed the old maths.topic / maths.level FK columns via
RemoveField state operations.  Django's RemoveField.state_forwards() does NOT
automatically remove Meta.indexes entries that reference the dropped fields —
it only removes the field itself.  Those three auto-named entries were therefore
left behind in the migration state.

After migration 0013 added short-named replacements the state contained BOTH
the old orphaned entries and the new correct ones, producing the
"Your models in app(s): 'maths' have changes" warning.

Migration 0014 was a DB-only RunPython (no state changes), so the orphaned
entries are still present in the state after it runs.

Fix — idempotent custom operation
----------------------------------
The helper ``RemoveIndexIfPresent`` filters the index list in the migration
state without raising an error when the named index is already absent.  This
makes the migration safe to apply regardless of whether an earlier (now-
replaced) version of migration 0014 already removed the entries on a given
database.

Database side: no operations — the corresponding DB indexes were dropped
automatically by MySQL when migration 0010 removed the underlying FK columns.
"""
from django.db import migrations


# ---------------------------------------------------------------------------
# Custom idempotent state-only operation
# ---------------------------------------------------------------------------

class RemoveIndexIfPresent(migrations.operations.base.Operation):
    """
    Remove a named index from the migration state without touching the DB.
    Unlike migrations.RemoveIndex, this is a no-op when the index is already
    absent from the state — making it safe for re-entrant/idempotent use.
    """

    reduces_to_sql = False
    reversible = True

    def __init__(self, model_name, name):
        self.model_name = model_name.lower()
        self.name = name

    # ── State mutations ───────────────────────────────────────────────────

    def state_forwards(self, app_label, state):
        model_state = state.models[app_label, self.model_name]
        indexes = model_state.options.get('indexes', [])
        model_state.options['indexes'] = [
            idx for idx in indexes if idx.name != self.name
        ]

    def state_backwards(self, app_label, state):
        # Reverse is deliberately a no-op: we cannot reconstruct the exact
        # index object that was removed (and it referenced fields that are
        # already gone from the state anyway).
        pass

    # ── DB mutations (none) ───────────────────────────────────────────────

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        pass  # DB index already gone — no DDL needed

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        pass

    # ── Introspection ─────────────────────────────────────────────────────

    def describe(self):
        return (
            f"Remove index {self.name!r} from {self.model_name} "
            f"(state-only, no-op if already absent)"
        )

    @property
    def migration_name_fragment(self):
        return f"remove_index_{self.name}"


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class Migration(migrations.Migration):

    dependencies = [
        ("maths", "0014_remove_auto_named_indexes"),
    ]

    operations = [
        # State-only, idempotent: removes each orphaned index name from the
        # migration graph if still present.  Safe whether or not a previous
        # version of migration 0014 already performed the same cleanup.
        # No DB operations — MySQL dropped these indexes automatically when
        # migration 0010 removed the underlying FK columns.
        RemoveIndexIfPresent(
            model_name="studentfinalanswer",
            name="maths_stude_student_ad30a8_idx",
        ),
        RemoveIndexIfPresent(
            model_name="studentfinalanswer",
            name="maths_stude_student_2e8b01_idx",
        ),
        RemoveIndexIfPresent(
            model_name="topiclevelstatistics",
            name="maths_topic_level_i_267d9e_idx",
        ),
    ]
