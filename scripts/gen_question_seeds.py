"""Generate JSON question banks for long division and prime factorization.

Output schema matches the app's "Upload Questions" parser
(classroom.upload_services.MathsQuestionParser):

    {
      "strand": "Number",
      "topic": "Long Division",
      "year_level": 4,
      "questions": [
        {
          "question_text": "...",
          "question_type": "long_division",
          "difficulty": 1,
          "points": 1,
          "explanation": "...",
          "dividend": 84, "divisor": 7,
          "answers": [{"text": "12", "is_correct": true}]
        },
        ...
      ]
    }

One file per (year, topic) — 10 files total (5 years × 2 topics).
"""
import json
import os
import random


LD_BANDS = {
    4: ((2, 9),   (20, 200)),
    5: ((2, 12),  (100, 800)),
    6: ((2, 15),  (500, 5000)),
    7: ((3, 25),  (2000, 25000)),
    8: ((4, 35),  (5000, 99999)),
}

PF_BANDS = {
    4: (4, 40),
    5: (30, 80),
    6: (80, 200),
    7: (200, 500),
    8: (500, 999),
}

QUESTIONS_PER_YEAR = 20


def is_prime(n):
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def long_division_answer(dividend, divisor):
    q, r = divmod(dividend, divisor)
    return f"{q}" if r == 0 else f"{q} r {r}"


def prime_factorization_answer(n):
    factors = []
    p = 2
    while n > 1:
        if n % p == 0:
            factors.append(p)
            n //= p
        else:
            p = 3 if p == 2 else p + 2
    return "x".join(str(f) for f in factors)


def difficulty_for_year(year):
    return min(3, max(1, year - 3))


def build_long_division(year):
    drange, mrange = LD_BANDS[year]
    rng = random.Random(1000 + year)
    seen = set()
    questions = []
    while len(questions) < QUESTIONS_PER_YEAR:
        d = rng.randint(*drange)
        n = rng.randint(*mrange)
        if (n, d) in seen:
            continue
        seen.add((n, d))
        questions.append({
            "question_text": f"Solve using long division: {n} ÷ {d}",
            "question_type": "long_division",
            "difficulty": difficulty_for_year(year),
            "points": 1,
            "explanation": f"{n} ÷ {d} = {long_division_answer(n, d)}",
            "dividend": n,
            "divisor": d,
            "answers": [{"text": long_division_answer(n, d), "is_correct": True}],
        })
    return {
        "strand": "Number",
        "topic": "Long Division",
        "year_level": year,
        "questions": questions,
    }


def build_prime_factorization(year):
    lo, hi = PF_BANDS[year]
    rng = random.Random(2000 + year)
    seen = set()
    questions = []
    candidates = [n for n in range(lo, hi + 1) if not is_prime(n)]
    rng.shuffle(candidates)
    for n in candidates:
        if len(questions) >= QUESTIONS_PER_YEAR:
            break
        if n in seen:
            continue
        seen.add(n)
        questions.append({
            "question_text": f"Find the prime factorization of {n}.",
            "question_type": "prime_factorization",
            "difficulty": difficulty_for_year(year),
            "points": 1,
            "explanation": f"{n} = {prime_factorization_answer(n).replace('x', ' x ')}",
            "target_number": n,
            "answers": [{"text": prime_factorization_answer(n), "is_correct": True}],
        })
    return {
        "strand": "Number",
        "topic": "Factors",
        "year_level": year,
        "questions": questions,
    }


def main():
    here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    base = os.path.join(os.path.dirname(here), "cwa_classroom", "maths", "seed_data")
    os.makedirs(base, exist_ok=True)

    written = []
    for year in range(4, 9):
        for builder, slug in (
            (build_long_division, "long_division"),
            (build_prime_factorization, "prime_factorization"),
        ):
            payload = builder(year)
            path = os.path.join(base, f"year{year}_{slug}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            written.append((path, len(payload["questions"])))

    for path, n in written:
        print(f"{os.path.basename(path)}: {n} questions")


if __name__ == "__main__":
    main()
