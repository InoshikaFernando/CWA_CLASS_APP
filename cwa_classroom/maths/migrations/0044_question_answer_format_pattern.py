# Adds the 'pattern' answer_format choice — "create your own number pattern"
# questions, which store no Answer row and so were graded wrong for everyone.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('maths', '0043_question_health_typed_questions'),
    ]

    operations = [
        migrations.AlterField(
            model_name='question',
            name='answer_format',
            field=models.CharField(
                choices=[
                    ('text', 'Text — exact match (case/space-insensitive)'),
                    ('algebra', 'Algebra — simplified polynomial (e.g. expand & simplify)'),
                    ('equation', 'Equation — algebraic equivalence (accepts vertex / factored / expanded form)'),
                    ('set', 'Set — list every value, any order (e.g. "what are the multiples of 9 between 50 and 70?")'),
                    ('pattern', 'Pattern — student invents their own number pattern (no stored answer)'),
                ],
                default='text',
                help_text=(
                    'For short_answer / calculation questions. "Algebra" grades the answer as a '
                    'fully simplified, expanded polynomial — e.g. (2x+3)(x-5) must be entered as '
                    '"2x^2 - 7x - 15". "Equation" grades by algebraic equivalence — for '
                    '"write the equation" questions any spelling of the same curve is accepted '
                    '(y=2(x-1)^2-2 == y=2x^2-4x). Term order and spacing are always ignored. '
                    '"Set" is for "list every value" questions — store the values as one '
                    'comma-separated answer ("54, 63"); the student must give them all, in any '
                    'order. Leave as "Text" when the order of the values is part of the answer '
                    '(e.g. "write these numbers in order"). "Pattern" is for "create your own '
                    'number pattern" questions, which have no single right answer and so store '
                    'no Answer row at all: the typed numbers are graded against what the '
                    'question asks for (same step each time, right operation, right count). '
                    'Without it such a question marks every student wrong.'
                ),
                max_length=10,
            ),
        ),
    ]
