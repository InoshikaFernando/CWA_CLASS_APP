"""The report's own "What's next" suggestions.

Rules, not generated prose, and the rules are the thing worth testing. This
text is read by a child about themselves and by a parent about their child, so
the failures that matter are not crashes — they are confident sentences the
figures do not support.
"""

from django.test import TestCase

from progress.reports import (
    MIN_TOPIC_ANSWERS, STRONG_PCT, WEAK_PCT, next_steps_section,
)


def topic(name, answered, accuracy):
    return {
        'topic': name, 'answered': answered,
        'correct': round(answered * accuracy / 100), 'accuracy_pct': accuracy,
    }


def data(topics=(), **totals):
    base = {
        'submissions': 6, 'activity_items': 6, 'assigned': 0, 'completed': 0,
        'avg_first_pct': 60, 'avg_best_pct': 70, 'improvement_pct': 0,
        'on_time_pct': 100,
    }
    base.update(totals)
    return {'totals': base, 'topics': list(topics), 'attempts': {
        'repeat_rate_pct': 50,
    }}


def kinds(result):
    return [item['kind'] for item in result['items']]


def texts(result):
    return ' '.join(item['text'] for item in result['items'])


class EvidenceTests(TestCase):
    """What the rules refuse to say."""

    def test_an_empty_period_gets_no_advice_at_all(self):
        """The report already says the period was empty."""
        result = next_steps_section(data(submissions=0, activity_items=0))

        self.assertEqual(result['items'], [])

    def test_one_wrong_answer_is_not_a_weakness(self):
        """The failure that would matter most: naming a gap on thin evidence.

        A single question answered wrongly is noise. Calling it a weak topic
        tells a child they are bad at something on the strength of nothing.
        """
        result = next_steps_section(data([topic('Probability', 1, 0)]))

        self.assertEqual(kinds(result), ['note'])
        self.assertNotIn('Probability', texts(result))

    def test_the_evidence_floor_is_the_documented_one(self):
        below = next_steps_section(
            data([topic('Money', MIN_TOPIC_ANSWERS - 1, 0)])
        )
        at = next_steps_section(data([topic('Money', MIN_TOPIC_ANSWERS, 0)]))

        self.assertNotIn('Money', texts(below))
        self.assertIn('Money', texts(at))

    def test_unclassified_is_never_named_as_a_topic(self):
        """"Unclassified" is a bucket, not something to go and practise."""
        result = next_steps_section(data([topic('Unclassified', 20, 10)]))

        self.assertEqual(kinds(result), ['note'])


class TheTreeTests(TestCase):
    def test_strong_here_and_weak_there_names_both(self):
        """The case the request was actually about."""
        result = next_steps_section(data([
            topic('Money', 8, 14),
            topic('Fractions', 10, 92),
        ]))

        self.assertEqual(kinds(result)[:2], ['strength', 'focus'])
        self.assertIn('Fractions is secure at 92%', texts(result))
        self.assertIn('Money is the one to put the time into', texts(result))

    def test_only_the_single_weakest_topic_is_named(self):
        """"Work on all five of these" is not a plan."""
        result = next_steps_section(data([
            topic('Money', 8, 10),
            topic('Angles', 8, 20),
            topic('Area', 8, 30),
        ]))

        self.assertIn('Money', texts(result))
        self.assertNotIn('Angles', texts(result))
        self.assertNotIn('Area', texts(result))

    def test_everything_secure_suggests_moving_on(self):
        result = next_steps_section(data([
            topic('Money', 8, 88),
            topic('Fractions', 10, 95),
        ]))

        self.assertIn('strength', kinds(result))
        self.assertIn(f'{STRONG_PCT}% or better', texts(result))

    def test_all_middling_names_the_one_with_most_room(self):
        result = next_steps_section(data([
            topic('Money', 8, 55),
            topic('Fractions', 10, 70),
        ]))

        self.assertEqual(kinds(result)[0], 'focus')
        self.assertIn('Money has the most room to improve', texts(result))

    def test_a_topic_on_the_weak_boundary_is_not_a_gap(self):
        result = next_steps_section(data([topic('Money', 8, WEAK_PCT)]))

        self.assertIn('most room to improve', texts(result))
        self.assertNotIn('put the time into', texts(result))


class EngagementFirstTests(TestCase):
    """Content advice is beside the point when the work was not started."""

    def test_nothing_attempted_says_so_and_stops(self):
        result = next_steps_section(data(
            [topic('Money', 8, 14)], assigned=5, completed=0,
        ))

        self.assertIn('None of the 5 homework due', texts(result))
        self.assertNotIn('Money', texts(result))

    def test_some_attempted_asks_for_the_rest_first(self):
        result = next_steps_section(data(
            [topic('Money', 8, 14)], assigned=5, completed=2,
        ))

        self.assertIn('2 of 5 homework due was attempted', texts(result))
        self.assertNotIn('Money', texts(result))

    def test_all_attempted_moves_on_to_the_topics(self):
        result = next_steps_section(data(
            [topic('Money', 8, 14)], assigned=5, completed=5,
        ))

        self.assertIn('Money', texts(result))


class HabitTests(TestCase):
    def test_retrying_that_works_is_named(self):
        result = next_steps_section(data(
            [topic('Money', 8, 60)],
            avg_first_pct=60, avg_best_pct=85, improvement_pct=25,
        ))

        self.assertIn('habit', kinds(result))
        self.assertIn('Retrying is working', texts(result))

    def test_not_retrying_is_suggested_instead(self):
        result = next_steps_section({
            'totals': {'submissions': 6, 'activity_items': 6, 'assigned': 0,
                       'completed': 0, 'avg_best_pct': 60, 'avg_first_pct': 60,
                       'improvement_pct': 0, 'on_time_pct': 100},
            'topics': [topic('Money', 8, 60)],
            'attempts': {'repeat_rate_pct': 0},
        })

        self.assertIn('A second attempt', texts(result))

    def test_no_habit_line_when_the_habits_are_fine(self):
        result = next_steps_section(data(
            [topic('Money', 8, 90)],
            avg_best_pct=90, improvement_pct=2, on_time_pct=100,
        ))

        self.assertNotIn('habit', kinds(result))


class ShapeTests(TestCase):
    def test_it_never_runs_to_more_than_three_lines(self):
        """More than three reads as a lecture and gets skimmed."""
        result = next_steps_section(data(
            [topic('Money', 8, 14), topic('Fractions', 10, 95)],
            assigned=5, completed=5, improvement_pct=25,
        ))

        self.assertLessEqual(len(result['items']), 3)

    def test_every_line_names_the_figure_it_rests_on(self):
        """A reader has to be able to disagree by checking the number."""
        result = next_steps_section(data([
            topic('Money', 8, 14),
            topic('Fractions', 10, 92),
        ]))

        for item in result['items']:
            self.assertRegex(
                item['text'], r'\d',
                f'no figure in: {item["text"]}',
            )
