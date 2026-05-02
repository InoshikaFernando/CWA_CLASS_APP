"""Seed long-division and prime-factorization questions from JSON banks.

The JSON files live at ``maths/seed_data/`` and are the source of truth.
To add more questions later, append to the JSON file and write a new
follow-up migration that calls ``seed_questions`` again — get_or_create
keeps it idempotent.
"""
import json
import os
from django.db import migrations


SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "seed_data",
)
LONG_DIVISION_JSON = os.path.join(SEED_DIR, "long_division_questions.json")
PRIME_FACTORIZATION_JSON = os.path.join(SEED_DIR, "prime_factorization_questions.json")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["questions"]


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


def _difficulty_for_year(year):
    return min(3, max(1, year - 3))


def seed_questions(apps, schema_editor):
    Subject = apps.get_model("classroom", "Subject")
    Level = apps.get_model("classroom", "Level")
    Topic = apps.get_model("classroom", "Topic")
    Question = apps.get_model("maths", "Question")
    Answer = apps.get_model("maths", "Answer")

    maths = Subject.objects.filter(name="Mathematics", school__isnull=True).first()
    if maths is None:
        return  # No global Mathematics subject — nothing to seed.

    long_division_topic, _ = Topic.objects.get_or_create(
        name="Long Division", subject=maths,
        defaults={"order": 99, "is_active": True},
    )
    factors_topic, _ = Topic.objects.get_or_create(
        name="Factors", subject=maths,
        defaults={"order": 99, "is_active": True},
    )

    levels_by_year = {lvl.level_number: lvl for lvl in Level.objects.all()}

    for entry in _load(LONG_DIVISION_JSON):
        year, dividend, divisor = entry["year"], entry["dividend"], entry["divisor"]
        level = levels_by_year.get(year)
        if not level:
            continue
        long_division_topic.levels.add(level)
        text = f"Solve using long division: {dividend} ÷ {divisor}"
        q, created = Question.objects.get_or_create(
            question_text=text, question_type="long_division",
            level=level, topic=long_division_topic,
            defaults={
                "difficulty": _difficulty_for_year(year),
                "dividend": dividend, "divisor": divisor,
                "explanation": f"{dividend} ÷ {divisor} = {_long_division_answer(dividend, divisor)}",
            },
        )
        if created:
            Answer.objects.create(
                question=q, answer_text=_long_division_answer(dividend, divisor),
                is_correct=True, order=1,
            )

    for entry in _load(PRIME_FACTORIZATION_JSON):
        year, n = entry["year"], entry["target_number"]
        level = levels_by_year.get(year)
        if not level:
            continue
        factors_topic.levels.add(level)
        text = f"Find the prime factorization of {n}."
        q, created = Question.objects.get_or_create(
            question_text=text, question_type="prime_factorization",
            level=level, topic=factors_topic,
            defaults={
                "difficulty": _difficulty_for_year(year),
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
    ld_dividends = [e["dividend"] for e in _load(LONG_DIVISION_JSON)]
    pf_targets = [e["target_number"] for e in _load(PRIME_FACTORIZATION_JSON)]
    Question.objects.filter(question_type="long_division", dividend__in=ld_dividends).delete()
    Question.objects.filter(question_type="prime_factorization", target_number__in=pf_targets).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("maths", "0020_question_target_number_alter_question_question_type"),
        ("classroom", "0001_initial"),
    ]
    operations = [
        migrations.RunPython(seed_questions, unseed_questions),
    ]
