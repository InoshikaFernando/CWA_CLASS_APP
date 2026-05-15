"""Utilities for BrainBuzz live quiz sessions."""
# Join-code helpers live in models.py to avoid circular imports.
# Re-export here for backwards-compatibility with any callers that
# do `from brainbuzz.utils import generate_join_code`.
from .models import generate_join_code, _JOIN_CODE_ALPHABET, _JOIN_CODE_LENGTH  # noqa: F401

import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

# Matches fenced code blocks: ```lang\n...\n```
_FENCE_RE = re.compile(r'```(\w*)\n([\s\S]*?)```', re.DOTALL)
# Only allow safe characters in the language label used as a CSS class name.
_SAFE_LANG_RE = re.compile(r'[^a-zA-Z0-9\-]')


def render_question_html(text: str) -> str:
    """Convert fenced code blocks in question_text to safe HTML.

    Rules:
    - ```python\\n...\\n``` becomes <pre class="bb-code"><code class="language-python">
    - Everything else is HTML-escaped prose in a <span class="bb-prose">.
    - A question with no code fences returns a single prose span — visually
      identical to an x-text render but now safe for x-html / |safe.

    Returns a mark_safe string ready for Django's |safe filter or Alpine x-html.
    """
    if not text:
        return mark_safe('')

    parts = []
    last_end = 0

    for m in _FENCE_RE.finditer(text):
        prose = text[last_end:m.start()].strip('\n')
        if prose:
            parts.append(f'<span class="bb-prose">{escape(prose)}</span>')

        raw_lang = (m.group(1) or 'python').strip()
        lang = _SAFE_LANG_RE.sub('', raw_lang) or 'python'
        code = m.group(2)
        if code.endswith('\n'):
            code = code[:-1]
        parts.append(
            f'<pre class="bb-code"><code class="language-{lang}">'
            f'{escape(code)}</code></pre>'
        )
        last_end = m.end()

    trailing = text[last_end:].strip('\n')
    if trailing:
        parts.append(f'<span class="bb-prose">{escape(trailing)}</span>')

    if not parts:
        parts.append(f'<span class="bb-prose">{escape(text)}</span>')

    return mark_safe(''.join(parts))
