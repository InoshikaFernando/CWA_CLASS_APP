"""
Migration: create homework_homework_topics M2M table if it doesn't exist.

Root cause: The test/production server was built from a legacy schema that
pre-dates the homework app's Django migrations. The initial migration (0001)
was never applied cleanly, so the topics ManyToManyField through-table
`homework_homework_topics` was never created in the legacy database.

This migration uses CREATE TABLE IF NOT EXISTS so it is safe to run on both:
  - fresh installs (table already exists → no-op)
  - legacy environments (table missing → create it)
"""

from django.db import migrations


def _create_topics_table_if_missing(apps, schema_editor):
    conn = schema_editor.connection
    vendor = conn.vendor

    with conn.cursor() as cur:
        if vendor == 'sqlite':
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS "homework_homework_topics" (
                    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                    "homework_id" bigint NOT NULL REFERENCES "homework_homework" ("id"),
                    "topic_id" bigint NOT NULL REFERENCES "classroom_topic" ("id"),
                    UNIQUE ("homework_id", "topic_id")
                )
                """
            )
        else:
            # MySQL / MariaDB
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS `homework_homework_topics` (
                    `id` bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    `homework_id` bigint NOT NULL,
                    `topic_id` bigint NOT NULL,
                    UNIQUE KEY `homework_homework_topics_homework_id_topic_id` (`homework_id`, `topic_id`),
                    CONSTRAINT `homework_homework_topics_homework_id_fk`
                        FOREIGN KEY (`homework_id`) REFERENCES `homework_homework` (`id`)
                        ON DELETE CASCADE,
                    CONSTRAINT `homework_homework_topics_topic_id_fk`
                        FOREIGN KEY (`topic_id`) REFERENCES `classroom_topic` (`id`)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )


class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0004_fix_legacy_schema'),
    ]

    operations = [
        migrations.RunPython(
            _create_topics_table_if_missing,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
