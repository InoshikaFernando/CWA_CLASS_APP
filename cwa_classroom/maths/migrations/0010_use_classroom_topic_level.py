"""
Migration 0010: Reduce coupling — point maths FK fields at classroom.Topic
and classroom.Level instead of the internal maths.Topic / maths.Level models.

Strategy (avoids FK constraint violations on MySQL):
  1. Add nullable shadow fields alongside existing ones on affected models.
  2. RunPython: ensure classroom.Subject(slug='mathematics') exists, then
     create / map classroom.Topic and classroom.Level entries, populate the
     shadow fields, and copy maths.Level.topics M2M data.
  3. Remove the old topic / level fields.
  4. Rename the shadow fields back to topic / level.
  5. Replace maths.Level.topics M2M (old target: maths.Topic →
     new target: classroom.Topic).

Affected models
───────────────
  • maths.Question            topic, level
  • maths.StudentFinalAnswer   topic, level
  • maths.TopicLevelStatistics topic, level
  • maths.BasicFactsResult     level
  • maths.Level                topics  (M2M target changes)
"""

from django.db import migrations, models
import django.db.models.deletion
from django.utils.text import slugify as django_slugify


# ---------------------------------------------------------------------------
# Data migration
# ---------------------------------------------------------------------------

def migrate_to_classroom_models(apps, schema_editor):
    MathsTopic = apps.get_model('maths', 'Topic')
    MathsLevel = apps.get_model('maths', 'Level')
    ClassroomTopic = apps.get_model('classroom', 'Topic')
    ClassroomLevel = apps.get_model('classroom', 'Level')
    ClassroomSubject = apps.get_model('classroom', 'Subject')
    Question = apps.get_model('maths', 'Question')
    StudentFinalAnswer = apps.get_model('maths', 'StudentFinalAnswer')
    TopicLevelStatistics = apps.get_model('maths', 'TopicLevelStatistics')
    BasicFactsResult = apps.get_model('maths', 'BasicFactsResult')

    # ── 1. Ensure global "Mathematics" classroom.Subject ──────────────────
    maths_subject, _ = ClassroomSubject.objects.get_or_create(
        slug='mathematics',
        school=None,
        defaults={'name': 'Mathematics', 'is_active': True},
    )

    # ── 2. Build maths.Topic → classroom.Topic map ────────────────────────
    topic_map = {}  # maths_topic_id → classroom_topic pk

    for mt in MathsTopic.objects.all():
        base_slug = django_slugify(mt.name) or f'topic-{mt.pk}'

        # Try exact name match within mathematics subject
        ct = ClassroomTopic.objects.filter(
            subject=maths_subject,
            name__iexact=mt.name,
        ).first()

        if ct is None:
            ct = ClassroomTopic.objects.filter(
                subject=maths_subject,
                slug=base_slug,
            ).first()

        if ct is None:
            # Create — ensure unique slug
            slug = base_slug
            counter = 1
            while ClassroomTopic.objects.filter(subject=maths_subject, slug=slug).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            ct = ClassroomTopic.objects.create(
                subject=maths_subject,
                name=mt.name,
                slug=slug,
                is_active=True,
            )

        topic_map[mt.pk] = ct.pk

    # ── 3. Build maths.Level → classroom.Level map ────────────────────────
    level_map = {}  # maths_level_id → classroom_level pk

    for ml in MathsLevel.objects.all():
        cl, _ = ClassroomLevel.objects.get_or_create(
            level_number=ml.level_number,
            defaults={'display_name': ml.title or f'Year {ml.level_number}'},
        )
        level_map[ml.pk] = cl.pk

    # ── 4. Copy maths.Level.topics M2M into classroom.Level.topics ────────
    # Access the M2M through the historical model's manager
    for ml in MathsLevel.objects.prefetch_related('topics').all():
        cl_pk = level_map.get(ml.pk)
        if cl_pk is None:
            continue
        cl = ClassroomLevel.objects.get(pk=cl_pk)
        for mt in ml.topics.all():
            ct_pk = topic_map.get(mt.pk)
            if ct_pk is not None:
                ct = ClassroomTopic.objects.get(pk=ct_pk)
                cl.topics.add(ct)

    # ── 5. Populate shadow fields on Question ─────────────────────────────
    for q in Question.objects.filter(topic_id__isnull=False):
        ct_pk = topic_map.get(q.topic_id)
        if ct_pk is not None:
            q.classroom_topic_id = ct_pk
            q.save(update_fields=['classroom_topic_id'])

    for q in Question.objects.filter(level_id__isnull=False):
        cl_pk = level_map.get(q.level_id)
        if cl_pk is not None:
            q.classroom_level_id = cl_pk
            q.save(update_fields=['classroom_level_id'])

    # ── 6. Populate shadow fields on StudentFinalAnswer ───────────────────
    for sfa in StudentFinalAnswer.objects.filter(topic_id__isnull=False):
        ct_pk = topic_map.get(sfa.topic_id)
        if ct_pk is not None:
            sfa.classroom_topic_id = ct_pk
            sfa.save(update_fields=['classroom_topic_id'])

    for sfa in StudentFinalAnswer.objects.filter(level_id__isnull=False):
        cl_pk = level_map.get(sfa.level_id)
        if cl_pk is not None:
            sfa.classroom_level_id = cl_pk
            sfa.save(update_fields=['classroom_level_id'])

    # ── 7. Populate shadow fields on TopicLevelStatistics ─────────────────
    for tls in TopicLevelStatistics.objects.filter(topic_id__isnull=False):
        ct_pk = topic_map.get(tls.topic_id)
        if ct_pk is not None:
            tls.classroom_topic_id = ct_pk
            tls.save(update_fields=['classroom_topic_id'])

    for tls in TopicLevelStatistics.objects.filter(level_id__isnull=False):
        cl_pk = level_map.get(tls.level_id)
        if cl_pk is not None:
            tls.classroom_level_id = cl_pk
            tls.save(update_fields=['classroom_level_id'])

    # ── 7b. Deduplicate TopicLevelStatistics on (classroom_level, classroom_topic)
    # If two old maths (level, topic) rows map to the same classroom pair,
    # keep the one with the highest student_count and delete the rest.
    # This prevents a unique-constraint violation in step 6.
    seen_pairs = {}
    for tls in TopicLevelStatistics.objects.filter(
        classroom_level_id__isnull=False,
        classroom_topic_id__isnull=False,
    ).order_by('-student_count', 'pk'):
        key = (tls.classroom_level_id, tls.classroom_topic_id)
        if key in seen_pairs:
            tls.delete()
        else:
            seen_pairs[key] = True

    # ── 8. Populate shadow fields on BasicFactsResult ─────────────────────
    for bfr in BasicFactsResult.objects.filter(level_id__isnull=False):
        cl_pk = level_map.get(bfr.level_id)
        if cl_pk is not None:
            bfr.classroom_level_id = cl_pk
            bfr.save(update_fields=['classroom_level_id'])


