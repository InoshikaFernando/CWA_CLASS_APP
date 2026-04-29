from django.db import migrations


def _delete_flipzo(apps, schema_editor):
    SubjectApp = apps.get_model('classroom', 'SubjectApp')
    SubjectApp.objects.filter(name__iexact='Flipzo').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0092_merge_20260420_1156'),
    ]

    operations = [
        migrations.RunPython(_delete_flipzo, migrations.RunPython.noop),
    ]
