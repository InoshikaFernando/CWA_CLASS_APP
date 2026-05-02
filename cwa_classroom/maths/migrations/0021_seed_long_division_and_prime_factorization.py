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
YEARS = (4, 5, 6, 7, 8)


def _load_year(year, slug):
    path = os.path.join(SEED_DIR, f"year{year}_{slug}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["questions"]


def _all_long_division():
    out = []
    for y in YEARS:
        for q in _load_year(y, "long_division"):
            out.append({"year": y, **q})
    return out


def _all_prime_factorization():
    out = []
    for y in YEARS:
        for q in _load_year(y, "prime_factorization"):
            out.append({"year": y, **q})
    return out


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

    for entry in _all_long_division():
        level = levels_by_year.get(entry["year"])
        if not level:
            continue
        long_division_topic.levels.add(level)
        q, created = Question.objects.get_or_create(
            question_text=entry["question_text"],
            question_type="long_division",
            level=level, topic=long_division_topic,
            defaults={
                "difficulty": entry.get("difficulty", _difficulty_for_year(entry["year"])),
                "points": entry.get("points", 1),
                "dividend": entry["dividend"],
                "divisor": entry["divisor"],
                "explanation": entry.get("explanation", ""),
            },
        )
        if created:
            for a in entry.get("answers", []):
                Answer.objects.create(
                    question=q,
                    answer_text=a.get("text") or a.get("answer_text", ""),
                    is_correct=bool(a.get("is_correct")),
                    order=a.get("order", 1),
                )

    for entry in _all_prime_factorization():
        level = levels_by_year.get(entry["year"])
        if not level:
            continue
        factors_topic.levels.add(level)
        q, created = Question.objects.get_or_create(
            question_text=entry["question_text"],
            question_type="prime_factorization",
            level=level, topic=factors_topic,
            defaults={
                "difficulty": entry.get("difficulty", _difficulty_for_year(entry["year"])),
                "points": entry.get("points", 1),
                "target_number": entry["target_number"],
                "explanation": entry.get("explanation", ""),
            },
        )
        if created:
            for a in entry.get("answers", []):
                Answer.objects.create(
                    question=q,
                    answer_text=a.get("text") or a.get("answer_text", ""),
                    is_correct=bool(a.get("is_correct")),
                    order=a.get("order", 1),
                )


def unseed_questions(apps, schema_editor):
    Question = apps.get_model("maths", "Question")
    ld_dividends = [e["dividend"] for e in _all_long_division()]
    pf_targets = [e["target_number"] for e in _all_prime_factorization()]
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
