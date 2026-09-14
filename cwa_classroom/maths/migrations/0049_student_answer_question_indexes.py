"""Indexes the wrong-answer leaderboard groups by.

``maths.question_difficulty`` counts, per question, how many of the answers
recorded against it were wrong. The only index StudentAnswer had led with
``student`` (the unique_together), so that GROUP BY had nothing to walk and
read the whole table — on a store that grows with every quiz anybody sits.
The second pair carries the "only answers given since it was reviewed" scan.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maths", "0048_question_retirement"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="studentanswer",
            index=models.Index(
                fields=["question", "is_correct"], name="maths_sa_question_correct_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="studentanswer",
            index=models.Index(
                fields=["question", "answered_at"], name="maths_sa_question_when_idx"
            ),
        ),
    ]
