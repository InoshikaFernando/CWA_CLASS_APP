from django.db import migrations


class Migration(migrations.Migration):
    """Merge two leaf nodes in the billing migration graph:
    - 0031_merge_20260511_1752
    - 0032_merge_billing_leaf_nodes
    """

    dependencies = [
        ('billing', '0031_merge_20260511_1752'),
        ('billing', '0032_merge_billing_leaf_nodes'),
    ]

    operations = []
