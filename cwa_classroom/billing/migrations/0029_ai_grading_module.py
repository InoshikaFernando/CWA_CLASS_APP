"""Add AI grading module choices, questions_per_month quota field, and AIGradingUsage model."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0028_add_is_default_to_package'),
        ('classroom', '0086_parentstudent_school_nullable'),
    ]

    operations = [
        # Add questions_per_month quota to ModuleProduct
        migrations.AddField(
            model_name='moduleproduct',
            name='questions_per_month',
            field=models.PositiveIntegerField(
                blank=True, null=True,
                help_text='Monthly AI-graded answer quota. Null = unlimited. Only relevant for ai_grading_* modules.',
            ),
        ),

        # Expand ModuleSubscription.module choices to include ai_grading tiers
        migrations.AlterField(
            model_name='modulesubscription',
            name='module',
            field=models.CharField(
                max_length=50,
                choices=[
                    ('teachers_attendance', 'Teachers Attendance'),
                    ('students_attendance', 'Students Attendance'),
                    ('student_progress_reports', 'Student Progress Reports'),
                    ('ai_import_starter', 'AI Question Import - Starter'),
                    ('ai_import_professional', 'AI Question Import - Professional'),
                    ('ai_import_enterprise', 'AI Question Import - Enterprise'),
                    ('ai_grading_starter', 'AI Grading - Starter (1,000 answers/mo)'),
                    ('ai_grading_professional', 'AI Grading - Professional (5,000 answers/mo)'),
                    ('ai_grading_enterprise', 'AI Grading - Enterprise (unlimited)'),
                ],
            ),
        ),

        # New AIGradingUsage model
        migrations.CreateModel(
            name='AIGradingUsage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_start', models.DateField(help_text='First day of the billing month.')),
                ('answers_graded', models.PositiveIntegerField(
                    default=0,
                    help_text='Number of answers graded by Claude this period (cache hits excluded).',
                )),
                ('tokens_used', models.PositiveIntegerField(default=0)),
                ('estimated_cost_usd', models.DecimalField(
                    max_digits=10, decimal_places=6, default=0,
                    help_text='Estimated Anthropic API cost in USD for this period.',
                )),
                ('school', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ai_grading_usage',
                    to='classroom.school',
                )),
            ],
            options={
                'ordering': ['-period_start'],
                'unique_together': {('school', 'period_start')},
            },
        ),

        # Seed the three AI grading module products
        migrations.RunSQL(
            sql="""
                INSERT INTO billing_moduleproduct (module, name, stripe_price_id, price, is_active, questions_per_month)
                VALUES
                    ('ai_grading_starter',      'AI Grading - Starter',      '', 15.00, 1, 1000),
                    ('ai_grading_professional', 'AI Grading - Professional',  '', 49.00, 1, 5000),
                    ('ai_grading_enterprise',   'AI Grading - Enterprise',    '', 149.00, 1, NULL)
                ON DUPLICATE KEY UPDATE name=VALUES(name);
            """,
            reverse_sql="""
                DELETE FROM billing_moduleproduct
                WHERE module IN ('ai_grading_starter', 'ai_grading_professional', 'ai_grading_enterprise');
            """,
        ),
    ]
