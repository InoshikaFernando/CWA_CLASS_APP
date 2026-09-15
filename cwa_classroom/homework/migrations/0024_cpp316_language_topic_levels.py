# CPP-316: Add language_topic_levels M2M to Homework
#
# Safe to run even if the through-table already exists (e.g. dev environments
# that previously ran the dev branch where this migration ran under a different
# number). SeparateDatabaseAndState updates Django's migration state while the
# RunSQL uses IF NOT EXISTS so the CREATE is a no-op when the table is present.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0023_alter_homework_options_alter_homework_managers'),
        ('languages', '0007_cpp316_language_progress'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='homework',
                    name='language_topic_levels',
                    field=models.ManyToManyField(
                        blank=True,
                        related_name='homeworks',
                        to='languages.languagetopiclevel',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS `homework_homework_language_topic_levels` (
                            `id` bigint NOT NULL AUTO_INCREMENT,
                            `homework_id` bigint NOT NULL,
                            `languagetopiclevel_id` bigint NOT NULL,
                            PRIMARY KEY (`id`),
                            UNIQUE KEY `homework_homework_lang_homework_id_languagetopiclevel_uniq`
                                (`homework_id`, `languagetopiclevel_id`)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """,
                    reverse_sql="DROP TABLE IF EXISTS `homework_homework_language_topic_levels`;",
                ),
            ],
        ),
    ]
