# -*- coding: utf-8 -*-
"""
Unit tests for the Japanese (kana) and Korean (hangul) language additions.

TestSeedTopicOrderConsistency  — regression: a multi-level topic's 'order'
    must be identical across all its level-entries, for every SEED
    language, not just ja/ko. Caught during code review: seed_language_
    exercises.py's Command.handle() keys LanguageTopic on (language, name)
    via get_or_create, so 'order' only takes effect from whichever
    level-entry gets seeded first — a later entry with a different
    'order' is silently discarded, leaving the SEED source lying about
    what it does. Japanese's ひらがな/カタカナ and Korean's 자음/모음 each
    had mismatched order values (e.g. beginner=1, intermediate=2) that
    produced real, gapped display-order values in the DB (1, 3 instead of
    1, 2) — fixed by aligning them, and this test stops it recurring for
    any future language.
TestJapaneseSeedStructure      — SEED['ja'] shape: 142 unique kana across
    4 topic-level entries, no cross-entry duplicates, MCQ prompts/options
    well-formed.
TestKoreanSeedStructure        — SEED['ko'] shape: 51 unique jamo across
    5 topic-level entries, same structural checks.
TestJapaneseUnlockChain        — seeds the REAL ja SEED data (not a
    synthetic topic) and proves the beginner->intermediate unlock chain
    actually fires for ひらがな and カタカナ independently, using the real
    _recalculate_progress()/_unlock_next_level() code path.
TestKoreanUnlockChain          — same for ko's 자음/모음/겹받침.
TestKanaHangulFontCoverage     — permanent regression version of the
    ad-hoc verification done while building NotoSansJP.otf/NotoSansKR.otf:
    every seeded kana/hangul character must render real ink (not a
    tofu/blank glyph) with zero font-variation warnings. Protects against
    a future re-subset silently dropping coverage.
"""
import warnings
from collections import defaultdict

import pytest

from languages.management.commands.seed_language_exercises import SEED
from languages.models import (
    Language, LanguageExercise, LanguageProgress, LanguageStudentAnswer,
    LanguageTopic, LanguageTopicLevel,
)
from languages.utils import get_canvas_config
from languages.views import _recalculate_progress


pytestmark = pytest.mark.langexpand


# ---------------------------------------------------------------------------
# Seed source structural checks (no DB)
# ---------------------------------------------------------------------------

class TestSeedTopicOrderConsistency:

    def test_every_multi_level_topic_has_one_consistent_order(self):
        for lang_code, lang_data in SEED.items():
            order_by_name = defaultdict(set)
            for topic in lang_data['topics']:
                order_by_name[topic['name']].add(topic['order'])
            inconsistent = {name: orders for name, orders in order_by_name.items() if len(orders) > 1}
            assert not inconsistent, (
                f"{lang_code}: topic(s) with mismatched 'order' across their "
                f"level-entries (only the first-seeded entry's order ever "
                f"takes effect, so this is dead/misleading data): {inconsistent}"
            )


def _chars_by_topic(lang_code):
    return {
        (t['name'], t['level']): t['letter_writing']
        for t in SEED[lang_code]['topics']
    }


class TestJapaneseSeedStructure:

    def test_142_unique_kana_no_cross_topic_duplicates(self):
        topics = _chars_by_topic('ja')
        seen = {}
        for key, chars in topics.items():
            for ch in chars:
                assert ch not in seen, f'{ch!r} appears in both {seen[ch]} and {key}'
                seen[ch] = key
        assert len(seen) == 142

    def test_topic_level_shape(self):
        keys = set(_chars_by_topic('ja').keys())
        assert keys == {
            ('ひらがな (Hiragana)', 'beginner'),
            ('ひらがな (Hiragana)', 'intermediate'),
            ('カタカナ (Katakana)', 'beginner'),
            ('カタカナ (Katakana)', 'intermediate'),
        }

    def test_phonics_mcq_well_formed(self):
        for topic in SEED['ja']['topics']:
            lw = set(topic['letter_writing'])
            for prompt, opts in topic['phonics_mcq']:
                assert prompt in lw
                assert len(opts) == 3
                assert len(set(opts)) == 3
                assert prompt not in opts


