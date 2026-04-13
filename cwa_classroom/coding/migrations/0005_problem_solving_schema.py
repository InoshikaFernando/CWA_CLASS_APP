"""
Migration 0005 — Problem Solving schema update
================================================
Changes applied:
  CodingProblem:
    - language FK: required → nullable (SET_NULL, null=True, blank=True)
    - category         — new CharField (choices, default='algorithm')
    - constraints      — new TextField (blank=True)
    - time_limit_seconds — new PositiveSmallIntegerField (default=5)
    - memory_limit_mb    — new PositiveSmallIntegerField (default=256)

  ProblemTestCase:
    - order → renamed to display_order
    - is_boundary_test — new BooleanField (default=False)

  New models:
    - ProblemSubmission
    - ProblemSubmissionResult
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('coding', '0004_studentexercisesubmission_blocks_xml'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── CodingProblem: make language nullable ────────────────────────────
        migrations.AlterField(
            model_name='codingproblem',
            name='language',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='problems',
                help_text='Leave blank for language-agnostic problems (students choose on submit).',
                to='coding.codinglanguage',
            ),
        ),

        # ── CodingProblem: add new fields ─────────────────────────────────────
        migrations.AddField(
            model_name='codingproblem',
            name='category',
            field=models.CharField(
                choices=[
                    ('algorithm', 'Algorithm'),
                    ('logic', 'Logic'),
                    ('data_structures', 'Data Structures'),
                    ('dynamic_programming', 'Dynamic Programming'),
                    ('graph_theory', 'Graph Theory'),
                    ('string_manipulation', 'String Manipulation'),
                    ('mathematics', 'Mathematics'),
                    ('sorting_searching', 'Sorting & Searching'),
                ],
                default='algorithm',
                help_text='Problem category used for filtering and grouping',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='codingproblem',
            name='constraints',
            field=models.TextField(
                blank=True,
                help_text="Constraints on input size, value ranges, etc. (e.g. '1 ≤ n ≤ 10⁶')",
            ),
        ),
        migrations.AddField(
            model_name='codingproblem',
            name='time_limit_seconds',
            field=models.PositiveSmallIntegerField(
                default=5,
                help_text='Maximum wall-clock execution time allowed per test case (seconds)',
            ),
        ),
        migrations.AddField(
            model_name='codingproblem',
            name='memory_limit_mb',
            field=models.PositiveSmallIntegerField(
                default=256,
                help_text='Maximum memory allowed per test case (megabytes)',
            ),
        ),

        # ── ProblemTestCase: rename order → display_order ────────────────────
        migrations.RenameField(
            model_name='problemtestcase',
            old_name='order',
            new_name='display_order',
        ),

        # ── ProblemTestCase: add is_boundary_test ────────────────────────────
        migrations.AddField(
            model_name='problemtestcase',
            name='is_boundary_test',
            field=models.BooleanField(
                default=False,
                help_text='True for boundary / edge-value test cases (e.g. empty input, max constraints).',
            ),
        ),

        # ── New model: ProblemSubmission ──────────────────────────────────────
        migrations.CreateModel(
            name='ProblemSubmission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('submitted_code', models.TextField(help_text="Exact code submitted by the student")),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('passed', 'Passed'), ('failed', 'Failed')],
                    db_index=True,
                    default='pending',
                    max_length=10,
                )),
                ('test_cases_passed', models.PositiveSmallIntegerField(
                    default=0,
                    help_text='Number of test cases (visible + hidden) that passed',
                )),
                ('total_test_cases', models.PositiveSmallIntegerField(
                    default=0,
                    help_text='Total number of test cases evaluated',
                )),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('student', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='problem_submissions',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('problem', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='problem_submissions',
                    to='coding.codingproblem',
                )),
                ('language', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='problem_submissions',
                    help_text='Language the student chose for this submission',
                    to='coding.codinglanguage',
                )),
            ],
            options={
                'ordering': ['-submitted_at'],
            },
        ),
        migrations.AddIndex(
            model_name='problemsubmission',
            index=models.Index(fields=['student', 'problem'], name='coding_ps_stu_prob_idx'),
        ),
        migrations.AddIndex(
            model_name='problemsubmission',
            index=models.Index(fields=['student', 'problem', 'status'], name='coding_ps_stu_prob_st_idx'),
        ),

        # ── New model: ProblemSubmissionResult ────────────────────────────────
        migrations.CreateModel(
            name='ProblemSubmissionResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('actual_output', models.TextField(
                    blank=True,
                    help_text="stdout captured from the student's program for this test case",
                )),
                ('is_passed', models.BooleanField(default=False)),
                ('execution_time_ms', models.PositiveIntegerField(
                    default=0,
                    help_text='Wall-clock execution time in milliseconds as reported by Piston',
                )),
                ('submission', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='results',
                    to='coding.problemsubmission',
                )),
                ('test_case', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='submission_results',
                    to='coding.problemtestcase',
                )),
            ],
            options={
                'ordering': ['submission', 'test_case__display_order'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='problemsubmissionresult',
            unique_together={('submission', 'test_case')},
        ),
        migrations.AddIndex(
            model_name='problemsubmissionresult',
            index=models.Index(fields=['submission', 'is_passed'], name='coding_psr_sub_passed_idx'),
        ),
    ]
