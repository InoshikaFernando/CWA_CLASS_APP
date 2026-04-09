from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0085_merge_20260406_0843'),
    ]

    operations = [
        # Step 1: Drop the old unique_together constraint
        migrations.AlterUniqueTogether(
            name='parentstudent',
            unique_together=set(),
        ),
        # Step 2: Make school nullable (SET_NULL so deleting a school doesn't wipe the link)
        migrations.AlterField(
            model_name='parentstudent',
            name='school',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='parent_student_links',
                to='classroom.school',
            ),
        ),
        # Step 3: Add two partial unique constraints in place of the old unique_together
        # - For school-based links: unique (parent, student, school)
        # - For schoolless (individual) links: unique (parent, student) where school IS NULL
        migrations.AddConstraint(
            model_name='parentstudent',
            constraint=models.UniqueConstraint(
                condition=models.Q(school__isnull=False),
                fields=['parent', 'student', 'school'],
                name='unique_parent_student_school',
            ),
        ),
        migrations.AddConstraint(
            model_name='parentstudent',
            constraint=models.UniqueConstraint(
                condition=models.Q(school__isnull=True),
                fields=['parent', 'student'],
                name='unique_parent_student_no_school',
            ),
        ),
    ]
