from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0048_emailcampaign_emailpreference_emaillog'),
    ]

    operations = [
        # Add school FK to Subject (null = global, set = school-created)
        migrations.AddField(
            model_name='subject',
            name='school',
            field=models.ForeignKey(
                blank=True,
                help_text='Null = global subject with question banks. Set = school-created custom subject.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='school_subjects',
                to='classroom.school',
            ),
        ),
        # Add global_subject self-FK for future mapping
        migrations.AddField(
            model_name='subject',
            name='global_subject',
            field=models.ForeignKey(
                blank=True,
                help_text='Future: link to global subject when it becomes available for level mapping.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='school_variants',
                to='classroom.subject',
            ),
        ),
        # Remove old unique constraints on name and slug
        migrations.AlterField(
            model_name='subject',
            name='name',
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name='subject',
            name='slug',
            field=models.SlugField(max_length=100),
        ),
        # Add new unique_together (school, slug)
        migrations.AlterUniqueTogether(
            name='subject',
            unique_together={('school', 'slug')},
        ),
    ]
