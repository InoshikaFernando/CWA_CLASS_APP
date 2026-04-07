"""
Migration: create homework_homeworkquestion and homework_homeworkstudentanswer
tables if they don't exist.

Root cause: The legacy server (Avinesh's test environment) was built from an
older schema that only had `homework_homework` and `homework_homeworksubmission`.
The `HomeworkQuestion` and `HomeworkStudentAnswer` models are new — they were
never present in the legacy DB, so Django's 0001_initial migration was faked
rather than applied, leaving these two tables missing.

Error observed on server:
  ProgrammingError: (1146, "Table '...homework_homeworkstudentanswer' doesn't exist")

This migration uses CREATE TABLE IF NOT EXISTS so it is idempotent:
  - fresh installs  → tables already exist → no-op
  - legacy server   → tables missing → create them
"""

from django.db import migrations


def _create_question_table_if_missing(apps, schema_editor):
    """Create homework_homeworkquestion if it doesn't exist."""
    conn = schema_editor.connection
    vendor = conn.vendor

    with conn.cursor() as cur:
        if vendor == 'sqlite':
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS "homework_homeworkquestion" (
                    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                    "order" integer unsigned NOT NULL,
                    "homework_id" bigint NOT NULL REFERENCES "homework_homework" ("id"),
                    "question_id" bigint NOT NULL REFERENCES "maths_question" ("id"),
                    UNIQUE ("homework_id", "question_id")
                )
                """
            )
        else:
            # MySQL / MariaDB
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS `homework_homeworkquestion` (
                    `id` bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    `order` int unsigned NOT NULL DEFAULT 0,
                    `homework_id` bigint NOT NULL,
                    `question_id` bigint NOT NULL,
                    UNIQUE KEY `homework_homeworkquestion_homework_id_question_id`
                        (`homework_id`, `question_id`),
                    CONSTRAINT `homework_homeworkquestion_homework_id_fk`
                        FOREIGN KEY (`homework_id`) REFERENCES `homework_homework` (`id`)
                        ON DELETE CASCADE,
                    CONSTRAINT `homework_homeworkquestion_question_id_fk`
                        FOREIGN KEY (`question_id`) REFERENCES `maths_question` (`id`)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )


def _create_student_answer_table_if_missing(apps, schema_editor):
    """Create homework_homeworkstudentanswer if it doesn't exist."""
    conn = schema_editor.connection
    vendor = conn.vendor

    with conn.cursor() as cur:
        if vendor == 'sqlite':
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS "homework_homeworkstudentanswer" (
                    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                    "text_answer" text NOT NULL,
                    "is_correct" bool NOT NULL,
                    "points_earned" double precision NOT NULL,
                    "question_id" bigint NOT NULL REFERENCES "maths_question" ("id"),
                    "selected_answer_id" bigint NULL REFERENCES "maths_answer" ("id"),
                    "submission_id" bigint NOT NULL
                        REFERENCES "homework_homeworksubmission" ("id"),
                    UNIQUE ("submission_id", "question_id")
                )
                """
            )
        else:
            # MySQL / MariaDB
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS `homework_homeworkstudentanswer` (
                    `id` bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    `text_answer` longtext NOT NULL,
                    `is_correct` tinyint(1) NOT NULL DEFAULT 0,
                    `points_earned` double NOT NULL DEFAULT 0,
                    `question_id` bigint NOT NULL,
                    `selected_answer_id` bigint NULL,
                    `submission_id` bigint NOT NULL,
                    UNIQUE KEY `homework_homeworkstudentanswer_submission_id_question_id`
                        (`submission_id`, `question_id`),
                    CONSTRAINT `homework_homeworkstudentanswer_question_id_fk`
                        FOREIGN KEY (`question_id`) REFERENCES `maths_question` (`id`)
                        ON DELETE CASCADE,
                    CONSTRAINT `homework_homeworkstudentanswer_selected_answer_id_fk`
                        FOREIGN KEY (`selected_answer_id`) REFERENCES `maths_answer` (`id`)
                        ON DELETE SET NULL,
                    CONSTRAINT `homework_homeworkstudentanswer_submission_id_fk`
                        FOREIGN KEY (`submission_id`)
                        REFERENCES `homework_homeworksubmission` (`id`)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )


class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0005_create_topics_m2m_if_missing'),
    ]

    operations = [
        migrations.RunPython(
            _create_question_table_if_missing,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            _create_student_answer_table_if_missing,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
