from django.db import migrations, models


def blank_emails_to_null(apps, schema_editor):
    """Convert empty-string emails to NULL so the unique constraint doesn't
    treat all no-email users as duplicates."""
    CustomUser = apps.get_model('accounts', 'CustomUser')
    updated = CustomUser.objects.filter(email='').update(email=None)
    if updated:
        print(f'  Converted {updated} blank email(s) to NULL')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_alter_customuser_block_type'),
    ]

    operations = [
        # 1. Allow NULL first so we can store NULL before adding unique index
        migrations.AlterField(
            model_name='customuser',
            name='email',
            field=models.EmailField(blank=True, null=True, default=None, max_length=254),
        ),
        # 2. Convert '' → NULL
        migrations.RunPython(blank_emails_to_null, migrations.RunPython.noop),
        # 3. Now add unique=True (no more duplicate '' entries)
        migrations.AlterField(
            model_name='customuser',
            name='email',
            field=models.EmailField(blank=True, null=True, default=None, max_length=254, unique=True),
        ),
    ]
