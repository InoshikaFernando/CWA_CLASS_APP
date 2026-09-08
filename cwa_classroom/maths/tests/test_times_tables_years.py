"""Which times tables a year may practise, and the two places that decide it.

Two systems used to answer this question and they disagreed:

* the times-tables quiz picker read ``TIMES_TABLES_BY_YEAR``;
* the year accordion on ``/maths/`` and the Mixed Quiz read ``Topic.levels``
  from the database.

So a Year 3 page could offer "Multiplication (7x)" while the constant said
Year 3 stops at 10. These tests pin both: the constant is one definition with a
sane fallback, and ``set_times_table_years`` makes the database agree with it.
"""
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from classroom.models import Level, Subject, Topic
from maths.constants import (
    MAX_TIMES_TABLE, TIMES_TABLES_BY_YEAR, times_tables_for_year,
)


# ── the curriculum itself ─────────────────────────────────────────────────
class TestTheScheme:
    def test_each_year_offers_at_least_what_the_year_below_did(self):
        """A ladder that goes backwards would take a table off a child who
        had it last year, mid-schooling."""
        years = sorted(TIMES_TABLES_BY_YEAR)
        for below, above in zip(years, years[1:]):
            assert set(TIMES_TABLES_BY_YEAR[below]) <= set(TIMES_TABLES_BY_YEAR[above]), (
                f'Year {above} drops tables Year {below} had')

    def test_every_year_from_one_to_ten_is_named(self):
        """Year 6 was missing once, and fell through to a default that gave it
        MORE tables than Year 7 — silently, because a missing key reads as an
        absent opinion rather than as a bug."""
        assert set(TIMES_TABLES_BY_YEAR) == set(range(1, 11))

    def test_the_ceiling_is_derived_from_the_scheme(self):
        assert MAX_TIMES_TABLE == max(
            t for tables in TIMES_TABLES_BY_YEAR.values() for t in tables)

    def test_an_unmapped_year_gets_the_senior_list_not_everything(self):
        """Year 13 is not in the dict. It must not thereby out-rank Year 10."""
        assert times_tables_for_year(13) == TIMES_TABLES_BY_YEAR[10]
        assert times_tables_for_year(3) == TIMES_TABLES_BY_YEAR[3]

    def test_the_lists_are_sorted_and_free_of_duplicates(self):
        for year, tables in TIMES_TABLES_BY_YEAR.items():
            assert tables == sorted(set(tables)), year


# ── the database side ─────────────────────────────────────────────────────
@pytest.fixture
def maths(db):
    subject = Subject.objects.create(name='Mathematics', slug='mathematics')
    levels = {n: Level.objects.create(level_number=n, display_name=f'Year {n}')
              for n in range(1, 11)}
    return {'subject': subject, 'levels': levels}


def tt(maths, name, years=(), slug=None):
    topic = Topic.objects.create(
        subject=maths['subject'], name=name,
        slug=slug or f'{name.lower().replace(" ", "-")}-{Topic.objects.count()}',
        is_active=True)
    for year in years:
        topic.levels.add(maths['levels'][year])
    return topic


def run(**kwargs):
    out = StringIO()
    call_command('set_times_table_years', stdout=out, stderr=out, **kwargs)
    return out.getvalue()


def years_of(topic):
    return sorted(topic.levels.values_list('level_number', flat=True))


class TestSetTimesTableYears:
    def test_a_table_reaches_exactly_the_years_the_curriculum_gives_it(self, maths):
        """5x is Year 3 and up under the current scheme; 3x starts at Year 4."""
        five = tt(maths, 'Multiplication (5×)')
        three = tt(maths, 'Division (3×)')

        run()

        assert years_of(five) == [y for y in range(1, 11)
                                  if 5 in times_tables_for_year(y)]
        assert years_of(three) == [y for y in range(1, 11)
                                   if 3 in times_tables_for_year(y)]

    def test_a_year_a_table_should_not_reach_is_unlinked(self, maths):
        """The case this command exists for: merging the duplicate times-table
        strands unioned their year links, so Year 3 gained 7x."""
        seven = tt(maths, 'Multiplication (7×)', years=(3,))

        run()

        assert 3 not in years_of(seven)

    def test_a_table_no_year_reaches_is_unlinked_but_never_deleted(self, maths):
        """15x is off the ladder now. The row and its questions stay."""
        fifteen = tt(maths, 'Multiplication (15×)', years=(9, 10))

        out = run()

        fifteen.refresh_from_db()
        assert years_of(fifteen) == []
        assert Topic.objects.filter(pk=fifteen.pk).exists()
        assert 'reach no year' in out
        assert 'Multiplication (15×)' in out

    def test_an_ordinary_topic_is_left_alone(self, maths):
        """Only rows named like a times table are this command's business."""
        fractions = tt(maths, 'Fractions', years=(3, 4, 5))

        run()

        assert years_of(fractions) == [3, 4, 5]

    def test_a_basic_facts_level_link_is_not_touched(self, maths):
        """Basic facts live at 100+ and are a different ladder.

        Dropping that link here would be a deletion nobody asked for.
        """
        basic = Level.objects.create(level_number=114, display_name='Mult 1')
        seven = tt(maths, 'Multiplication (7×)', years=(3,))
        seven.levels.add(basic)

        run()

        assert 114 in seven.levels.values_list('level_number', flat=True)

    def test_dry_run_writes_nothing(self, maths):
        seven = tt(maths, 'Multiplication (7×)', years=(3,))

        out = run(dry_run=True)

        assert years_of(seven) == [3]
        assert 'DRY RUN' in out

    def test_running_twice_changes_nothing_the_second_time(self, maths):
        tt(maths, 'Multiplication (7×)', years=(3,))

        run()
        out = run()

        assert 'Changed 0 topic(s)' in out

    def test_an_ascii_x_is_matched_too(self, maths):
        """A hand-typed row must not be silently skipped."""
        seven = tt(maths, 'Multiplication (7x)', years=(3,))

        run()

        assert 3 not in years_of(seven)

    def test_no_maths_subject_is_rejected(self, db):
        Level.objects.create(level_number=1, display_name='Year 1')
        with pytest.raises(CommandError):
            run()

    def test_no_year_levels_is_rejected_rather_than_a_silent_no_op(self, db):
        """Every link would look "already correct" against an empty ladder."""
        Subject.objects.create(name='Mathematics', slug='mathematics')
        Level.objects.create(level_number=114, display_name='Mult 1')
        with pytest.raises(CommandError):
            run()
