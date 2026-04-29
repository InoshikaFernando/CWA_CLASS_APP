"""
ranking.py
~~~~~~~~~~
Rank computation with tie-breaker logic for BrainBuzz sessions.

Tie-breaking strategy:
  1. Primary: Score (descending, highest first)
  2. Secondary: Last correct answer time (ascending, earlier wins)
  3. Tertiary: Join order (ascending, earlier join wins)

Usage:
    participants = BrainBuzzParticipant.objects.filter(session=session)
    ranks = compute_ranks(participants)
    # Returns: {participant_id: rank, ...}
"""
from typing import Dict, List, Tuple, Optional
from datetime import datetime


def compute_ranks(
    participants_with_scores: List[Dict],
) -> Dict[int, int]:
    """
    Compute ranks for participants with tie-breaking.
    
    Args:
        participants_with_scores: List of dicts with keys:
            - id: Participant ID
            - score: Total score
            - last_correct_time: datetime of last correct answer (or None)
            - joined_at: datetime of joining session
    
    Returns:
        Dict mapping participant_id → rank (1-indexed)
    
    Algorithm:
        1. Sort by (score DESC, last_correct_time ASC, joined_at ASC)
        2. Assign ranks 1, 2, 3, ...
        3. Ties have same rank, next different score gets +1 position
    
    Examples:
        >>> participants = [
        ...     {'id': 1, 'score': 2000, 'last_correct_time': None, 'joined_at': datetime(2026, 1, 1, 10, 0, 0)},
        ...     {'id': 2, 'score': 1000, 'last_correct_time': None, 'joined_at': datetime(2026, 1, 1, 10, 0, 1)},
        ... ]
        >>> ranks = compute_ranks(participants)
        >>> ranks[1]
        1
        >>> ranks[2]
        2
    """
    if not participants_with_scores:
        return {}
    
    # Sort by: score DESC, last_correct_time ASC (None → end), joined_at ASC
    def sort_key(p):
        score = -p['score']  # Negative for descending
        last_correct = p.get('last_correct_time') or datetime.max
        joined_at = p.get('joined_at') or datetime.max
        return (score, last_correct, joined_at)
    
    sorted_participants = sorted(participants_with_scores, key=sort_key)
    
    # Assign ranks
    ranks = {}
    current_rank = 1
    prev_score = None
    prev_last_correct = None
    prev_joined_at = None
    
    for position, participant in enumerate(sorted_participants, start=1):
        participant_id = participant['id']
        score = participant['score']
        last_correct_time = participant.get('last_correct_time')
        joined_at = participant.get('joined_at')
        
        # Assign new rank if any sorting criteria changed from previous
        if position > 1:
            if (score != prev_score or 
                last_correct_time != prev_last_correct or 
                joined_at != prev_joined_at):
                current_rank = position
        
        ranks[participant_id] = current_rank
        prev_score = score
        prev_last_correct = last_correct_time
        prev_joined_at = joined_at
    
    return ranks


def get_rank_for_participant(
    participant_id: int,
    all_participants: List[Dict],
) -> int:
    """
    Get rank for a specific participant.
    
    Args:
        participant_id: Participant to find rank for
        all_participants: List of all participants with scores
    
    Returns:
        Rank (1-indexed), or -1 if participant not found
    """
    ranks = compute_ranks(all_participants)
    return ranks.get(participant_id, -1)


def apply_ranks_to_leaderboard(
    participants_with_scores: List[Dict],
) -> List[Dict]:
    """
    Add 'rank' field to each participant dict.
    
    Args:
        participants_with_scores: List of participant dicts
    
    Returns:
        Same list with 'rank' field added to each
    """
    if not participants_with_scores:
        return []
    
    ranks = compute_ranks(participants_with_scores)
    
    for participant in participants_with_scores:
        participant['rank'] = ranks.get(participant['id'], -1)
    
    return participants_with_scores


def rank_change_on_answer(
    participant_id: int,
    new_score: int,
    all_participants: List[Dict],
) -> Tuple[int, int]:
    """
    Calculate rank change when a participant answers a question.
    
    Args:
        participant_id: Participant who just answered
        new_score: Their new total score
        all_participants: List of all participants
    
    Returns:
        Tuple of (old_rank, new_rank) for the participant
    """
    # Get old rank
    old_ranks = compute_ranks(all_participants)
    old_rank = old_ranks.get(participant_id, 0)
    
    # Update participant's score in list (simulate the update)
    for p in all_participants:
        if p['id'] == participant_id:
            p['score'] = new_score
            break
    
    # Recompute ranks
    new_ranks = compute_ranks(all_participants)
    new_rank = new_ranks.get(participant_id, 0)
    
    return old_rank, new_rank


# SQL-equivalent for reference (used for batch rank updates):
RANK_COMPUTATION_SQL = """
SELECT 
    id,
    ROW_NUMBER() OVER (
        ORDER BY 
            score DESC,
            last_correct_time ASC NULLS LAST,
            joined_at ASC
    ) as rank
FROM brainbuzz_brainbuzzparticipant
WHERE session_id = %s
ORDER BY rank ASC;
"""
