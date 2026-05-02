"""Seed long-division and prime-factorization questions from JSON banks.

The JSON files at ``maths/seed_data/year{N}_{type}.json`` are the source
of truth. Each file matches the in-app Upload-Questions schema so it can
also be uploaded via the UI as-is.

Idempotent via get_or_create on (question_text, type, level, topic). To
add more questions later, append to the JSON file and write a follow-up
migration that calls ``seed_questions`` again.
"""
import json
import os
from django.db import migrations


SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "seed_data",
)
YEARS = (4, 5, 6, 7, 8)
SLUGS = ("long_division", "prime_factorization")
TOPIC_BY_SLUG = {
    "long_division": "Long Division",
    "prime_factorization": "Factors",
}


def _load(year, slug):
    path = os.path.join(SEED_DIR, f"year{year}_{slug}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_questions(apps, schema_editor):
    Subject = apps.get_model("classroom", "Subject")
    Level = apps.get_model("classroom", "Level")
    Topic = apps.get_model("classroom", "Topic")
    Question = apps.get_model("maths", "Question")
    Answer = apps.get_model("maths", "Answer")

    maths = Subject.objects.filter(name="Mathematics", school__isnull=True).first()
    if maths is None:
        return

    # Ensure both topics live under the "Number" strand so they appear
    # alongside Division / Multiplication in the topic browser.
    number_strand = Topic.objects.filter(
        subject=maths, name="Number", parent__isnull=True,
    ).first()

    topic_cache = {}
    for slug, name in TOPIC_BY_SLUG.items():
        topic, created = Topic.objects.get_or_create(
            name=name, subject=maths,
            defaults={"order": 99, "is_active": True, "parent": number_strand},
        )
        # Backfill parent on pre-existing rows that were created before this
        # migration set the strand.
        if not created and number_strand and topic.parent_id is None:
            topic.parent = number_strand
            topic.save(update_fields=["parent"])
        topic_cache[slug] = topic

    levels_by_year = {lvl.level_number: lvl for lvl in Level.objects.all()}

    for year in YEARS:
        level = levels_by_year.get(year)
        if not level:
            continue
        for slug in SLUGS:
            data = _load(year, slug)
            if not data:
                continue
            topic = topic_cache[slug]
            topic.levels.add(level)
            for entry in data.get("questions", []):
                fields = {
                    "difficulty": entry.get("difficulty", 1),
                    "points": entry.get("points", 1),
                    "explanation": entry.get("explanation", ""),
                }
                for fname in ("dividend", "divisor", "target_number"):
                    if fname in entry and entry[fname] is not None:
                        fields[fname] = entry[fname]

                q, created = Question.objects.get_or_create(
                    question_text=entry["question_text"],
                    question_type=entry["question_type"],
                    level=level, topic=topic,
                    defaults=fields,
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
    dividends, targets = [], []
    for year in YEARS:
        for entry in (_load(year, "long_division") or {}).get("questions", []):
            if entry.get("dividend") is not None:
                dividends.append(entry["dividend"])
        for entry in (_load(year, "prime_factorization") or {}).get("questions", []):
            if entry.get("target_number") is not None:
                targets.append(entry["target_number"])
    Question.objects.filter(question_type="long_division", dividend__in=dividends).delete()
    Question.objects.filter(question_type="prime_factorization", target_number__in=targets).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("maths", "0021_seed_long_division_and_prime_factorization"),
    ]
    operations = [
        migrations.RunPython(seed_questions, unseed_questions),
    ]
