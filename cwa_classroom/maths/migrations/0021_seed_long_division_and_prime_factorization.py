from django.db import migrations


# (year_level, dividend, divisor)
LONG_DIVISION_DATA = [
    (4, 48, 4),
    (4, 96, 8),
    (4, 144, 6),
    (5, 156, 12),
    (5, 425, 5),
    (5, 728, 7),
    (6, 3270, 5),
    (6, 6435, 9),
    (7, 9876, 7),
    (7, 12480, 8),
    (8, 98765, 7),
    (8, 14400, 16),
]


# (year_level, target_number)
PRIME_FACTORIZATION_DATA = [
    (4, 8),
    (4, 12),
    (4, 18),
    (4, 20),
    (5, 36),
    (5, 50),
    (5, 72),
    (6, 100),
    (6, 120),
    (6, 144),
    (7, 168),
    (7, 210),
    (8, 360),
    (8, 504),
]


def _long_division_answer(dividend, divisor):
    q, r = divmod(dividend, divisor)
    return f"{q}" if r == 0 else f"{q} r {r}"


def _prime_factorization_answer(n):
    factors = []
    p = 2
    while n > 1:
        if n % p == 0:
            factors.append(p)
            n //= p
        else:
            p = 3 if p == 2 else p + 2
    return "x".join(str(f) for f in factors)


def seed_questions(apps, schema_editor):
    Subject = apps.get_model("classroom", "Subject")
    Level = apps.get_model("classroom", "Level")
    Topic = apps.get_model("classroom", "Topic")
    Question = apps.get_model("maths", "Question")
    Answer = apps.get_model("maths", "Answer")

    maths = Subject.objects.filter(name="Mathematics", school__isnull=True).first()
    if maths is None:
        return  # No global Mathematics subject — nothing to seed.

    def _get_topic(name):
        topic, _ = Topic.objects.get_or_create(
            name=name, subject=maths,
            defaults={"order": 99, "is_active": True},
        )
        return topic

    long_division_topic = _get_topic("Long Division")
    factors_topic = _get_topic("Factors")

    for year, dividend, divisor in LONG_DIVISION_DATA:
        level = Level.objects.filter(level_number=year).first()
        if not level:
            continue
        long_division_topic.levels.add(level)
        text = f"Solve using long division: {dividend} ÷ {divisor}"
        q, created = Question.objects.get_or_create(
            question_text=text,
            question_type="long_division",
            level=level,
            topic=long_division_topic,
            defaults={
                "difficulty": min(3, max(1, year - 3)),
                "dividend": dividend,
                "divisor": divisor,
                "explanation": f"{dividend} ÷ {divisor} = {_long_division_answer(dividend, divisor)}",
            },
        )
        if created:
            Answer.objects.create(
                question=q, answer_text=_long_division_answer(dividend, divisor),
                is_correct=True, order=1,
            )

    for year, n in PRIME_FACTORIZATION_DATA:
        level = Level.objects.filter(level_number=year).first()
        if not level:
            continue
        factors_topic.levels.add(level)
        text = f"Find the prime factorization of {n}."
        q, created = Question.objects.get_or_create(
            question_text=text,
            question_type="prime_factorization",
            level=level,
            topic=factors_topic,
            defaults={
                "difficulty": min(3, max(1, year - 3)),
                "target_number": n,
                "explanation": f"{n} = {_prime_factorization_answer(n).replace('x', ' x ')}",
            },
        )
        if created:
            Answer.objects.create(
                question=q, answer_text=_prime_factorization_answer(n),
                is_correct=True, order=1,
            )


def unseed_questions(apps, schema_editor):
    Question = apps.get_model("maths", "Question")
    targets = [d for _, d, _ in LONG_DIVISION_DATA]
    pf_targets = [n for _, n in PRIME_FACTORIZATION_DATA]
    Question.objects.filter(question_type="long_division", dividend__in=targets).delete()
    Question.objects.filter(question_type="prime_factorization", target_number__in=pf_targets).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("maths", "0020_question_target_number_alter_question_question_type"),
        ("classroom", "0001_initial"),
    ]
    operations = [
        migrations.RunPython(seed_questions, unseed_questions),
    ]
