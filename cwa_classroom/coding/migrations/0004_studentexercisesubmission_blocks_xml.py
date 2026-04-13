from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coding', '0003_seed_coding_languages'),
    ]

    operations = [
        migrations.AddField(
            model_name='studentexercisesubmission',
            name='blocks_xml',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Blockly workspace XML for Scratch block exercises (empty for text-based languages)',
            ),
            preserve_default=False,
        ),
    ]
