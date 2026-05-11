"""
fix_proof_rubrics.py
--------------------
One-off script to:
  1. Update rubrics for parallel-lines proof questions to list multiple valid paths
  2. Clear AIGradingCache for those questions so they are re-evaluated fresh
  3. Re-grade any existing AI-graded answers for those questions

Run on the server (with venv active) from the cwa_classroom directory:
  python manage.py shell < ../scripts/fix_proof_rubrics.py

Safe to re-run (idempotent).
"""

# ---------------------------------------------------------------------------
# Model imports
# ---------------------------------------------------------------------------
from maths.models import Question
from homework.models import HomeworkStudentAnswer, HomeworkSubmission, AIGradingCache
from worksheets.grading_service import grade_extended_answer

# ── 1. Rubric updates ──────────────────────────────────────────────────────
# These are the parallel-lines proof questions.  Each has multiple valid
# proof paths via different angle-pair relationships.  We replace any rubric
# that only lists one prescriptive path with a fact-based rubric that accepts
# any mathematically valid chain.

RUBRIC_UPDATES = {
    r'b \+ e = 180': (
        'Full marks: Any valid chain of angle relationships that logically proves b + e = 180. '
        'Valid approaches include (but are not limited to): '
        '(1) a + b = 180 (angles on a straight line) and a = e (corresponding angles, parallel lines) → b + e = 180; '
        '(2) b = d (vertically opposite angles) and d + e = 180 (co-interior / same-side interior angles, parallel lines) → b + e = 180; '
        '(3) b = f (corresponding angles) and f + e = 180 (angles on a straight line) → b + e = 180. '
        'Key angle facts a student may use: corresponding angles equal (parallel lines), '
        'co-interior angles sum to 180° (parallel lines), vertically opposite angles equal, '
        'angles on a straight line sum to 180°. '
        'Award full marks for any correct logical sequence — even if it differs from these examples.'
    ),
    r'a \+ f = 180': (
        'Full marks: Any valid chain of angle relationships that logically proves a + f = 180. '
        'Valid approaches include (but are not limited to): '
        '(1) a = e (corresponding angles) and e + f = 180 (angles on a straight line) → a + f = 180; '
        '(2) a + b = 180 (angles on a straight line) and b = f (corresponding angles) → a + f = 180; '
        '(3) f = d (vertically opposite) and a + d = 180 (co-interior angles, parallel lines) → a + f = 180. '
        'Key facts: corresponding angles equal (parallel lines), co-interior angles sum to 180° (parallel lines), '
        'vertically opposite angles equal, angles on a straight line sum to 180°. '
        'Award full marks for any correct logical chain.'
    ),
    r'a \+ d = b \+ c': (
        'Full marks: Any valid argument proving a + d = b + c. '
        'Valid approaches include: '
        '(1) a = c (vertically opposite) and b = d (vertically opposite) → a + d = c + b = b + c; '
        '(2) a + b = 180 (linear pair) and c + d = 180 (linear pair) → a + d = 180 - b + 180 - c = ... '
        'with algebraic rearrangement; '
        '(3) any other valid sequence using angle-pair relationships. '
        'Key facts: vertically opposite angles equal, angles on a straight line sum to 180°. '
        'Award full marks for any correct logical chain.'
    ),
    r'a \+ b \+ c \+ d = 360': (
        'Full marks: Any valid argument proving all four angles sum to 360°. '
        'Valid approaches: '
        '(1) a + b = 180° (linear pair) and c + d = 180° (linear pair) → total = 360°; '
        '(2) a + d = 180° (co-interior) and b + c = 180° (co-interior) → total = 360°; '
        '(3) angles around a point sum to 360°. '
        'Key facts: angles on a straight line sum to 180°, angles around a point sum to 360°. '
        'Award full marks for any correct logical argument.'
    ),
}

print("=" * 60)
print("Step 1: Updating proof question rubrics")
print("=" * 60)

updated_count = 0
question_pks = []

for pattern, new_rubric in RUBRIC_UPDATES.items():
    qs = Question.objects.filter(question_text__iregex=pattern)
    if not qs.exists():
        print(f"  [NOT FOUND] No question matching pattern: {pattern!r}")
        continue
    for q in qs:
        old = (q.grading_rubric or '')[:80]
        q.grading_rubric = new_rubric
        q.save(update_fields=['grading_rubric'])
        question_pks.append(q.pk)
        print(f"  [UPDATED] Q{q.pk}: {q.question_text[:55]!r}")
        print(f"            Old rubric: {old!r}")
        updated_count += 1

print(f"\n  {updated_count} question(s) updated. PKs: {question_pks}")

# ── 2. Clear AIGradingCache for those questions ────────────────────────────
print()
print("=" * 60)
print("Step 2: Clearing AIGradingCache for updated questions")
print("=" * 60)

deleted, _ = AIGradingCache.objects.filter(question_id__in=question_pks).delete()
print(f"  Deleted {deleted} cache entries.")

# ── 3. Re-grade existing AI-graded answers for those questions ─────────────
print()
print("=" * 60)
print("Step 3: Re-grading existing answers for updated questions")
print("=" * 60)

answers = HomeworkStudentAnswer.objects.filter(
    question_id__in=question_pks,
    review_status=HomeworkStudentAnswer.REVIEW_AI_DONE,
).select_related('question', 'submission')

print(f"  Found {answers.count()} AI-graded answer(s) to re-evaluate.")
print()

affected_submissions = set()

for ans in answers:
    q = ans.question
    answer_text = ans.text_answer or ''
    if not answer_text.strip():
        print(f"  [SKIP] Q{q.pk} / Ans{ans.pk}: empty answer")
        continue

    school = ans.submission.school if ans.submission else None

    print(f"  Grading Q{q.pk} ({q.question_text[:45]!r})")
    print(f"    Answer: {answer_text[:80]!r}")

    result = grade_extended_answer(q, answer_text, school=school)

    old_correct = ans.is_correct
    old_score = ans.ai_score_fraction

    ans.is_correct = result['is_correct']
    ans.ai_score_fraction = result['score_fraction']
    ans.ai_feedback = result['feedback']
    ans.points_earned = (result['score_fraction'] * (q.points or 1.0)) if q.points else (1.0 if result['is_correct'] else 0.0)
    ans.save(update_fields=['is_correct', 'ai_score_fraction', 'ai_feedback', 'points_earned'])

    affected_submissions.add(ans.submission_id)

    print(f"    Before: correct={old_correct}, score={old_score}")
    print(f"    After:  correct={result['is_correct']}, score={result['score_fraction']:.2f}")
    print(f"    Feedback: {result['feedback'][:120]}")
    hit = result.get('cache_hit')
    print(f"    Cache hit: {hit}, Tokens in/out: {result.get('input_tokens')}/{result.get('output_tokens')}")
    print()

# ── 4. Recalculate submission totals ──────────────────────────────────────
print("=" * 60)
print("Step 4: Recalculating submission scores")
print("=" * 60)

for sub_id in affected_submissions:
    try:
        sub = HomeworkSubmission.objects.prefetch_related('answers').get(pk=sub_id)
        all_ans = list(sub.answers.all())
        correct_count = sum(1 for a in all_ans if a.is_correct)
        total_pts = sum((a.points_earned or 0) for a in all_ans)
        sub.score = correct_count
        sub.points = total_pts
        sub.save(update_fields=['score', 'points'])
        print(f"  Submission {sub_id}: {correct_count}/{len(all_ans)} correct, {total_pts:.1f} points")
    except HomeworkSubmission.DoesNotExist:
        print(f"  Submission {sub_id}: not found")

print()
print("Done.")
