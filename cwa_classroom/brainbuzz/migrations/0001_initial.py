import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BrainBuzzSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('join_code', models.CharField(db_index=True, max_length=6, unique=True)),
                ('subject', models.CharField(choices=[('maths', 'Maths'), ('coding', 'Coding')], max_length=20)),
                ('state', models.CharField(choices=[('lobby', 'Lobby'), ('in_progress', 'In Progress'), ('ended', 'Ended')], db_index=True, default='lobby', max_length=20)),
                ('state_version', models.PositiveIntegerField(default=0)),
                ('current_question_index', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='brainbuzz_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='BrainBuzzSessionQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order_index', models.PositiveSmallIntegerField()),
                ('question_text', models.TextField()),
                ('question_type', models.CharField(choices=[('multiple_choice', 'Multiple Choice'), ('true_false', 'True / False'), ('short_answer', 'Short Answer'), ('fill_blank', 'Fill in the Blank')], default='multiple_choice', max_length=20)),
                ('options', models.JSONField(blank=True, default=list)),
                ('accepted_answers', models.JSONField(blank=True, default=list)),
                ('time_limit_seconds', models.PositiveSmallIntegerField(default=20)),
                ('question_start_time_utc', models.DateTimeField(blank=True, null=True)),
                ('question_deadline_utc', models.DateTimeField(blank=True, null=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='brainbuzz.brainbuzzsession')),
            ],
            options={
                'ordering': ['session', 'order_index'],
            },
        ),
        migrations.CreateModel(
            name='BrainBuzzParticipant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nickname', models.CharField(max_length=50)),
                ('is_active', models.BooleanField(default=True)),
                ('total_score', models.PositiveIntegerField(default=0)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='participants', to='brainbuzz.brainbuzzsession')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='brainbuzz_participations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-total_score', 'joined_at'],
            },
        ),
        migrations.CreateModel(
            name='BrainBuzzSubmission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('answer_payload', models.JSONField(help_text='{"option_id": "..."} or {"text": "..."}')),
                ('is_correct', models.BooleanField(default=False)),
                ('score_awarded', models.PositiveIntegerField(default=0)),
                ('participant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='submissions', to='brainbuzz.brainbuzzparticipant')),
                ('session_question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='submissions', to='brainbuzz.brainbuzzsessionquestion')),
            ],
            options={
                'ordering': ['-submitted_at'],
            },
        ),
        migrations.AddIndex(
            model_name='brainbuzzsession',
            index=models.Index(fields=['join_code', 'state'], name='bb_session_code_state_idx'),
        ),
        migrations.AddIndex(
            model_name='brainbuzzsessionquestion',
            index=models.Index(fields=['session', 'order_index'], name='bb_sq_session_order_idx'),
        ),
        migrations.AddIndex(
            model_name='brainbuzzparticipant',
            index=models.Index(fields=['session', 'nickname'], name='bb_part_session_nick_idx'),
        ),
        migrations.AddIndex(
            model_name='brainbuzzsubmission',
            index=models.Index(fields=['session_question', 'participant'], name='bb_sub_sq_part_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='brainbuzzsessionquestion',
            unique_together={('session', 'order_index')},
        ),
        migrations.AlterUniqueTogether(
            name='brainbuzzsubmission',
            unique_together={('participant', 'session_question')},
        ),
    ]