class TestKoreanSeedStructure:

    def test_51_unique_jamo_no_cross_topic_duplicates(self):
        topics = _chars_by_topic('ko')
        seen = {}
        for key, chars in topics.items():
            for ch in chars:
                assert ch not in seen, f'{ch!r} appears in both {seen[ch]} and {key}'
                seen[ch] = key
        assert len(seen) == 51

    def test_topic_level_shape(self):
        keys = set(_chars_by_topic('ko').keys())
        assert keys == {
            ('자음 (Consonants)', 'beginner'),
            ('자음 (Consonants)', 'intermediate'),
            ('모음 (Vowels)', 'beginner'),
            ('모음 (Vowels)', 'intermediate'),
            ('겹받침 (Final Consonant Clusters)', 'beginner'),
        }

    def test_phonics_mcq_well_formed(self):
        for topic in SEED['ko']['topics']:
            lw = set(topic['letter_writing'])
            for prompt, opts in topic['phonics_mcq']:
                assert prompt in lw
                assert len(opts) == 3
                assert len(set(opts)) == 3
                assert prompt not in opts

    def test_final_clusters_each_decompose_into_two_basic_consonants(self):
        """Sanity check on the linguistic claim baked into the SEED comment
        (each of the 11 겹받침 is literally two of the 19 consonants written
        together) using the actual jamo names, independent of the derivation
        script's own FINAL_CLUSTER_PARTS table."""
        import unicodedata
        clusters = dict(SEED['ko']['topics'][4]['phonics_mcq'])  # prompts only needed as keys
        cluster_chars = SEED['ko']['topics'][4]['letter_writing']
        assert len(cluster_chars) == 11
        for ch in cluster_chars:
            name = unicodedata.name(ch)
            assert name.startswith('HANGUL LETTER '), name
            # e.g. "HANGUL LETTER RIEUL-KIYEOK" -> two components joined by '-'
            assert '-' in name, f'{ch!r} ({name}) does not look like a two-part cluster name'


# ---------------------------------------------------------------------------
# Real unlock-chain behaviour (actual SEED data, not synthetic topics)
# ---------------------------------------------------------------------------

def _seed_into_db(lang_code):
    """Mirrors seed_language_exercises.Command.handle()'s DB-writing logic
    for a single language, without going through call_command (avoids
    pulling in every other SEED language and stdout noise)."""
    data = SEED[lang_code]
    lang, _ = Language.objects.get_or_create(
        code=lang_code,
        defaults={'name': data['name'], 'script_type': data['script_type'], 'is_active': True, 'order': 90},
    )
    levels = {}
    for topic_data in data['topics']:
        topic, _ = LanguageTopic.objects.get_or_create(
            language=lang, name=topic_data['name'],
            defaults={'order': topic_data['order'], 'is_active': True},
        )
        level, _ = LanguageTopicLevel.objects.get_or_create(
            topic=topic, level_choice=topic_data['level'],
        )
        exercises = []
        for i, char in enumerate(topic_data['letter_writing']):
            ex, _ = LanguageExercise.objects.get_or_create(
                topic_level=level, exercise_type=LanguageExercise.LETTER_WRITING,
                prompt=char, defaults={'points': 1, 'order': i, 'is_active': True},
            )
            exercises.append(ex)
        levels[(topic_data['name'], topic_data['level'])] = (level, exercises)
    return levels


def _master(student, level, exercises):
    for ex in exercises:
        LanguageStudentAnswer.objects.create(
            student=student, exercise=ex, score=100.0, is_correct=True, points_earned=ex.points,
        )
    _recalculate_progress(student, level)


