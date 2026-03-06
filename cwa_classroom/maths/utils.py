"""
Utility functions for database operations with retry logic
"""
import time
from functools import wraps
from django.db import transaction, OperationalError
from django.db.utils import DatabaseError


def retry_on_db_lock(max_retries=5, delay=0.01, backoff=2):
    """
    Decorator to retry database operations on lock errors.
    Useful for SQLite which has limited concurrency.
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries (seconds)
        backoff: Multiplier for delay on each retry
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (OperationalError, DatabaseError) as e:
                    # Check if it's a database lock error
                    error_str = str(e).lower()
                    if 'locked' in error_str or 'database is locked' in error_str:
                        last_exception = e
                        if attempt < max_retries - 1:
                            # Wait before retrying
                            time.sleep(current_delay)
                            current_delay *= backoff
                            continue
                    # If it's not a lock error, or we've exhausted retries, raise it
                    raise
            
            # If we've exhausted all retries, raise the last exception
            if last_exception:
                raise last_exception
            return None
        return wrapper
    return decorator


from contextlib import contextmanager

@contextmanager
def atomic_with_retry(max_retries=5, delay=0.01, backoff=2):
    """
    Context manager for atomic transactions with retry logic.
    Usage:
        with atomic_with_retry():
            # database operations
    """
    current_delay = delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                yield
                return
        except (OperationalError, DatabaseError) as e:
            error_str = str(e).lower()
            if 'locked' in error_str or 'database is locked' in error_str:
                last_exception = e
                if attempt < max_retries - 1:
                    time.sleep(current_delay)
                    current_delay *= backoff
                    continue
            raise
    
    if last_exception:
        raise last_exception


@retry_on_db_lock(max_retries=5)
def save_student_final_answer(student, session_id, topic, level, points_earned):
    """
    Helper function to save StudentFinalAnswer with retry logic.
    This wraps the common pattern of getting attempt number and saving.
    """
    from maths.models import StudentFinalAnswer
    
    attempt_number = StudentFinalAnswer.get_next_attempt_number(
        student=student,
        topic=topic,
        level=level
    )
    
    StudentFinalAnswer.objects.update_or_create(
        student=student,
        session_id=session_id,
        defaults={
            'topic': topic,
            'level': level,
            'attempt_number': attempt_number,
            'points_earned': points_earned,
        }
    )

