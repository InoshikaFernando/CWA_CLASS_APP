from django.db import migrations


class Migration(migrations.Migration):
    """Merge two leaf nodes:
    - 0030_merge_20260510_2233 (merged ai_grading + perf_indexes)
    - 0031_seed_pages_per_month (seeds pages_per_month on ModuleProduct)
    """

    dependencies = [
        ('billing', '0030_merge_20260510_2233'),
        ('billing', '0031_seed_pages_per_month'),
    ]

    operations = []