@pytest.mark.django_db
class TestJapaneseUnlockChain:

    def test_mastering_hiragana_beginner_unlocks_hiragana_intermediate(self):
        from accounts.models import CustomUser, Role, UserRole
        student = CustomUser.objects.create_user(username='ja_unlock_1', password='x', email='j1@test.com')
        role, _ = Role.objects.get_or_create(name='student')
        UserRole.objects.get_or_create(user=student, role=role)

        levels = _seed_into_db('ja')
        beg_level, beg_exs = levels[('ひらがな (Hiragana)', 'beginner')]
        inter_level, _ = levels[('ひらがな (Hiragana)', 'intermediate')]
        kata_inter_level, _ = levels[('カタカナ (Katakana)', 'intermediate')]

        assert not LanguageProgress.objects.filter(student=student, topic_level=inter_level).exists()

        _master(student, beg_level, beg_exs)

        assert LanguageProgress.objects.get(student=student, topic_level=inter_level).is_unlocked is True
        # Katakana's intermediate must NOT be affected by hiragana's mastery
        # -- it's a different topic entirely.
        assert not LanguageProgress.objects.filter(student=student, topic_level=kata_inter_level).exists()

    def test_mastering_katakana_beginner_unlocks_katakana_intermediate(self):
        from accounts.models import CustomUser, Role, UserRole
        student = CustomUser.objects.create_user(username='ja_unlock_2', password='x', email='j2@test.com')
        role, _ = Role.objects.get_or_create(name='student')
        UserRole.objects.get_or_create(user=student, role=role)

        levels = _seed_into_db('ja')
        beg_level, beg_exs = levels[('カタカナ (Katakana)', 'beginner')]
        inter_level, _ = levels[('カタカナ (Katakana)', 'intermediate')]

        _master(student, beg_level, beg_exs)

        assert LanguageProgress.objects.get(student=student, topic_level=inter_level).is_unlocked is True


@pytest.mark.django_db
class TestKoreanUnlockChain:

    def test_mastering_consonants_beginner_unlocks_consonants_intermediate(self):
        from accounts.models import CustomUser, Role, UserRole
        student = CustomUser.objects.create_user(username='ko_unlock_1', password='x', email='k1@test.com')
        role, _ = Role.objects.get_or_create(name='student')
        UserRole.objects.get_or_create(user=student, role=role)

        levels = _seed_into_db('ko')
        beg_level, beg_exs = levels[('자음 (Consonants)', 'beginner')]
        inter_level, _ = levels[('자음 (Consonants)', 'intermediate')]
        vowel_inter_level, _ = levels[('모음 (Vowels)', 'intermediate')]

        _master(student, beg_level, beg_exs)

        assert LanguageProgress.objects.get(student=student, topic_level=inter_level).is_unlocked is True
        assert not LanguageProgress.objects.filter(student=student, topic_level=vowel_inter_level).exists()

    def test_final_clusters_topic_is_unlocked_by_default(self):
        """겹받침 is deliberately a standalone single-level ('beginner')
        topic, not a level of 자음 -- so it must be unlocked from the start
        like any other beginner topic, with no dependency on consonant
        mastery."""
        from accounts.models import CustomUser, Role, UserRole
        from languages.views import _is_level_locked
        student = CustomUser.objects.create_user(username='ko_unlock_2', password='x', email='k2@test.com')
        role, _ = Role.objects.get_or_create(name='student')
        UserRole.objects.get_or_create(user=student, role=role)

        levels = _seed_into_db('ko')
        clusters_level, _ = levels[('겹받침 (Final Consonant Clusters)', 'beginner')]

        assert _is_level_locked(student, clusters_level) is False


# ---------------------------------------------------------------------------
# Font coverage regression (no DB — pure font/scoring check)
# ---------------------------------------------------------------------------

class TestKanaHangulFontCoverage:

    @pytest.mark.parametrize('lang_code,script_type', [('ja', 'kana'), ('ko', 'hangul')])
    def test_every_seeded_character_renders_real_ink_with_no_font_warnings(self, lang_code, script_type):
        from languages import scoring

        chars = set()
        for topic in SEED[lang_code]['topics']:
            chars.update(topic['letter_writing'])
        assert chars, f'no letter_writing characters found for {lang_code}'

        cfg = get_canvas_config(script_type)
        below_threshold = []
        warned = []
        for ch in sorted(chars):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                mask = scoring.render_glyph_mask(ch, script_type, cfg)
            if caught:
                warned.append((ch, [str(w.message) for w in caught]))
            if int(mask.sum()) < scoring.MIN_TEMPLATE_INK_PX:
                below_threshold.append(ch)

        assert not below_threshold, (
            f'{lang_code}: characters render below MIN_TEMPLATE_INK_PX '
            f'(tofu/blank glyph — font subset likely missing coverage): {below_threshold}'
        )
        assert not warned, (
            f'{lang_code}: font-variation warnings during rendering '
            f'(expected zero on a Variable-source subset): {warned}'
        )
