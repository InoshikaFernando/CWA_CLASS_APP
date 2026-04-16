# Reintroduces homework_assigned choice to Notification.notification_type.
# The original migration (0088_alter_notification_notification_type) was
# removed when PR #152 was reverted, but the homework_assigned value was
# added to models.py earlier (commit 366f50a8, before PR #152) and remains
# in the model — leaving a migration/model drift that makemigrations
# detected. This migration reconciles the schema with the existing model.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0088_school_default_fee'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                choices=[
                    ('criteria_approval', 'Criteria Approval Request'),
                    ('criteria_approved', 'Criteria Approved'),
                    ('criteria_rejected', 'Criteria Rejected'),
                    ('enrollment_request', 'Enrollment Request'),
                    ('enrollment_approved', 'Enrollment Approved'),
                    ('enrollment_rejected', 'Enrollment Rejected'),
                    ('attendance', 'Attendance'),
                    ('parent_link_request', 'Parent Link Request'),
                    ('parent_link_approved', 'Parent Link Approved'),
                    ('parent_link_rejected', 'Parent Link Rejected'),
                    ('homework_assigned', 'Homework Assigned'),
                    ('general', 'General'),
                ],
                default='general',
                max_length=30,
            ),
        ),
    ]
