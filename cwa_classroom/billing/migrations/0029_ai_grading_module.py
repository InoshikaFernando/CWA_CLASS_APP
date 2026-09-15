"""Add AI grading module choices, questions_per_month quota field, and AIGradingUsage model."""
from django.db import migrations, models
import django.db.models.deletion

_AI_GRADING_PRODUCTS = [
    ('ai_grading_starter',      'AI Grading - Starter',      15.00, 1000),
    ('ai_grading_professional', 'AI Grading - Professional',  49.00, 5000),
    ('ai_grading_enterprise',   'AI Grading - Enterprise',    149.00, None),
]


def _seed_ai_grading_products(apps, schema_editor):
    # ORM update_or_create instead of raw "ON DUPLICATE KEY UPDATE" SQL —
    # that's MySQL-only syntax and breaks `migrate` on sqlite (local dev,
    # CI). Matches its semantics: only `name` is refreshed on conflict.
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    for module, name, price, quota in _AI_GRADING_PRODUCTS:
        ModuleProduct.objects.update_or_create(
            module=module,
            defaults={
                'name': name,
                'stripe_price_id': '',
                'price': price,
                'is_active': True,
                'questions_per_month': quota,
            },
        )


def _unseed_ai_grading_products(apps, schema_editor):
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    ModuleProduct.objects.filter(
        module__in=[m for m, *_ in _AI_GRADING_PRODUCTS],
    ).delete()


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
        migrations.RunPython(_seed_ai_grading_products, _unseed_ai_grading_products),
    ]
