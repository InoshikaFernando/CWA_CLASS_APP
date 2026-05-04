"""Utilities for BrainBuzz live quiz sessions."""
# Join-code helpers live in models.py to avoid circular imports.
# Re-export here for backwards-compatibility with any callers that
# do `from brainbuzz.utils import generate_join_code`.
from .models import generate_join_code, _JOIN_CODE_ALPHABET, _JOIN_CODE_LENGTH  # noqa: F401
