"""
Migration: introduce TopicLevel and restructure CodingExercise

Steps
-----
1. Create the TopicLevel table.
2. Add a nullable topic_level FK to CodingExercise.
3. Data-migrate: for every unique (topic_id, level) pair in CodingExercise
   create a TopicLevel row, then set exercise.topic_level accordingly.
4. Make topic_level non-nullable.
5. Drop the legacy topic (FK) and level (CharField) columns.
"""
from django.db import migrations, models
import django.db.models.deletion


def populate_topic_levels(apps, schema_editor):
    CodingExercise = apps.get_model('coding', 'CodingExercise')
    TopicLevel     = apps.get_model('coding', 'TopicLevel')

    seen = {}
    for ex in CodingExercise.objects.select_related('topic').order_by('id'):
        key = (ex.topic_id, ex.level)
        if key not in seen:
            tl, _ = TopicLevel.objects.get_or_create(
                topic_id=ex.topic_id,
                level_choice=ex.level,
            )
            seen[key] = tl
        ex.topic_level = seen[key]
        ex.save(update_fields=['topic_level'])


def reverse_populate(apps, schema_editor):
    CodingExercise = apps.get_model('coding', 'CodingExercise')
    for ex in CodingExercise.objects.select_related('topic_level').order_by('id'):
        if ex.topic_level_id:
            ex.topic_id = ex.topic_level.topic_id
            ex.level    = ex.topic_level.level_choice
            ex.save(update_fields=['topic_id', 'level'])


class Migration(migrations.Migration):

    dependencies = [
        ('coding', '0009_fix_last_reset_week_year_encoded'),
    ]

    operations = [
        # ── 1. Create TopicLevel ──────────────────────────────────────
        migrations.CreateModel(
            name='TopicLevel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('topic', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='topic_levels',
                    to='coding.codingtopic',
                )),
                ('level_choice', models.CharField(
                    choices=[
                        ('beginner',     'Beginner'),
                        ('intermediate', 'Intermediate'),
                        ('advanced',     'Advanced'),
                    ],
                    max_length=20,
                )),
                ('is_active', models.BooleanField(default=True)),
                ('order',     models.PositiveSmallIntegerField(default=0)),
            ],
            options={
                'ordering': ['topic', 'level_choice'],
                'unique_together': {('topic', 'level_choice')},
            },
        ),

        # ── 2. Add nullable topic_level FK to CodingExercise ─────────
        migrations.AddField(
            model_name='codingexercise',
            name='topic_level',
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='exercises',
                to='coding.topiclevel',
            ),
        ),

        # ── 3. Data migration ────────────────────────────────────────
        migrations.RunPython(populate_topic_levels, reverse_populate),

        # ── 4. Make topic_level non-nullable ─────────────────────────
        migrations.AlterField(
            model_name='codingexercise',
            name='topic_level',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='exercises',
                to='coding.topiclevel',
            ),
        ),

        # ── 5. Remove legacy topic + level fields ────────────────────
        migrations.RemoveField(model_name='codingexercise', name='topic'),
        migrations.RemoveField(model_name='codingexercise', name='level'),

        # ── 6. Update ordering to use new traversal ──────────────────
        migrations.AlterModelOptions(
            name='codingexercise',
            options={'ordering': ['topic_level__topic', 'topic_level__level_choice', 'order']},
        ),
    ]
