from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0069_pending_password_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='term',
            name='is_confirmed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='term',
            name='confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='Holiday',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='holidays', to='classroom.school')),
                ('academic_year', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='holidays', to='classroom.academicyear')),
            ],
            options={
                'ordering': ['start_date'],
                'unique_together': {('school', 'name', 'start_date')},
            },
        ),
    ]
