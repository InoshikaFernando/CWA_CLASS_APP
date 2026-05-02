"""Generate JSON question banks for long division and prime factorization."""
import json
import os
import random

random.seed(42)


def gen_long_division():
    out = []
    bands = {
        4: ((2, 9), (20, 200)),
        5: ((2, 12), (100, 800)),
        6: ((2, 15), (500, 5000)),
        7: ((3, 25), (2000, 25000)),
        8: ((4, 35), (5000, 99999)),
    }
    for year, (drange, mrange) in bands.items():
        seen = set()
        while sum(1 for x in out if x["year"] == year) < 20:
            divisor = random.randint(*drange)
            dividend = random.randint(*mrange)
            key = (dividend, divisor)
            if key in seen:
                continue
            seen.add(key)
            out.append({"year": year, "dividend": dividend, "divisor": divisor})
    return out


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


def gen_prime_factorization():
    out = []
    bands = {
        4: (4, 30),
        5: (30, 80),
        6: (80, 200),
        7: (200, 500),
        8: (500, 999),
    }
    for year, (lo, hi) in bands.items():
        seen = set()
        while sum(1 for x in out if x["year"] == year) < 20:
            n = random.randint(lo, hi)
            if n in seen or is_prime(n):
                continue
            seen.add(n)
            out.append({"year": year, "target_number": n})
    return out


def main():
    here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    base = os.path.join(
        os.path.dirname(here), "cwa_classroom", "maths", "seed_data",
    )
    os.makedirs(base, exist_ok=True)

    ld = gen_long_division()
    pf = gen_prime_factorization()

    with open(os.path.join(base, "long_division_questions.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"question_type": "long_division", "count": len(ld), "questions": ld},
            f, indent=2,
        )
    with open(os.path.join(base, "prime_factorization_questions.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"question_type": "prime_factorization", "count": len(pf), "questions": pf},
            f, indent=2,
        )

    print(f"long_division: {len(ld)} questions")
    print(f"prime_factorization: {len(pf)} questions")


if __name__ == "__main__":
    main()
