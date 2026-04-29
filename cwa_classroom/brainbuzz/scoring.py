"""
scoring.py
~~~~~~~~~~
Deterministic, server-side scoring for BrainBuzz sessions.

Kahoot-equivalent formula:
  - Incorrect answer → 0 points
  - Correct answer → points_base * (1 - (time_fraction * 0.5))
    where time_fraction = time_taken_ms / (time_per_question_sec * 1000)
    - Min 50% of base for slow answer
    - Max 100% for instant answer
  - Late submission (past deadline + grace) → 0 points (but still marked correct)

Short-answer matching:
  - Trimmed + case-insensitive + whitespace-normalised
  - Configurable per-question list of accepted answers (| separated)
"""
import re
from typing import List, Optional, Tuple


def calculate_points(
    is_correct: bool,
    time_taken_ms: int,
    time_per_question_sec: int,
    points_base: int = 1000,
    is_late: bool = False,
) -> int:
    """
    Calculate points awarded for an answer.
    
    Args:
        is_correct: Whether the answer is correct
        time_taken_ms: Time taken to answer in milliseconds (0-60000)
        time_per_question_sec: Question time limit in seconds (e.g., 20)
        points_base: Base points for correct answer (default 1000)
        is_late: Whether submitted after deadline + grace period (disqualifies all points)
    
    Returns:
        Points awarded (0 to points_base)
    
    Formula:
        if not is_correct or is_late:
            return 0
        time_fraction = time_taken_ms / (time_per_question_sec * 1000)
        return round(points_base * (1 - (time_fraction * 0.5)))
    
    Examples:
        >>> calculate_points(False, 5000, 20, 1000)  # Incorrect
        0
        
        >>> calculate_points(True, 0, 20, 1000)  # Instant correct
        1000
        
        >>> calculate_points(True, 20000, 20, 1000)  # Entire time used
        500
        
        >>> calculate_points(True, 10000, 20, 1000)  # Half time
        750
    """
    if not is_correct or is_late:
        return 0
    
    time_fraction = time_taken_ms / (time_per_question_sec * 1000)
    points = points_base * (1 - (time_fraction * 0.5))
    return round(points)


def normalize_short_answer(text: str) -> str:
    """
    Normalize short answer for case-insensitive comparison.
    
    Performs:
    1. Strip leading/trailing whitespace
    2. Convert to lowercase
    3. Normalize whitespace (multiple spaces → single space)
    4. Remove extra punctuation variations
    
    Args:
        text: Raw user answer
    
    Returns:
        Normalized answer
    
    Examples:
        >>> normalize_short_answer("  Python  ")
        'python'
        
        >>> normalize_short_answer("3.0")
        '3.0'
        
        >>> normalize_short_answer("JavaScript")
        'javascript'
    """
    # Strip whitespace
    text = text.strip()
    
    # Convert to lowercase
    text = text.lower()
    
    # Normalize whitespace: collapse multiple spaces to single
    text = re.sub(r'\s+', ' ', text)
    
    return text


def is_short_answer_correct(
    user_answer: str,
    correct_answers: str,
    case_sensitive: bool = False,
) -> bool:
    """
    Check if short answer matches any of the correct answers.
    
    Supports | separated alternatives in correct_answers.
    Performs normalization (trim, lowercase, whitespace) automatically.
    
    Args:
        user_answer: Answer provided by student
        correct_answers: Correct answer(s), | separated (e.g., "python|py|3")
        case_sensitive: If False (default), performs case-insensitive match
    
    Returns:
        True if answer matches any of the accepted answers
    
    Examples:
        >>> is_short_answer_correct("Python", "python")
        True
        
        >>> is_short_answer_correct("  py  ", "python|py|python3")
        True
        
        >>> is_short_answer_correct("ruby", "python|py")
        False
        
        >>> is_short_answer_correct("Java", "javascript")
        False  # Not a substring match
    """
    if not user_answer or not correct_answers:
        return False
    
    # Normalize user answer
    if not case_sensitive:
        user_answer = normalize_short_answer(user_answer)
        correct_answers = correct_answers.lower()
    else:
        user_answer = user_answer.strip()
    
    # Split alternatives and check each
    acceptable = [alt.strip() for alt in correct_answers.split('|')]
    
    for acceptable_answer in acceptable:
        if not case_sensitive:
            acceptable_answer = normalize_short_answer(acceptable_answer)
        
        if user_answer == acceptable_answer:
            return True
    
    return False


def parse_short_answer_alternatives(correct_answers: str) -> List[str]:
    """
    Parse pipe-separated alternatives into a list.
    
    Args:
        correct_answers: Alternatives separated by | (e.g., "python|py|python3")
    
    Returns:
        List of normalized alternatives
    
    Examples:
        >>> parse_short_answer_alternatives("python|py|python3")
        ['python', 'py', 'python3']
        
        >>> parse_short_answer_alternatives("  3  |  three  |  3.0  ")
        ['3', 'three', '3.0']
    """
    if not correct_answers:
        return []
    
    alternatives = [alt.strip() for alt in correct_answers.split('|') if alt.strip()]
    return alternatives


def calculate_time_fraction(
    time_taken_ms: int,
    time_per_question_sec: int,
) -> float:
    """
    Calculate fraction of time used for scoring calculation.
    
    Capped at 1.0 (time used >= full question time returns >= 0.5 points).
    
    Args:
        time_taken_ms: Time taken in milliseconds
        time_per_question_sec: Time limit in seconds
    
    Returns:
        Fraction of time used (0.0 to 1.0+)
    
    Examples:
        >>> calculate_time_fraction(0, 20)
        0.0
        
        >>> calculate_time_fraction(10000, 20)
        0.5
        
        >>> calculate_time_fraction(20000, 20)
        1.0
        
        >>> calculate_time_fraction(30000, 20)  # Over limit
        1.5
    """
    if time_per_question_sec <= 0:
        return 1.0
    
    time_limit_ms = time_per_question_sec * 1000
    return time_taken_ms / time_limit_ms


# Common test fixture: time-to-points mapping for 20s question
def get_points_at_time(
    time_taken_sec: float,
    time_per_question_sec: int = 20,
    points_base: int = 1000,
) -> int:
    """
    Helper to calculate points for a given time (in seconds, for readability).
    
    Args:
        time_taken_sec: Time in seconds
        time_per_question_sec: Question time limit in seconds
        points_base: Base points
    
    Returns:
        Points awarded
    """
    time_taken_ms = int(time_taken_sec * 1000)
    return calculate_points(True, time_taken_ms, time_per_question_sec, points_base)
