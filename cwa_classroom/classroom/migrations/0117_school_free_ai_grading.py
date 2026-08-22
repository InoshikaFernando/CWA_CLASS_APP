# The grading service reads school.free_ai_grading to waive the AI grading
# module and its monthly cap. The field was never added, so getattr(...,
# False) made it permanently False and the escape hatch silently did nothing.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0116_emailqueue_attribution_and_retry_cap'),
    ]

    operations = [
        migrations.AddField(
            model_name='school',
            name='free_ai_grading',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Give this school AI grading without the paid module and '
                    'without a monthly cap — for schools the owner has granted '
                    'free access. The grading service has always looked for '
                    'this flag; until now it was read off a field that did not '
                    'exist, so it was silently always False and the escape '
                    'hatch never worked.'
                ),
            ),
        ),
    ]
