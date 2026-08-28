# Rejoins the two leaf nodes classroom acquired when CPP-348 (the Messaging
# Centre) merged into `test`. Its 0107_scheduledmessageattachment /
# 0108_merge_20260626_1129 lineage was branched off 0106 in June and nothing was
# ever chained onto it, while the other lineage ran on to 0117 — so `migrate`
# refused to pick a leaf and the test-site deploy stopped dead.
#
# No operations: both lineages touch different models, so this is a graph join
# and not a schema change.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("classroom", "0108_merge_20260626_1129"),
        ("classroom", "0117_school_free_ai_grading"),
    ]

    operations = []
