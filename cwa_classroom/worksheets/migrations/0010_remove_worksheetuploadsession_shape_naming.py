"""Drop the name-the-shape mode flag.

The upload form's "Name-the-shape mode" checkbox is gone: a sheet of shapes is
now detected per item by the classifier (``name_the_shape`` in
``worksheets/services.py``), mixed with the page's ordinary questions, so the
whole-upload switch has nothing left to switch. Forward: drop the column.
Reverse: restore it with its old default so a rollback keeps working.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('worksheets', '0009_worksheetsubmission_art_picture_key'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='worksheetuploadsession',
            name='shape_naming',
        ),
    ]
