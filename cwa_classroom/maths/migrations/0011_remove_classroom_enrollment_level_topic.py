"""
Migration 0011: Remove maths.ClassRoom, maths.Enrollment, maths.Level,
and maths.Topic models.

After migration 0010, Question/StudentFinalAnswer/TopicLevelStatistics/BasicFactsResult
all point directly to classroom.Topic and classroom.Level. The internal maths
models are no longer needed:

  - maths.Enrollment   — replaced by classroom.ClassRoom student M2M
  - maths.ClassRoom    — replaced by classroom.ClassRoom
  - maths.Level.topics — M2M to classroom.Topic (now on classroom.Level directly)
  - maths.Level        — replaced by classroom.Level
  - maths.Topic        — replaced by classroom.Topic

Drop order respects FK constraints:
  1. Delete Enrollment (FK → ClassRoom)
  2. Remove ClassRoom.levels M2M (FK → Level)
  3. Delete ClassRoom
  4. Remove Level.topics M2M (FK → classroom.Topic)
  5. Delete Level
  6. Delete Topic
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("maths", "0010_use_classroom_topic_level"),
    ]

    operations = [
        # 1. Enrollment (references ClassRoom)
        migrations.DeleteModel(
            name="Enrollment",
        ),
        # 2. ClassRoom.levels M2M (references Level)
        migrations.RemoveField(
            model_name="ClassRoom",
            name="levels",
        ),
        # 3. ClassRoom itself
        migrations.DeleteModel(
            name="ClassRoom",
        ),
        # 4. Level.topics M2M (references classroom.Topic)
        migrations.RemoveField(
            model_name="Level",
            name="topics",
        ),
        # 5. Level
        migrations.DeleteModel(
            name="Level",
        ),
        # 6. Topic
        migrations.DeleteModel(
            name="Topic",
        ),
    ]
