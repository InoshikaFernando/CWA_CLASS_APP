"""The ai_import classification prompt keeps its image-necessity rule and warns
against boxing a neighbouring question's figure (the cross-question mislocation).
Zero-token: just inspects the built prompt string.
"""
from ai_import.services import _build_classification_prompt


def test_prompt_keeps_necessity_rule_and_neighbour_guard():
    p = _build_classification_prompt([], [])
    assert 'most questions need NO image' in p
    assert 'wrongly-attached image is worse than none' in p.lower()
    assert "never a neighbouring question's figure" in p
