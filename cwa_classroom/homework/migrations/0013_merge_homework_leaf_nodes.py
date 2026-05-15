from django.db import migrations


class Migration(migrations.Migration):
    """Merge two leaf nodes in the homework migration graph:
    - 0012_ai_grading_cache_human_verified
    - 0012_merge_20260511_1752
    """

    dependencies = [
        ('homework', '0012_ai_grading_cache_human_verified'),
        ('homework', '0012_merge_20260511_1752'),
    ]

    operations = []