def reverse_migration(apps, schema_editor):
    pass  # Non-destructive — shadow fields removed on reverse schema rollback


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class Migration(migrations.Migration):

    dependencies = [
        ('maths', '0009_question_classroom_question_department'),
        ('classroom', '0069_pending_password_fields'),
    ]

    operations = [
        # ── Step 1: add nullable shadow fields ────────────────────────────

        # maths.Question
        migrations.AddField(
            model_name='question',
            name='classroom_topic',
            field=models.ForeignKey(
                'classroom.Topic',
                null=True, blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='maths_questions_new',
            ),
        ),
        migrations.AddField(
            model_name='question',
            name='classroom_level',
            field=models.ForeignKey(
                'classroom.Level',
                null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='maths_questions_by_level_new',
            ),
        ),

        # maths.StudentFinalAnswer
        migrations.AddField(
            model_name='studentfinalanswer',
            name='classroom_topic',
            field=models.ForeignKey(
                'classroom.Topic',
                null=True, blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='maths_final_answers_new',
            ),
        ),
        migrations.AddField(
            model_name='studentfinalanswer',
            name='classroom_level',
            field=models.ForeignKey(
                'classroom.Level',
                null=True, blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='maths_final_answers_by_level_new',
            ),
        ),

        # maths.TopicLevelStatistics
        migrations.AddField(
            model_name='topicLevelStatistics',
            name='classroom_topic',
            field=models.ForeignKey(
                'classroom.Topic',
                null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='maths_level_statistics_new',
            ),
        ),
        migrations.AddField(
            model_name='topicLevelStatistics',
            name='classroom_level',
            field=models.ForeignKey(
                'classroom.Level',
                null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='maths_topic_statistics_new',
            ),
        ),

        # maths.BasicFactsResult
        migrations.AddField(
            model_name='basicfactsresult',
            name='classroom_level',
            field=models.ForeignKey(
                'classroom.Level',
                null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='maths_basic_facts_results_new',
            ),
        ),

        # ── Step 2: populate shadow fields via data migration ─────────────
        migrations.RunPython(migrate_to_classroom_models, reverse_migration),

        # ── Step 3: explicitly drop unique_together on TopicLevelStatistics
        # before removing the old fields — MySQL may reject the DROP COLUMN
        # if the unique constraint is still present during the ALTER TABLE.
        migrations.AlterUniqueTogether(
            name='topicLevelStatistics',
            unique_together=set(),
        ),

        # ── Step 3b: remove old FK fields ─────────────────────────────────
        migrations.RemoveField(model_name='question', name='topic'),
        migrations.RemoveField(model_name='question', name='level'),
        migrations.RemoveField(model_name='studentfinalanswer', name='topic'),
        migrations.RemoveField(model_name='studentfinalanswer', name='level'),
        migrations.RemoveField(model_name='topicLevelStatistics', name='topic'),
        migrations.RemoveField(model_name='topicLevelStatistics', name='level'),
        migrations.RemoveField(model_name='basicfactsresult', name='level'),

        # ── Step 4: rename shadow fields to their canonical names ─────────
        migrations.RenameField(
            model_name='question',
            old_name='classroom_topic', new_name='topic',
        ),
        migrations.RenameField(
            model_name='question',
            old_name='classroom_level', new_name='level',
        ),
        migrations.RenameField(
            model_name='studentfinalanswer',
            old_name='classroom_topic', new_name='topic',
        ),
        migrations.RenameField(
            model_name='studentfinalanswer',
            old_name='classroom_level', new_name='level',
        ),
        migrations.RenameField(
            model_name='topicLevelStatistics',
            old_name='classroom_topic', new_name='topic',
        ),
        migrations.RenameField(
            model_name='topicLevelStatistics',
            old_name='classroom_level', new_name='level',
        ),
        migrations.RenameField(
            model_name='basicfactsresult',
            old_name='classroom_level', new_name='level',
        ),

        # ── Step 5: replace maths.Level.topics M2M target ─────────────────
        # Drop the old M2M (data already copied in step 2) then add new one.
        migrations.RemoveField(model_name='level', name='topics'),
        migrations.AddField(
            model_name='level',
            name='topics',
            field=models.ManyToManyField(
                'classroom.Topic',
                related_name='maths_levels',
                blank=True,
            ),
        ),

        # ── Step 6: restore unique constraints and indexes ─────────────────
        # unique_together on TopicLevelStatistics (was dropped with the old
        # 'topic' / 'level' fields and must be recreated on the renamed fields)
        migrations.AlterUniqueTogether(
            name='topicLevelStatistics',
            unique_together={('level', 'topic')},
        ),
        migrations.AddIndex(
            model_name='topicLevelStatistics',
            index=models.Index(fields=['level', 'topic'], name='maths_tls_level_topic_idx'),
        ),
        # StudentFinalAnswer compound indexes on (student, topic, level)
        migrations.AddIndex(
            model_name='studentfinalanswer',
            index=models.Index(
                fields=['student', 'topic', 'level'],
                name='maths_sfa_student_topic_level_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='studentfinalanswer',
            index=models.Index(
                fields=['student', 'topic', 'level', 'attempt_number'],
                name='maths_sfa_student_topic_level_attempt_idx',
            ),
        ),
    ]
