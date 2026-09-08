"""Render the small amount of markup teachers actually type into a comment.

Teacher comments are a plain TextField, and teachers write markdown in them —
``**for**`` loops was reaching a parent as literal asterisks. Rendering the body
raw is not an option: it is free text typed by a user and shown to families.

So the body is **escaped first** and the subset converted afterwards. Any HTML a
teacher types is already inert by the time the tags are inserted, which is what
makes this safe without a sanitiser dependency. Only bold, italic and line
breaks are recognised; anything else stays as typed rather than silently
disappearing.
"""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# Bold before italic: '**x**' would otherwise match the single-asterisk rule
# twice and render as '<em><em>x</em></em>'.
_BOLD = re.compile(r'\*\*(?=\S)(.+?)(?<=\S)\*\*', re.DOTALL)
_ITALIC = re.compile(r'(?<!\*)\*(?=\S)([^*]+?)(?<=\S)\*(?!\*)')


@register.filter(name='teacher_markup')
def teacher_markup(value):
    if not value:
        return ''
    out = escape(value)
    out = _BOLD.sub(r'<strong>\1</strong>', out)
    out = _ITALIC.sub(r'<em>\1</em>', out)
    return mark_safe(out.replace('\n', '<br>'))
